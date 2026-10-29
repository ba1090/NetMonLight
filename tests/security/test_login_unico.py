"""Schermata d'accesso unica (/dashboard): utenti e amministratori entrano dallo stesso modulo."""
from conftest import netmon


def test_admin_credentials_on_user_login_go_to_admin(client, fresh_admin):
    r = client.post("/api/auth/login", json={"email": fresh_admin.login, "password": fresh_admin.password})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["redirect"] == "/admin" and j["stage"] == "mfa"       # il codice dell'app lo chiede il pannello
    cookie = r.cookies.get(netmon.ADMIN_COOKIE)
    client.cookies.clear()
    assert cookie and not r.cookies.get(netmon.COOKIE)            # nessuna sessione da utente
    st = client.get("/api/admin/auth/state", headers={"Cookie": f"{netmon.ADMIN_COOKIE}={cookie}"}).json()
    assert st["stage"] == "mfa"


def test_wrong_admin_password_is_a_plain_failure(client, fresh_admin):
    r = client.post("/api/auth/login", json={"email": fresh_admin.login, "password": "sbagliata-123456"})
    assert r.status_code == 401
    assert "redirect" not in r.text and not r.cookies.get(netmon.ADMIN_COOKIE)


def test_user_credentials_stay_on_dashboard(client, make_user):
    u = make_user()
    r = client.post("/api/auth/login", json={"email": u.email, "password": u.password})
    client.cookies.clear()
    assert r.status_code == 200 and "redirect" not in r.json()


def test_user_and_admin_with_same_email(client, make_user):
    """Stessa email per un utente e un amministratore: la password dice dove si entra."""
    u = make_user()
    temp = "Provvisoria-Unica-123"
    netmon.auth.create_admin(u.email, temp, "Doppio")
    r = client.post("/api/auth/login", json={"email": u.email, "password": u.password})
    client.cookies.clear()
    assert r.status_code == 200 and "redirect" not in r.json()
    r = client.post("/api/auth/login", json={"email": u.email, "password": temp})
    client.cookies.clear()
    assert r.status_code == 200 and r.json()["redirect"] == "/admin" and r.json()["stage"] == "password"
