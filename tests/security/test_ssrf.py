"""SSRF: gli indirizzi ntfy li sceglie l'utente, e il server li contatta. Non deve poter far
contattare al server servizi interni (127.0.0.1, la rete privata della VM, i metadati del
provider cloud su 169.254.169.254) né altri schemi (http, file).

check_public_https risolve il nome UNA volta e la connessione va a quell'IP (niente DNS
rebinding tra il controllo e la connessione)."""
import socket

import pytest

import notifier
from conftest import netmon


def fake_dns(*ips):
    return lambda host, port, **kw: [(socket.AF_INET6 if ":" in ip else socket.AF_INET, 1, 6, "", (ip, port))
                                     for ip in ips]


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254", "0.0.0.0",
                                "100.64.0.1", "::1", "fd00::1", "fe80::1", "::ffff:127.0.0.1"])
def test_internal_addresses_refused(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", fake_dns(ip))
    with pytest.raises(notifier.UnsafeUrl):
        notifier.check_public_https("https://ntfy.example.com/topic")


def test_mixed_public_and_private_refused(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", fake_dns("93.184.216.34", "10.0.0.1"))
    with pytest.raises(notifier.UnsafeUrl):
        notifier.check_public_https("https://ntfy.example.com/topic")


@pytest.mark.parametrize("url", ["http://ntfy.sh/x", "file:///etc/passwd", "gopher://x/", "https://user:pw@ntfy.sh/x",
                                 "https://ntfy.sh:99999/x", "https:///x", ""])
def test_bad_schemes_refused(monkeypatch, url):
    monkeypatch.setattr(socket, "getaddrinfo", fake_dns("93.184.216.34"))
    with pytest.raises(notifier.UnsafeUrl):
        notifier.check_public_https(url)


def test_public_ok_and_pinned(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", fake_dns("93.184.216.34"))
    u, port, ip = notifier.check_public_https("https://ntfy.example.com/topic")
    assert ip == "93.184.216.34" and port == 443


def test_account_refuses_internal_ntfy(make_user, monkeypatch):
    u = make_user()
    monkeypatch.setattr(socket, "getaddrinfo", fake_dns("169.254.169.254"))
    r = u.post("/api/account/notify", {"ntfy_url": "https://metadata.example.com/topic"})
    assert r.status_code == 422
    for bad in ("http://ntfy.sh/x", "https://ntfy.sh", "javascript:alert(1)", "https://a b/x"):
        assert u.post("/api/account/notify", {"ntfy_url": bad}).status_code == 422
    for chat in ("abc", "1; DROP", "12"):
        assert u.post("/api/account/notify", {"telegram_chat": chat}).status_code == 422
