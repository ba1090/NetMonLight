"""Dispositivi in rete: la sonda unisce l'elenco del FRITZ!Box e la mappa mesh (senza inviare i MAC),
il server ripulisce i dati, li conserva fra un invio e l'altro e ricorda quando ha visto i dispositivi."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "probe"))
sys.dont_write_bytecode = True

import probe  # noqa: E402

from conftest import netmon  # noqa: E402

HOSTS = [
    {"MACAddress": "AA:AA:AA:AA:AA:01", "IPAddress": "192.168.178.10", "HostName": "NAS", "Active": "1",
     "InterfaceType": "Ethernet", "X_AVM-DE_Port": "2", "X_AVM-DE_Speed": "1000", "X_AVM-DE_Model": "DS220+"},
    {"MACAddress": "AA:AA:AA:AA:AA:02", "IPAddress": "192.168.178.44", "HostName": "iPhone", "Active": "1",
     "InterfaceType": "802.11", "X_AVM-DE_Speed": "0", "X_AVM-DE_Guest": "0"},
    {"MACAddress": "AA:AA:AA:AA:AA:03", "IPAddress": "192.168.178.22", "HostName": "Termostato", "Active": "1",
     "InterfaceType": "802.11", "X_AVM-DE_Speed": "26"},
    {"MACAddress": "AA:AA:AA:AA:AA:04", "IPAddress": "", "HostName": "iPad", "Active": "0", "InterfaceType": ""},
]


def topo():
    def node(uid, name, mac, role=None, ifaces=()):
        return {"uid": uid, "device_name": name, "device_mac_address": mac, "is_meshed": role is not None,
                "mesh_role": role or "unknown", "node_interfaces": list(ifaces)}

    def iface(uid, typ, name="", links=()):
        return {"uid": uid, "type": typ, "name": name, "node_links": list(links)}

    def link(a, b, rate=None, rcpi=None, typ="WLAN"):
        return {"uid": a + b, "node_interface_1_uid": a, "node_interface_2_uid": b, "state": "CONNECTED", "type": typ,
                "cur_data_rate_rx": rate, "cur_data_rate_tx": rate, "rx_rcpi": rcpi}
    l_phone = link("box-w5", "ph-w", 866000, 116)                    # -52 dBm
    l_rep = link("box-w5", "rep-w", 1200000, 140)
    l_term = link("rep-w24", "te-w", 26000, 62)                      # -79 dBm
    l_nas = link("box-lan", "nas-lan", 1000000, None, "LAN")
    return {"nodes": [
        node("box", "FRITZ!Box", "00:00:00:00:00:01", "master", [
            iface("box-w5", "WLAN", "AP:5G:0", [l_phone, l_rep]), iface("box-lan", "LAN", "LAN:2", [l_nas])]),
        node("rep", "Repeater Sala", "00:00:00:00:00:02", "slave", [
            iface("rep-w", "WLAN", "AP:5G:0", [l_rep]), iface("rep-w24", "WLAN", "AP:2G:0", [l_term])]),
        node("ph", "iPhone", "aa:aa:aa:aa:aa:02", None, [iface("ph-w", "WLAN", "", [l_phone])]),
        node("te", "Termostato", "aa:aa:aa:aa:aa:03", None, [iface("te-w", "WLAN", "", [l_term])]),
        node("nas", "NAS", "aa:aa:aa:aa:aa:01", None, [iface("nas-lan", "LAN", "", [l_nas])]),
    ]}


def test_probe_merges_hosts_and_mesh_without_macs():
    by_mac = {}
    probe.parse_mesh(topo(), by_mac)
    devs = probe.net_devices(HOSTS, by_mac)
    names = [d["name"] for d in devs]
    assert names[-1] == "iPad" and not devs[-1]["on"]                  # prima i collegati
    nas, phone, term = (next(d for d in devs if d["name"] == n) for n in ("NAS", "iPhone", "Termostato"))
    assert nas["via"] == "lan" and nas["port"] == 2 and nas["rate"] == 1000 and nas["model"] == "DS220+"
    assert phone["via"] == "wifi" and phone["node"] == "FRITZ!Box" and phone["signal"] == -52 and phone["rate"] == 866
    assert term["node"] == "Repeater Sala" and term["signal"] == -79 and term["rate"] == 26
    assert "aa:aa" not in repr(devs).lower() and "mac" not in repr(devs).lower()


def test_probe_without_mesh_uses_fritz_speed():
    devs = probe.net_devices(HOSTS, {})
    term = next(d for d in devs if d["name"] == "Termostato")
    assert term["via"] == "wifi" and term["rate"] == 26 and term["node"] is None


def test_server_cleans_keeps_and_remembers(two_users):
    a, pa, b, pb = two_users
    nasty = [{"name": "<img src=x>\u0000" + "x" * 100, "ip": "1.2.3.4; rm", "on": "yes", "via": "plc", "port": 999,
              "signal": 50, "rate": 10 ** 9, "model": 5, "guest": 1, "mac": "aa:bb"}] * 300
    good = [{"name": "TV", "ip": "192.168.178.50", "on": True, "via": "wifi", "band": "5 GHz", "node": "FRITZ!Box",
             "signal": -58, "rate": 390, "model": "", "guest": False}]
    assert pa.report(fritz={"ok": True, "netdev": good + nasty}).status_code == 200
    nd = netmon.monitor.state[pa.key]["fritz"]["netdev"]
    assert len(nd) == netmon.NETDEV_MAX and nd[0]["name"] == "TV" and nd[0]["rate"] == 390
    bad = nd[1]
    assert bad["ip"] == "" and bad["on"] is False and bad["via"] == "" and bad["port"] is None
    assert bad["signal"] is None and bad["rate"] is None and bad["model"] == "" and bad["guest"] is False
    assert len(bad["name"]) == 60 and "\u0000" not in bad["name"] and "mac" not in bad
    # report senza elenco (arriva ogni 5 minuti): resta quello di prima
    assert pa.report(fritz={"ok": True}).status_code == 200
    assert netmon.monitor.state[pa.key]["fritz"]["netdev"][0]["name"] == "TV"
    # spento: «visto» con l'ora dell'ultima volta che era collegato
    before = time.time()
    off = [{**good[0], "on": False, "rate": None}]
    assert pa.report(fritz={"ok": True, "netdev": off}).status_code == 200
    seen = netmon.monitor.state[pa.key]["fritz"]["netdev"][0]["seen"]
    assert before - 60 < seen <= before
    # lo vede solo il proprietario della sonda
    mine = next(p for p in a.get("/api/status").json()["probes"] if p["name"] == pa.key)
    assert mine["fritz"]["netdev"][0]["name"] == "TV"
    assert all(p["name"] != pa.key for p in b.get("/api/status").json()["probes"])
