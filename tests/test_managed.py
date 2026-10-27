"""Sonda gestita da un altro sistema (NETMON_MANAGED_BY, per esempio un'app che la contiene).

Lì aggiornamenti, riavvio, reti Wi-Fi e disinstallazione li fa quel sistema: la sonda lo dice al
server (system.managed_by) e risponde dicendo da dove farli; il server non le manda comandi che
fallirebbero sempre (né dalla pagina, né programmati, né automatici).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "probe"))
sys.dont_write_bytecode = True

import probe  # noqa: E402
import sysops  # noqa: E402

from conftest import PASSWORD, netmon  # noqa: E402

NAME = "Sistema di prova"
MANAGED_SYSTEM = {"version": "1.0.0", "managed_by": NAME, "remote_ops": False, "full_update": False}


@pytest.fixture
def managed(monkeypatch):
    """La sonda come la avvia un altro sistema (NETMON_MANAGED_BY)."""
    monkeypatch.setattr(sysops, "MANAGED_BY", NAME)
    probe._static.clear()
    probe._wifi_cache.clear()
    yield
    probe._static.clear()
    probe._wifi_cache.clear()


def test_probe_operations_say_where_to_do_them(managed):
    for ok, message in (sysops.reboot(), sysops.uninstall(), sysops.start_upgrade(),
                        sysops.start_wifi({"action": "add", "ssid": "Casa"}),
                        sysops.update_from_server("https://netmon.example.test/api/report", "t")[:2]):
        assert not ok
        assert NAME in message and "sudo" not in message
    assert sysops.wifi_problem() == "managed"


def test_probe_reports_managed_and_server_keeps_it(managed):
    info = probe.collect_system({"server_url": "https://netmon.example.test/api/report"})
    assert info["managed_by"] == NAME and info["os"] == NAME
    assert info["wifi_why"] == "managed" and not info["wifi_cmd"]
    assert not info["remote_ops"] and not info["full_update"]
    # il server tiene il campo (clean_system conserva al massimo 60 campi)
    assert netmon.clean_system(info)["managed_by"] == NAME


def test_probe_alone_is_not_managed():
    assert not sysops.MANAGED_BY
    probe._static.clear()
    probe._wifi_cache.clear()
    info = probe.collect_system({"server_url": "https://netmon.example.test/api/report"})
    assert "managed_by" not in info and info["wifi_why"] != "managed"


@pytest.fixture
def probes(make_user):
    """Un utente con una sonda gestita da un altro sistema e una che fa da sé, entrambe collegate."""
    u = make_user(plan="alto")
    gestita, sola = u.new_probe("gestita"), u.new_probe("da sola")
    assert gestita.report(system=MANAGED_SYSTEM).status_code == 200
    assert sola.report(system={"version": "1.0.0", "remote_ops": True, "full_update": True}).status_code == 200
    return u, gestita, sola


@pytest.mark.parametrize("command", ["update", "upgrade", "reboot"])
def test_server_refuses_commands_for_managed(probes, command):
    u, gestita, sola = probes
    r = u.post("/api/probe-command", {"probe": gestita.key, "command": command})
    assert r.status_code == 409 and NAME in r.json()["detail"]
    assert not netmon.monitor.state[gestita.key].get("command")
    assert u.post("/api/probe-command", {"probe": sola.key, "command": command}).status_code == 200


def test_server_refuses_wifi_for_managed(probes):
    u, gestita, _ = probes
    r = u.post("/api/probe-wifi", {"probe": gestita.key, "action": "add", "ssid": "Casa", "psk": "password123",
                                   "password": PASSWORD})
    assert r.status_code == 409 and NAME in r.json()["detail"]


def test_scheduled_update_skips_managed(probes):
    _, gestita, sola = probes
    s = {"id": "prova-gestita", "cmd": "update", "probes": [gestita.key, sola.key], "created_by": "prova"}
    result = netmon.sched_start_probes(s)
    assert "gestite da un altro sistema" in result and "gestita" in result
    assert not netmon.monitor.state[gestita.key].get("command")
    assert netmon.monitor.state[sola.key]["command"]["state"] == "pending"


def test_auto_update_skips_managed(probes, monkeypatch):
    u, gestita, sola = probes
    monkeypatch.setattr(netmon, "probe_dist_version", lambda: "9.9.9")
    started = netmon.auto_update_run({gestita.key: u.id, sola.key: u.id}, set(), set())
    assert started == [sola.key]
    assert not netmon.monitor.state[gestita.key].get("command")


def test_admin_list_marks_managed(probes, admin):
    _, gestita, sola = probes
    r = admin.get("/api/admin/probes")
    assert r.status_code == 200, r.text
    by_key = {p["key"]: p for p in r.json()["probes"]}
    assert by_key[gestita.key]["managed_by"] == NAME
    assert by_key[sola.key]["managed_by"] is None
