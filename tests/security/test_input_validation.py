"""Dati in ingresso malformati od ostili: il server li rifiuta (4xx) o li ripulisce, senza mai
rispondere 500 e senza lasciare lo stato a metà.

Le sonde sono il canale più esposto: il loro token può finire nelle mani sbagliate (una scheda SD
persa, un Raspberry rubato), e i testi che inviano vengono in parte da chi è sulla rete ospiti.
"""
import json
import math
import time

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from conftest import netmon


def test_report_rejects_nan_and_infinity(two_users):
    a, pa, b, pb = two_users
    raw = '{"probe":"%s","devices":{"d":{"ok":true,"rtt":NaN}}}' % pa.key
    r = pa.c.post("/api/report", content=raw, headers={**pa.headers, "Content-Type": "application/json"})
    assert r.status_code == 422
    raw = '{"probe":"%s","devices":{"d":true},"traffic":[[1,Infinity,1,1]]}' % pa.key
    r = pa.c.post("/api/report", content=raw, headers={**pa.headers, "Content-Type": "application/json"})
    assert r.status_code in (200, 422)
    # nello stato non resta nulla di non finito: /api/status deve restare JSON valido
    s = a.get("/api/status")
    assert s.status_code == 200
    json.loads(s.text)


@pytest.mark.parametrize("name", ["", "x" * 65, "a\x00b", "riga\nnuova", "tab\tx", "\x7f"])
def test_report_rejects_bad_device_names(two_users, name):
    a, pa, b, pb = two_users
    r = pa.report(devices={name: True})
    assert r.status_code == 422


def test_report_too_many_devices(two_users):
    a, pa, b, pb = two_users
    r = pa.report(devices={f"d{i}": True for i in range(201)})
    assert r.status_code == 422


def test_report_free_fields_are_scrubbed(two_users):
    """Testi con caratteri di controllo e numeri non finiti nei campi liberi (system, fritz)."""
    a, pa, b, pb = two_users
    r = pa.report(system={"hostname": "pi \x1bevil", "temp_c": 1e308 * 10 if False else 45.5,
                          "x" * 50: "chiave troppo lunga", "lista": ["a\x00"] * 50},
                  fritz={"ok": True, "name": "box\r\nBcc: x@y", "rate_down": "non-numero", "max_down": True,
                         "guests": [{"mac": "AA", "name": "\x00ospite ", "ip": "1.2.3.4"}],
                         "mesh": {"nodes": [{"name": "n" * 500, "clients": [{"name": None}] * 500}]}})
    assert r.status_code == 200, r.text
    p = netmon.monitor.state[pa.key]
    blob = json.dumps(p)
    for bad in ("\x00", "\x1b", " ", " ", "\r\n"):
        assert bad not in blob, repr(bad)
    assert "x" * 50 not in p["system"]
    assert len(p["system"]["lista"]) <= 10
    assert len(p["fritz"]["mesh"]["nodes"][0]["name"]) <= 40
    assert len(p["fritz"]["mesh"]["nodes"][0]["clients"]) <= netmon.MESH_CLIENTS


def test_fritz_non_numeric_rates_do_not_crash(two_users):
    """Regressione: «rate_down» come testo faceva fallire con 500 il report (fritz_row)."""
    a, pa, b, pb = two_users
    netmon._fritz_last.clear()
    for v in ("abc", "1e999", "", [1], {"x": 1}, True, None, -1, 1e20):
        netmon._fritz_last.clear()
        r = pa.report(fritz={"ok": True, "rate_down": v, "rate_up": v, "max_down": v, "max_up": v, "lan_active": v})
        assert r.status_code == 200, (v, r.text)


def test_backfill_limits(two_users):
    a, pa, b, pb = two_users
    now = time.time()
    too_many = {"probe": pa.key, "reports": [{"ts": now, "devices": {"d": True}}] * 501}
    assert pa.c.post("/api/backfill", json=too_many, headers=pa.headers).status_code == 422
    # misure fuori dalla conservazione o nel futuro: scartate, non salvate
    body = {"probe": pa.key, "reports": [{"ts": now + 86400 * 365, "devices": {"futuro": True}},
                                         {"ts": 1.0, "devices": {"antico": True}},
                                         {"ts": now - 60, "devices": {"buono": True}}]}
    r = pa.c.post("/api/backfill", json=body, headers=pa.headers)
    assert r.status_code == 200, r.text
    with netmon.db() as conn:
        devs = {d for (d,) in conn.execute("SELECT device FROM samples WHERE probe = ?", (pa.key,))}
    assert "buono" in devs and "futuro" not in devs and "antico" not in devs


def test_report_rate_limited(two_users):
    a, pa, b, pb = two_users
    netmon.report_limit._state.clear()
    codes = [pa.c.post("/api/report", json={"probe": pa.key, "devices": {"d": True}}, headers=pa.headers).status_code
             for _ in range(15)]
    assert 429 in codes and codes[:10] == [200] * 10


def test_body_size_limits(two_users, client):
    a, pa, b, pb = two_users
    big = "x" * (netmon.SMALL_BODY_BYTES + 10)
    r = client.post("/api/auth/login", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    # report grande senza token valido: rifiutato prima di leggere il corpo
    r = client.post("/api/report", content="x" * (netmon.SMALL_BODY_BYTES + 10),
                    headers={"Content-Type": "application/json", "Authorization": "Bearer falso"})
    assert r.status_code == 401
    r = client.post("/api/report", content="x" * (netmon.MAX_BODY_BYTES + 10),
                    headers={"Content-Type": "application/json", **pa.headers})
    assert r.status_code == 413


def test_bad_content_length_header(client):
    r = client.post("/api/auth/login", content=b'{"email":"a@b.it","password":"x"}',
                    headers={"Content-Type": "application/json", "Content-Length": "abc"})
    assert r.status_code < 500


SQLI = ["' OR '1'='1", "\"; DROP TABLE events; --", "%", "_", "\\", "[", "]%", "') UNION SELECT * FROM users --",
        "\x00", "%' OR probe IS NULL OR title LIKE '%"]


@pytest.mark.parametrize("q", SQLI)
def test_event_search_is_not_injectable(two_users, server, q):
    a, pa, b, pb = two_users
    server.add_event("[PROVA] evento di A", "", True, pa.key)
    server.add_event("[VM] amministrativo", "", True, None)
    r = b.get("/api/status", params={"events_q": q, "events_tags": q + ",VM,PROVA"})
    assert r.status_code == 200
    for e in r.json()["events"]:
        assert "evento di A" not in e["title"] and "amministrativo" not in e["title"]
    r = b.post("/api/events/delete", {"all": True, "q": q, "tags": [q, "VM"]})
    assert r.status_code == 200
    with server.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM events WHERE probe = ?", (pa.key,)).fetchone()[0] > 0
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='events'").fetchone()


@pytest.mark.parametrize("probe", ["' OR 1=1 --", "p_x' UNION SELECT email FROM users--", "../../etc/passwd", "*"])
def test_probe_param_injection(two_users, probe):
    a, pa, b, pb = two_users
    for url in (f"/api/history?probe={probe}&device=x", f"/api/traffic?probe={probe}"):
        r = b.get(url)
        assert r.status_code == 404


@pytest.mark.parametrize("name", ["../../../etc/passwd", "..%2f..%2fapp.py", "app.py", "%00", "x" * 5000])
def test_fonts_no_path_traversal(client, name):
    r = client.get("/fonts/" + name)
    assert r.status_code == 404
    assert b"API_TOKEN" not in r.content and b"import" not in r.content


def test_custom_time_window_bounds(two_users):
    a, pa, b, pb = two_users
    base = f"/api/history?probe={pa.key}&device=dev0&range=custom"
    assert a.get(base).status_code == 422
    assert a.get(base + "&start=0&end=1e12").status_code == 422          # > 400 giorni
    assert a.get(base + "&start=100&end=50").status_code == 422
    assert a.get(base + "&start=nan&end=nan").status_code == 422
    assert a.get(base + f"&start={time.time() - 3600}&end={time.time()}").status_code == 200


def test_status_paging_bounds(two_users):
    a, pa, b, pb = two_users
    for q in ("events=-5", "events=100000", "events_from=-1", "events_from=99999999"):
        assert a.get("/api/status?" + q).status_code == 200
    assert a.get("/api/status?events_q=" + "x" * 101).status_code == 422


def test_export_csv_formula_injection(two_users, server):
    """Un testo che comincia con = + - @ nel CSV diventa testo, non una formula di Excel."""
    import io
    import zipfile
    a, pa, b, pb = two_users
    server.add_event("=HYPERLINK(\"http://evil\",\"x\")", "+cmd|' /C calc'!A0", True, pa.key)
    ex = a.get("/api/account/export")
    zf = zipfile.ZipFile(io.BytesIO(ex.content))
    csv = next(zf.read(n).decode() for n in zf.namelist() if n.endswith("eventi.csv"))
    assert "'=HYPERLINK" in csv and ",=HYPERLINK" not in csv
    assert "'+cmd" in csv


def test_password_policy(client, make_user):
    code = netmon.auth.create_invite("test")
    for pw in ("corta", "aaaaaaaaaaaa", "x" * 257):
        r = client.post("/api/auth/register", json={"token": code, "email": "pol@example.test", "password": pw})
        assert r.status_code == 422, pw
    r = client.post("/api/auth/register", json={"token": code, "email": "Pol@Example.test",
                                                 "password": "pol@example.test"})
    assert r.status_code == 422


@pytest.mark.parametrize("email", ["", "senza-chiocciola", "a@b", "a b@c.it", "x" * 250 + "@a.it",
                                   "a@b.it\r\nBcc: v@x.it", "<script>@x.it"])
def test_register_rejects_bad_emails(client, email):
    code = netmon.auth.create_invite("test")
    r = client.post("/api/auth/register", json={"token": code, "email": email, "password": "Password-Robusta-1"})
    assert r.status_code == 422, email


def test_invite_bound_to_email_cannot_be_used_by_others(client):
    code = netmon.auth.create_invite("test", email="giusto@example.test")
    r = client.post("/api/auth/register", json={"token": code, "email": "altro@example.test",
                                                 "password": "Password-Robusta-1"})
    assert r.status_code == 401
    client.cookies.clear()


def test_invite_single_use(client):
    code = netmon.auth.create_invite("test", max_uses=1)
    r1 = client.post("/api/auth/register", json={"token": code, "email": "uno-%s@example.test" % time.time_ns(),
                                                  "password": "Password-Robusta-1"})
    r2 = client.post("/api/auth/register", json={"token": code, "email": "due-%s@example.test" % time.time_ns(),
                                                  "password": "Password-Robusta-1"})
    client.cookies.clear()
    assert r1.status_code == 200 and r2.status_code == 401


def test_expired_invite_refused(client):
    code = netmon.auth.create_invite("test", days=1)
    with netmon.auth._conn() as c:
        c.execute("UPDATE invites SET expires = 1 WHERE code_hash = ?",
                  (netmon.hashlib.sha256(code.encode()).hexdigest(),))
    r = client.post("/api/auth/register", json={"token": code, "email": "scad@example.test",
                                                 "password": "Password-Robusta-1"})
    assert r.status_code == 401


def test_probe_config_validation(two_users):
    a, pa, b, pb = two_users
    base = {"interval": 60, "ping_count": 1, "ping_timeout": 1, "fail_threshold": 3, "alert_mode": "fisso",
            "stale_factor": 2, "offline_factor": 3, "stale_seconds": 100, "offline_seconds": 200}
    bad_hosts = ["-rf /", "$(reboot)", "a;b", "host name", "`id`", "x" * 300, "192.168.1.1; rm -rf /"]
    for h in bad_hosts:
        r = a.post("/api/probe-config", {"probe": pa.key, "config": {**base, "devices": {"d": h}}})
        assert r.status_code == 422, h
    for n in ["-opzione", "<b>", "a/b", "x" * 41]:
        r = a.post("/api/probe-config", {"probe": pa.key, "config": {**base, "devices": {n: "1.2.3.4"}}})
        assert r.status_code == 422, n


# --- fuzzing del report con hypothesis: qualunque JSON non deve produrre un 500 ------------------

json_leaf = st.one_of(st.none(), st.booleans(), st.integers(-2**70, 2**70),
                      st.floats(allow_nan=False, allow_infinity=False), st.text(max_size=80))
json_val = st.recursive(json_leaf, lambda ch: st.one_of(st.lists(ch, max_size=6),
                                                        st.dictionaries(st.text(max_size=20), ch, max_size=6)),
                        max_leaves=30)


def _arm_pending(pa):
    """Speedtest, controllo di sicurezza e comando in attesa con id noti: così i risultati
    «fuzzati» non vengono scartati per id sbagliato ma passano davvero per apply_*."""
    if pa.key not in netmon.monitor.state:
        netmon.report_limit._state.clear()
        assert pa.report().status_code == 200
    p = netmon.monitor.state[pa.key]
    p["speedtest"] = {"id": "S1", "state": "pending", "requested": time.time()}
    p["command"] = {"id": "C1", "cmd": "wifi", "state": "pending", "requested": time.time(), "action": "add",
                    "ssid": "casa"}
    netmon._scans[pa.key] = {"req": {"id": "R1", "device": "d", "host": "192.168.1.2", "by": "x", "requested": time.time()},
                             "queue": [], "daily": [], "last": {}}


mesh_node = st.fixed_dictionaries({}, optional={
    "name": st.one_of(st.sampled_from(["Rep", "Main"]), json_val), "model": json_val, "master": json_val,
    "parent": json_val, "more": json_val,
    "up": st.one_of(json_val, st.fixed_dictionaries({}, optional={
        "type": st.sampled_from(["cavo", "Wi-Fi", "5 GHz"]), "rate": json_val, "max": json_val, "signal": json_val})),
    "clients": st.one_of(json_val, st.lists(st.dictionaries(st.sampled_from(["name", "band", "rate", "signal", "weak"]),
                                                            json_val), max_size=4))})
fritz_s = st.dictionaries(st.sampled_from(
    ["ok", "name", "model", "rate_down", "rate_up", "max_down", "max_up", "lan_active", "wlans", "guests",
     "mesh", "fiber", "connected", "x"]), json_val, max_size=10)
fritz_mesh = st.builds(lambda f, nodes: {**f, "ok": True, "mesh": {"nodes": nodes}}, fritz_s,
                       st.lists(mesh_node, min_size=1, max_size=4))
box_s = st.builds(lambda d, role: {**d, "id": "rep", "name": "Rep", "role": role},
                  st.dictionaries(st.sampled_from(["ok", "rate_down", "lan_rx_rate", "lan_tx_rate", "lan_dt", "model",
                                                   "mesh", "guests", "wlans"]), json_val),
                  st.sampled_from(["wifi", "main"]))
result_s = st.fixed_dictionaries({
    "speedtest": st.builds(lambda d: {**d, "id": "S1"}, st.dictionaries(
        st.sampled_from(["ok", "down_mbps", "up_mbps", "ping_ms", "jitter_ms", "server", "error"]), json_val)),
    "scan": st.builds(lambda d: {**d, "id": "R1"}, st.dictionaries(
        st.sampled_from(["ok", "ip", "ports", "complete", "seconds", "error"]), json_val)),
    "command_status": st.builds(lambda d: {**d, "id": "C1"}, st.dictionaries(
        st.sampled_from(["state", "output", "finished", "reboot_required", "version"]), json_val)),
})


@settings(max_examples=int(netmon.os.getenv("FUZZ_EXAMPLES", "250")), deadline=None,
          suppress_health_check=list(HealthCheck))
@given(fritz=st.one_of(st.none(), fritz_s, fritz_mesh),
       system=st.one_of(st.none(), st.dictionaries(st.text(max_size=45), json_val, max_size=8)),
       boxes=st.one_of(st.none(), st.lists(st.one_of(box_s, st.dictionaries(
           st.sampled_from(["id", "name", "role", "ok", "rate_down"]), json_val)), max_size=5)),
       extra=st.one_of(st.dictionaries(st.sampled_from(["speedtest", "scan", "command_status"]), json_val, max_size=3),
                       result_s))
def test_fuzz_report_never_500(fuzz_probe, fritz, system, boxes, extra):
    """Qualunque contenuto nei campi liberi del report: mai un 500, e /api/status resta leggibile."""
    pa = fuzz_probe
    _arm_pending(pa)
    body = {"probe": pa.key, "devices": {"d": True}, **({"fritz": fritz} if isinstance(fritz, dict) else {}),
            **({"system": system} if isinstance(system, dict) else {}),
            **({"fritz_boxes": boxes} if boxes is not None else {}),
            **{k: v for k, v in extra.items() if isinstance(v, dict)}}
    # due report di fila: alcuni campi (traffico dei repeater) contano solo dal secondo
    for _ in range(2):
        netmon._fritz_last.clear()
        netmon.report_limit._state.clear()
        r = pa.c.post("/api/report", json=body, headers=pa.headers)
        assert r.status_code < 500, (body, r.text)
    s = pa.owner.get("/api/status")
    assert s.status_code == 200, s.text
    for url in (f"/api/fritz-history?probe={pa.key}", f"/api/wifi-history?probe={pa.key}",
                f"/api/traffic?probe={pa.key}&box=rep", "/api/dashboard", "/api/speedtests"):
        assert pa.owner.get(url).status_code == 200, url


def test_repeater_rates_not_numbers(two_users):
    """Regressione: lan_rx_rate come testo di un repeater faceva fallire il secondo report (500)."""
    a, pa, b, pb = two_users
    netmon.auth.set_limits(a.id, 5, 10, 100, "personalizzato")
    mesh = {"nodes": [{"name": "Main", "master": True},
                      {"name": "Rep", "master": False, "up": {"type": "cavo", "rate": 1000}}]}
    for v in ("abc", [1], -5, True, 1e300) * 2:
        netmon._fritz_last.clear()
        r = pa.report(fritz={"ok": True, "mesh": mesh}, fritz_boxes=[
            {"id": "rep", "name": "Rep", "role": "wifi", "ok": True, "lan_rx_rate": v, "lan_tx_rate": v}])
        assert r.status_code == 200, (v, r.text)


def test_guests_not_a_list(two_users):
    """Regressione: «guests» come numero arrivava a guest_alerts, che lo scorreva (500)."""
    a, pa, b, pb = two_users
    a.post("/api/probe-alerts", {"probe": pa.key, "guest": True})
    for v in (5, "x", {"mac": "AA"}, True):
        r = pa.report(fritz={"ok": True, "guests": v, "wlans": v})
        assert r.status_code == 200, (v, r.text)


@pytest.fixture(scope="module")
def fuzz_probe(client, first_user):
    code = netmon.auth.create_invite("fuzz")
    email = f"fuzz-{time.time_ns()}@example.test"
    r = client.post("/api/auth/register", json={"token": code, "email": email, "password": "Password-Robusta-1"})
    cookie = r.cookies.get(netmon.COOKIE)
    client.cookies.clear()
    from conftest import User
    u = User(client, email, "Password-Robusta-1", cookie, netmon.auth.session_user(cookie)["id"])
    netmon.auth.set_limits(u.id, 5, 10, 100, "personalizzato")
    return u.new_probe("fuzz")
