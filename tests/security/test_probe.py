"""Sonda (Raspberry Pi): cosa esegue e chi può cambiarle la configurazione.

- gli indirizzi dei dispositivi finiscono nella riga di comando di `ping`: niente che inizi con
  «-» (sarebbe un'opzione) o con caratteri da shell;
- la configurazione che arriva dal server è ricontrollata campo per campo (un server compromesso
  non deve poter far eseguire nulla alla sonda);
- il controllo di sicurezza (scansione delle porte) riguarda solo la rete di casa;
- tutto ciò che il server accetta, la sonda lo accetta: altrimenti la configurazione salvata sul
  server non arriva mai alla sonda e nessuno se ne accorge;
- la pagina locale (porta 8080) chiede la password, accetta solo la LAN e il nome giusto
  (DNS rebinding) e rifiuta le richieste da altri siti (CSRF).
"""
import base64
import importlib
import ipaddress
import os
import socket
import sys
import threading
from pathlib import Path

import httpx
import pytest
from hypothesis import given, settings, strategies as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "probe"))
sys.dont_write_bytecode = True

import probe  # noqa: E402

from conftest import netmon  # noqa: E402


@pytest.mark.parametrize("host", ["-f", "--flood", "-c1000000", "a;reboot", "$(id)", "`id`", "a b", "a|b",
                                  "a&&b", "fe80::1%eth0", "", " 192.168.1.1", "192.168.1.1\n", "x" * 300,
                                  "..", ".a", "-1.2.3.4"])
def test_probe_rejects_dangerous_hosts(host):
    assert not probe.valid_host(host)


@pytest.mark.parametrize("host", ["192.168.1.1", "10.0.0.1", "fritz.box", "nas.local", "2001:db8::1", "router"])
def test_probe_accepts_normal_hosts(host):
    assert probe.valid_host(host)


def test_clean_remote_rejects_bad_config():
    cfg = {"interval": 60}
    for devices in ({}, {"x": "-f"}, {"-x": "1.2.3.4"}, {"x": 5}, [("x", "1.2.3.4")], None,
                    {f"d{i}": "1.2.3.4" for i in range(201)}):
        with pytest.raises(ValueError):
            probe.clean_remote(cfg, {"devices": devices})
    out = probe.clean_remote(cfg, {"devices": {"a": "1.2.3.4"}, "interval": True, "ping_count": 999,
                                   "ping_timeout": "1; reboot", "probe_name": "$(id)", "token": "rubato",
                                   "server_url": "https://evil.example/api/report", "fritz_password": "x"})
    assert "interval" not in out and "ping_count" not in out and "ping_timeout" not in out
    assert "probe_name" not in out
    # server_url, token e credenziali FRITZ non si cambiano dal server
    assert not {"token", "server_url", "fritz_password"} & set(out)


@pytest.mark.parametrize("target", ["8.8.8.8", "1.1.1.1", "127.0.0.1", "169.254.1.1", "224.0.0.1", "0.0.0.0",
                                    "::1", "2001:4860:4860::8888", "::ffff:8.8.8.8", "100.64.0.1"])
def test_scan_only_home_network(target):
    with pytest.raises(ValueError):
        probe.scan_target(target)


def test_scan_hostname_resolving_outside_refused(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    with pytest.raises(ValueError):
        probe.scan_target("sembra-locale.lan")


@pytest.mark.parametrize("target", ["192.168.1.10", "10.1.2.3", "172.16.5.5", "fd00::5"])
def test_scan_allows_private(target):
    assert ipaddress.ip_address(probe.scan_target(target)).is_private


# --- server e sonda d'accordo --------------------------------------------------------------------

host_chars = st.text(alphabet="abcdef0123456789:.-xyzABC_ %;$", min_size=1, max_size=40)


@settings(max_examples=3000, deadline=None)
@given(host=host_chars)
def test_server_accepts_only_what_probe_accepts(host):
    """Un indirizzo che la pagina del server salva deve essere accettato anche dalla sonda."""
    from pydantic import ValidationError
    base = {"interval": 60, "ping_count": 1, "ping_timeout": 1, "fail_threshold": 3, "alert_mode": "fisso",
            "stale_factor": 2, "offline_factor": 3, "stale_seconds": 100, "offline_seconds": 200}
    try:
        netmon.ProbeConfig(**base, devices={"d": host})
    except ValidationError:
        return
    assert probe.valid_host(host), f"il server accetta {host!r} ma la sonda lo rifiuta"


# --- pagina locale della sonda -------------------------------------------------------------------

WEB_PW = "Pagina-Locale-Prova-1"


@pytest.fixture(scope="module")
def local_page(tmp_path_factory):
    d = tmp_path_factory.mktemp("sonda")
    cfg = d / "config.yaml"
    cfg.write_text("server_url: https://srv.example/api/report\ntoken: sonda_SEGRETO123\nprobe_name: casa\n"
                   "devices:\n  router: 192.168.1.1\nfritz_password: FritzSegreta\n")
    os.environ.update({"PROBE_CONFIG": str(cfg), "WEB_PASSWORD": WEB_PW, "WEB_ENV": str(d / "web.env")})
    cw = importlib.import_module("config_web")
    cw = importlib.reload(cw)
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), cw.Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    port = srv.server_address[1]
    yield cw, f"http://127.0.0.1:{port}", port
    srv.shutdown()


def auth(pw=WEB_PW):
    return {"Authorization": "Basic " + base64.b64encode(f"x:{pw}".encode()).decode()}


def test_local_page_requires_password(local_page):
    cw, base, port = local_page
    cw._auth_fails.clear()
    assert httpx.get(base + "/api/config").status_code == 401
    assert httpx.get(base + "/").status_code == 401
    assert httpx.get(base + "/api/config", headers=auth("sbagliata")).status_code == 401
    r = httpx.get(base + "/api/config", headers=auth())
    assert r.status_code == 200


def test_local_page_csp_only_its_scripts(local_page):
    """Pagina locale: niente 'unsafe-inline' per gli script, solo le impronte di quelli della pagina."""
    import hashlib
    import re
    cw, base, port = local_page
    cw._auth_fails.clear()
    r = httpx.get(base + "/", headers=auth())
    assert r.status_code == 200
    script_src = re.search(r"script-src([^;]*)", r.headers["content-security-policy"]).group(1)
    assert "unsafe-inline" not in script_src
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", r.text, re.S | re.I)
    assert scripts
    for sc in scripts:
        assert base64.b64encode(hashlib.sha256(sc.encode()).digest()).decode() in script_src


def test_local_page_masks_secrets(local_page):
    cw, base, port = local_page
    cw._auth_fails.clear()
    r = httpx.get(base + "/api/config", headers=auth())
    assert "SEGRETO123" not in r.text and "FritzSegreta" not in r.text


def test_local_page_dns_rebinding_refused(local_page):
    cw, base, port = local_page
    cw._auth_fails.clear()
    for host in ("evil.example.com", f"evil.example.com:{port}", "127.0.0.1.nip.io", "sonda.evil.com"):
        r = httpx.get(base + "/api/config", headers={**auth(), "Host": host})
        assert r.status_code == 403, host


def test_local_page_csrf_refused(local_page):
    cw, base, port = local_page
    cw._auth_fails.clear()
    body = {"field": "token"}
    r = httpx.post(base + "/api/reveal", json=body, headers={**auth(), "Origin": "http://evil.example.com"})
    assert r.status_code == 403
    # modulo HTML di un altro sito: non è JSON
    r = httpx.post(base + "/api/reveal", content="field=token",
                   headers={**auth(), "Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 400
    r = httpx.post(base + "/api/reveal", content='{"field":"token"}',
                   headers={**auth(), "Content-Type": "text/plain"})
    assert r.status_code == 400
    # dalla pagina stessa funziona
    r = httpx.post(base + "/api/reveal", json=body, headers={**auth(), "Origin": f"http://127.0.0.1:{port}"})
    assert r.status_code == 200 and "SEGRETO123" in r.text


def test_local_page_bruteforce_blocked(local_page):
    cw, base, port = local_page
    cw._auth_fails.clear()
    codes = []
    for i in range(cw.AUTH_MAX_FAILS + 2):
        codes.append(httpx.get(base + "/api/config", headers=auth(f"x{i}"), timeout=10).status_code)
    assert 429 in codes
    assert httpx.get(base + "/api/config", headers=auth()).status_code == 429   # anche con quella giusta
    cw._auth_fails.clear()


def test_local_page_headers(local_page):
    cw, base, port = local_page
    cw._auth_fails.clear()
    r = httpx.get(base + "/", headers=auth())
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_local_page_refuses_public_clients(local_page):
    """Un client con IP pubblico (porta 8080 inoltrata per errore dal router) viene rifiutato."""
    cw, base, port = local_page

    class Fake(cw.Handler):
        def __init__(self):
            self.client_address = ("8.8.8.8", 1234)
            self.headers = {"Host": "192.168.1.20"}
            self.sent = []

        def send_json(self, obj, code=200):
            self.sent.append(code)

        def _plain(self, code, text, extra=None):
            self.sent.append(code)
    h = Fake()
    assert h.allowed() is False and h.sent == [403]
