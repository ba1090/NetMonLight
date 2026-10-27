"""Impostazioni → Notifiche: interruttori dei canali e topic ntfy proposto."""
import re

from conftest import netmon


def _recipients(uid, monkeypatch):
    monkeypatch.setattr(netmon.registry, "owner_of", lambda key: uid)
    ok, to = netmon.recipients("p_x")
    assert ok
    return to


def test_switch_off_keeps_destination_but_sends_nothing(make_user, monkeypatch):
    u = make_user()
    monkeypatch.setattr(netmon, "check_public_https", lambda url: None)
    url = "https://ntfy.sh/netmon-prova1234567890"
    assert u.post("/api/account/notify", {"telegram_chat": "123456789", "ntfy_url": url,
                                          "telegram_on": True, "ntfy_on": True}).status_code == 200
    to = _recipients(u.id, monkeypatch)
    assert to["telegram_chat"] == "123456789" and to["ntfy_url"] == url

    assert u.post("/api/account/notify", {"telegram_chat": "123456789", "ntfy_url": url,
                                          "telegram_on": False, "ntfy_on": False}).status_code == 200
    to = _recipients(u.id, monkeypatch)
    assert to["telegram_chat"] == "" and to["ntfy_url"] == ""
    n = u.get("/api/account/notify").json()
    assert n["telegram_chat"] == "123456789" and n["ntfy_url"] == url      # restano salvati
    assert n["telegram_on"] is False and n["ntfy_on"] is False

    # senza i campi degli interruttori (client vecchi) restano come sono
    assert u.post("/api/account/notify", {"telegram_chat": "123456789", "ntfy_url": url}).status_code == 200
    assert _recipients(u.id, monkeypatch)["ntfy_url"] == ""


def test_ntfy_suggestion_stable_and_secret(make_user):
    a, b = make_user(), make_user()
    sa = a.get("/api/account/notify").json()["ntfy_suggest"]
    assert re.fullmatch(r"https://ntfy\.sh/netmon-[0-9a-z]{16}", sa)
    assert a.get("/api/account/notify").json()["ntfy_suggest"] == sa          # sempre lo stesso
    assert b.get("/api/account/notify").json()["ntfy_suggest"] != sa
    # non è un hash della sola email
    import hashlib
    assert hashlib.sha256(a.email.encode()).hexdigest()[:16] not in sa
    n = a.get("/api/account/notify").json()
    assert n["ntfy_url"] == "" and n["ntfy_on"] is False                        # proposto, non acceso
