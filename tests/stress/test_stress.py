"""Prove di carico (lente): pytest -m stress tests/stress

STRESS_SECONDS (predefinito 90) allunga la prova «sustained»; per una prova di ore usare
direttamente  python tests/stress/stress.py sustained --seconds 7200 --out <cartella>.
"""
import asyncio
import os

import pytest

import stress

pytestmark = pytest.mark.stress
SECONDS = int(os.getenv("STRESS_SECONDS", "90"))


def assert_healthy(res, p95_ms=None):
    assert not res.get("unexpected"), res["unexpected"][:5]
    log = res["server_log"]
    assert log["traceback"] == 0 and log["watchdog_errors"] == 0, log["tail"]
    for group, lat in (res.get("latency") or {}).items():
        five = {c: n for c, n in lat["codes"].items() if int(c) >= 500}
        assert not five, f"{group}: risposte 5xx {five}"
        if p95_ms and group in p95_ms:
            assert lat["p95_ms"] <= p95_ms[group], f"{group}: p95 {lat['p95_ms']} ms"


def test_sustained_mixed_population():
    res = asyncio.run(stress.sustained(seconds=SECONDS, scale=1.0))
    assert_healthy(res, {"probe:report": 1000, "ui:status:vuoto": 1000, "ui:status:basso": 1000,
                         "ui:status:grande": 3000})
    rss = [s["rss_mb"] for s in res["resources"]]
    assert max(rss) < stress.MEMORY_MAX_MB * 0.8, f"memoria {max(rss)} MB"
    fds = [s["fds"] for s in res["resources"]]
    assert fds[-1] - fds[0] < 100, f"file aperti in crescita: {fds[0]} → {fds[-1]}"
    assert res["health_after"] == 200


def test_login_storm_memory_bounded():
    res = asyncio.run(stress.login_storm(n=300))
    assert res["peak_rss_mb"] < stress.MEMORY_MAX_MB, res["peak_rss_mb"]
    assert_healthy(res)
    codes = res["latency"]["storm:login"]["codes"]
    assert set(codes) <= {"401", "429", 401, 429}, codes


def test_backfill_flood():
    res = asyncio.run(stress.backfill_flood(n_probes=50, batches=25))
    assert_healthy(res)
    assert res["rows_in_db"] >= 0.95 * res["reports_sent"] * 20
    assert res["peak_rss_mb"] < stress.MEMORY_MAX_MB


def test_big_chunked_bodies_without_credentials():
    """Corpi da 10 MB senza Content-Length e senza credenziali (Caddy li lascia passare fino a 10 MB)."""
    res = asyncio.run(stress.big_bodies(n=12, mb=10))
    assert res["health_after"] == 200
    assert res["peak_rss_mb"] < stress.MEMORY_MAX_MB, f"picco {res['peak_rss_mb']} MB con 12 richieste anonime"


def test_long_history():
    res = asyncio.run(stress.history(days=30, devices=200))
    assert_healthy(res)
    assert res["peak_rss_mb"] < stress.MEMORY_MAX_MB
