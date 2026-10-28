"""Controllo degli accessi: chi non ha le credenziali giuste non legge e non cambia nulla.

- ogni rotta /api e /internal senza credenziali viene rifiutata (elenco generato dalle rotte
  dell'applicazione: una rotta nuova senza controllo fa fallire la prova);
- la sessione di un utente non apre il pannello di amministrazione e viceversa;
- la chiave del server e il token di una sonda non danno accesso alle API della pagina;
- un amministratore a metà accesso (password giusta, codice non ancora dato) non entra.
"""
import pytest
from fastapi.routing import APIRoute

from conftest import API_TOKEN, netmon

# Rotte pubbliche per scelta: sito di presentazione, pagine HTML senza dati, icone, stato dell'accesso, login/registrazione.
PUBLIC = {
    ("GET", "/"), ("GET", "/admin"), ("GET", "/dashboard"), ("GET", "/status"), ("GET", "/privacy"), ("GET", "/health"),
    ("GET", "/en/"), ("GET", "/de/"), ("GET", "/fr/"), ("GET", "/en"), ("GET", "/de"), ("GET", "/fr"),
    ("GET", "/robots.txt"), ("GET", "/sitemap.xml"), ("GET", "/favicon.svg"), ("GET", "/favicon.ico"),
    ("GET", "/favicon-32.png"), ("GET", "/apple-touch-icon.png"), ("GET", "/fonts/{name}"),
    ("GET", "/scarica-sonda"), ("GET", "/api/update-key"),
    ("GET", "/api/auth/state"), ("GET", "/api/admin/auth/state"),
    ("POST", "/api/auth/logout"), ("POST", "/api/admin/auth/logout"), ("POST", "/api/lang"),
}
# Rotte che rispondono a una credenziale nel corpo (token, codice, chiave della VM): senza, 4xx.
CREDENTIAL_IN_BODY = {
    "/api/auth/register", "/api/auth/login", "/api/auth/password", "/api/auth/delete",
    "/api/admin/auth/login", "/api/admin/auth/mfa", "/api/admin/auth/password",
    "/api/admin/auth/totp/confirm", "/api/admin/auth/totp/begin", "/api/admin/auth/mfa/email",
    "/api/report", "/api/backfill", "/api/vm/join", "/api/vm/notice", "/api/vm/where",
}


def all_routes():
    out = []
    for r in netmon.app.routes:
        if isinstance(r, APIRoute):
            for m in sorted(r.methods - {"HEAD"}):
                out.append((m, r.path))
    return out


def dummy_path(path):
    return path.replace("{name}", "x.woff2")


# Corpi plausibili: superano la validazione, così la risposta dipende solo dall'accesso.
SAMPLE_BODY = {
    "probe": "p_000000000000", "device": "dev0", "password": "x" * 12, "id": 1, "name": "x",
    "order": [], "prio": "alta", "command": "reboot", "action": "add", "ssid": "rete", "ids": [1],
    "all": True, "code": "123456", "email": "a@b.it", "token": "x", "lang": "it", "tz": "",
    "mode": "account", "unit": "giorni", "value": 1, "hours": 1, "daily": True, "auto": True,
    "chat": "", "ntfy": "", "notify_email": True, "current": "x" * 12, "new": "y" * 12,
}


@pytest.mark.parametrize("method,path", all_routes())
def test_route_requires_credentials(client, method, path):
    """Senza cookie, senza token: nessuna rotta riservata risponde 2xx."""
    if (method, path) in PUBLIC:
        pytest.skip("rotta pubblica per scelta")
    client.cookies.clear()
    r = client.request(method, dummy_path(path), json=SAMPLE_BODY if method == "POST" else None,
                       params={"probe": "p_000000000000", "device": "dev0", "id": "x"})
    assert r.status_code >= 400, f"{method} {path} risponde {r.status_code} senza credenziali: {r.text[:200]}"
    assert r.status_code < 500, f"{method} {path}: errore interno senza credenziali: {r.text[:200]}"


def test_public_routes_have_no_user_data(client, two_users):
    """Le pagine pubbliche sono gusci: non contengono email, chiavi di sonde o nomi di dispositivi."""
    a, pa, b, pb = two_users
    client.cookies.clear()
    for method, path in PUBLIC:
        if method != "GET":
            continue
        r = client.get(dummy_path(path))
        body = r.content.decode("utf-8", "replace")
        for secret in (a.email, b.email, pa.key, pb.key, pa.token, API_TOKEN):
            assert secret not in body, f"{path} contiene {secret!r}"


def test_multivm_routes_do_not_exist(client):
    """NetMon Light è un server solo: niente rotte del gateway né del collegamento di altre VM."""
    for path in ("/internal/status", "/internal/vms", "/internal/invites", "/internal/is-admin",
                 "/internal/has-user?email=a@b.it", "/internal/has-probe?h=" + "0" * 64, "/api/admin/vms"):
        r = client.get(path, headers={"X-Netmon-Gateway": "indovinata"})
        assert r.status_code == 404, path
    for path in ("/api/vm/join", "/api/vm/notice", "/api/vm/where", "/api/admin/move", "/api/admin/move/check",
                 "/api/admin/vms/token", "/api/admin/schedules/all"):
        assert client.post(path, json={}).status_code in (404, 405), path


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"])
def test_api_schema_not_published(client, path):
    """Nessuna documentazione automatica: lo schema elencherebbe tutte le rotte."""
    r = client.get(path)
    assert r.status_code == 404, f"{path}: {r.status_code}"
    assert "/internal/" not in r.text


def test_server_key_gives_no_ui_access(client, first_user):
    """La chiave del server non apre le API della pagina (né come cookie né come Bearer)."""
    for h in ({"Authorization": f"Bearer {API_TOKEN}"}, {"Cookie": f"{netmon.COOKIE}={API_TOKEN}"}):
        assert client.get("/api/status", headers=h).status_code == 401
        assert client.get("/api/probes", headers=h).status_code == 401
        assert client.get("/api/admin/overview", headers=h).status_code == 401


def test_server_key_cannot_register_after_first_user(client, first_user):
    r = client.post("/api/auth/register", json={"token": API_TOKEN, "email": "altro@example.test",
                                                 "password": "Password-Robusta-1"})
    assert r.status_code == 401


def test_server_key_refused_as_probe_token(client, two_users):
    a, pa, b, pb = two_users
    r = client.post("/api/report", json={"probe": pa.key, "devices": {"x": True}},
                    headers={"Authorization": f"Bearer {API_TOKEN}"})
    assert r.status_code == 401


def test_probe_token_gives_no_ui_access(client, two_users):
    a, pa, b, pb = two_users
    for h in ({"Authorization": f"Bearer {pa.token}"}, {"Cookie": f"{netmon.COOKIE}={pa.token}"}):
        assert client.get("/api/status", headers=h).status_code == 401
        assert client.get(f"/api/history?probe={pa.key}&device=dev0", headers=h).status_code == 401


def test_user_session_is_not_admin(client, two_users):
    a, pa, b, pb = two_users
    h = {"Cookie": f"{netmon.ADMIN_COOKIE}={a.cookie}"}
    assert client.get("/api/admin/overview", headers=h).status_code == 401
    assert a.get("/api/admin/overview").status_code == 401
    assert a.post("/api/admin/users/block", {"id": b.id, "password": a.password}).status_code == 401


def test_admin_session_is_not_user(client, admin):
    h = {"Cookie": f"{netmon.COOKIE}={admin.cookie}"}
    assert client.get("/api/status", headers=h).status_code == 401


def test_admin_half_login_cannot_use_panel(client, first_user):
    """Password giusta ma secondo fattore non dato: solo i passi dell'accesso, niente pannello."""
    login, temp = f"mezzo-{netmon.secrets.token_hex(3)}@example.test", "Provvisoria-1234abcd"
    netmon.auth.create_admin(login, temp)
    r = client.post("/api/admin/auth/login", json={"login": login, "password": temp})
    assert r.status_code == 200
    cookie = r.cookies.get(netmon.ADMIN_COOKIE)
    client.cookies.clear()
    h = {"Cookie": f"{netmon.ADMIN_COOKIE}={cookie}"}
    assert r.json()["stage"] == "password"
    for path in ("/api/admin/overview", "/api/admin/probes", "/api/admin/vm", "/api/admin/email"):
        assert client.get(path, headers=h).status_code == 403, path
    # anche dopo il cambio della password provvisoria serve l'app di autenticazione
    r = client.post("/api/admin/auth/password", json={"current": temp, "new": temp + "-x"}, headers=h)
    assert r.status_code == 200 and r.json()["stage"] == "setup"
    h = {"Cookie": f"{netmon.ADMIN_COOKIE}={r.cookies.get(netmon.ADMIN_COOKIE)}"}
    client.cookies.clear()
    assert client.get("/api/admin/overview", headers=h).status_code == 403


def test_admin_mfa_stage_rejects_wrong_and_replayed_codes(client, fresh_admin):
    """Con l'app attivata, a ogni accesso serve un codice; lo stesso codice non vale due volte."""
    admin = fresh_admin
    netmon.auth.create_admin(admin.login, admin.password)        # password provvisoria, app resta
    r = client.post("/api/admin/auth/login", json={"login": admin.login, "password": admin.password})
    h = {"Cookie": f"{netmon.ADMIN_COOKIE}={r.cookies.get(netmon.ADMIN_COOKIE)}"}
    client.cookies.clear()
    assert r.json()["stage"] == "mfa"
    assert client.get("/api/admin/overview", headers=h).status_code == 403
    assert client.post("/api/admin/auth/mfa", json={"code": "000000"}, headers=h).status_code == 401
    code = netmon.mfa.totp(admin.secret, netmon.mfa.current_step() + 1)
    assert client.post("/api/admin/auth/mfa", json={"code": code}, headers=h).status_code == 200
    # stesso codice in una nuova sessione: rifiutato (passo già usato)
    r = client.post("/api/admin/auth/login", json={"login": admin.login, "password": admin.password})
    h2 = {"Cookie": f"{netmon.ADMIN_COOKIE}={r.cookies.get(netmon.ADMIN_COOKIE)}"}
    client.cookies.clear()
    if r.json()["stage"] == "mfa":
        assert client.post("/api/admin/auth/mfa", json={"code": code}, headers=h2).status_code == 401


def test_forwarded_admin_headers_ignored(client, two_users):
    """Le intestazioni del vecchio gateway (X-Netmon-Admin…) non danno nessun accesso."""
    h = {"X-Netmon-Gateway": "qualunque", "X-Netmon-Admin": "finto@example.test", "X-Netmon-Pw-Checked": "1",
         "X-Forwarded-For": "10.0.0.1"}
    assert client.get("/api/admin/overview", headers=h).status_code == 401
    assert client.post("/api/admin/users/block", json={"id": 1, "password": "x"}, headers=h).status_code == 401


def test_vm_header_is_ignored(admin):
    """L'intestazione X-Netmon-VM non inoltra niente: la richiesta vale per questo server."""
    r = admin.get("/api/admin/overview", headers={"X-Netmon-VM": "vmfinta"})
    assert r.status_code == 200 and "vms" not in r.json()


def test_forged_session_cookies_rejected(client, two_users):
    a, pa, b, pb = two_users
    for raw in ("", "x", a.cookie[:-1], a.cookie + "x", "A" * 101, "' OR '1'='1", a.cookie.upper()):
        r = client.get("/api/status", headers={"Cookie": f"{netmon.COOKIE}={raw}"})
        assert r.status_code == 401, raw


def test_logout_revokes_session_server_side(client, make_user):
    u = make_user()
    old = u.cookie
    assert u.get("/api/status").status_code == 200
    assert u.post("/api/auth/logout", {}).status_code == 200
    assert client.get("/api/status", headers={"Cookie": f"{netmon.COOKIE}={old}"}).status_code == 401


def test_logout_all_revokes_every_session(client, make_user):
    u = make_user()
    r = client.post("/api/auth/login", json={"email": u.email, "password": u.password})
    other = r.cookies.get(netmon.COOKIE)
    client.cookies.clear()
    assert u.post("/api/auth/logout", {"all": True}).status_code == 200
    assert client.get("/api/status", headers={"Cookie": f"{netmon.COOKIE}={other}"}).status_code == 401


def test_password_change_revokes_other_sessions(client, make_user):
    u = make_user()
    r = client.post("/api/auth/login", json={"email": u.email, "password": u.password})
    other = r.cookies.get(netmon.COOKIE)
    client.cookies.clear()
    r = u.post("/api/auth/password", {"current": u.password, "new": "Nuova-Password-456!"})
    assert r.status_code == 200
    assert client.get("/api/status", headers={"Cookie": f"{netmon.COOKIE}={other}"}).status_code == 401
    assert client.get("/api/status", headers={"Cookie": f"{netmon.COOKIE}={u.cookie}"}).status_code == 401
    fresh = r.cookies.get(netmon.COOKIE)
    client.cookies.clear()
    assert client.get("/api/status", headers={"Cookie": f"{netmon.COOKIE}={fresh}"}).status_code == 200


def test_blocked_user_loses_access_immediately(client, make_user, admin):
    u = make_user()
    assert u.get("/api/status").status_code == 200
    r = admin.post("/api/admin/users/block", {"id": u.id, "password": admin.password})
    assert r.status_code == 200, r.text
    assert u.get("/api/status").status_code == 401
    r = client.post("/api/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 403


def test_expired_session_rejected(client, make_user):
    u = make_user()
    with netmon.auth._conn() as c:
        c.execute("UPDATE sessions SET expires = 1 WHERE id_hash = ?", (netmon.hashlib.sha256(u.cookie.encode()).hexdigest(),))
    assert u.get("/api/status").status_code == 401
