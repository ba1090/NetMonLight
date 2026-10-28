"""Porte dei dispositivi quando il ping fallisce: la sonda prova solo le porte trovate aperte
dall'ultimo controllo di sicurezza, e solo per i dispositivi scelti; se una risponde, niente avviso."""
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "probe"))
sys.dont_write_bytecode = True

import probe  # noqa: E402

from conftest import netmon  # noqa: E402

CFG = {"devices": {"cam": "192.168.1.30", "nas": "192.168.1.10"}, "interval": 60, "ping_count": 1, "ping_timeout": 1,
       "fail_threshold": 2, "alert_mode": "proporzionale", "stale_factor": 1.5, "offline_factor": 3,
       "stale_seconds": 90, "offline_seconds": 180}


def setup(make_user):
    u = make_user()
    p = u.new_probe()
    r = p.report(devices={"cam": {"ok": True, "host": "192.168.1.30", "rtt": 3}, "nas": {"ok": True, "host": "192.168.1.10", "rtt": 2}},
                 config_rev=1, config=CFG, system={"scan": True, "scan_modes": True, "port_check": True})
    assert r.status_code == 200, r.text
    e = netmon.scan_entry(p.key)
    e["last"]["cam"] = {"finished": time.time(), "ok": True, "host": "192.168.1.30",
                        "ports": [{"port": 554, "service": "RTSP", "risk": "media", "note": ""},
                                  {"port": 80, "service": "HTTP", "risk": "media", "note": ""}]}
    return u, p


def state(u, p, dev):
    pr = [x for x in u.get("/api/status").json()["probes"] if x["name"] == p.key][0]
    return [d for d in pr["devices"] if d["name"] == dev][0]


def test_port_open_keeps_device_up_without_alert(make_user):
    u, p = setup(make_user)
    # senza attivarla: nessuna porta mandata alla sonda
    assert "port_check" not in p.report(devices={"cam": {"ok": True, "host": "192.168.1.30"}}).json()
    r = u.post("/api/probe-scan-portcheck", {"probe": p.key, "device": "cam", "on": True})
    assert r.status_code == 200, r.text
    reply = p.report(devices={"cam": {"ok": True, "host": "192.168.1.30"}}).json()
    assert reply["port_check"] == {"cam": [554, 80]}
    for _ in range(4):                                   # ben oltre la soglia di 2 ping falliti
        p.report(devices={"cam": {"ok": False, "host": "192.168.1.30", "port": 554}})
    d = netmon.monitor.state[p.key]["devices"]["cam"]
    assert not d["down"] and d["fails"] == 0 and d["port_ok"] == 554
    st = state(u, p, "cam")
    assert st["state"] == "warn" and "554" in st["text"], st
    # di nuovo il ping: torna normale
    p.report(devices={"cam": {"ok": True, "host": "192.168.1.30", "rtt": 3}})
    assert state(u, p, "cam")["state"] == "ok"


def test_port_not_in_list_or_not_enabled_counts_as_failure(make_user):
    u, p = setup(make_user)
    u.post("/api/probe-scan-portcheck", {"probe": p.key, "device": "cam", "on": True})
    for _ in range(3):
        p.report(devices={"cam": {"ok": False, "host": "192.168.1.30", "port": 22},      # porta mai vista aperta
                          "nas": {"ok": False, "host": "192.168.1.10", "port": 445}})    # prova non attiva
    devs = netmon.monitor.state[p.key]["devices"]
    assert devs["cam"]["down"] and devs["nas"]["down"]


def test_enable_needs_a_scan_with_open_ports(make_user):
    u, p = setup(make_user)
    r = u.post("/api/probe-scan-portcheck", {"probe": p.key, "device": "nas", "on": True})
    assert r.status_code == 409
    other = make_user()
    assert other.post("/api/probe-scan-portcheck", {"probe": p.key, "device": "cam", "on": True}).status_code == 404


def test_probe_tries_only_listed_ports_on_home_network(monkeypatch):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    try:
        probe.port_check_set({"cam": [1, port, "x", True, 70000], "nas": "no", 5: [80]})
        assert probe._port_check == {"cam": [1, port]}
        monkeypatch.setattr(probe, "scan_target", lambda host: "127.0.0.1")
        assert probe.port_check({"cam": "192.168.1.30", "nas": "192.168.1.10"}, ["cam", "nas"]) == {"cam": port}
        assert probe.port_check({"cam": "192.168.1.30"}, []) == {}            # risponde al ping: niente prove
        monkeypatch.undo()
        # indirizzo pubblico: la sonda non prova nulla
        assert probe.port_check({"cam": "8.8.8.8"}, ["cam"]) == {}
    finally:
        srv.close()
        probe.port_check_set({})
