"""Attacchi noti simulati contro il server: ricognizione, attraversamento di percorsi, SQL injection,
CSRF, IDOR, token delle sonde, sessioni, campi in più, schermata d'accesso unica, tentativi
distribuiti, «Importa un utente» e CSP delle pagine.

Ogni prova rifà un attacco che il server deve respingere: se una modifica futura apre un buco, la
prova fallisce. Le altre prove di sicurezza (accessi rotta per rotta, isolamento tra account, XSS nel
browser, sonda) restano nei loro file.
"""
import base64
import hashlib
import json
import re
import secrets
import time
import zipfile

import pytest
from fastapi.routing import APIRoute

from conftest import API_TOKEN, PASSWORD, netmon, new_email

HTML_PAGES = ["/", "/en/", "/de/", "/fr/", "/dashboard", "/admin", "/privacy"]


# ------------------------------------------------------------------ ricognizione
@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/.env", "/.git/config", "/server/.env",
                                  "/app.py", "/data/auth.db", "/backup.zip", "/debug", "/metrics", "/.DS_Store"])
def test_no_hidden_files_or_docs(client, path):
    client.cookies.clear()
    r = client.get(path, follow_redirects=False)
    assert r.status_code in (301, 302, 307, 308, 401, 404, 405), (path, r.status_code)
    for secret in ("API_TOKEN", "openapi", "[core]", "SQLite format", "SMTP_", API_TOKEN):
        assert secret not in r.text


def test_health_and_auth_state_reveal_nothing(client, two_users):
    a, pa, b, pb = two_users
    client.cookies.clear()
    assert set(client.get("/health").json()) <= {"ok", "version", "probe_version"}
    for path in ("/api/auth/state", "/api/admin/auth/state"):
        assert "@" not in client.get(path).text


# ------------------------------------------------------------------ intestazioni e CSP
@pytest.mark.parametrize("path", HTML_PAGES)
def test_pages_have_security_headers(client, path):
    client.cookies.clear()
    r = client.get(path)
    assert r.status_code == 200
    for k in ("x-content-type-options", "x-frame-options", "referrer-policy"):
        assert k in r.headers, (path, k)
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp and "default-src 'self'" in csp and "object-src 'none'" in csp


@pytest.mark.parametrize("path", HTML_PAGES)
def test_csp_allows_only_the_page_scripts(client, path):
    """Niente 'unsafe-inline' per gli script: parte solo uno script con l'impronta dichiarata."""
    client.cookies.clear()
    r = client.get(path)
    script_src = re.search(r"script-src([^;]*)", r.headers["content-security-policy"]).group(1)
    assert "unsafe-inline" not in script_src and "unsafe-eval" not in script_src
    declared = set(re.findall(r"'sha256-([^']+)'", script_src))
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", r.text, re.S | re.I)
    assert scripts, path
    for s in scripts:
        assert base64.b64encode(hashlib.sha256(s.encode()).digest()).decode() in declared, path
    # un testo arrivato dalla rete e scritto nella pagina non avrebbe la sua impronta nell'elenco
    injected = base64.b64encode(hashlib.sha256(b"alert(1)").digest()).decode()
    assert injected not in declared


def test_csp_unchanged_on_304(client):
    """Con l'ETag il browser riusa la pagina che ha già: la 304 non porta una CSP diversa."""
    client.cookies.clear()
    r = client.get("/dashboard")
    r2 = client.get("/dashboard", headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304 and "content-security-policy" not in r2.headers


def test_api_not_cached_and_no_cors(client):
    client.cookies.clear()
    r = client.get("/api/auth/state", headers={"Origin": "https://evil.example"})
    assert r.headers.get("cache-control") == "no-store"
    assert "access-control-allow-origin" not in r.headers
    r = client.options("/api/auth/login", headers={"Origin": "https://evil.example",
                                                   "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


# ------------------------------------------------------------------ attraversamento di percorsi e metodi
@pytest.mark.parametrize("path", ["/fonts/../app.py", "/fonts/..%2fapp.py", "/fonts/%2e%2e%2fapp.py", "/fonts/..%5capp.py",
                                  "/fonts/....//app.py", "/fonts/%252e%252e%252fapp.py", "/fonts/x.woff2%00.py",
                                  "/fonts/..%2f..%2f..%2fetc%2fpasswd", "/en/../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd",
                                  "/favicon.svg/../app.py"])
def test_path_traversal(client, path):
    r = client.get(path)
    for leak in ("import ", "root:x:", "API_TOKEN"):
        assert leak not in r.text, path


@pytest.mark.parametrize("method", ["TRACE", "PUT", "DELETE", "PATCH"])
def test_unexpected_methods(client, method):
    r = client.request(method, "/api/auth/login", headers={"X-Secret": "abc123"})
    assert r.status_code in (400, 404, 405) and "abc123" not in r.text


# ------------------------------------------------------------------ SQL injection e tipi
@pytest.mark.parametrize("email", ["' OR '1'='1", "admin@example.test'--", "\" OR 1=1--", "'; DROP TABLE users;--",
                                   "x@example.test\x00", "*", "%", "_%@example.test"])
def test_sql_injection_login(client, first_user, email):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": email, "password": "' OR '1'='1"})
    assert r.status_code in (401, 422, 429)
    assert netmon.COOKIE not in r.headers.get("set-cookie", "")
    assert netmon.auth.has_users()                       # la tabella c'è ancora


@pytest.mark.parametrize("value", [{"$ne": ""}, ["x@example.test"], 1, None, True])
def test_type_confusion_login(client, value):
    r = client.post("/api/auth/login", json={"email": value, "password": value})
    assert r.status_code in (401, 422)


@pytest.mark.parametrize("q", ["' OR 1=1--", "p_x' UNION SELECT email,pw_hash FROM users--", "1;SELECT sqlite_version()"])
@pytest.mark.parametrize("path", ["/api/history", "/api/traffic", "/api/availability", "/api/speedtests",
                                  "/api/fritz-history", "/api/wifi-history"])
def test_sql_injection_api(two_users, q, path):
    a, pa, b, pb = two_users
    r = b.get(path, params={"probe": q, "device": q, "box": q, "hours": "24"})
    assert r.status_code < 500
    for leak in ("pw_hash", "scrypt$", a.email):
        assert leak not in r.text


# ------------------------------------------------------------------ CSRF
def test_csrf_simple_requests_refused(two_users):
    """Un sito estraneo può mandare solo richieste «semplici» (modulo, testo): nessuna viene accettata."""
    a, pa, b, pb = two_users
    attempts = [
        {"content": json.dumps({"probe": pa.key, "name": "csrf"}), "headers": {"Content-Type": "text/plain"}},
        {"content": f"probe={pa.key}&name=csrf", "headers": {"Content-Type": "application/x-www-form-urlencoded"}},
        {"files": {"probe": (None, pa.key), "name": (None, "csrf")}},
    ]
    for kw in attempts:
        headers = {**a.headers, **kw.pop("headers", {})}
        r = a.c.post("/api/probes/rename", headers=headers, **kw)
        assert r.status_code in (400, 415, 422), r.status_code
    assert "csrf" not in a.get("/api/probes").text


def test_session_cookie_flags(client, make_user):
    u = make_user()
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": u.email, "password": PASSWORD},
                    headers={"Cookie": f"{netmon.COOKIE}=FISSATA123"})
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc
    raw = r.cookies.get(netmon.COOKIE)
    assert raw and raw != "FISSATA123" and len(raw) >= 32       # niente session fixation
    client.cookies.clear()


# ------------------------------------------------------------------ IDOR su tutte le rotte delle sonde
def _probe_routes():
    out = []
    for r in netmon.app.routes:
        if not isinstance(r, APIRoute) or not r.path.startswith("/api/"):
            continue
        if r.path.startswith(("/api/admin", "/api/auth", "/api/account")) or r.path in (
                "/api/report", "/api/backfill", "/api/probe-config", "/api/probe-update", "/api/probe-package",
                "/api/probe-package/info", "/api/update-key", "/api/lang"):
            continue
        for m in sorted(r.methods - {"HEAD"}):
            out.append((m, r.path))
    return out


def test_idor_sweep(two_users):
    """B prova ogni rotta delle sonde con la sonda di A: nessuna risposta la tocca o la mostra."""
    a, pa, b, pb = two_users
    body = {"probe": pa.key, "device": "dev0", "name": "pwned", "password": b.password, "id": 1, "ids": [1],
            "order": ["dev0"], "prio": "alta", "command": "reboot", "action": "add", "ssid": "x",
            "url": "evil.example.net", "mode": "account", "minutes": 10, "hours": 1, "value": 1, "unit": "giorni",
            "all": False, "daily": True, "ports": [80], "enabled": True}
    before = json.dumps(a.get("/api/probes").json(), sort_keys=True)
    routes = _probe_routes()
    assert len(routes) > 30
    for m, path in routes:
        if m == "GET":
            r = b.get(path, params={"probe": pa.key, "device": "dev0", "box": "x"})
        else:
            r = b.post(path, body)
        assert r.status_code < 500, (m, path, r.text[:200])
        if r.status_code != 422:                     # il 422 ripete il corpo mandato da B stesso
            assert pa.key not in r.text, (m, path, r.status_code, r.text[:200])
    assert json.dumps(a.get("/api/probes").json(), sort_keys=True) == before
    assert "pwned" not in a.get("/api/status").text


# ------------------------------------------------------------------ token delle sonde
def test_probe_tokens(client, two_users):
    a, pa, b, pb = two_users
    client.cookies.clear()
    r = client.post("/api/report", json={"probe": pa.key, "devices": {"x": {"ok": False, "host": "1.1.1.1"}}},
                    headers=pb.headers)
    assert "x" not in a.get("/api/status").json().get("probes", [{}])[0].get("devices", {}) or r.status_code >= 400
    r = client.post("/api/report", json={"probe": pa.key, "devices": {}}, headers={"Authorization": "Bearer " + API_TOKEN})
    assert r.status_code == 401
    r = client.get("/api/probe-config", params={"probe": pa.key},
                   headers={"Authorization": "Bearer " + pa.token[:-1] + ("x" if pa.token[-1] != "x" else "y")})
    assert r.status_code == 401
    for path in ("/api/probes", "/api/status", "/api/backup"):
        assert pa.token not in a.get(path).text, path


# ------------------------------------------------------------------ sessioni
def test_sessions_cross_use_and_logout(client, make_user, admin):
    u = make_user()
    assert u.get("/api/admin/overview").status_code in (401, 403)
    assert client.get("/api/admin/overview", headers={"Cookie": f"{netmon.ADMIN_COOKIE}={u.cookie}"}).status_code in (401, 403)
    assert client.get("/api/status", headers={"Cookie": f"{netmon.COOKIE}={admin.cookie}"}).status_code == 401
    assert admin.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"Cookie": f"{netmon.COOKIE}={u.cookie[:-2]}xx"}).status_code == 401
    assert u.post("/api/auth/logout", {}).status_code == 200
    assert u.get("/api/status").status_code == 401         # il cookie rubato non vale più


def test_mass_assignment(two_users):
    a, pa, b, pb = two_users
    b.post("/api/probes/rename", {"probe": pb.key, "name": "x", "owner": a.id, "is_admin": 1})
    assert pb.key not in a.get("/api/probes").text
    b.post("/api/account/view", {"is_admin": True, "plan": "alto", "max_probes": 999})
    row = netmon.auth.get_user(b.id)
    assert not row.get("is_admin") and row.get("max_probes") != 999


# ------------------------------------------------------------------ schermata d'accesso unica
def test_unified_login_does_not_reveal_admin_emails(client, fresh_admin):
    """I limiti dei tentativi del pannello non cambiano la risposta: un'email di amministratore
    risponde come qualunque altra email con la password sbagliata."""
    client.cookies.clear()
    netmon.admin_pw_throttle._fails[f"ip:testclient|{fresh_admin.login}"] = [time.time()] * 10
    netmon.admin_account_throttle._fails[f"acct:{fresh_admin.login}"] = [time.time()] * 200
    r_admin = client.post("/api/auth/login", json={"email": fresh_admin.login, "password": "sbagliata-123"})
    netmon.throttle._fails.clear()
    r_other = client.post("/api/auth/login", json={"email": new_email("nessuno"), "password": "sbagliata-123"})
    assert r_admin.status_code == r_other.status_code == 401
    assert r_admin.json() == r_other.json()


def test_unified_login_same_work_for_every_email(client, fresh_admin, monkeypatch):
    """Due verifiche della password per ogni email: chi misura i tempi non distingue gli amministratori."""
    calls = []
    real = netmon.auth.burn_password_check
    monkeypatch.setattr(netmon.auth, "burn_password_check", lambda pw: (calls.append(1), real(pw)))
    client.cookies.clear()
    client.post("/api/auth/login", json={"email": new_email("nessuno"), "password": "sbagliata-123"})
    assert calls == [1]
    calls.clear()
    client.post("/api/auth/login", json={"email": fresh_admin.login, "password": "sbagliata-123"})
    assert calls == []                  # qui la seconda verifica la fa il passaggio del pannello


# ------------------------------------------------------------------ tentativi distribuiti
def test_spray_watch_threshold():
    w = netmon.SprayWatch(fails=10, window=3600, min_ips=5)
    assert all(w.fail("a@x.it", "10.0.0.1", now=1000 + i) is None for i in range(30))   # un solo IP: no
    hits = [w.fail("b@x.it", f"10.0.0.{i % 6}", now=1000 + i) for i in range(10)]
    assert hits[-1] == (10, 6) and all(h is None for h in hits[:-1])
    assert w.fail("b@x.it", "10.0.0.9", now=1000 + 3700) is None                       # finestra scaduta


def test_spray_alert_only_for_existing_accounts(make_user, monkeypatch):
    u = make_user()
    sent = []
    monkeypatch.setattr(netmon, "spray", netmon.SprayWatch(fails=8, window=3600, min_ips=4))
    monkeypatch.setattr(netmon, "admin_notice", lambda title, body="", **kw: sent.append((title, body, kw)))
    for i in range(8):
        netmon.spray_check(new_email("inventata"), f"10.1.0.{i}")
        netmon.spray_check("nessuno@example.test", f"10.2.0.{i}")
    assert sent == []
    for i in range(8):
        netmon.spray_check(u.email, f"10.3.0.{i}")
    assert len(sent) == 1
    title, body, kw = sent[0]
    assert u.email in title and "8 password sbagliate da 8 indirizzi" in body
    assert kw["gap_key"] == "spray:" + u.email and kw["gap"] >= 3600 and kw["ok"] is False


def test_spray_counted_on_failed_login(client, make_user, monkeypatch):
    u = make_user()
    seen = []
    monkeypatch.setattr(netmon, "spray_check", lambda email, ip: seen.append((email, ip)))
    client.cookies.clear()
    client.post("/api/auth/login", json={"email": u.email, "password": "sbagliata-123"})
    assert seen == [(u.email, "testclient")]
    assert u.get("/api/status").status_code == 200           # nessun blocco dell'account


# ------------------------------------------------------------------ Importa un utente: solo i campi previsti
def _upload(admin, data, tid):
    r = admin.c.post(f"/api/admin/transfer/upload?id={tid}&part=0&parts=1", content=data,
                     headers={**admin.headers, "Content-Type": "application/octet-stream"})
    return r


def _job(admin, tid):
    for _ in range(200):
        j = admin.get(f"/api/admin/transfer/job?id={tid}").json()
        if j["state"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("importazione non finita")


def _crafted(tmp_path, make_user, change):
    """Zip di trasferimento vero, poi modificato come farebbe chi prepara un file apposta."""
    u = make_user()
    assert u.new_probe("sonda importata").report().status_code == 200
    src = tmp_path / "orig.zip"
    netmon.transfer_export(u.id, {}, str(src))
    out = tmp_path / "mod.zip"
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(out, "w") as zo:
        for item in zi.infolist():
            data = zi.read(item.filename)
            if item.filename == "account.json":
                acc = json.loads(data)
                change(acc)
                data = json.dumps(acc).encode()
            zo.writestr(item.filename, data)
    return out.read_bytes()


def test_import_ignores_privileged_fields(tmp_path, make_user, admin):
    email, key = new_email("importato"), "p_" + secrets.token_hex(6)

    def change(acc):
        acc["user"].update(email=email, is_admin=1, verify_hash="x" * 64, verify_expires=9e9, plan="alto",
                           max_probes=7, colonna_inventata="x", id=1)
        acc["probes"][0].update(key=key, key_ok=1, owner=1, token_hash=secrets.token_hex(32))
    tid = "i" + secrets.token_hex(10)
    r = _upload(admin, _crafted(tmp_path, make_user, change), tid)
    assert r.status_code == 200, r.text
    acc = r.json()["preview"]["account"]
    assert acc["plan"] == "alto" and acc["limits"] == {"max_probes": 7}        # visti prima di importare
    r = admin.post("/api/admin/transfer/import", {"id": tid, "password": admin.password})
    assert r.status_code == 200, r.text
    j = _job(admin, r.json()["id"])
    assert j["state"] == "done", j
    with netmon.auth._conn() as c:
        row = c.execute("SELECT id, is_admin, verify_hash, plan, max_probes FROM users WHERE email = ?", (email,)).fetchone()
        assert row[0] != 1 and row[1] == 0 and row[2] is None and row[3] == "alto" and row[4] == 7
        pr = c.execute("SELECT owner, key_ok FROM probes WHERE key = ?", (key,)).fetchone()
        assert pr == (row[0], 0)


@pytest.mark.parametrize("change", [
    lambda acc: acc["user"].update(pw_hash="testo-in-chiaro"),
    lambda acc: acc["user"].update(email=["a@b.it"]),
    lambda acc: acc["probes"].append(dict(acc["probes"][0])),                       # stessa chiave due volte
    lambda acc: acc["probes"][0].update(key="../../etc"),
], ids=["hash", "email-lista", "chiave-doppia", "chiave-strana"])
def test_import_refuses_malformed_accounts(tmp_path, make_user, admin, change):
    def mod(acc):
        acc["user"]["email"] = new_email("rotto") if not isinstance(acc["user"].get("email"), list) else acc["user"]["email"]
        change(acc)
    r = _upload(admin, _crafted(tmp_path, make_user, mod), "r" + secrets.token_hex(10))
    assert r.status_code == 422, r.text


def test_import_refuses_token_of_existing_probe(tmp_path, make_user, admin):
    """Lo stesso file con un'altra email: le sonde hanno token già in uso qui, l'import si ferma prima."""
    def change(acc):
        acc["user"]["email"] = new_email("copia")
        acc["probes"][0]["key"] = "p_" + secrets.token_hex(6)
    tid = "k" + secrets.token_hex(10)
    r = _upload(admin, _crafted(tmp_path, make_user, change), tid)
    assert r.status_code == 200 and r.json()["preview"]["clash"]
    r = admin.post("/api/admin/transfer/import", {"id": tid, "password": admin.password})
    assert r.status_code == 200, r.text
    j = _job(admin, r.json()["id"])
    assert j["state"] == "error" and "stesse chiavi" in j["detail"], j


# ------------------------------------------------------------------ registrazione sul server vuoto
def test_first_account_with_access_code(client, admin, monkeypatch):
    """Server ancora senza utenti: un codice creato dal pannello basta, non serve la chiave del server.
    Un codice inventato o una chiave sbagliata restano rifiutati."""
    monkeypatch.setattr(netmon.auth, "has_users", lambda: False)
    client.cookies.clear()
    r = client.post("/api/auth/register", json={"token": "chiave-sbagliata", "email": new_email("primo"), "password": PASSWORD})
    assert r.status_code == 401 and r.json()["detail"] == "Chiave del server o codice di accesso non validi."
    r = client.post("/api/auth/register", json={"token": "accesso_" + "x" * 20, "email": new_email("primo"), "password": PASSWORD})
    assert r.status_code == 401
    code = admin.post("/api/admin/invites/new", {"note": "primo", "max_uses": 1}).json()["code"]
    r = client.post("/api/auth/register", json={"token": code, "email": new_email("primo"), "password": PASSWORD})
    assert r.status_code == 200, r.text
    client.cookies.clear()


def test_import_keeps_notification_channels(tmp_path, make_user, admin):
    """I canali di notifica dell'utente (chat Telegram, topic ntfy, interruttori) arrivano con l'import."""
    email, key = new_email("canali"), "p_" + secrets.token_hex(6)

    def change(acc):
        acc["user"].update(email=email, telegram_chat="123456789", telegram_on=1,
                           ntfy_url="https://ntfy.sh/prova-canali", ntfy_on=0)
        acc["probes"][0].update(key=key, token_hash=secrets.token_hex(32))
    tid = "c" + secrets.token_hex(10)
    assert _upload(admin, _crafted(tmp_path, make_user, change), tid).status_code == 200
    r = admin.post("/api/admin/transfer/import", {"id": tid, "password": admin.password})
    assert _job(admin, r.json()["id"])["state"] == "done"
    with netmon.auth._conn() as c:
        row = c.execute("SELECT telegram_chat, telegram_on, ntfy_url, ntfy_on FROM users WHERE email = ?", (email,)).fetchone()
    assert row == ("123456789", 1, "https://ntfy.sh/prova-canali", 0)
