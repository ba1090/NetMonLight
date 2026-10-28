"""Dopo un aggiornamento o una ripartenza della sonda: 5 minuti prima di dirla in ritardo o muta."""
from conftest import netmon

M = netmon.monitor
G = netmon.RESTART_GRACE


def probe(now, **kw):
    p = {"interval": 60, "last_seen": now, "offline": False, "system": {"model": "Raspberry Pi Zero 2 W"}}
    p.update(kw)
    return p


def test_grace_after_update_done_lasts_five_minutes():
    now = 1_000_000.0
    p = probe(now, command={"cmd": "update", "state": "done", "requested": now - 200, "done_at": now})
    base = 60 * M.stale_factor
    assert M.restart_reason(p, now + 10) == "update"
    assert M.stale_after(p, now + 10) == base + G
    # 4 minuti di silenzio subito dopo l'aggiornamento: non è in ritardo, né irraggiungibile
    assert now + 240 - p["last_seen"] < M.stale_after(p, now + 240)
    # finita la finestra valgono le soglie di sempre
    assert M.restart_reason(p, now + G + 1) is None
    assert M.stale_after(p, now + G + 1) == base


def test_grace_after_any_restart_of_the_probe():
    now = 2_000_000.0
    p = probe(now, restart_at=now - 30)
    assert M.restart_reason(p, now) == "restart"
    assert M.offline_after(p, now) == 60 * M.heartbeat_factor + G
    assert M.restart_reason(probe(now, restart_at=now - G - 5), now) is None


def test_no_grace_without_restart():
    now = 3_000_000.0
    p = probe(now, command={"cmd": "update", "state": "error", "requested": now - 100, "done_at": now})
    assert M.restart_reason(p, now) is None
    assert M.stale_after(p, now) == 60 * M.stale_factor


def test_report_with_fresh_probe_records_restart_and_done_time():
    now = netmon.time.time()
    p = {"command": {"id": "abc", "cmd": "update", "state": "running", "requested": now - 60}}
    netmon.apply_command_status("k", p, {"id": "abc", "state": "done", "version": "x"})
    assert abs(p["command"]["done_at"] - now) < 5


def test_status_says_restarting_instead_of_late(make_user):
    u = make_user()
    p = u.new_probe()
    assert p.report(n=1, system={"probe_uptime": 20.0, "cpus": 4}).status_code == 200
    st = netmon.monitor.state[p.key]
    assert abs(st["restart_at"] - (netmon.time.time() - 20)) < 5
    st["last_seen"] -= 150                              # primo ciclo lento: 2 minuti e mezzo di silenzio
    mine = [x for x in u.get("/api/status").json()["probes"] if x["name"] == p.key][0]
    assert mine["state"] == "ok" and mine["text"].startswith("in ripartenza"), mine["text"]
    st["restart_at"] -= netmon.RESTART_GRACE           # finestra finita: torna «in ritardo»
    mine = [x for x in u.get("/api/status").json()["probes"] if x["name"] == p.key][0]
    assert mine["state"] == "warn" and mine["text"].startswith("in ritardo"), mine["text"]
