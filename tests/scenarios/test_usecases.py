"""Casi d'uso, dal più piccolo al più grande:

- account appena nato, 0 sonde: ogni pagina e API funziona e non mostra nulla di altri;
- piani basso / medio / alto: i limiti di sonde, FRITZ!Box e dispositivi valgono davvero;
- account grande: 50 sonde, 1000 dispositivi, 10 FRITZ!Box (piano personalizzato) — tutto
  arriva, tutto si vede, e le API restano veloci;
- limiti abbassati dall'amministratore: i dispositivi in più restano fuori senza perdere nulla.
"""
import io
import json
import time
import zipfile

import pytest

from conftest import netmon


def timed(fn):
    s = time.perf_counter()
    r = fn()
    return r, time.perf_counter() - s


def fritz_payload(name="FRITZ!Box 7590", guests=3):
    return {"ok": True, "connected": True, "name": name, "model": "7590", "rate_down": 50e6, "rate_up": 10e6,
            "max_down": 100e6, "max_up": 20e6, "lan_active": 4,
            "wlans": [{"ssid": "Casa", "band": "2,4 GHz", "clients": 5, "guest": False},
                      {"ssid": "Ospiti", "band": "5 GHz", "clients": guests, "guest": True}],
            "guests": [{"mac": f"AA:BB:CC:00:00:{i:02X}", "ip": f"192.168.179.{i + 10}", "name": f"ospite{i}"}
                       for i in range(guests)]}


# --- 0 sonde ---------------------------------------------------------------------------------------

def test_empty_account_everything_works(make_user):
    u = make_user()
    s = u.get("/api/status")
    assert s.status_code == 200 and s.json()["probes"] == [] and s.json()["events_total"] == 0
    assert u.get("/api/probes").json()["count"] == 0
    d = u.get("/api/dashboard")
    assert d.status_code == 200 and d.json()["probes"] == []
    assert u.get("/api/speedtests").json()["probes"] == {}
    assert u.get("/api/speedtest/settings").status_code == 200
    assert u.get("/api/account/notify").status_code == 200
    assert u.get("/api/account/retention").status_code == 200
    b = u.get("/api/backup")
    assert b.status_code == 200 and b.json()["probes"] == {}
    ex = u.get("/api/account/export")
    names = zipfile.ZipFile(io.BytesIO(ex.content)).namelist()
    assert set(names) == {"LEGGIMI.txt", "account.json", "sonde.json"}
    assert u.post("/api/events/delete", {"all": True}).json()["deleted"] == 0
    assert u.post("/api/account/history/delete", {"password": u.password, "confirm": "ELIMINA"}).json()["deleted"] == 0
    assert u.post("/api/speedtest/settings", {"probes": [], "offset": 30}).status_code == 200
    assert u.post("/api/account/layout", {"order": []}).status_code == 200
    r = u.post("/api/auth/delete", {"password": u.password, "mode": "all", "confirm": "ELIMINA"})
    assert r.status_code == 200


def test_new_account_default_plan_is_basso(make_user):
    u = make_user()
    lim = u.get("/api/probes").json()
    assert (lim["limit"], lim["fritz_limit"], lim["devices_limit"]) == netmon.PLANS["basso"]


def test_probe_created_but_never_connected(make_user):
    u = make_user()
    u.new_probe("mai collegata")
    pl = u.get("/api/probes").json()["probes"]
    assert pl[0]["connected"] is False
    assert u.get("/api/status").json()["probes"] == []
    assert u.get("/api/dashboard").json()["probes"][0]["devices"] == []


# --- piani ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("plan", ["basso", "medio", "alto"])
def test_plan_limits(make_user, plan):
    max_p, max_f, max_d = netmon.PLANS[plan]
    u = make_user(plan=plan)
    probes = [u.new_probe(f"s{i}") for i in range(max_p)]
    r = u.post("/api/probes/new", {"name": "una di troppo"})
    assert r.status_code == 409
    # ogni sonda manda 3 FRITZ!Box e 30 dispositivi: il server ne tiene solo quanti ne spettano
    for p in probes:
        body = {f"d{i:02d}": {"ok": True, "host": f"192.168.1.{i + 1}", "rtt": 1.0} for i in range(30)}
        cfg = {"devices": {k: v["host"] for k, v in body.items()}, "interval": 60, "ping_count": 1,
               "ping_timeout": 1, "fail_threshold": 3, "alert_mode": "fisso", "stale_factor": 2, "offline_factor": 3,
               "stale_seconds": 100, "offline_seconds": 200}
        assert p.report(devices=body, config=cfg, config_rev=1, fritz=fritz_payload(),
                        fritz_boxes=[{**fritz_payload(f"box{j}"), "id": f"b{j}", "role": "main"} for j in range(2)]
                        ).status_code == 200
        # seconda volta: ora la quota è nota e le misure in più vengono scartate
        assert p.report(devices=body, config=cfg, config_rev=1, fritz=fritz_payload(),
                        fritz_boxes=[{**fritz_payload(f"box{j}"), "id": f"b{j}", "role": "main"} for j in range(2)]
                        ).status_code == 200
    st = u.get("/api/status").json()["probes"]
    measured = sum(len([d for d in p["devices"] if not d.get("pending") and d["state"] != "off"]) for p in st)
    fritz = sum((1 if p["fritz"] else 0) + len(p["fritz_boxes"]) for p in st)
    assert measured <= max_d, (measured, max_d)
    assert fritz <= max_f, (fritz, max_f)
    # la configurazione consegnata alla sonda dice la sua quota
    for p in probes:
        cfg = netmon.config_for_probe(p.key, netmon.monitor.state[p.key]["config"])
        assert cfg["devices_max"] <= max(1, max_d) and cfg["fritz_max"] <= max(0, max_f - 1)


@pytest.mark.xfail(strict=True, reason="config_for_probe: con la quota a zero la sonda riceve TUTTI i dispositivi "
                                       "(il server scarta le misure, ma la sonda li pinga lo stesso)")
def test_probe_without_quota_gets_one_device(make_user):
    u = make_user(plan="medio")                    # 2 sonde, 15 dispositivi in tutto
    p1, p2 = u.new_probe("prima"), u.new_probe("seconda")
    base = {"interval": 60, "ping_count": 1, "ping_timeout": 1, "fail_threshold": 3, "alert_mode": "fisso",
            "stale_factor": 2, "offline_factor": 3, "stale_seconds": 100, "offline_seconds": 200}
    for p in (p1, p2):
        devs = {f"d{i:02d}": {"ok": True, "host": f"10.0.0.{i + 1}"} for i in range(15)}
        p.report(devices=devs, config={**base, "devices": {k: v["host"] for k, v in devs.items()}}, config_rev=1)
    cfg = netmon.config_for_probe(p2.key, netmon.monitor.state[p2.key]["config"])
    assert len(cfg["devices"]) <= cfg["devices_max"]


def test_config_over_limit_refused(make_user):
    u = make_user(plan="basso")
    p = u.new_probe()
    p.report(n=3)
    base = {"interval": 60, "ping_count": 1, "ping_timeout": 1, "fail_threshold": 3, "alert_mode": "fisso",
            "stale_factor": 2, "offline_factor": 3, "stale_seconds": 100, "offline_seconds": 200}
    ok = u.post("/api/probe-config", {"probe": p.key, "config": {**base, "devices": {f"d{i}": f"10.0.0.{i + 1}"
                                                                                  for i in range(5)}}})
    assert ok.status_code == 200
    r = u.post("/api/probe-config", {"probe": p.key, "config": {**base, "devices": {f"d{i}": f"10.0.0.{i + 1}"
                                                                                 for i in range(6)}}})
    assert r.status_code == 409


def test_limits_lowered_keep_data(make_user, admin):
    """L'amministratore abbassa i dispositivi: quelli in più restano salvati ma non controllati."""
    u = make_user(probes=1, fritz=1, devices=20)
    p = u.new_probe()
    devs = {f"d{i:02d}": {"ok": True, "host": f"10.0.0.{i + 1}", "rtt": 1.0} for i in range(20)}
    cfg = {"devices": {k: v["host"] for k, v in devs.items()}, "interval": 60, "ping_count": 1, "ping_timeout": 1,
           "fail_threshold": 3, "alert_mode": "fisso", "stale_factor": 2, "offline_factor": 3, "stale_seconds": 100,
           "offline_seconds": 200}
    assert p.report(devices=devs, config=cfg, config_rev=1).status_code == 200
    r = admin.post("/api/admin/users/limits", {"id": u.id, "password": admin.password, "max_probes": 1,
                                               "max_fritz": 1, "max_devices": 5, "plan": "personalizzato"})
    assert r.status_code == 200, r.text
    r = p.report(devices=devs, config_rev=1)
    assert r.status_code == 200
    reply = r.json()
    assert "config" in reply and len(reply["config"]["devices"]) == 5
    assert len(netmon.monitor.state[p.key]["config"]["devices"]) == 20        # nulla perso sul server
    # rialzato il limite, tornano tutti
    admin.post("/api/admin/users/limits", {"id": u.id, "password": admin.password, "max_probes": 1,
                                           "max_fritz": 1, "max_devices": 50, "plan": "personalizzato"})
    r = p.report(devices=devs, config_rev=reply["config_rev"])
    cfg2 = netmon.config_for_probe(p.key, netmon.monitor.state[p.key]["config"])
    assert len(cfg2["devices"]) == 20


# --- account grande: 50 sonde, 1000 dispositivi, 10 FRITZ!Box -----------------------------------

@pytest.fixture(scope="module")
def big_account(client, first_user):
    from conftest import User
    code = netmon.auth.create_invite("test")
    email = f"grande-{time.time_ns()}@example.test"
    r = client.post("/api/auth/register", json={"token": code, "email": email, "password": "Password-Robusta-1"})
    cookie = r.cookies.get(netmon.COOKIE)
    client.cookies.clear()
    u = User(client, email, "Password-Robusta-1", cookie, netmon.auth.session_user(cookie)["id"])
    netmon.auth.set_limits(u.id, 50, 10, 1000, "personalizzato")
    probes = [u.new_probe(f"sede {i:02d}") for i in range(50)]
    base = {"interval": 60, "ping_count": 1, "ping_timeout": 1, "fail_threshold": 3, "alert_mode": "fisso",
            "stale_factor": 2, "offline_factor": 3, "stale_seconds": 100, "offline_seconds": 200}
    t0 = time.perf_counter()
    for i, p in enumerate(probes):
        devs = {f"dev{j:02d}": {"ok": j % 7 != 0, "host": f"10.{i}.0.{j + 1}", "rtt": 2.0 + j} for j in range(20)}
        cfg = {**base, "devices": {k: v["host"] for k, v in devs.items()}}
        extra = {"fritz": fritz_payload(f"fritz-{i}")} if i < 10 else {}
        for _ in range(3):                      # 3 cicli: stato, quota e configurazione assestati
            assert p.report(devices=devs, config=cfg, config_rev=1, system={"temp_c": 50.0, "load1": 0.3},
                            traffic=[[time.time() - 10, 1e6, 2e6, 10]] if i < 10 else None, **extra).status_code == 200
    u.setup_seconds = time.perf_counter() - t0
    return u, probes


def test_big_account_everything_visible(big_account):
    u, probes = big_account
    (r, dt) = timed(lambda: u.get("/api/status"))
    assert r.status_code == 200
    st = r.json()
    assert len(st["probes"]) == 50
    assert sum(len(p["devices"]) for p in st["probes"]) == 1000
    assert sum(1 for p in st["probes"] if p["fritz"]) == 10
    assert all(p["devices_max"] >= 20 for p in st["probes"])
    assert dt < 2.0, f"/api/status con 50 sonde e 1000 dispositivi: {dt:.2f}s"


def test_big_account_latencies(big_account):
    u, probes = big_account
    times = {}
    for url in ("/api/status", "/api/probes", "/api/dashboard?range=24h", "/api/dashboard?range=30d",
                "/api/speedtests?days=30", "/api/speedtest/settings", "/api/backup",
                f"/api/history?probe={probes[0].key}&device=dev01&range=30d",
                f"/api/traffic?probe={probes[0].key}&range=7d", f"/api/fritz-history?probe={probes[0].key}",
                f"/api/wifi-history?probe={probes[0].key}", f"/api/sysmetrics?probe={probes[0].key}"):
        r, dt = timed(lambda: u.get(url))
        assert r.status_code == 200, (url, r.text[:200])
        times[url] = dt
    slow = {k: round(v, 2) for k, v in times.items() if v > 3.0}
    assert not slow, f"API lente con l'account grande: {slow}"


def test_big_account_report_cost(big_account):
    """Un report di una sonda dell'account grande: quanto costa (conta i giri su tutte le 50 sonde)."""
    u, probes = big_account
    p = probes[-1]
    devs = {f"dev{j:02d}": {"ok": True, "host": f"10.49.0.{j + 1}", "rtt": 2.0} for j in range(20)}
    ts = []
    for _ in range(10):
        r, dt = timed(lambda: p.report(devices=devs, config_rev=1))
        assert r.status_code == 200
        ts.append(dt)
    ts.sort()
    assert ts[len(ts) // 2] < 0.25, f"report mediano {ts[len(ts) // 2] * 1000:.0f} ms"


def test_big_account_limits_hold(big_account):
    u, probes = big_account
    assert u.post("/api/probes/new", {"name": "la 51esima"}).status_code == 409
    # 11° FRITZ!Box: la sonda 20 (senza FRITZ) prova ad aggiungerne uno, il server non lo tiene
    p = probes[20]
    devs = {f"dev{j:02d}": {"ok": True, "host": f"10.20.0.{j + 1}", "rtt": 2.0} for j in range(20)}
    assert p.report(devices=devs, config_rev=1, fritz=fritz_payload("undicesimo")).status_code == 200
    assert not netmon.monitor.state[p.key].get("fritz")
    # 1001° dispositivo: l'ultima sonda creata (a lei resta la parte finale del totale) ne chiede 21
    p0 = probes[-1]
    devs = {f"dev{j:02d}": {"ok": True, "host": f"10.49.0.{j + 1}", "rtt": 2.0} for j in range(21)}
    base = {"interval": 60, "ping_count": 1, "ping_timeout": 1, "fail_threshold": 3, "alert_mode": "fisso",
            "stale_factor": 2, "offline_factor": 3, "stale_seconds": 100, "offline_seconds": 200}
    r = u.post("/api/probe-config", {"probe": p0.key, "config": {**base, "devices": {k: v["host"] for k, v in devs.items()}}})
    assert r.status_code == 409


def test_big_account_export(big_account):
    u, probes = big_account
    r, dt = timed(lambda: u.get("/api/account/export"))
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    folders = {n.split("/")[0] for n in zf.namelist() if "/" in n}
    assert len(folders) == 50
    assert dt < 10, f"export dell'account grande: {dt:.1f}s"


def test_big_account_delete_all(big_account, server):
    u, probes = big_account
    keys = [p.key for p in probes]
    r, dt = timed(lambda: u.post("/api/auth/delete", {"password": u.password, "mode": "all", "confirm": "ELIMINA"}))
    assert r.status_code == 200
    with server.db() as conn:
        marks = ",".join("?" * len(keys))
        for t in netmon.HISTORY_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {t} WHERE probe IN ({marks})", keys).fetchone()[0] == 0
    assert not any(k in netmon.monitor.state for k in keys)
    assert dt < 15, f"eliminazione dell'account grande: {dt:.1f}s"
