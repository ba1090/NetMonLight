"""Dashboard → Disponibilità: ping risposti e persi per casella, solo per le sonde dell'account."""
import time

from conftest import netmon


def _insert(probe, device, rows):
    with netmon.db() as conn:
        conn.executemany("INSERT INTO samples (ts, probe, device, ok, rtt) VALUES (?,?,?,?,?)",
                         [(t, probe, device, ok, 5.0 if ok else None) for t, ok in rows])


def test_cells_count_answered_and_lost(make_user):
    u = make_user()
    p = u.new_probe()
    assert p.report(n=1).status_code == 200
    now = time.time()
    _insert(p.key, "dev0", [(now - 3 * 3600, 1), (now - 3 * 3600 + 60, 0), (now - 10 * 3600, 0)])
    r = u.get(f"/api/availability?range=24h&n=48&off=60&d={p.key}%01dev0")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["n"] == 48 and j["bucket"] == 1800 and len(j["devices"][p.key + "\x01dev0"]) == 48
    cells = j["devices"][p.key + "\x01dev0"]
    assert sum(c[0] for c in cells) >= 1 and sum(c[1] for c in cells) == 2
    # caselle allineate alla mezz'ora nell'ora del browser (UTC+1)
    assert (j["until"] + 3600) % 1800 == 0 and j["until"] > now >= j["until"] - 1800
    # n non ammesso: torna quello predefinito; 7 giorni a 4 ore
    assert u.get(f"/api/availability?range=7d&n=5&d={p.key}%01dev0").json()["bucket"] == 4 * 3600


def test_other_users_probes_are_not_read(make_user):
    a, b = make_user(), make_user()
    p = a.new_probe()
    assert p.report(n=1).status_code == 200
    r = b.get(f"/api/availability?d={p.key}%01dev0")
    assert r.status_code == 200 and r.json()["devices"] == {}


def test_choice_saved_in_account(make_user):
    u = make_user()
    assert u.get("/api/status").status_code == 200
    body = {"avail": True, "avail_devs": ["p_x\x01NAS", "senza-separatore"], "avail_range": "7d"}
    assert u.post("/api/account/dash", body).status_code == 200
    d = netmon.auth.get_dash(u.id)
    assert d["avail_devs"] == ["p_x\x01NAS"] and d["avail_range"] == "7d"
    assert u.post("/api/account/dash", {"avail_range": "1 anno"}).status_code == 200
    d = netmon.auth.get_dash(u.id)
    assert d["avail_devs"] is None and d["avail_range"] == "24h"       # mai scelti: priorità Alta
