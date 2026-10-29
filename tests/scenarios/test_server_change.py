"""Indirizzo del server cambiato dalla pagina dell'utente: serve la password, la sonda prova il
nuovo indirizzo con il suo token e ci passa solo se quel server la riconosce."""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "probe"))
sys.dont_write_bytecode = True

import probe  # noqa: E402

from conftest import PASSWORD, netmon  # noqa: E402

SYS = {"server_change": True}


def setup(make_user):
    u = make_user()
    p = u.new_probe()
    assert p.report(n=1, system=SYS).status_code == 200
    return u, p


def test_request_needs_password_and_valid_https(make_user):
    u, p = setup(make_user)
    assert u.post("/api/probes/server", {"probe": p.key, "url": "vm2.example.net", "password": "sbagliata"}).status_code == 401
    r = u.post("/api/probes/server", {"probe": p.key, "url": "http://evil.example.com", "password": PASSWORD})
    assert r.status_code == 422 and "https" in r.json()["detail"]
    r = u.post("/api/probes/server", {"probe": p.key, "url": "vm2.example.net", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["url"] == "https://vm2.example.net/api/report"
    # un altro utente non può toccare la sonda
    other = make_user()
    assert other.post("/api/probes/server", {"probe": p.key, "url": "vm3.example.net", "password": PASSWORD}).status_code == 404


def test_probe_reports_success_then_server_acks(make_user):
    u, p = setup(make_user)
    u.post("/api/probes/server", {"probe": p.key, "url": "vm2.example.net", "password": PASSWORD})
    reply = p.report(n=1, system=SYS).json()
    req = reply["server_change"]
    assert req["url"] == "https://vm2.example.net/api/report"
    reply = p.report(n=1, system=SYS, server_change={"id": req["id"], "ok": True, "error": ""}).json()
    assert reply["server_change_ack"] == req["id"] and "server_change" not in reply
    pr = [x for x in u.get("/api/probes").json()["probes"] if x["key"] == p.key][0]
    assert pr["server_change"]["state"] == "done"


def test_probe_refusal_keeps_it_here(make_user):
    u, p = setup(make_user)
    u.post("/api/probes/server", {"probe": p.key, "url": "vm2.example.net", "password": PASSWORD})
    req = p.report(n=1, system=SYS).json()["server_change"]
    p.report(n=1, system=SYS, server_change={"id": req["id"], "ok": False, "error": "quel server non riconosce il token di questa sonda"})
    pr = [x for x in u.get("/api/probes").json()["probes"] if x["key"] == p.key][0]
    assert pr["server_change"]["state"] == "error" and "token" in pr["server_change"]["error"]


def test_managed_and_old_probes_are_refused(make_user):
    u = make_user()
    p = u.new_probe()
    p.report(n=1, system={})                                        # sonda vecchia
    assert u.post("/api/probes/server", {"probe": p.key, "url": "vm2.example.net", "password": PASSWORD}).status_code == 409
    p.report(n=1, system={"server_change": True, "managed_by": "Home Assistant"})
    r = u.post("/api/probes/server", {"probe": p.key, "url": "vm2.example.net", "password": PASSWORD})
    assert r.status_code == 409 and "Home Assistant" in r.json()["detail"]


def test_probe_switches_only_after_ack_and_only_if_accepted(tmp_path, monkeypatch):
    cfgf = tmp_path / "config.yaml"
    cfgf.write_text("server_url: https://vm1.example.net/api/report\ntoken: sonda_x\nprobe_name: casa\n")
    monkeypatch.setattr(probe, "CONFIG_PATH", str(cfgf))
    cfg = {"server_url": "https://vm1.example.net/api/report", "token": "sonda_x", "probe_name": "casa", "config_rev": 1}
    seen = []

    def fake(self, method, url, token=None, body=None, params=None, timeout=15):
        seen.append((url, token))
        if "vm9" in url:
            e = probe.HttpError("401 Unauthorized"); e.status = 401; raise e
        return {"config_rev": 1}
    monkeypatch.setattr(probe.Http, "request", fake)
    # rifiutato: non cambia nulla
    probe.server_change_requested({"id": "a", "url": "https://vm9.example.net/api/report"}, cfg)
    assert probe.server_change_status() == {"id": "a", "ok": False, "error": "quel server non riconosce il token di questa sonda"}
    assert probe.server_change_acked(cfg, "a") is False
    assert "vm1" in cfgf.read_text()
    # accettato: passa solo dopo la conferma del server attuale
    probe.server_change_requested({"id": "b", "url": "https://vm2.example.net/api/report"}, cfg)
    assert seen[-1] == ("https://vm2.example.net/api/probe-config", "sonda_x")
    assert probe.server_change_status()["ok"] is True and "vm1" in cfgf.read_text()
    assert probe.server_change_acked(cfg, "altro") is False
    assert probe.server_change_acked(cfg, "b") is True
    assert yaml.safe_load(cfgf.read_text())["server_url"] == "https://vm2.example.net/api/report"
    assert probe.server_change_status() is None
    # indirizzo in chiaro verso Internet: rifiutato senza nemmeno provarlo
    n = len(seen)
    probe.server_change_requested({"id": "c", "url": "http://evil.example.com/api/report"}, cfg)
    assert probe.server_change_status()["ok"] is False and len(seen) == n
    probe._server_change.clear()
