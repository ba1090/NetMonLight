"""Ambiente di prova di netmon: un server vero, con i dati in una cartella temporanea.

Il server (server/app.py) legge la configurazione all'import, quindi le variabili d'ambiente si
impostano qui prima di importarlo. Tutte le prove di una sessione condividono un solo server:
ogni prova crea i SUOI utenti e le SUE sonde (email e nomi casuali), così non si pestano i piedi.

Nessuna rete esterna: SMTP, Telegram e ntfy non sono configurati, quindi nessun avviso esce.
"""
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server"

_DATA = Path(tempfile.mkdtemp(prefix="netmon-test-"))
API_TOKEN = "chiave-server-" + secrets.token_urlsafe(16)
os.environ.update({
    "API_TOKEN": API_TOKEN,
    "DATA_DIR": str(_DATA),
    "COOKIE_SECURE": "0",
    "VM_ID": "",
    "ROLE": "",
    "GATEWAY_SECRET": "",
    "TRUSTED_PROXIES": "",
    "SMTP_HOST": "",
    "TELEGRAM_BOT_TOKEN": "",
    "NEW_USER_PLAN": "basso",
    "MIN_FREE_MB": "1",
    "SCRYPT_SLOTS": "4",
    "PUBLIC_URL": "https://netmon.example.test",
})
sys.path.insert(0, str(SERVER))

import app as netmon          # noqa: E402  (dopo le variabili d'ambiente)
import mfa                    # noqa: E402
from fastapi.testclient import TestClient   # noqa: E402

PASSWORD = "Password-Prova-123!"


@pytest.fixture(scope="session")
def data_dir():
    return _DATA


@pytest.fixture(scope="session")
def server():
    """Il modulo del server (per leggere stato e database dalle prove)."""
    return netmon


@pytest.fixture(scope="session")
def client():
    with TestClient(netmon.app, base_url="https://testserver") as c:
        yield c


def _reset_limits():
    for name in ("throttle", "account_throttle", "admin_throttle", "admin_pw_throttle", "admin_account_throttle"):
        t = getattr(netmon, name)
        t._fails.clear()
        t._busy.clear()
    for name in ("report_limit", "backfill_limit", "bulk_rows_limit"):
        getattr(netmon, name)._state.clear()


@pytest.fixture(autouse=True)
def _limits_reset():
    """I limiti dei tentativi sono per IP, e qui tutte le richieste vengono da «testclient»."""
    _reset_limits()
    yield


class User:
    """Un utente della pagina di stato con la sua sessione."""

    def __init__(self, client, email, password, cookie, uid):
        self.c, self.email, self.password, self.cookie, self.id = client, email, password, cookie, uid

    @property
    def headers(self):
        return {"Cookie": f"{netmon.COOKIE}={self.cookie}"}

    def get(self, url, **kw):
        return self.c.get(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def new_probe(self, name=None):
        r = self.post("/api/probes/new", {"name": name or "sonda " + secrets.token_hex(3)})
        assert r.status_code == 200, r.text
        return Probe(self.c, r.json()["key"], r.json()["token"], self)

    def set_limits(self, probes=None, fritz=None, devices=None, plan="personalizzato"):
        netmon.auth.set_limits(self.id, probes, fritz, devices, plan)


class Probe:
    def __init__(self, client, key, token, owner):
        self.c, self.key, self.token, self.owner = client, key, token, owner

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def report(self, devices=None, n=3, **extra):
        if devices is None:
            devices = {f"dev{i}": {"ok": True, "host": f"192.168.1.{i + 10}", "rtt": 1.5 + i} for i in range(n)}
        body = {"probe": self.key, "interval": 60, "devices": devices, **extra}
        netmon.report_limit._state.pop(self.key, None)
        return self.c.post("/api/report", json=body, headers=self.headers)


def new_email(tag="u"):
    return f"{tag}-{secrets.token_hex(5)}@example.test"


@pytest.fixture(scope="session")
def first_user(client):
    """Il primo account del server: nasce con la chiave del server (API_TOKEN)."""
    email = new_email("primo")
    r = client.post("/api/auth/register", json={"token": API_TOKEN, "email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    cookie = r.cookies.get(netmon.COOKIE)
    client.cookies.clear()
    uid = netmon.auth.session_user(cookie)["id"]
    return User(client, email, PASSWORD, cookie, uid)


@pytest.fixture
def make_user(client, first_user):
    """Nuovo utente registrato con un codice di accesso (come fa l'amministratore)."""
    def make(plan=None, password=PASSWORD, email=None, **limits):
        email = email or new_email()
        code = netmon.auth.create_invite("test", email=email)
        r = client.post("/api/auth/register", json={"token": code, "email": email, "password": password})
        assert r.status_code == 200, r.text
        cookie = r.cookies.get(netmon.COOKIE)
        client.cookies.clear()
        u = User(client, email, password, cookie, netmon.auth.session_user(cookie)["id"])
        if plan or limits:
            netmon.auth.set_limits(u.id, limits.get("probes"), limits.get("fritz"), limits.get("devices"),
                                   plan or "personalizzato")
        return u
    return make


@pytest.fixture
def two_users(make_user):
    """Due account con una sonda ciascuno, già collegata e con qualche misura."""
    a, b = make_user(plan="alto"), make_user(plan="alto")
    pa, pb = a.new_probe("sonda A"), b.new_probe("sonda B")
    assert pa.report().status_code == 200
    assert pb.report().status_code == 200
    return a, pa, b, pb


class Admin:
    def __init__(self, client, login, password, cookie):
        self.c, self.login, self.password, self.cookie = client, login, password, cookie

    @property
    def headers(self):
        return {"Cookie": f"{netmon.ADMIN_COOKIE}={self.cookie}"}

    def get(self, url, **kw):
        return self.c.get(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers={**self.headers, **kw.pop("headers", {})}, **kw)


def admin_login_full(client, login, password, secret=None):
    """Accesso completo dell'amministratore: password, cambio password provvisoria, TOTP."""
    r = client.post("/api/admin/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    cookie = r.cookies.get(netmon.ADMIN_COOKIE)
    client.cookies.clear()
    h = {"Cookie": f"{netmon.ADMIN_COOKIE}={cookie}"}
    stage = r.json()["stage"]
    if stage == "password":
        new = password + "-nuova"
        r = client.post("/api/admin/auth/password", json={"current": password, "new": new}, headers=h)
        assert r.status_code == 200, r.text
        cookie = r.cookies.get(netmon.ADMIN_COOKIE)
        client.cookies.clear()
        h = {"Cookie": f"{netmon.ADMIN_COOKIE}={cookie}"}
        password, stage = new, r.json()["stage"]
    if stage == "setup":
        r = client.post("/api/admin/auth/totp/begin", json={"password": ""}, headers=h)
        assert r.status_code == 200, r.text
        secret = r.json()["secret"].replace(" ", "")
        code = mfa.totp(secret, mfa.current_step())
        r = client.post("/api/admin/auth/totp/confirm", json={"code": code}, headers=h)
        assert r.status_code == 200, r.text
        stage = r.json()["stage"]
    if stage == "mfa":
        # un codice non ancora usato: il passo successivo (DRIFT = 1)
        code = mfa.totp(secret, mfa.current_step() + 1)
        r = client.post("/api/admin/auth/mfa", json={"code": code, "method": "app"}, headers=h)
        assert r.status_code == 200, r.text
        stage = r.json()["stage"]
    assert stage == "full", stage
    return Admin(client, login, password, cookie), secret


def _new_admin(client):
    login = new_email("admin")
    temp = "Provvisoria-" + secrets.token_hex(6)
    netmon.auth.create_admin(login, temp, "Admin di prova")
    adm, secret = admin_login_full(client, login, temp)
    adm.secret = secret
    return adm


@pytest.fixture(scope="session")
def admin(client, first_user):
    """Amministratore con accesso completo, condiviso: le prove non devono rovinargli la sessione."""
    return _new_admin(client)


@pytest.fixture
def fresh_admin(client, first_user):
    """Amministratore tutto suo, per le prove che ne cambiano password, sessioni o blocchi."""
    return _new_admin(client)


def wait_until(cond, timeout=5.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def pytest_configure(config):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "stress"))


def pytest_sessionfinish(session, exitstatus):
    import shutil
    shutil.rmtree(_DATA, ignore_errors=True)
