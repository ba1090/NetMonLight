"""Risorse del processo: ogni richiesta restituisce quello che prende (connessioni al database,
file aperti). Il garbage collector è spento durante la prova, così una connessione lasciata aperta
non viene «salvata» per caso: sotto carico, sulla VM, il collector passa troppo di rado."""
import gc
import os

from conftest import netmon


def open_fds():
    return len(os.listdir(f"/proc/{os.getpid()}/fd"))


def test_no_db_connection_leak(two_users):
    a, pa, b, pb = two_users
    gc.collect()
    gc.disable()
    try:
        start = open_fds()
        for i in range(40):
            pa.report()
            a.get("/api/status")
            a.get(f"/api/history?probe={pa.key}&device=dev0")
            a.get("/api/dashboard")
            a.get("/api/probes")
            a.post("/api/order", {"probe": pa.key, "order": []})
            b.get(f"/api/history?probe={pa.key}&device=dev0")          # 404
            pa.c.get(f"/api/probe-config?probe={pa.key}", headers=pa.headers)
        grown = open_fds() - start
    finally:
        gc.enable()
    assert grown < 10, f"{grown} descrittori in più dopo 320 richieste: connessioni non chiuse"


def test_connection_closed_after_with():
    with netmon.db() as conn:
        conn.execute("SELECT 1")
    try:
        conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        assert "closed" in str(exc).lower()
    else:
        raise AssertionError("la connessione resta aperta dopo il with")
    with netmon.auth._conn() as c:
        c.execute("SELECT 1")
    try:
        c.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        assert "closed" in str(exc).lower()
    else:
        raise AssertionError("la connessione di auth.db resta aperta dopo il with")
