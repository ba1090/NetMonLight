# netmon gateway: un solo indirizzo pubblico davanti a più VM netmon (vm1, vm2, ... vmN).
#
# Sulla stessa macchina gira l'orchestratore: netmon con ROLE=orchestratore, che ha il pannello di
# amministrazione di tutte le VM e l'elenco delle VM con le loro chiavi. Le VM probe sono server
# netmon con VM_ID impostato: scrivono il proprio nome in testa ai segreti che generano (token
# delle sonde, cookie di sessione, codici di accesso), separato da un punto. Il gateway legge quel
# nome e inoltra la richiesta alla VM giusta:
#
# Con il collegamento diretto (le VM hanno un indirizzo pubblico, es. https://vm2.dominio.it) sonde e
# utenti parlano con la loro VM: il gateway mostra solo la pagina d'accesso («/»), chiede alle VM chi
# ha quell'email (o legge la VM nel codice di accesso) e manda il browser all'indirizzo della VM.
# Tutto il resto continua a passare dal gateway come prima, per le sonde ancora puntate qui:
#
#   sonde               Authorization: Bearer sonda_vm2.xxxx      -> vm2
#   pagina dell'utente  cookie netmon_session=vm2.xxxx             -> vm2
#   registrazione       codice accesso_vm2.xxxx nel corpo          -> vm2
#   accesso (login)     solo l'email: si chiede alle VM chi ce l'ha -> la VM che risponde sì
#   amministrazione     /admin e /api/admin/*                      -> orchestratore
#   VM che si collegano /api/vm/* (token, avvisi)                  -> orchestratore
#   /health senza VM collegate (prima installazione)                -> orchestratore
#   tutto il resto      (pagine pubbliche, token senza prefisso di versioni precedenti) -> DEFAULT_VM
#
# L'elenco delle VM si rilegge dall'orchestratore ogni REFRESH_SECONDS (e subito, quando arriva un
# nome che non conosce: una VM appena collegata).
#
# Configurazione (variabili d'ambiente, vedi env.example):
#   ORCHESTRATOR     indirizzo dell'orchestratore (predefinito http://127.0.0.1:8000)
#   GATEWAY_SECRET   lo stesso valore del .env dell'orchestratore
#   DEFAULT_VM       VM per tutto ciò che non porta un nome (predefinito: vm1 se c'è, altrimenti la prima)
#   PUBLIC_URL       indirizzo del gateway (lo copia installa-server.sh dal .env dell'orchestratore)
#   OLD_HOSTS        nomi precedenti del gateway (dominio cambiato): rimandano tutti a PUBLIC_URL
import asyncio
import hashlib
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from urllib.parse import quote, urlsplit

from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask

log = logging.getLogger("netmon-gateway")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

VM_NAME_RE = re.compile(r"^[a-z0-9]{1,16}$")

ORCHESTRATOR = os.getenv("ORCHESTRATOR", "http://127.0.0.1:8000").strip().rstrip("/")
GATEWAY_SECRET = os.getenv("GATEWAY_SECRET", "").strip()
if not GATEWAY_SECRET:
    raise SystemExit("GATEWAY_SECRET è vuoto: copia quello del .env dell'orchestratore (/opt/netmon/.env)")
DEFAULT_ENV = os.getenv("DEFAULT_VM", "").strip().lower()
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
OLD_HOSTS = {h.strip().lower() for h in os.getenv("OLD_HOSTS", "").split(",") if h.strip()}
REFRESH_SECONDS = 30
TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT", "60"))
MAX_BODY = 10 * 1024 * 1024        # come il limite di Caddy e del server
EMAIL_CACHE_SECONDS = 24 * 3600

SESSION_COOKIE = "netmon_session"

# Intestazioni da non copiare tra le due connessioni (RFC 9110, 7.6.1), più quelle che httpx
# ricalcola da solo.
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
       "transfer-encoding", "upgrade", "content-length", "host"}

VMS: dict[str, str] = {}                          # VM probe: nome -> indirizzo privato
KEYS: dict[str, str] = {}                         # nome -> chiave della VM (per /internal/has-user)
PUBLIC: dict[str, str] = {}                       # nome -> indirizzo pubblico della VM ("" se non ce l'ha)
client: httpx.AsyncClient | None = None
email_vm: dict[str, tuple[str, float]] = {}       # email -> (vm, quando l'abbiamo saputo)
MOVED_PROBES: dict[str, str] = {}                 # utenti spostati: impronta del token della sonda -> vm
MOVED_USERS: dict[str, str] = {}                  # email -> vm
_last_refresh = [0.0]


def default_vm() -> str | None:
    if DEFAULT_ENV in VMS:
        return DEFAULT_ENV
    if "vm1" in VMS:
        return "vm1"
    return min(VMS) if VMS else None


async def refresh_vms():
    """Rilegge l'elenco delle VM dall'orchestratore. Se non risponde resta quello di prima."""
    _last_refresh[0] = time.monotonic()
    try:
        r = await client.get(f"{ORCHESTRATOR}/internal/vms", headers={"X-Netmon-Gateway": GATEWAY_SECRET}, timeout=5)
        data = r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Elenco delle VM non aggiornato (l'orchestratore non risponde: %s)", exc)
        return
    if not isinstance(data, dict):
        log.warning("Elenco delle VM non aggiornato: l'orchestratore risponde %s (GATEWAY_SECRET diverso?)", r.status_code)
        return
    keys = data.get("keys") or {}
    fresh = {k: v.rstrip("/") for k, v in (data.get("vms") or {}).items()
             if VM_NAME_RE.match(str(k)) and isinstance(v, str) and v.startswith(("http://", "https://"))
             and isinstance(keys.get(k), str)}
    if fresh != VMS:
        log.info("Elenco delle VM: %s", ", ".join(f"{k}={v}" for k, v in fresh.items()) or "nessuna")
    VMS.clear()
    VMS.update(fresh)
    KEYS.clear()
    KEYS.update({k: keys[k] for k in fresh})
    for mine, theirs in ((MOVED_PROBES, data.get("moved_probes")), (MOVED_USERS, data.get("moved_users"))):
        if isinstance(theirs, dict):
            mine.clear()
            mine.update({str(k): v for k, v in theirs.items() if v in fresh})
    public = data.get("public") or {}
    PUBLIC.clear()
    PUBLIC.update({k: str(public.get(k) or "").rstrip("/") for k in fresh
                   if str(public.get(k) or "").startswith(("https://", "http://"))})


async def refresh_loop():
    while True:
        await refresh_vms()
        await asyncio.sleep(REFRESH_SECONDS)


@asynccontextmanager
async def lifespan(_app):
    global client
    client = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)
    log.info("Gateway pronto: orchestratore %s", ORCHESTRATOR)
    task = asyncio.create_task(refresh_loop())
    yield
    task.cancel()
    await client.aclose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


async def vm_of(secret: str | None, prefix: str = "") -> str | None:
    """Nome della VM scritto in testa a un segreto ("<prefix><vm>.<casuale>"), se è una VM nota.
    Un nome sconosciuto può essere una VM appena collegata: si rilegge l'elenco (al massimo ogni 5 s)."""
    if not secret or not secret.startswith(prefix):
        return None
    head, dot, _ = secret[len(prefix):].partition(".")
    if not dot or not VM_NAME_RE.match(head):
        return None
    if head not in VMS and time.monotonic() - _last_refresh[0] > 5:
        await refresh_vms()
    return head if head in VMS else None


def normalize_email(email) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", "", str(email or "")).strip().lower()


async def is_admin(email: str) -> bool:
    try:
        r = await client.get(f"{ORCHESTRATOR}/internal/is-admin", params={"email": email},
                             headers={"X-Netmon-Gateway": GATEWAY_SECRET}, timeout=5)
        return r.status_code == 200 and bool(r.json().get("found"))
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("L'orchestratore non risponde a is-admin: %s", exc)
        return False


async def vm_for_email(email: str, fresh: bool = False) -> str | None:
    """La VM su cui vive l'account con questa email: dalla memoria, altrimenti lo si chiede a tutte.
    fresh: lo si chiede comunque alle VM (pagina di accesso: un utente appena spostato non deve
    essere mandato alla VM di prima, che la memoria ricorda ancora)."""
    if email in MOVED_USERS and not fresh:         # spostato da una VM all'altra dal pannello
        return MOVED_USERS[email]
    hit = email_vm.get(email)
    if not fresh and hit and hit[0] in VMS and time.time() - hit[1] < EMAIL_CACHE_SECONDS:
        return hit[0]
    if not email:
        return None

    async def ask(name, base):
        try:
            r = await client.get(f"{base}/internal/has-user", params={"email": email},
                                 headers={"X-Netmon-Gateway": KEYS.get(name, "")}, timeout=5)
            return name if r.status_code == 200 and r.json().get("found") else None
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("%s non risponde a has-user: %s", name, exc)
            return None

    found = [n for n in await asyncio.gather(*(ask(n, b) for n, b in list(VMS.items()))) if n]
    if len(found) > 1:
        log.error("L'email %s esiste su più VM (%s): uso %s", email, ", ".join(found), found[0])
    if found:
        # vale dove l'account c'è davvero, anche contro un vecchio spostamento: un utente spostato e
        # poi eliminato e reimportato altrove (da backup) non deve tornare alla VM dello spostamento
        email_vm[email] = (found[0], time.time())
        return found[0]
    return MOVED_USERS.get(email)


probe_vm: dict[str, tuple[str | None, float]] = {}   # impronta del token -> (vm o None, quando)


async def vm_for_probe(token: str) -> str | None:
    """La VM di una sonda con un token senza nome della VM (trasferita da un server senza gateway):
    lo si chiede a tutte, una volta all'ora per token (se nessuna la conosce, ogni minuto)."""
    h = hashlib.sha256(token.encode()).hexdigest()
    hit = probe_vm.get(h)
    if hit and time.time() - hit[1] < (3600 if hit[0] in VMS else 60):
        return hit[0] if hit[0] in VMS else None

    async def ask(name, base):
        try:
            r = await client.get(f"{base}/internal/has-probe", params={"h": h},
                                 headers={"X-Netmon-Gateway": KEYS.get(name, "")}, timeout=5)
            return name if r.status_code == 200 and r.json().get("found") else None
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("%s non risponde a has-probe: %s", name, exc)
            return None

    found = [n for n in await asyncio.gather(*(ask(n, b) for n, b in list(VMS.items()))) if n]
    if len(probe_vm) > 10000:
        probe_vm.clear()
    probe_vm[h] = (found[0] if found else None, time.time())
    return found[0] if found else None


def json_field(body: bytes, field: str):
    try:
        data = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return None
    return data.get(field) if isinstance(data, dict) else None


ORCH = ""                                          # destinazione «orchestratore» in pick_vm
GATEWAY_ASSETS = ("/favicon.svg", "/favicon.ico", "/favicon-32.png", "/apple-touch-icon.png", "/privacy",
                  "/robots.txt", "/sitemap.xml")


async def pick_vm(request: Request, body: bytes) -> str | None:
    path = request.url.path
    # 1. amministrazione e VM che si collegano: l'orchestratore
    if path == "/admin" or path.startswith(("/admin/", "/api/admin/", "/api/vm/")):
        return ORCH
    # icone, caratteri e informativa delle pagine servite qui (accesso e pannello): sempre
    # dall'orchestratore, mai con un rimando a una VM (il browser spesso non lo segue per l'icona,
    # e se quella VM non risponde la scheda resta senza icona)
    if path in GATEWAY_ASSETS or path.startswith("/fonts/"):
        return ORCH
    # 2. sonde: il token personale porta il nome della VM
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if token and MOVED_PROBES:                     # sonda di un utente spostato: il nome nel token è quello vecchio
        vm = MOVED_PROBES.get(hashlib.sha256(token.encode()).hexdigest())
        if vm in VMS:
            return vm
    vm = await vm_of(token, "sonda_")
    if vm:
        return vm
    if token.startswith("sonda_") and "." not in token and len(token) < 200:
        vm = await vm_for_probe(token)             # token di prima del gateway: chi ha la sonda?
        if vm:
            return vm
    # 3. accesso: chi ha questa email
    if path == "/api/auth/login" and request.method == "POST":
        return await vm_for_email(normalize_email(json_field(body, "email"))) or default_vm()
    # 4. registrazione: il codice di accesso dice dove nascerà l'account
    if path == "/api/auth/register" and request.method == "POST":
        return await vm_of(str(json_field(body, "token") or "").strip(), "accesso_") or default_vm()
    # 5. utente collegato
    return await vm_of(request.cookies.get(SESSION_COOKIE)) or default_vm()


def forward_headers(request: Request) -> dict:
    # X-Forwarded-For arriva da Caddy (sulla stessa macchina) con l'IP vero come ultima voce:
    # passa così com'è, e la VM ci crede perché l'IP del gateway è nel suo TRUSTED_PROXIES.
    out = [(k, v) for k, v in request.headers.items()
           if k.lower() not in HOP and k.lower() not in ("x-netmon-gateway", "x-netmon-admin", "x-netmon-admin-name", "x-netmon-pw-checked")]
    out.append(("host", request.headers.get("host", "")))
    if "x-forwarded-proto" not in request.headers:
        out.append(("x-forwarded-proto", request.url.scheme))
    return httpx.Headers(out)


# Logo come in server/brand.py (rigenerati da tools/genera-icone.py: se cambia il disegno,
# aggiorna anche qui).
LOGO_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#174A72"/><path d="M32.00 12.00L49.32 22.00L49.32 42.00L32.00 52.00L14.68 42.00L14.68 22.00Z" fill="none" stroke="#FFFFFF" stroke-opacity=".45" stroke-width="1.8" stroke-linejoin="round"/><path d="M32 32L32.00 12.00M32 32L49.32 22.00M32 32L49.32 42.00M32 32L32.00 52.00M32 32L14.68 42.00M32 32L14.68 22.00" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round"/><circle cx="32.00" cy="12.00" r="4" fill="#FFFFFF"/><circle cx="49.32" cy="22.00" r="4" fill="#FFFFFF"/><circle cx="49.32" cy="42.00" r="4" fill="#FFFFFF"/><circle cx="32.00" cy="52.00" r="4" fill="#FFFFFF"/><circle cx="14.68" cy="42.00" r="4" fill="#FFFFFF"/><circle cx="14.68" cy="22.00" r="4" fill="#FFFFFF"/><circle cx="32" cy="32" r="9.00" fill="#174A72"/><path d="M32.00 24.50L24.00 31.50L26.60 31.50L26.60 39.00L37.40 39.00L37.40 31.50L40.00 31.50Z" fill="#7FB8E0" stroke="#7FB8E0" stroke-width="1.50" stroke-linejoin="round"/></svg>'


ACCESS_PAGE = """<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NetMon Home tool · accesso</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<style>
:root{--bg:#F0F4F8;--card:#fff;--fg:#1C2430;--muted:#5A6878;--line:#D5DFE9;--accent:#174A72;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d2128;--fg:#e8eaee;--muted:#9aa3b2;--line:#323844;--accent:#6FA8DC;--bad:#ff8a80}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--fg);
font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:16px}
main{width:100%;max-width:380px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:28px}
h1{margin:0 0 6px;font-size:1.4rem;line-height:1.15;display:flex;align-items:center;gap:14px;letter-spacing:-.01em}
h1 svg{width:60px;height:60px;flex:none;border-radius:13px}h1 small{display:block;font-size:.95rem;font-weight:500;color:var(--muted)}p{margin:0 0 18px;color:var(--muted);font-size:14px}
label{display:block;font-size:14px;color:var(--muted);margin:12px 0 4px}
input{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:9px;background:transparent;color:var(--fg);font:inherit}
button{width:100%;margin-top:18px;padding:11px;border:0;border-radius:9px;background:var(--accent);color:#fff;font:inherit;font-weight:600;cursor:pointer}
button:disabled{opacity:.6}a{color:var(--accent);font-size:14px}.msg{min-height:20px;margin-top:12px;font-size:14px;color:var(--bad)}
.alt{margin-top:16px;text-align:center}
</style></head><body><main>
<h1>__NETMON_LOGO__<span translate="no">NetMon <small>Home tool</small></span></h1><p id="sub">Inserisci la tua email: ti porto alla tua pagina.</p>
<form id="f">
  <label for="email">Email</label><input id="email" type="email" autocomplete="username" required autofocus>
  <div id="code-box" hidden><label for="code">Codice di accesso</label><input id="code" autocomplete="off" spellcheck="false"></div>
  <button id="go" type="submit">Avanti</button>
  <div class="msg" id="msg" role="status"></div>
</form>
<div class="alt"><a href="#" id="toggle">Ho un codice di accesso (nuovo account)</a></div>
</main>
<script>
const $ = s => document.querySelector(s);
let reg = false;
function mode(r) {
  reg = r; $("#code-box").hidden = !r; $("#code").required = r;
  $("#go").textContent = r ? "Registrati" : "Avanti";
  $("#sub").textContent = r ? "Inserisci l'email e il codice che hai ricevuto." : "Inserisci la tua email: ti porto alla tua pagina.";
  $("#toggle").textContent = r ? "Ho già un account" : "Ho un codice di accesso (nuovo account)";
}
$("#toggle").onclick = e => { e.preventDefault(); mode(!reg); };
async function go(body) {
  $("#go").disabled = true; $("#msg").textContent = "";
  try {
    const r = await fetch("/gateway/accedi", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const res = await r.json().catch(() => ({}));
    if (!r.ok || !res.url) throw new Error(res.detail || "Riprova tra poco.");
    location.href = res.url;
  } catch (e) { $("#msg").textContent = e.message; $("#go").disabled = false; }
}
$("#f").onsubmit = e => {
  e.preventDefault();
  const email = $("#email").value.trim().toLowerCase();
  go(reg ? { email, codice: $("#code").value.trim() } : { email });
};
// link d'invito delle email di prima (#invito=CODICE&email=...): si va subito alla VM giusta
if (location.hash.startsWith("#invito=")) {
  const q = new URLSearchParams(location.hash.slice(1));
  history.replaceState(null, "", location.pathname);
  mode(true); $("#email").value = q.get("email") || ""; $("#code").value = q.get("invito") || "";
  if ($("#code").value) go({ email: $("#email").value, codice: $("#code").value });
}
</script></body></html>"""
ACCESS_HTML = (ACCESS_PAGE.replace("__NETMON_LOGO__", LOGO_SVG.replace("<svg ", '<svg aria-hidden="true" focusable="false" ', 1)))

_access_hits: dict[str, list[float]] = {}


def access_limited(ip: str) -> bool:
    """Al massimo 20 richieste al minuto per IP alla pagina d'accesso (dice su che VM sta un'email)."""
    now = time.monotonic()
    hits = [t for t in _access_hits.get(ip, []) if now - t < 60]
    if len(_access_hits) > 5000:
        _access_hits.clear()
    _access_hits[ip] = hits + [now]
    return len(hits) >= 20


def direct_mode() -> bool:
    return any(PUBLIC.get(k) for k in VMS)


@app.post("/gateway/accedi")
async def gateway_access(request: Request):
    """Dove mandare il browser: la VM dell'account (dall'email) o quella del codice di accesso."""
    ip = request.headers.get("x-forwarded-for", "").split(",")[-1].strip() or (request.client.host if request.client else "?")
    if access_limited(ip):
        return JSONResponse({"detail": "Troppi tentativi: riprova tra un minuto."}, status_code=429)
    body = await request.body()
    email = normalize_email(json_field(body, "email"))[:254]
    code = str(json_field(body, "codice") or "").strip()[:200]
    if not VMS:
        await refresh_vms()
    if code:
        vm = await vm_of(code, "accesso_") or default_vm()
        frag = "#invito=" + quote(code, safe="") + ("&email=" + quote(email, safe="") if email else "")
    elif "@" in email:
        if time.monotonic() - _last_refresh[0] > 5:
            await refresh_vms()                    # utenti appena spostati tra le VM
        vm = await vm_for_email(email, fresh=True)
        frag = "#accesso=" + quote(email, safe="")
        # non è un utente di nessuna VM ma è un amministratore: al pannello, qui sul gateway
        if not vm and await is_admin(email):
            return {"url": "/admin" + frag}
        vm = vm or default_vm()
    else:
        return JSONResponse({"detail": "Scrivi la tua email."}, status_code=422)
    if not vm:
        return JSONResponse({"detail": "Servizio non ancora pronto: nessuna VM collegata."}, status_code=503)
    base = PUBLIC.get(vm)
    if not base:
        return JSONResponse({"detail": "Servizio momentaneamente non disponibile: riprova più tardi."}, status_code=503)
    return {"url": base + "/" + frag}


PROBE_PATHS = ("/api/report", "/api/backfill", "/api/probe-config", "/api/probe-update", "/api/probe-package")


@app.middleware("http")
async def old_host_redirect(request: Request, call_next):
    """Dominio cambiato: i vecchi nomi del gateway (OLD_HOSTS) rimandano a PUBLIC_URL. Le sonde ricevono
    il nuovo indirizzo come quelle di un utente spostato (410 con «moved») e lo salvano da sole."""
    host = request.headers.get("host", "").lower().split(":", 1)[0]
    parts = urlsplit(PUBLIC_URL)
    if (host not in OLD_HOSTS or parts.scheme != "https" or not parts.hostname or parts.hostname in OLD_HOSTS
            or request.url.path.startswith("/internal/")):
        return await call_next(request)
    path = request.url.path
    if path.startswith(PROBE_PATHS) and request.headers.get("authorization", "").startswith("Bearer "):
        url = PUBLIC_URL + "/api/report"
        return JSONResponse({"detail": f"Sonda spostata: ora scrive a {url}.", "moved": url}, status_code=410)
    if request.method in ("GET", "HEAD"):
        return RedirectResponse(PUBLIC_URL + path + (("?" + request.url.query) if request.url.query else ""),
                                status_code=301)
    return JSONResponse({"detail": f"Indirizzo cambiato: usa {PUBLIC_URL}."}, status_code=421)


@app.get("/gateway/health")
async def gateway_health():
    try:
        r = await client.get(f"{ORCHESTRATOR}/health", timeout=5)
        orch = r.status_code == 200
    except httpx.HTTPError:
        orch = False
    return {"ok": orch, "orchestrator": orch, "vms": sorted(VMS), "default": default_vm(),
            "public": {k: PUBLIC.get(k, "") for k in sorted(VMS)}}


@app.get("/gateway/admin")
async def gateway_admin():
    """Indirizzo delle versioni precedenti (scelta della VM): ora il pannello è uno solo."""
    return RedirectResponse("/admin", status_code=303)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy(request: Request, path: str):
    if request.url.path.startswith("/internal/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if request.method in ("GET", "HEAD") and request.url.path in ("/", "/status") and direct_mode():
        return HTMLResponse(ACCESS_HTML, headers={"Cache-Control": "no-store"})
    body = await request.body()
    if len(body) > MAX_BODY:
        return JSONResponse({"detail": "Richiesta troppo grande."}, status_code=413)
    vm = await pick_vm(request, body)
    if vm is None and time.monotonic() - _last_refresh[0] > 5:
        await refresh_vms()                        # magari una VM si è appena collegata
        vm = await pick_vm(request, body)
    if vm is None and request.url.path == "/health":
        vm = ORCH
    if vm is None:
        return JSONResponse({"detail": "Nessuna VM collegata: aggiungine una dal pannello di amministrazione."},
                            status_code=503)
    # Collegamento diretto: le pagine e le API degli utenti si usano all'indirizzo della loro VM.
    # Qui passano solo le sonde (token nell'intestazione): il contenuto di una VM non deve mai
    # essere servito con l'indirizzo del gateway, dove vive il pannello di amministrazione.
    if (vm != ORCH and direct_mode() and PUBLIC.get(vm) and request.url.path != "/health"
            and not request.headers.get("authorization", "").startswith("Bearer sonda_")):
        target = PUBLIC[vm] + request.url.path + (("?" + request.url.query) if request.url.query else "")
        if request.method in ("GET", "HEAD"):
            return RedirectResponse(target, status_code=302)
        return JSONResponse({"detail": f"Usa l'indirizzo della tua VM: {PUBLIC[vm]}"}, status_code=421)
    base = ORCHESTRATOR if vm == ORCH else VMS[vm]
    url = base + request.url.path + (("?" + request.url.query) if request.url.query else "")
    req = client.build_request(request.method, url, headers=forward_headers(request), content=body)
    try:
        upstream = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        log.warning("%s non raggiungibile per %s %s: %s", vm or "orchestratore", request.method, request.url.path, exc)
        return JSONResponse({"detail": "Server momentaneamente non raggiungibile, riprova tra poco."},
                            status_code=502)
    if request.url.path == "/api/vm/join" and upstream.status_code == 200:
        asyncio.get_running_loop().call_later(1, lambda: asyncio.ensure_future(refresh_vms()))
    if request.url.path == "/api/auth/login" and upstream.status_code == 401:
        email_vm.pop(normalize_email(json_field(body, "email")), None)   # magari l'account è stato spostato
    # aiter_raw: i byte così come arrivano (anche compressi), quindi Content-Encoding e
    # Content-Length della VM restano validi e si copiano tali e quali.
    resp = StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code,
                             background=BackgroundTask(upstream.aclose))
    resp.raw_headers = [(k.lower().encode("latin-1"), v.encode("latin-1"))
                        for k, v in upstream.headers.multi_items()
                        if k.lower() not in (HOP - {"content-length"}) | {"date", "server"}]   # li mette uvicorn
    return resp
