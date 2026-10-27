"""Prove di carico di netmon su un server vero (uvicorn in un processo a parte).

Uso diretto (risultati in una cartella, con un riepilogo leggibile):

    python tests/stress/stress.py sustained --seconds 1800 --scale 1 --out /tmp/netmon-stress
    python tests/stress/stress.py login-storm
    python tests/stress/stress.py big-bodies
    python tests/stress/stress.py backfill-flood
    python tests/stress/stress.py history --days 30

Da pytest:  pytest -m stress tests/stress   (durata con STRESS_SECONDS, predefinita 90 s)

Scenario «sustained» (il principale): una popolazione mista di account, dal più piccolo al più
grande, che usa il server come nella realtà per tutto il tempo richiesto:

    profilo       account  sonde/acc  dispositivi/sonda  FRITZ!Box/sonda
    vuoto            20        0             -                 -
    basso            20        1             5                 1
    medio            10        2            7-8                1
    alto              5        4            11                 1
    grande            2       50            20       10 sonde con 1 FRITZ!Box

Ogni sonda manda un report ogni ~10 s (l'intervallo minimo reale) con ping, a volte guasti
(avvisi), FRITZ!Box con ospiti e traffico; chiede la configurazione come la sonda vera. Ogni
account con la pagina aperta la aggiorna ogni 5 s e ogni tanto apre grafici e Dashboard. In più,
in sottofondo: cambi di configurazione, pause, rinomine, login e logout, e un «curioso» che prova
password sbagliate e chiavi di sonde altrui (deve ricevere solo 401/404/429).

Durante la prova si misurano ogni 10 s memoria (RSS, il limite del servizio è MemoryMax=384M),
thread, file aperti e dimensione dei database; alla fine latenze per gruppo di API, codici di
risposta ed eventuali errori nel registro del server.
"""
import argparse
import warnings
import asyncio
import json
import os
import random
import secrets
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from live import PASSWORD, LiveServer  # noqa: E402

warnings.filterwarnings("ignore", message="Setting per-request cookies")
MEMORY_MAX_MB = 384               # MemoryMax di netmon-server.service

PROFILES = {          # nome: (account, sonde per account, dispositivi in tutto, FRITZ!Box in tutto, piano)
    "vuoto": (20, 0, 0, 0, "basso"),
    "basso": (20, 1, 5, 1, "basso"),
    "medio": (10, 2, 15, 2, "medio"),
    "alto": (5, 4, 45, 4, "alto"),
    "grande": (2, 50, 1000, 10, None),
}
CFG_BASE = {"interval": 10, "ping_count": 1, "ping_timeout": 1, "fail_threshold": 3, "alert_mode": "fisso",
            "stale_factor": 2, "offline_factor": 3, "stale_seconds": 60, "offline_seconds": 120}


class Stats:
    def __init__(self):
        self.lat = defaultdict(list)
        self.codes = defaultdict(Counter)
        self.errors = Counter()
        self.samples = []
        self.bad = []                  # risposte inattese (5xx, o 2xx dove serviva un rifiuto)

    def add(self, group, code, dt):
        self.lat[group].append(dt)
        self.codes[group][code] += 1
        if code >= 500:
            self.bad.append((group, code))

    def summary(self):
        out = {}
        for g, v in sorted(self.lat.items()):
            v = sorted(v)
            q = lambda p: v[min(len(v) - 1, int(p * len(v)))] * 1000   # noqa: E731
            out[g] = {"n": len(v), "p50_ms": round(q(.50), 1), "p95_ms": round(q(.95), 1),
                      "p99_ms": round(q(.99), 1), "max_ms": round(v[-1] * 1000, 1),
                      "codes": dict(self.codes[g])}
        return out


async def call(st, client, group, method, url, **kw):
    t = time.perf_counter()
    try:
        r = await client.request(method, url, **kw)
    except httpx.HTTPError as exc:
        st.errors[f"{group}: {type(exc).__name__}"] += 1
        st.add(group, 599, time.perf_counter() - t)
        return None
    st.add(group, r.status_code, time.perf_counter() - t)
    client.cookies.clear()          # ogni richiesta porta il SUO cookie: niente sessioni condivise per sbaglio
    return r


def fritz(i, guests):
    return {"ok": True, "connected": True, "name": f"FRITZ-{i}", "model": "7590", "rate_down": random.uniform(1e6, 9e7),
            "rate_up": random.uniform(1e5, 2e7), "max_down": 1e8, "max_up": 2e7, "lan_active": 3,
            "wlans": [{"ssid": "Casa", "band": "5 GHz", "clients": random.randint(0, 20), "guest": False},
                      {"ssid": "Ospiti", "band": "2,4 GHz", "clients": guests, "guest": True}],
            "guests": [{"mac": f"02:00:00:{i % 256:02X}:{g // 256:02X}:{g % 256:02X}", "ip": f"192.168.179.{g + 2}",
                        "name": f"ospite-{g}"} for g in range(guests)]}


class Probe:
    def __init__(self, key, token, n_devices, has_fritz, idx):
        self.key, self.token, self.idx = key, token, idx
        self.devices = {f"dev{j:03d}": f"10.{idx // 250}.{idx % 250}.{j + 1}" for j in range(n_devices)}
        self.has_fritz = has_fritz
        self.rev = 1
        self.down = set()

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def body(self):
        # guasti: ogni tanto un dispositivo cade e poi torna (avvisi veri)
        if self.devices and random.random() < 0.05:
            self.down ^= {random.choice(list(self.devices))}
        devs = {n: {"ok": n not in self.down, "host": h, "rtt": None if n in self.down else round(random.uniform(1, 40), 2)}
                for n, h in self.devices.items()}
        b = {"probe": self.key, "interval": 10, "devices": devs or {"solo": True}, "config_rev": self.rev,
             "system": {"temp_c": round(random.uniform(40, 70), 1), "load1": round(random.random(), 2),
                        "speedtest": True, "scan": True}}
        if self.devices and self.rev == 1:
            b["config"] = {**CFG_BASE, "devices": self.devices}
        if self.has_fritz:
            b["fritz"] = fritz(self.idx, random.randint(0, 4))
            now = time.time()
            b["traffic"] = [[now - 10 + k, random.uniform(1e5, 1e7), random.uniform(1e6, 9e7), 2] for k in range(5)]
        return b


async def setup_population(srv, scale, st, client):
    """Account e sonde di tutti i profili. Restituisce (utenti, sonde)."""
    db = srv.authdb()
    users, probes = [], []
    first = True
    for prof, (n_acc, n_probes, devs_total, fritz_total, plan) in PROFILES.items():
        n_acc = max(1, int(round(n_acc * scale)))
        for a in range(n_acc):
            email = f"{prof}-{a}-{secrets.token_hex(3)}@example.test"
            token = srv.api_token if first else db.create_invite("stress", email=email)
            first = False
            r = await client.post("/api/auth/register", json={"token": token, "email": email, "password": PASSWORD},
                                  headers={"X-Forwarded-For": f"10.200.{len(users) // 250}.{len(users) % 250 + 1}"})
            r.raise_for_status()
            cookie = r.cookies.get("netmon_session")
            with db._conn() as c:
                uid = c.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
            if plan:
                db.set_limits(uid, None, None, None, plan)
            else:
                db.set_limits(uid, n_probes, fritz_total, devs_total, "personalizzato")
            u = {"email": email, "cookie": cookie, "id": uid, "profile": prof, "probes": [],
                 "ip": f"10.100.{len(users) // 250}.{len(users) % 250 + 1}"}
            per = devs_total // n_probes if n_probes else 0
            extra = devs_total - per * n_probes if n_probes else 0
            for k in range(n_probes):
                r = await client.post("/api/probes/new", json={"name": f"{prof} {a} s{k}"},
                                      cookies={"netmon_session": cookie})
                r.raise_for_status()
                p = Probe(r.json()["key"], r.json()["token"], per + (1 if k < extra else 0), k < fritz_total,
                          len(probes))
                u["probes"].append(p)
                probes.append(p)
            users.append(u)
    return users, probes


async def probe_loop(p, client, st, stop, interval):
    await asyncio.sleep(random.uniform(0, interval))
    n = 0
    while not stop.is_set():
        r = await call(st, client, "probe:report", "POST", "/api/report", json=p.body(), headers=p.headers)
        if r is not None and r.status_code == 200:
            rep = r.json()
            if rep.get("config_rev"):
                p.rev = max(p.rev, int(rep["config_rev"]))
        n += 1
        if n % 6 == 0:          # come config_poll della sonda vera
            await call(st, client, "probe:config", "GET", f"/api/probe-config?probe={p.key}&rev={p.rev}",
                       headers=p.headers)
        await asyncio.sleep(interval * random.uniform(0.9, 1.1))


async def user_loop(u, client, st, stop, period):
    """La pagina di stato aperta: /api/status ogni 5 s, ogni tanto grafici e Dashboard."""
    ck = {"netmon_session": u["cookie"]}
    h = {"X-Forwarded-For": u["ip"]}
    await asyncio.sleep(random.uniform(0, period))
    n = 0
    while not stop.is_set():
        await call(st, client, f"ui:status:{u['profile']}", "GET", "/api/status", cookies=ck, headers=h)
        n += 1
        if u["probes"] and n % 4 == 0:
            p = random.choice(u["probes"])
            dev = random.choice(list(p.devices) or ["solo"])
            rng = random.choice(["1h", "6h", "24h", "7d", "30d"])
            url = random.choice([f"/api/history?probe={p.key}&device={dev}&range={rng}",
                                 f"/api/traffic?probe={p.key}&range={rng}",
                                 f"/api/fritz-history?probe={p.key}&range={rng}",
                                 f"/api/sysmetrics?probe={p.key}&range={rng}"])
            await call(st, client, "ui:history", "GET", url, cookies=ck, headers=h)
        if n % 10 == 0:
            await call(st, client, f"ui:dashboard:{u['profile']}", "GET",
                       f"/api/dashboard?range={random.choice(['24h', '7d', '30d'])}", cookies=ck, headers=h)
        await asyncio.sleep(period * random.uniform(0.8, 1.2))


async def churn_loop(users, client, st, stop, srv):
    """Modifiche in sottofondo: configurazione, pause, rinomine, accessi."""
    while not stop.is_set():
        await asyncio.sleep(random.uniform(1, 3))
        u = random.choice(users)
        ck = {"netmon_session": u["cookie"]}
        h = {"X-Forwarded-For": u["ip"]}
        act = random.random()
        if u["probes"] and act < 0.3:
            p = random.choice(u["probes"])
            if p.devices:
                d = random.choice(list(p.devices))
                await call(st, client, "ui:write", "POST", "/api/device/pause",
                           json={"probe": p.key, "device": d, "hours": 1}, cookies=ck, headers=h)
                await call(st, client, "ui:write", "POST", "/api/device/resume",
                           json={"probe": p.key, "device": d}, cookies=ck, headers=h)
        elif u["probes"] and act < 0.5:
            p = random.choice(u["probes"])
            await call(st, client, "ui:write", "POST", "/api/probes/rename",
                       json={"probe": p.key, "name": f"rinominata {random.randint(1, 999)}"}, cookies=ck, headers=h)
        elif u["probes"] and act < 0.6:
            p = random.choice(u["probes"])
            if p.devices:
                await call(st, client, "ui:write", "POST", "/api/probe-config",
                           json={"probe": p.key, "config": {**CFG_BASE, "devices": p.devices}}, cookies=ck, headers=h)
        elif act < 0.7:
            await call(st, client, "ui:write", "POST", "/api/events/delete",
                       json={"all": True, "tags": ["OK"]}, cookies=ck, headers=h)
        elif act < 0.8:
            r = await call(st, client, "auth:login", "POST", "/api/auth/login",
                           json={"email": u["email"], "password": PASSWORD}, headers=h)
            if r is not None and r.status_code == 200:
                await call(st, client, "auth:logout", "POST", "/api/auth/logout", json={},
                           cookies={"netmon_session": r.cookies.get("netmon_session")}, headers=h)
        elif act < 0.85:
            await call(st, client, "ui:export", "GET", "/api/account/export", cookies=ck, headers=h)
        else:
            await call(st, client, "ui:read", "GET", "/api/speedtests?days=30", cookies=ck, headers=h)


async def snoop_loop(users, client, st, stop):
    """Un curioso: password sbagliate, sonde degli altri, token inventati. Mai un 2xx."""
    keys = [p.key for u in users for p in u["probes"]]
    victim = next(u for u in users if u["probes"])
    attacker = next(u for u in users if u["profile"] == "vuoto")
    ck = {"netmon_session": attacker["cookie"]}
    while not stop.is_set():
        await asyncio.sleep(random.uniform(0.5, 1.5))
        k = random.choice(keys)
        for group, method, url, kw in (
            ("snoop:idor", "GET", f"/api/history?probe={k}&device=dev000", {"cookies": ck}),
            ("snoop:idor", "POST", "/api/probes/rename", {"json": {"probe": k, "name": "presa"}, "cookies": ck}),
            ("snoop:token", "POST", "/api/report", {"json": {"probe": k, "devices": {"x": True}},
                                                   "headers": {"Authorization": "Bearer sonda_" + secrets.token_urlsafe(30)}}),
            ("snoop:login", "POST", "/api/auth/login", {"json": {"email": victim["email"], "password": "sbagliata-123"},
                                                       "headers": {"X-Forwarded-For": "198.51.100.7"}}),
        ):
            r = await call(st, client, group, method, url, **kw)
            if r is not None and r.status_code < 400:
                st.bad.append((group, r.status_code, url))


def db_sizes(data):
    return {f.name: round(f.stat().st_size / 1e6, 2) for f in data.iterdir() if f.is_file()}


async def monitor_loop(srv, st, stop, every=10):
    t0 = time.time()
    while not stop.is_set():
        st.samples.append({"t": round(time.time() - t0), "rss_mb": round(srv.rss_mb(), 1), "threads": srv.threads(),
                           "fds": srv.open_fds(), "files_mb": db_sizes(srv.data)})
        try:
            await asyncio.wait_for(stop.wait(), every)
        except asyncio.TimeoutError:
            pass


def server_log_problems(srv):
    text = srv.log_path.read_text(errors="replace") if srv.log_path.exists() else ""
    return {"traceback": text.count("Traceback"), "error_lines": text.count(" ERROR "),
            "watchdog_errors": text.count("Errore nel watchdog"),
            "tail": "\n".join(l for l in text.splitlines() if "ERROR" in l or "Traceback" in l)[-3000:]}


async def sustained(seconds=120, scale=1.0, interval=10.0, ui_period=5.0, out=None, data_dir=None):
    st = Stats()
    with LiveServer(data_dir=data_dir) as srv:
        limits = httpx.Limits(max_connections=400, max_keepalive_connections=200)
        async with httpx.AsyncClient(base_url=srv.base, timeout=60, limits=limits) as client:
            t = time.time()
            users, probes = await setup_population(srv, scale, st, client)
            setup_s = time.time() - t
            stop = asyncio.Event()
            tasks = [asyncio.create_task(monitor_loop(srv, st, stop))]
            tasks += [asyncio.create_task(probe_loop(p, client, st, stop, interval)) for p in probes]
            tasks += [asyncio.create_task(user_loop(u, client, st, stop, ui_period)) for u in users]
            tasks += [asyncio.create_task(churn_loop(users, client, st, stop, srv)) for _ in range(3)]
            tasks.append(asyncio.create_task(snoop_loop(users, client, st, stop)))
            await asyncio.sleep(seconds)
            stop.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            # dopo il carico: il server risponde ancora subito?
            r = await call(st, client, "after:health", "GET", "/health")
        result = {
            "scenario": "sustained", "seconds": seconds, "scale": scale, "setup_seconds": round(setup_s, 1),
            "users": len(users), "probes": len(probes), "devices": sum(len(p.devices) for p in probes),
            "fritz": sum(p.has_fritz for p in probes), "requests": sum(len(v) for v in st.lat.values()),
            "latency": st.summary(), "transport_errors": dict(st.errors), "unexpected": st.bad[:50],
            "resources": st.samples, "server_log": server_log_problems(srv),
            "health_after": r.status_code if r is not None else None,
        }
    return finish(result, out)


async def login_storm(n=300, out=None):
    """Raffica di accessi (password sbagliate da IP diversi): scrypt costa 32 MB per verifica, ma al
    massimo SCRYPT_SLOTS insieme. Intanto le sonde devono continuare a essere servite."""
    st = Stats()
    with LiveServer() as srv:
        async with httpx.AsyncClient(base_url=srv.base, timeout=120,
                                     limits=httpx.Limits(max_connections=n + 20)) as client:
            users, probes = await setup_population(srv, 0.1, st, client)
            stop = asyncio.Event()
            mon = asyncio.create_task(monitor_loop(srv, st, stop, every=1))
            bg = [asyncio.create_task(probe_loop(p, client, st, stop, 2)) for p in probes[:10]]
            victim = users[1]["email"]
            await asyncio.gather(*(call(st, client, "storm:login", "POST", "/api/auth/login",
                                        json={"email": victim if i % 2 else f"x{i}@example.test",
                                              "password": f"sbagliata-{i:06d}"},
                                        headers={"X-Forwarded-For": f"203.0.{i // 250}.{i % 250 + 1}"})
                                   for i in range(n)))
            await asyncio.sleep(2)
            stop.set()
            await asyncio.gather(mon, *bg, return_exceptions=True)
        peak = max(s["rss_mb"] for s in st.samples)
        result = {"scenario": "login-storm", "attempts": n, "peak_rss_mb": peak, "latency": st.summary(),
                  "unexpected": st.bad[:50], "server_log": server_log_problems(srv), "resources": st.samples}
    return finish(result, out)


async def big_bodies(n=12, mb=10, out=None):
    """Corpi grandi SENZA Content-Length (trasferimento a pezzi): il controllo sulla dimensione del
    middleware legge solo Content-Length, Caddy tronca a 10 MB. Senza credenziali, quanta memoria
    si riesce a far usare al server? (Con MemoryMax=384M, systemd lo uccide oltre.)"""
    st = Stats()
    with LiveServer() as srv:
        payload = b'{"probe":"x","devices":{' + b",".join(b'"d%d":true' % i for i in range(10)) + b'},"system":{"x":"' \
            + b"A" * (mb * 1024 * 1024 - 200) + b'"}}'

        async def chunks():
            for i in range(0, len(payload), 65536):
                yield payload[i:i + 65536]

        async with httpx.AsyncClient(base_url=srv.base, timeout=120, limits=httpx.Limits(max_connections=n + 5)) as client:
            stop = asyncio.Event()
            mon = asyncio.create_task(monitor_loop(srv, st, stop, every=0.5))
            base_rss = srv.rss_mb()
            res = await asyncio.gather(*(call(st, client, f"chunked:{path}", "POST", path, content=chunks(),
                                              headers={"Content-Type": "application/json"})
                                         for path in ["/api/report", "/api/auth/login"] * (n // 2)))
            h = await call(st, client, "after:health", "GET", "/health")
            await asyncio.sleep(1)
            stop.set()
            await mon
        peak = max(s["rss_mb"] for s in st.samples)
        result = {"scenario": "big-bodies", "requests": n, "body_mb": mb, "baseline_rss_mb": round(base_rss, 1),
                  "peak_rss_mb": peak, "codes": {k: dict(v) for k, v in st.codes.items()},
                  "health_after": h.status_code if h is not None else None, "server_log": server_log_problems(srv),
                  "resources": st.samples}
    return finish(result, out)


async def backfill_flood(n_probes=50, batches=25, out=None):
    """Dopo un'interruzione della rete tutte le sonde tornano insieme e svuotano il buffer
    (fino a 5000 report ciascuna, a blocchi di 200)."""
    st = Stats()
    with LiveServer() as srv:
        async with httpx.AsyncClient(base_url=srv.base, timeout=120, limits=httpx.Limits(max_connections=200)) as client:
            db = srv.authdb()
            email = f"flood-{secrets.token_hex(3)}@example.test"
            r = await client.post("/api/auth/register", json={"token": srv.api_token, "email": email, "password": PASSWORD})
            ck = {"netmon_session": r.cookies.get("netmon_session")}
            with db._conn() as c:
                uid = c.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
            db.set_limits(uid, n_probes, n_probes, n_probes * 20, "personalizzato")
            probes = []
            for i in range(n_probes):
                r = await client.post("/api/probes/new", json={"name": f"f{i}"}, cookies=ck)
                probes.append(Probe(r.json()["key"], r.json()["token"], 20, False, i))
            for p in probes:
                await call(st, client, "probe:report", "POST", "/api/report", json=p.body(), headers=p.headers)
            stop = asyncio.Event()
            mon = asyncio.create_task(monitor_loop(srv, st, stop, every=1))
            now = time.time()

            async def flood(p):
                for b in range(batches):
                    reps = [{"ts": now - 3600 * 4 + (b * 200 + k) * 2.5,
                             "devices": {n: True for n in p.devices}} for k in range(200)]
                    await call(st, client, "probe:backfill", "POST", "/api/backfill",
                               json={"probe": p.key, "reports": reps}, headers=p.headers)

            async def ui():
                while not stop.is_set():
                    await call(st, client, "ui:status", "GET", "/api/status", cookies=ck)
                    await asyncio.sleep(1)
            u = asyncio.create_task(ui())
            t = time.time()
            await asyncio.gather(*(flood(p) for p in probes))
            took = time.time() - t
            stop.set()
            await asyncio.gather(mon, u)
        with sqlite3.connect(srv.data / "events.db") as conn:
            rows = conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        result = {"scenario": "backfill-flood", "probes": n_probes, "reports_sent": n_probes * batches * 200,
                  "rows_in_db": rows, "seconds": round(took, 1), "latency": st.summary(),
                  "peak_rss_mb": max(s["rss_mb"] for s in st.samples), "unexpected": st.bad[:50],
                  "server_log": server_log_problems(srv)}
    return finish(result, out)


async def history(days=30, devices=1000, every=60, out=None):
    """Storico lungo: un account grande con `days` giorni di misure ogni `every` secondi per
    `devices` dispositivi. Quanto costano grafici, Dashboard, export e pulizia della conservazione?"""
    import tempfile
    data = Path(tempfile.mkdtemp(prefix="netmon-hist-"))
    st = Stats()
    # 1) account e sonde con il server acceso, 2) storico scritto a server spento, 3) misure
    with LiveServer(data_dir=data) as srv:
        async with httpx.AsyncClient(base_url=srv.base, timeout=600) as client:
            db = srv.authdb()
            email = f"storico-{secrets.token_hex(3)}@example.test"
            r = await client.post("/api/auth/register", json={"token": srv.api_token, "email": email, "password": PASSWORD})
            cookie = r.cookies.get("netmon_session")
            with db._conn() as c:
                uid = c.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
            n_probes = max(1, devices // 20)
            db.set_limits(uid, n_probes, 10, devices, "personalizzato")
            probes = []
            for i in range(n_probes):
                r = await client.post("/api/probes/new", json={"name": f"h{i}"}, cookies={"netmon_session": cookie})
                p = Probe(r.json()["key"], r.json()["token"], 20, i < 10, i)
                probes.append(p)
                await client.post("/api/report", json=p.body(), headers=p.headers)
    t0 = time.time()
    now = time.time()
    with sqlite3.connect(data / "events.db") as conn:
        conn.execute("PRAGMA synchronous=OFF")
        for p in probes:
            rows = [(ts, p.key, d, 1 if random.random() > 0.01 else 0, random.uniform(1, 30))
                    for ts in range(int(now - days * 86400), int(now), every) for d in p.devices]
            conn.executemany("INSERT OR IGNORE INTO samples VALUES (?,?,?,?,?)", rows)
            if p.has_fritz:
                conn.executemany("INSERT OR IGNORE INTO traffic (ts, probe, up, down, dt, box) VALUES (?,?,?,?,?,'')",
                                 [(ts, p.key, 1e6, 5e7, 30) for ts in range(int(now - days * 86400), int(now), 30)])
                conn.executemany("INSERT OR IGNORE INTO fritz_hist (ts, probe, box, down, up, max_down, max_up, lan, wifi) "
                                 "VALUES (?,?,'',?,?,?,?,?,?)",
                                 [(ts, p.key, 5e7, 1e6, 1e8, 2e7, 3, '{"Casa": 5, "guests": 1}')
                                  for ts in range(int(now - days * 86400), int(now), 30)])
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    fill_s = time.time() - t0
    size_mb = (data / "events.db").stat().st_size / 1e6
    with LiveServer(data_dir=data) as srv:
        async with httpx.AsyncClient(base_url=srv.base, timeout=600) as client:
            ck = {"netmon_session": cookie}
            base_rss = srv.rss_mb()
            stop = asyncio.Event()
            mon = asyncio.create_task(monitor_loop(srv, st, stop, every=1))
            p = probes[0]
            for rng in ("24h", "7d", "30d"):
                await call(st, client, f"history:{rng}", "GET", f"/api/history?probe={p.key}&device=dev000&range={rng}", cookies=ck)
                await call(st, client, f"traffic:{rng}", "GET", f"/api/traffic?probe={p.key}&range={rng}", cookies=ck)
                await call(st, client, f"fritz:{rng}", "GET", f"/api/fritz-history?probe={p.key}&range={rng}", cookies=ck)
                await call(st, client, f"dashboard:{rng}", "GET", f"/api/dashboard?range={rng}", cookies=ck)
            # 8 grafici insieme dallo stesso utente: i limiti HEAVY_* devono rispondere 429, non bloccare tutto
            await asyncio.gather(*(call(st, client, "history:parallel", "GET",
                                        f"/api/history?probe={p.key}&device=dev{k:03d}&range=30d", cookies=ck)
                                   for k in range(12)))
            # mentre un utente legge 30 giorni, le sonde scrivono: i report restano veloci?
            async def reports():
                for _ in range(20):
                    for q in probes[:10]:
                        await call(st, client, "probe:report-during-history", "POST", "/api/report",
                                   json=q.body(), headers=q.headers)
                    await asyncio.sleep(0.5)
            await asyncio.gather(reports(), *(call(st, client, "dashboard:30d-concurrent", "GET", "/api/dashboard?range=30d",
                                                   cookies=ck) for _ in range(3)))
            await call(st, client, "export", "GET", "/api/account/export", cookies=ck)
            # conservazione: da «sempre» a 7 giorni, con la pulizia che parte subito
            await call(st, client, "retention:purge", "POST", "/api/account/retention",
                       json={"unit": "giorni", "value": 7, "password": PASSWORD}, cookies=ck)
            await call(st, client, "after:status", "GET", "/api/status", cookies=ck)
            stop.set()
            await mon
            after = sqlite3.connect(data / "events.db").execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        result = {"scenario": "history", "days": days, "devices": devices, "rows": total, "db_mb": round(size_mb),
                  "fill_seconds": round(fill_s), "rows_after_purge": after, "baseline_rss_mb": round(base_rss, 1),
                  "peak_rss_mb": max(s["rss_mb"] for s in st.samples), "latency": st.summary(),
                  "server_log": server_log_problems(srv)}
    return finish(result, out)


def finish(result, out):
    if out:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{result['scenario']}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=["sustained", "login-storm", "big-bodies", "backfill-flood", "history"])
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--devices", type=int, default=1000)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    fn = {"sustained": lambda: sustained(a.seconds, a.scale, a.interval, out=a.out),
          "login-storm": lambda: login_storm(out=a.out), "big-bodies": lambda: big_bodies(out=a.out),
          "backfill-flood": lambda: backfill_flood(out=a.out),
          "history": lambda: history(a.days, a.devices, out=a.out)}[a.scenario]
    res = asyncio.run(fn())
    res.pop("resources", None)
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
