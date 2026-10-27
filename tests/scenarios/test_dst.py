"""Cambio dell'ora legale: i dati restano (istanti in UTC) e gli speedtest periodici restano all'ora scelta."""
from datetime import datetime
from zoneinfo import ZoneInfo

from conftest import netmon

ROME = ZoneInfo("Europe/Rome")


def at(y, mo, d, h, mi=0, fold=0):
    return datetime(y, mo, d, h, mi, fold=fold, tzinfo=ROME).timestamp()


def plan(monkeypatch, since, now, freq="24h", key="p_dst"):
    monkeypatch.setattr(netmon.registry, "keys_of", lambda owner: [key])
    monkeypatch.setattr(netmon, "speed_min_every", lambda owner: 60)
    monkeypatch.setattr(netmon, "speed_prefs", lambda owner: {"offset": 30, "alerts": {}})
    monkeypatch.setattr(netmon.auth, "get_user", lambda owner: {"tz": "Europe/Rome"})
    monkeypatch.setitem(netmon._speed, key, {"on": True, "freq": freq, "since": since})
    return netmon.speed_plan(1, now)[key]


def local(t):
    return datetime.fromtimestamp(t, ROME).strftime("%d/%m %H:%M")


def test_daily_test_keeps_its_hour_after_autumn_change(monkeypatch):
    since = at(2026, 10, 20, 3)                         # scelto in estate: ogni giorno alle 3:00
    last, nxt = plan(monkeypatch, since, at(2026, 10, 25, 12))
    assert (local(last), local(nxt)) == ("25/10 03:00", "26/10 03:00")
    last, nxt = plan(monkeypatch, since, at(2026, 11, 3, 2, 59))
    assert (local(last), local(nxt)) == ("02/11 03:00", "03/11 03:00")


def test_daily_test_keeps_its_hour_after_spring_change(monkeypatch):
    since = at(2026, 3, 20, 3)
    last, nxt = plan(monkeypatch, since, at(2026, 3, 30, 12))
    assert (local(last), local(nxt)) == ("30/03 03:00", "31/03 03:00")


def test_hourly_tests_in_repeated_hour_never_go_backwards(monkeypatch):
    since = at(2026, 10, 20, 0)
    prima = plan(monkeypatch, since, at(2026, 10, 25, 2, 30, fold=0), "1h")
    dopo = plan(monkeypatch, since, at(2026, 10, 25, 2, 30, fold=1), "1h")       # stessa ora, un'ora dopo
    assert prima[0] <= at(2026, 10, 25, 2, 30, fold=0) and dopo[0] <= at(2026, 10, 25, 2, 30, fold=1)
    assert dopo[0] >= prima[0] and dopo[1] > at(2026, 10, 25, 2, 30, fold=1)


def test_minute_steps_stay_in_seconds(monkeypatch):
    since = at(2026, 10, 25, 0)
    monkeypatch.setitem(netmon._speed, "p_m", {"on": True, "freq": "custom", "n": 90, "unit": "m", "since": since})
    monkeypatch.setattr(netmon.registry, "keys_of", lambda owner: ["p_m"])
    monkeypatch.setattr(netmon, "speed_min_every", lambda owner: 60)
    monkeypatch.setattr(netmon, "speed_prefs", lambda owner: {"offset": 30, "alerts": {}})
    monkeypatch.setattr(netmon.auth, "get_user", lambda owner: {"tz": "Europe/Rome"})
    last, nxt = netmon.speed_plan(1, since + 10 * 3600)["p_m"]
    assert nxt - last == 90 * 60 and (last - since) % (90 * 60) == 0
