"""Grafico del ping: disservizi notificati (dagli avvisi registrati) distinti dai ping persi senza avviso."""
import time

from conftest import netmon


def _fill(key, device, since, fails, events):
    """Un controllo al minuto per 2 ore; `fails` = minuti falliti; `events` = (minuto, titolo, corpo)."""
    with netmon.db() as conn:
        conn.executemany("INSERT INTO samples (ts, probe, device, ok, rtt) VALUES (?,?,?,?,?)",
                         [(since + m * 60, key, device, 0 if m in fails else 1, None if m in fails else 12.0)
                          for m in range(120)])
        conn.executemany("INSERT INTO events (ts, title, body, critical, recovery, probe) VALUES (?,?,?,0,0,?)",
                         [(since + m * 60 + 5, t, b, key) for m, t, b in events])


def _hist(u, key, device):
    r = u.get("/api/history", params={"probe": key, "device": device, "range": "6h"})
    assert r.status_code == 200, r.text
    return r.json()


def test_outage_from_alert_and_isolated_losses(make_user):
    u = make_user()
    p = u.new_probe("casa")
    assert p.report(n=1).status_code == 200
    since = time.time() - 3 * 3600
    _fill(p.key, "dev0", since, {10, 40, 41, 42, 43, 44, 80},
          [(42, "[ALERT] dev0 non risponde (casa)", ""), (45, "[OK] dev0 di nuovo raggiungibile (casa)", "")])
    h = _hist(u, p.key, "dev0")
    assert len(h["outages"]) == 1
    o = h["outages"][0]
    assert abs(o["start"] - (since + 40 * 60)) < 1 and abs(o["alert"] - (since + 42 * 60 + 5)) < 1
    assert abs(o["end"] - (since + 45 * 60 + 5)) < 1 and not o["ongoing"]
    assert h["alarm"]["threshold"] >= 1 and h["alarm"]["prio"] == "normale" and h["alarm"]["paused"] is False
    assert h["stats"]["lost"] == 7                     # i ping persi isolati restano nel conto


def test_ongoing_and_network_outage(make_user):
    u = make_user()
    p = u.new_probe("casa")
    assert p.report(n=2).status_code == 200
    since = time.time() - 3 * 3600
    # tutta la rete giù: vale anche per dev0; tornata la rete, dev1 resta giù fino al suo [OK]
    _fill(p.key, "dev0", since, set(range(20, 26)), [])
    _fill(p.key, "dev1", since, set(range(20, 30)) | set(range(100, 120)),
          [(22, "[CRITICO] Nessun dispositivo risponde (casa)", ""),
           (26, "[OK] La rete di 'casa' risponde di nuovo", "Almeno un dispositivo risponde di nuovo dopo 4 min. "
                                                           "Ancora non raggiungibili: dev1."),
           (30, "[OK] dev1 di nuovo raggiungibile (casa)", ""),
           (102, "[ALERT] dev1 non risponde (casa)", "")])
    d0 = _hist(u, p.key, "dev0")["outages"]
    assert len(d0) == 1 and abs(d0[0]["end"] - (since + 26 * 60 + 5)) < 1
    d1 = _hist(u, p.key, "dev1")["outages"]
    assert len(d1) == 2 and abs(d1[0]["end"] - (since + 30 * 60 + 5)) < 1
    assert d1[1]["ongoing"] is True                    # ancora giù: arriva fino a adesso


def test_names_are_matched_exactly(make_user):
    """«router» non prende gli avvisi di «router 2», e un nome con _ non fa da jolly."""
    u = make_user()
    p = u.new_probe("casa")
    assert p.report(n=1).status_code == 200
    since = time.time() - 3 * 3600
    _fill(p.key, "a_b", since, set(range(30, 35)),
          [(32, "[ALERT] axb non risponde (casa)", ""), (33, "[ALERT] a_b 2 non risponde (casa)", ""),
           (50, "[OK] axb di nuovo raggiungibile (casa)", "")])
    assert _hist(u, p.key, "a_b")["outages"] == []


def test_no_alert_no_outage(make_user):
    """Ping persi senza avviso (soglia non raggiunta, priorità Mai, sonda in pausa): nessun disservizio."""
    u = make_user()
    p = u.new_probe("casa")
    assert p.report(n=1).status_code == 200
    _fill(p.key, "dev0", time.time() - 3 * 3600, {5, 6, 50}, [])
    h = _hist(u, p.key, "dev0")
    assert h["outages"] == [] and h["stats"]["lost"] == 3
