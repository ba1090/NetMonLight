"""XSS nella pagina di stato e nel pannello, con un browser vero (Chromium headless).

Chi controlla la rete può scegliere testi che arrivano fino alla pagina: il nome di un dispositivo
sulla rete ospiti (lo legge il FRITZ!Box), il nome di un nodo mesh, l'SSID, il nome del server dello
speedtest, i servizi trovati dal controllo di sicurezza... E la CSP della pagina ammette gli script
in linea ('unsafe-inline'), quindi un <img onerror> inserito come HTML verrebbe ESEGUITO.

La prova riempie ogni campo libero con un frammento HTML che, se interpretato, scrive un segno su
window (top.X<n>=1), apre tutte le pagine e le schede (utente e amministratore) e controlla che
nessun segno compaia.
"""
import re
import secrets
import time

import httpx
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from live import LiveServer, make_account  # noqa: E402

pw = pytest.importorskip("playwright.sync_api")

PAYLOADS = {}


def P(field, short=False):
    """Frammento che segna l'esecuzione; diverso per campo, per sapere da dove viene."""
    n = len(PAYLOADS) + 1
    PAYLOADS[f"X{n}"] = field
    if short:                                        # campi da 40 caratteri
        return f"<img src=x onerror=top.X{n}=1>"
    return f"\"'><img src=x onerror=top.X{n}=1><svg onload=top.X{n}=1>"


@pytest.fixture(scope="module")
def poisoned():
    with LiveServer() as srv:
        db = srv.authdb()
        email, cookie, uid = make_account(srv, db, first=True, probes=5, fritz=10, devices=100)
        c = httpx.Client(base_url=srv.base, timeout=30, cookies={"netmon_session": cookie})
        r = c.post("/api/probes/new", json={"name": "sonda prova"})
        key, token = r.json()["key"], r.json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        dev = {P("nome dispositivo", True): {"ok": False, "host": P("host dispositivo"), "rtt": None},
               "normale": {"ok": True, "host": "192.168.1.2", "rtt": 3.0},
               "lento": {"ok": True, "host": "192.168.1.3", "rtt": 80.0}}
        fritz = {"ok": True, "connected": True, "name": P("nome fritz", True), "model": P("modello fritz"),
                 "os": P("versione fritz"), "external_ip": P("ip esterno"), "rate_down": P("rate come testo"),
                 "wlans": [{"ssid": P("ssid"), "band": P("banda", True), "clients": 2, "guest": True}],
                 "guests": [{"mac": "AA:BB:CC:DD:EE:01", "ip": P("ip ospite"), "name": P("nome ospite"),
                             "signal": P("segnale ospite")}],
                 "mesh": {"nodes": [{"name": P("nodo mesh", True), "model": P("modello mesh", True), "master": True,
                                     "clients": [{"name": P("client mesh", True), "band": "2,4 GHz", "rate": 1000}]},
                                    {"name": P("repeater", True), "model": "X", "master": False,
                                     "parent": P("parent mesh", True),
                                     "up": {"type": "Wi-Fi", "rate": 100000, "max": 200000, "signal": -60},
                                     "clients": [{"name": P("client rep", True), "band": "cavo"}]}]},
                 "fiber": {"state": P("stato fibra")},
                 "netdev": [{"name": P("nome disp. in rete"), "ip": "192.168.1.60", "on": True, "via": "wifi",
                             "band": P("banda disp.", True), "node": P("nodo disp.", True), "signal": -80, "rate": 20,
                             "model": P("modello disp.")},
                            {"name": P("disp. spento"), "ip": "192.168.1.61", "on": False, "model": P("modello spento")}]}
        boxes = [{"id": "b2", "name": P("nome fritz 2", True), "role": "main", "model": P("modello 2"),
                  "ok": True}, {"id": "rep", "name": P("nome rep", True), "role": "wifi", "ok": True}]
        system = {"hostname": P("hostname sonda"), "os": P("os sonda"), "model": P("modello pi"),
                  "speedtest": True, "scan": True, "wifi_cmd": True, "wifi_known": [P("rete nota", True)],
                  "ip": P("ip sonda"), "link": "wifi", "ssid": P("ssid sonda"), "version": P("versione sonda"),
                  "temp_c": 45.0, "load1": 0.5}
        cfg = {"devices": {"normale": "192.168.1.2", "lento": "192.168.1.3", "esterno": "example.com"},
               "interval": 60, "ping_count": 1, "ping_timeout": 1, "fail_threshold": 1, "alert_mode": "fisso",
               "stale_factor": 2, "offline_factor": 3, "stale_seconds": 100, "offline_seconds": 200,
               "probe_name": P("nome sonda (config)", True)}
        body = {"probe": key, "interval": 60, "devices": dev, "fritz": fritz, "fritz_boxes": boxes,
                "system": system, "config": cfg, "config_rev": 1,
                "traffic": [[time.time() - 30, 1e6, 5e6, 30]]}
        r = httpx.post(srv.base + "/api/report", json=body, headers=h, timeout=30)
        assert r.status_code == 200, r.text
        # i report seguenti rimandano tutto: un report senza FRITZ!Box lo toglierebbe dallo stato
        again = {k: body[k] for k in ("probe", "devices", "fritz", "fritz_boxes", "system")}
        again["config_rev"] = 1
        # speedtest e controllo di sicurezza chiesti dalla pagina, risultati «avvelenati» dalla sonda
        assert c.post("/api/probe-speedtest", json={"probe": key}).status_code == 200
        cfgp = httpx.get(srv.base + f"/api/probe-config?probe={key}", headers=h).json()
        sid = cfgp["speedtest"]["id"]
        r = httpx.post(srv.base + "/api/report", headers=h, json={
            **again,
            "speedtest": {"id": sid, "ok": True, "down_mbps": 100, "up_mbps": 20, "ping_ms": 9,
                          "server": P("server speedtest")}})
        assert r.status_code == 200, r.text
        assert c.post("/api/probe-scan", json={"probe": key, "device": "normale"}).status_code == 200
        scan = httpx.get(srv.base + f"/api/probe-config?probe={key}", headers=h).json()["scan"]
        r = httpx.post(srv.base + "/api/report", headers=h, json={
            **again,
            "scan": {"id": scan["id"], "ok": True, "ip": P("ip scan"), "ports": [
                {"port": 23, "service": P("servizio", True), "risk": "alta", "note": P("nota porta")}]}})
        assert r.status_code == 200, r.text
        assert c.post("/api/probe-command", json={"probe": key, "command": "update"}).status_code == 200
        cmd = httpx.get(srv.base + f"/api/probe-config?probe={key}", headers=h).json()["command"]
        r = httpx.post(srv.base + "/api/report", headers=h, json={
            **again,
            "command_status": {"id": cmd["id"], "state": "error", "output": P("output comando"),
                               "version": P("versione comando")}})
        assert r.status_code == 200, r.text
        # pausa con nota: la nota la scrive l'utente, ma finisce nella pagina
        c.post("/api/device/pause", json={"probe": key, "device": "lento", "hours": 1, "note": P("nota pausa")})
        # amministratore: il pannello mostra email, sonde e dispositivi degli utenti
        login = f"admin-{secrets.token_hex(3)}@example.test"
        temp = "Provvisoria-" + secrets.token_hex(6)
        db.create_admin(login, temp, P("nome admin", True))
        yield srv, cookie, key, (login, temp)


def collect(page):
    return page.evaluate("Object.keys(window).filter(k => /^X\\d+$/.test(k))")


OPEN_ALL = "document.querySelectorAll('details').forEach(d => d.open = true)"


def visit_user(page, srv, cookie, key=None):
    page.context.add_cookies([{"name": "netmon_session", "value": cookie, "url": srv.base}])
    page.goto(srv.base + "/dashboard")
    page.wait_for_function("document.querySelector('#page-net') !== null")
    page.wait_for_timeout(1500)
    for js in ["showPage('dash')", "showPage('net', true, 'fritzbox')", "showPage('net', true, 'sonde')",
               "showPage('net', true, 'eventi')", "showPage('net', true, 'mappa')", "showPage('pi')",
               "showPage('set')"]:
        page.evaluate(js)
        page.wait_for_timeout(700)
        page.evaluate(OPEN_ALL)
        page.wait_for_timeout(200)
    for tab in ("view", "probes", "checks", "notify", "backup"):
        page.evaluate(f"showTab('{tab}')")
        page.wait_for_timeout(500)
    # dispositivi in rete: anche quelli spenti e la finestra di «+ Monitora»
    page.evaluate("showPage('net', true, 'fritzbox')")
    page.wait_for_timeout(500)
    page.evaluate("document.querySelectorAll('section.netdev .nd-foot input').forEach(c => c.click())")
    page.wait_for_timeout(300)
    for n in page.query_selector_all("section.netdev .mon button")[:2]:
        try:
            n.click(timeout=500)
            page.wait_for_timeout(300)
            page.evaluate("document.querySelectorAll('dialog[open]').forEach(d => d.close())")
        except Exception:  # noqa: BLE001
            pass
    # apre lo storico di ogni dispositivo cliccabile e lo scudo del controllo di sicurezza
    page.evaluate("showPage('net', true, 'sonde')")
    page.wait_for_timeout(500)
    if key:
        page.evaluate(f"openScan('{key}', 'normale')")
        page.wait_for_timeout(500)
        page.evaluate("document.querySelectorAll('dialog[open]').forEach(d => d.close())")
    for sel in (".dev", ".device", "[data-device]", ".shield", "button.scan"):
        for n in page.query_selector_all(sel)[:10]:
            try:
                n.click(timeout=500)
                page.wait_for_timeout(300)
                page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001 — non tutti sono cliccabili
                pass


def admin_cookie(srv, login, temp):
    import mfa  # noqa: PLC0415 (server/ è già nel path grazie a live.authdb)
    c = httpx.Client(base_url=srv.base, timeout=30)
    r = c.post("/api/admin/auth/login", json={"login": login, "password": temp})
    new = temp + "-n"
    r = c.post("/api/admin/auth/password", json={"current": temp, "new": new})
    r = c.post("/api/admin/auth/totp/begin", json={})
    secret = r.json()["secret"].replace(" ", "")
    r = c.post("/api/admin/auth/totp/confirm", json={"code": mfa.totp(secret, mfa.current_step())})
    assert r.json()["stage"] == "full", r.text
    return c.cookies.get("netmon_admin")


def test_no_script_runs_from_probe_data(poisoned):
    srv, cookie, key, (login, temp) = poisoned
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        dialogs = []
        page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        visit_user(page, srv, cookie, key)
        hit = collect(page)
        # il frammento deve comparire come TESTO (la pagina mostra i dati, non li interpreta)
        text = page.evaluate("document.body.innerText")
        b.close()
    assert not dialogs
    leaks = {k: PAYLOADS[k] for k in hit}
    assert not leaks, f"script eseguiti dalla pagina di stato: {leaks}"
    assert "onerror=top.X" in text, "i dati avvelenati non sono arrivati alla pagina: prova non significativa"
    assert not [e for e in errors if "X" in e and "onerror" in e]


def test_no_script_runs_in_admin_panel(poisoned):
    srv, cookie, key, (login, temp) = poisoned
    adm = admin_cookie(srv, login, temp)
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context()
        ctx.add_cookies([{"name": "netmon_admin", "value": adm, "url": srv.base + "/api/admin"}])
        page = ctx.new_page()
        page.goto(srv.base + "/admin")
        page.wait_for_timeout(2000)
        subs = page.evaluate("Object.fromEntries(Object.entries(SUBS).map(([k, v]) => [k, v.map(s => s.key)]))")
        for pg, keys in subs.items():
            for k in keys:
                page.evaluate(f"showPage('{pg}', true, '{k}')")
                page.wait_for_timeout(600)
        hit = collect(page)
        text = page.evaluate("document.body.innerText")
        b.close()
    leaks = {k: PAYLOADS[k] for k in hit}
    assert not leaks, f"script eseguiti dal pannello: {leaks}"
    assert key in text or "onerror=top.X" in text, "il pannello non mostra le sonde: prova non significativa"
