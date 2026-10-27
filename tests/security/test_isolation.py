"""Isolamento tra account: un utente non vede e non tocca le sonde, lo storico e gli eventi di un
altro, nemmeno conoscendo la chiave interna della sonda (p_xxxxxxxxxxxx), che compare negli URL.

Per ogni API che accetta una sonda si prova l'accesso «incrociato» (utente B sulla sonda di A) e si
controlla che: la risposta sia 404 (non rivela che la sonda esiste), lo stato di A non cambi, e la
risposta non contenga nulla di A.
"""
import io
import json
import time
import zipfile

import pytest

from conftest import netmon


def snapshot(key):
    p = netmon.monitor.state.get(key)
    return json.dumps(p, sort_keys=True, default=str), netmon.registry.owner_of(key), netmon.registry.name_of(key)


GET_ENDPOINTS = [
    "/api/history?probe={k}&device=dev0",
    "/api/traffic?probe={k}",
    "/api/fritz-history?probe={k}",
    "/api/wifi-history?probe={k}",
    "/api/sysmetrics?probe={k}",
]

POST_ENDPOINTS = [
    ("/api/order", lambda k, pw: {"probe": k, "order": ["dev1", "dev0"]}),
    ("/api/device/pause", lambda k, pw: {"probe": k, "device": "dev0", "hours": 1}),
    ("/api/device/resume", lambda k, pw: {"probe": k, "device": "dev0"}),
    ("/api/priority", lambda k, pw: {"probe": k, "device": "dev0", "prio": "mai"}),
    ("/api/probe-alerts", lambda k, pw: {"probe": k, "guest": True}),
    ("/api/probe-command", lambda k, pw: {"probe": k, "command": "reboot"}),
    ("/api/probe-speedtest", lambda k, pw: {"probe": k}),
    ("/api/probe-scan", lambda k, pw: {"probe": k, "device": "dev0"}),
    ("/api/probe-scan-cancel", lambda k, pw: {"probe": k, "device": "dev0"}),
    ("/api/probe-scan-daily", lambda k, pw: {"probe": k, "device": "dev0", "daily": True}),
    ("/api/probe-wifi", lambda k, pw: {"probe": k, "action": "add", "ssid": "rete", "psk": "12345678",
                                       "password": pw}),
    ("/api/probe-config", lambda k, pw: {"probe": k, "config": {
        "devices": {"spia": "8.8.8.8"}, "interval": 60, "ping_count": 1, "ping_timeout": 1, "fail_threshold": 3,
        "alert_mode": "fisso", "stale_factor": 2, "offline_factor": 3, "stale_seconds": 100,
        "offline_seconds": 200}}),
    ("/api/probes/rename", lambda k, pw: {"probe": k, "name": "rubata"}),
    ("/api/probes/pause", lambda k, pw: {"probe": k, "hours": 1}),
    ("/api/probes/resume", lambda k, pw: {"probe": k}),
    ("/api/probes/token", lambda k, pw: {"probe": k}),
    ("/api/probes/delete", lambda k, pw: {"probe": k, "password": pw}),
    ("/api/speedtest/settings", lambda k, pw: {"probes": [{"probe": k, "on": True, "freq": "24h"}]}),
]


@pytest.mark.parametrize("url", GET_ENDPOINTS)
def test_cross_user_reads_are_404(two_users, url):
    a, pa, b, pb = two_users
    r = b.get(url.format(k=pa.key))
    assert r.status_code == 404, r.text
    assert pa.key not in r.text
    # il proprietario invece legge
    assert a.get(url.format(k=pa.key)).status_code == 200


@pytest.mark.parametrize("url,body", POST_ENDPOINTS, ids=[u for u, _ in POST_ENDPOINTS])
def test_cross_user_writes_are_refused(two_users, url, body):
    a, pa, b, pb = two_users
    # Lo stato «di riposo» di A dipende dal tempo (last_seen): si confronta solo ciò che conta
    before = snapshot(pa.key)
    r = b.post(url, body(pa.key, b.password))
    assert r.status_code == 404, f"{url}: {r.status_code} {r.text}"
    assert snapshot(pa.key) == before, f"{url} ha cambiato la sonda di un altro utente"
    assert netmon.registry.owner_of(pa.key) == a.id
    # il token di A funziona ancora (nessuno l'ha rigenerato)
    assert pa.report().status_code == 200


def test_unknown_probe_key_same_answer_as_foreign(two_users):
    """Sonda inesistente e sonda di un altro: stessa risposta, non si scopre quali chiavi esistono."""
    a, pa, b, pb = two_users
    r1 = b.get(f"/api/history?probe={pa.key}&device=dev0")
    r2 = b.get("/api/history?probe=p_ffffffffffff&device=dev0")
    assert (r1.status_code, r1.json()) == (r2.status_code, r2.json())
    r1 = b.post("/api/probes/rename", {"probe": pa.key, "name": "x"})
    r2 = b.post("/api/probes/rename", {"probe": "p_ffffffffffff", "name": "x"})
    assert (r1.status_code, r1.json()) == (r2.status_code, r2.json())


def test_status_lists_only_own_probes(two_users):
    a, pa, b, pb = two_users
    sa, sb = a.get("/api/status").json(), b.get("/api/status").json()
    assert {p["name"] for p in sa["probes"]} == {pa.key}
    assert {p["name"] for p in sb["probes"]} == {pb.key}
    assert pa.key not in json.dumps(sb) and a.email not in json.dumps(sb)
    pl = b.get("/api/probes").json()
    assert [p["key"] for p in pl["probes"]] == [pb.key]


def test_events_are_per_account(two_users, server):
    a, pa, b, pb = two_users
    server.add_event("[PROVA] evento segreto di A", "dettaglio", True, pa.key)
    server.add_event("[PROVA] evento di B", "", True, pb.key)
    server.add_event("[VM] evento amministrativo", "", True, None)
    eb = b.get("/api/status?events=200").json()
    titles = [e["title"] for e in eb["events"]]
    assert "[PROVA] evento di B" in titles
    assert not any("segreto di A" in t or "amministrativo" in t for t in titles)
    # ricerca e filtri non escono dal proprio account
    eb = b.get("/api/status", params={"events_q": "segreto", "events_tags": "PROVA,VM"}).json()
    assert eb["events_total"] == 0
    # cancellare gli eventi di A per id, o «tutti», non tocca A
    with server.db() as conn:
        ids = [r[0] for r in conn.execute("SELECT rowid FROM events WHERE probe = ?", (pa.key,))]
        vm_ids = [r[0] for r in conn.execute("SELECT rowid FROM events WHERE probe IS NULL")]
    assert b.post("/api/events/delete", {"ids": ids + vm_ids}).json()["deleted"] == 0
    b.post("/api/events/delete", {"all": True})
    with server.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM events WHERE probe = ?", (pa.key,)).fetchone()[0] == len(ids)
        assert conn.execute("SELECT COUNT(*) FROM events WHERE probe IS NULL").fetchone()[0] >= len(vm_ids)


def test_dashboard_and_speedtests_only_own(two_users):
    a, pa, b, pb = two_users
    d = b.get("/api/dashboard?range=24h").json()
    assert [p["probe"] for p in d["probes"]] == [pb.key]
    s = b.get("/api/speedtests").json()
    assert set(s["probes"]) == {pb.key}
    st = b.get("/api/speedtest/settings").json()
    assert [p["probe"] for p in st["probes"]] == [pb.key]


def test_backup_and_export_only_own(two_users):
    a, pa, b, pb = two_users
    bk = b.get("/api/backup")
    assert bk.status_code == 200
    assert pa.key not in bk.text and "sonda A" not in bk.text
    ex = b.get("/api/account/export")
    assert ex.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(ex.content))
    blob = b"".join(zf.read(n) for n in zf.namelist()).decode("utf-8", "replace")
    assert pa.key not in blob and a.email not in blob
    assert pb.key in blob and b.email in blob
    # nessun segreto nell'export: né token né impronte
    for secret in (pb.token, "scrypt$", netmon.hashlib.sha256(pb.token.encode()).hexdigest()):
        assert secret not in blob


def test_probe_token_writes_only_its_own_probe(two_users):
    """Il campo «probe» del report non decide dove finiscono i dati: decide il token."""
    a, pa, b, pb = two_users
    before_b = snapshot(pb.key)
    body = {"probe": pb.key, "interval": 60,
            "devices": {"iniettato": {"ok": False, "host": "10.0.0.66", "rtt": None}}}
    netmon.report_limit._state.pop(pa.key, None)
    r = pa.c.post("/api/report", json=body, headers=pa.headers)
    assert r.status_code == 200
    assert snapshot(pb.key) == before_b
    assert "iniettato" in netmon.monitor.state[pa.key]["devices"]
    with netmon.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM samples WHERE probe = ? AND device = 'iniettato'",
                            (pb.key,)).fetchone()[0] == 0


def test_probe_config_poll_bound_to_token(two_users):
    a, pa, b, pb = two_users
    r = pa.c.get(f"/api/probe-config?probe={pb.key}", headers=pa.headers)
    assert r.status_code == 200
    # risponde per la sonda del token (A), mai con la configurazione di B
    cfg_b = (netmon.monitor.state[pb.key].get("config") or {})
    assert json.dumps(cfg_b) == "{}" or r.json().get("config") != cfg_b


def test_backfill_bound_to_token(two_users):
    a, pa, b, pb = two_users
    body = {"probe": pb.key, "reports": [{"ts": time.time() - 30, "devices": {"riempito": True}}]}
    r = pa.c.post("/api/backfill", json=body, headers=pa.headers)
    assert r.status_code == 200, r.text
    with netmon.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM samples WHERE probe = ? AND device = 'riempito'",
                            (pb.key,)).fetchone()[0] == 0


def test_claim_foreign_probe_refused(two_users):
    a, pa, b, pb = two_users
    r = b.post("/api/probes/claim", {"token": pa.token})
    assert r.status_code == 404
    assert netmon.registry.owner_of(pa.key) == a.id


def test_rotated_token_stops_old_one(two_users):
    a, pa, b, pb = two_users
    r = a.post("/api/probes/token", {"probe": pa.key})
    assert r.status_code == 200
    old = pa.token
    pa.token = r.json()["token"]
    netmon.report_limit._state.clear()
    assert pa.c.post("/api/report", json={"probe": pa.key, "devices": {"x": True}},
                     headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert pa.report().status_code == 200


def test_delete_account_all_wipes_everything(client, make_user, server):
    u = make_user(plan="alto")
    p = u.new_probe()
    assert p.report().status_code == 200
    server.add_event("[PROVA] da cancellare", "", True, p.key)
    r = u.post("/api/auth/delete", {"password": u.password, "mode": "all", "confirm": "ELIMINA"})
    assert r.status_code == 200, r.text
    assert u.get("/api/status").status_code == 401
    assert p.key not in netmon.monitor.state
    assert not netmon.registry.exists(p.key)
    with server.db() as conn:
        for t in netmon.HISTORY_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {t} WHERE probe = ?", (p.key,)).fetchone()[0] == 0, t
    assert p.report().status_code == 401         # token revocato
    with netmon.auth._conn() as c:
        assert c.execute("SELECT COUNT(*) FROM users WHERE email = ?", (u.email,)).fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (u.id,)).fetchone()[0] == 0


def test_delete_account_keeps_probes_but_detaches(client, make_user, server):
    """Con mode=account le sonde restano senza proprietario: nessun altro utente le vede."""
    u = make_user(plan="alto")
    p = u.new_probe()
    assert p.report().status_code == 200
    r = u.post("/api/auth/delete", {"password": u.password, "mode": "account"})
    assert r.status_code == 200
    assert netmon.registry.owner_of(p.key) is None
    other = make_user(plan="alto")
    assert p.key not in json.dumps(other.get("/api/status").json())
    assert other.get(f"/api/history?probe={p.key}&device=dev0").status_code == 404


def test_new_user_does_not_inherit_orphans(client, make_user):
    """Un nuovo account non eredita le sonde di account eliminati."""
    u = make_user(plan="alto")
    p = u.new_probe()
    p.report()
    u.post("/api/auth/delete", {"password": u.password, "mode": "account"})
    v = make_user(plan="alto")
    assert v.get("/api/probes").json()["probes"] == []


def test_re_registration_same_email_does_not_see_old_probes(client, make_user):
    """Stessa email ri-registrata dopo l'eliminazione: account nuovo, nessun dato vecchio."""
    u = make_user(plan="alto")
    p = u.new_probe()
    p.report()
    u.post("/api/auth/delete", {"password": u.password, "mode": "account"})
    v = make_user(plan="alto", email=u.email)
    assert v.get("/api/probes").json()["probes"] == []
    assert v.get(f"/api/history?probe={p.key}&device=dev0").status_code == 404


def test_account_history_delete_only_own(two_users, server):
    a, pa, b, pb = two_users
    with server.db() as conn:
        before = conn.execute("SELECT COUNT(*) FROM samples WHERE probe = ?", (pa.key,)).fetchone()[0]
    assert before > 0
    r = b.post("/api/account/history/delete", {"password": b.password, "confirm": "ELIMINA"})
    assert r.status_code == 200
    with server.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM samples WHERE probe = ?", (pa.key,)).fetchone()[0] == before
        assert conn.execute("SELECT COUNT(*) FROM samples WHERE probe = ?", (pb.key,)).fetchone()[0] == 0


def test_retention_change_only_purges_own(two_users, server):
    a, pa, b, pb = two_users
    old = time.time() - 20 * 86400
    with server.db() as conn:
        conn.execute("INSERT INTO samples (ts, probe, device, ok, rtt) VALUES (?,?,?,?,?)", (old, pa.key, "vecchio", 1, 1.0))
        conn.execute("INSERT INTO samples (ts, probe, device, ok, rtt) VALUES (?,?,?,?,?)", (old, pb.key, "vecchio", 1, 1.0))
        conn.commit()
    r = b.post("/api/account/retention", {"unit": "giorni", "value": 1, "password": b.password})
    assert r.status_code == 200, r.text
    with server.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM samples WHERE probe = ? AND device='vecchio'", (pa.key,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM samples WHERE probe = ? AND device='vecchio'", (pb.key,)).fetchone()[0] == 0


def test_wifi_psk_never_in_status_or_export(two_users, server):
    """La password Wi-Fi chiesta per la sonda non resta nello stato né nelle risposte."""
    a, pa, b, pb = two_users
    pa.report(system={"wifi_cmd": True, "wifi_known": []})
    psk = "SegretissimaWifi99"
    r = a.post("/api/probe-wifi", {"probe": pa.key, "action": "add", "ssid": "casa", "psk": psk,
                                   "password": a.password})
    assert r.status_code == 200, r.text
    assert psk not in a.get("/api/status").text
    assert psk not in json.dumps(netmon.monitor.state, default=str)
    ex = a.get("/api/account/export")
    zf = zipfile.ZipFile(io.BytesIO(ex.content))
    assert psk.encode() not in b"".join(zf.read(n) for n in zf.namelist())
    # la riceve solo la sonda, con il suo token, una volta
    cfg = pa.c.get(f"/api/probe-config?probe={pa.key}", headers=pa.headers).json()
    assert psk in json.dumps(cfg)
    assert psk not in pb.c.get(f"/api/probe-config?probe={pa.key}", headers=pb.headers).text
