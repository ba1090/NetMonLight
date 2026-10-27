"""Salvataggio dei dati: cosa resta sul disco e chi lo può leggere.

- password: solo impronte scrypt con sale diverso per ogni account;
- sessioni, token delle sonde, codici di accesso: solo impronte SHA-256 (il valore in chiaro esiste
  solo nel cookie o sulla sonda);
- file dei dati leggibili solo dall'utente del servizio (con UMask=0077 di netmon-server.service);
- password, token e password Wi-Fi non finiscono nei registri né nei file di stato;
- cookie HttpOnly, Secure e SameSite=Strict; intestazioni di sicurezza su ogni risposta.
"""
import hashlib
import logging
import os
import secrets
import sqlite3
import stat
import statistics
import sys
import time
from pathlib import Path

import httpx
import pytest

from conftest import API_TOKEN, PASSWORD, netmon

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from live import LiveServer, make_account  # noqa: E402


def dump_db(path):
    """Tutto il contenuto di un database SQLite, compresi WAL e pagine libere, come byte."""
    out = b""
    for p in (path, Path(str(path) + "-wal")):
        if p.exists():
            out += p.read_bytes()
    return out


def test_passwords_stored_as_scrypt_with_unique_salt(make_user, data_dir):
    u1, u2 = make_user(), make_user()          # stessa password per entrambi
    with netmon.auth._conn() as c:
        h1 = c.execute("SELECT pw_hash FROM users WHERE id = ?", (u1.id,)).fetchone()[0]
        h2 = c.execute("SELECT pw_hash FROM users WHERE id = ?", (u2.id,)).fetchone()[0]
    assert h1.startswith("scrypt$") and h2.startswith("scrypt$")
    algo, n, r, p, salt, dk = h1.split("$")
    assert int(n) >= 2 ** 15 and int(r) >= 8
    assert h1 != h2, "due account con la stessa password hanno la stessa impronta: sale mancante"
    raw = dump_db(data_dir / "auth.db")
    assert PASSWORD.encode() not in raw


def test_sessions_tokens_invites_stored_hashed(two_users, data_dir):
    a, pa, b, pb = two_users
    code = netmon.auth.create_invite("test")
    raw = dump_db(data_dir / "auth.db")
    for secret in (a.cookie, b.cookie, pa.token, pb.token, code):
        assert secret.encode() not in raw, "segreto in chiaro in auth.db"
    with netmon.auth._conn() as c:
        assert c.execute("SELECT 1 FROM sessions WHERE id_hash = ?",
                         (hashlib.sha256(a.cookie.encode()).hexdigest(),)).fetchone()
        assert c.execute("SELECT 1 FROM probes WHERE token_hash = ?",
                         (hashlib.sha256(pa.token.encode()).hexdigest(),)).fetchone()


def test_secrets_have_enough_entropy(two_users):
    a, pa, b, pb = two_users
    assert len(a.cookie) >= 40               # token_urlsafe(32): 256 bit
    assert pa.token.startswith("sonda_") and len(pa.token) >= 40
    code = netmon.auth.create_invite("test")
    assert len(code.removeprefix("accesso_")) >= 24


def test_secure_delete_enabled(data_dir):
    with netmon.auth._conn() as c:
        assert c.execute("PRAGMA secure_delete").fetchone()[0] == 1


def test_deleted_password_not_recoverable_from_file(make_user, data_dir):
    """Cambiata la password, la vecchia impronta non resta leggibile nel file (secure_delete)."""
    u = make_user()
    with netmon.auth._conn() as c:
        old = c.execute("SELECT pw_hash FROM users WHERE id = ?", (u.id,)).fetchone()[0]
    assert u.post("/api/auth/password", {"current": u.password, "new": "Altra-Password-789!"}).status_code == 200
    with netmon.auth._conn() as c:
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert old.encode() not in dump_db(data_dir / "auth.db")


def test_secrets_never_logged(client, make_user, caplog):
    caplog.set_level(logging.DEBUG)
    u = make_user()
    p = u.new_probe()
    p.report()
    client.post("/api/auth/login", json={"email": u.email, "password": "Sbagliata-123456"})
    client.post("/api/auth/login", json={"email": u.email, "password": u.password})
    client.cookies.clear()
    u.post("/api/probes/delete", {"probe": p.key, "password": "Sbagliata-999999"})
    text = caplog.text
    for secret in (u.password, "Sbagliata-123456", "Sbagliata-999999", p.token, u.cookie, API_TOKEN):
        assert secret not in text, f"segreto nei registri: {secret[:6]}…"


def test_session_cookie_flags(client, make_user, monkeypatch):
    u = make_user()
    monkeypatch.setattr(netmon, "COOKIE_SECURE", True)
    r = client.post("/api/auth/login", json={"email": u.email, "password": u.password})
    client.cookies.clear()
    sc = [v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith(netmon.COOKIE)][0].lower()
    assert "httponly" in sc and "secure" in sc and "samesite=strict" in sc and "path=/" in sc


def test_admin_cookie_scoped_to_admin_api(client, fresh_admin, monkeypatch):
    monkeypatch.setattr(netmon, "COOKIE_SECURE", True)
    r = client.post("/api/admin/auth/login", json={"login": fresh_admin.login, "password": fresh_admin.password})
    client.cookies.clear()
    sc = [v for k, v in r.headers.multi_items() if k == "set-cookie"][0].lower()
    assert "httponly" in sc and "secure" in sc and "samesite=strict" in sc and "path=/api/admin" in sc


def test_security_headers(client, two_users):
    a, pa, b, pb = two_users
    for url, html in (("/status", True), ("/admin", True), ("/api/status", False), ("/health", False)):
        r = a.get(url)
        h = r.headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"
        if html:
            csp = h["content-security-policy"]
            assert "frame-ancestors 'none'" in csp and "default-src 'self'" in csp
            assert "http:" not in csp and "*" not in csp
    assert a.get("/api/status").headers["cache-control"] == "no-store"
    assert a.get("/api/account/export").headers["cache-control"] == "no-store"


def test_export_temp_file_removed(two_users, data_dir):
    a, pa, b, pb = two_users
    assert a.get("/api/account/export").status_code == 200
    time.sleep(0.2)
    assert not list(data_dir.glob(".export-*.zip"))


def test_wifi_password_never_on_disk(two_users, data_dir):
    a, pa, b, pb = two_users
    pa.report(system={"wifi_cmd": True})
    psk = "WifiSulDisco-" + secrets.token_hex(4)
    a.post("/api/probe-wifi", {"probe": pa.key, "action": "add", "ssid": "casa", "psk": psk, "password": a.password})
    netmon.save_state()
    netmon.flush_state()
    for f in data_dir.rglob("*"):
        if f.is_file():
            assert psk.encode() not in f.read_bytes(), f"password Wi-Fi in {f.name}"


def test_login_timing_does_not_reveal_accounts(client, make_user):
    """Email esistente con password sbagliata e email inesistente: stessi tempi (impronta fittizia)."""
    u = make_user()

    def t(email):
        netmon.throttle._fails.clear()
        netmon.account_throttle._fails.clear()
        s = time.perf_counter()
        client.post("/api/auth/login", json={"email": email, "password": "Sbagliata-123456"})
        return time.perf_counter() - s
    known = [t(u.email) for _ in range(7)]
    unknown = [t(f"nessuno-{i}@example.test") for i in range(7)]
    mk, mu = statistics.median(known), statistics.median(unknown)
    assert abs(mk - mu) / max(mk, mu) < 0.5, (mk, mu)
    # e le risposte sono identiche
    netmon.throttle._fails.clear()
    r1 = client.post("/api/auth/login", json={"email": u.email, "password": "Sbagliata-123456"})
    r2 = client.post("/api/auth/login", json={"email": "nessuno@example.test", "password": "Sbagliata-123456"})
    assert (r1.status_code, r1.json()) == (r2.status_code, r2.json())


def test_bruteforce_login_blocked(client, make_user):
    u = make_user()
    codes = [client.post("/api/auth/login", json={"email": u.email, "password": f"Sbagliata-{i:06d}"}).status_code
             for i in range(8)]
    assert codes[:5] == [401] * 5 and set(codes[5:]) == {429}
    # anche con la password giusta, finché dura il blocco
    assert client.post("/api/auth/login", json={"email": u.email, "password": u.password}).status_code == 429
    client.cookies.clear()


def test_bruteforce_ipv6_counts_per_64(client, make_user, monkeypatch):
    """Chi ha una rete IPv6 /64 non ottiene tentativi nuovi cambiando indirizzo."""
    u = make_user()
    ips = iter(f"2001:db8:1:2::{i:x}" for i in range(1, 100))
    monkeypatch.setattr(netmon, "client_ip", lambda request: next(ips))
    codes = [client.post("/api/auth/login", json={"email": u.email, "password": f"Sbagliata-{i:06d}"}).status_code
             for i in range(8)]
    assert 429 in codes


def test_x_forwarded_for_not_trusted_from_outside(client, make_user):
    """X-Forwarded-For inventato da chi chiama non aggira il blocco (vale solo da un proxy fidato)."""
    u = make_user()
    codes = [client.post("/api/auth/login", json={"email": u.email, "password": f"Sbagliata-{i:06d}"},
                         headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code for i in range(8)]
    assert 429 in codes


def test_admin_bruteforce_lockout(client, fresh_admin):
    codes = [client.post("/api/admin/auth/login", json={"login": fresh_admin.login,
                                                        "password": f"Sbagliata-{i:06d}"}).status_code
             for i in range(8)]
    assert 429 in codes or 423 in codes
    client.cookies.clear()


def test_admin_sensitive_actions_need_password(admin, make_user):
    u = make_user()
    r = admin.post("/api/admin/users/block", {"id": u.id, "password": "sbagliata-123"})
    assert r.status_code == 401
    assert u.get("/api/status").status_code == 200


def test_files_private_under_service_umask(tmp_path):
    """Con UMask=0077 (netmon-server.service) nessun file dei dati è leggibile da altri utenti."""
    with LiveServer(data_dir=tmp_path / "data") as srv:
        db = srv.authdb()
        email, cookie, uid = make_account(srv, db, first=True, probes=2, fritz=2, devices=20)
        c = httpx.Client(base_url=srv.base, cookies={"netmon_session": cookie}, timeout=30)
        r = c.post("/api/probes/new", json={"name": "s1"})
        tok, key = r.json()["token"], r.json()["key"]
        httpx.post(srv.base + "/api/report", json={"probe": key, "devices": {"d": True}},
                   headers={"Authorization": f"Bearer {tok}"})
        c.get("/api/account/export")
        c.post("/api/speedtest/settings", json={"probes": [], "offset": 30})
        time.sleep(1)
    bad = []
    for f in (tmp_path / "data").rglob("*"):
        mode = stat.S_IMODE(f.stat().st_mode)
        if mode & 0o077:
            bad.append(f"{f.relative_to(tmp_path)} {oct(mode)}")
    assert not bad, f"file leggibili da altri utenti: {bad}"


def test_auth_db_private_even_without_umask(data_dir):
    """auth.db (impronte di password e sessioni) è 600 anche se il servizio parte senza UMask."""
    mode = stat.S_IMODE((data_dir / "auth.db").stat().st_mode)
    assert mode == 0o600, oct(mode)
