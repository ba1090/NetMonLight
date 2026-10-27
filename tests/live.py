"""Server netmon vero in un processo a parte (uvicorn), per le prove nel browser e di carico.

A differenza del TestClient (stesso processo, una richiesta per volta) qui ci sono il ciclo di
eventi di uvicorn, i thread del database e il watchdog veri: è come gira sulla VM, con le stesse
impostazioni del servizio systemd (UMask 0077, SCRYPT_SLOTS=3).
"""
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server"
PASSWORD = "Password-Prova-123!"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServer:
    def __init__(self, data_dir=None, env=None, log_path=None, app="app:app", cwd=SERVER, health="/health"):
        self.data = Path(data_dir or tempfile.mkdtemp(prefix="netmon-live-"))
        self.data.mkdir(parents=True, exist_ok=True)
        self.app, self.cwd, self.health = app, cwd, health
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.api_token = "chiave-" + secrets.token_urlsafe(16)
        self.env = {**os.environ, "API_TOKEN": self.api_token, "DATA_DIR": str(self.data), "COOKIE_SECURE": "0",
                    "SMTP_HOST": "", "TELEGRAM_BOT_TOKEN": "",
                    "MIN_FREE_MB": "1", "SCRYPT_SLOTS": "3", "MALLOC_ARENA_MAX": "2", "NEW_USER_PLAN": "basso",
                    "PUBLIC_URL": self.base, **(env or {})}
        self.log_path = Path(log_path or self.data.parent / f"{self.data.name}.log")
        self.proc = None

    def start(self, timeout=30):
        self._log = open(self.log_path, "ab")
        cmd = [sys.executable, "-m", "uvicorn", self.app, "--host", "127.0.0.1", "--port", str(self.port),
               "--no-access-log", "--ws", "none", "--timeout-keep-alive", "65"]
        # UMask=0077 come in netmon-server.service
        self.proc = subprocess.Popen(cmd, cwd=self.cwd, env=self.env, stdout=self._log, stderr=subprocess.STDOUT,
                                     preexec_fn=lambda: os.umask(0o077))
        end = time.time() + timeout
        while time.time() < end:
            try:
                if httpx.get(self.base + self.health, timeout=1).status_code < 500:
                    return self
            except httpx.HTTPError:
                pass
            if self.proc.poll() is not None:
                raise RuntimeError("il server non parte: " + self.log_path.read_text()[-3000:])
            time.sleep(0.2)
        raise RuntimeError("il server non risponde")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if getattr(self, "_log", None):
            self._log.close()

    def rss_mb(self):
        """Memoria residente del processo del server (come MemoryMax di systemd la conta)."""
        try:
            for line in Path(f"/proc/{self.proc.pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
        except OSError:
            pass
        return 0.0

    def threads(self):
        try:
            return len(os.listdir(f"/proc/{self.proc.pid}/task"))
        except OSError:
            return 0

    def open_fds(self):
        try:
            return len(os.listdir(f"/proc/{self.proc.pid}/fd"))
        except OSError:
            return 0

    def authdb(self):
        """Accesso diretto ad auth.db (codici di accesso, limiti) senza passare dal pannello."""
        sys.path.insert(0, str(SERVER))
        import auth  # noqa: PLC0415
        return auth.AuthDB(self.data / "auth.db")

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def register(base, token, email, password=PASSWORD, client=None):
    c = client or httpx.Client(base_url=base, timeout=30)
    r = c.post("/api/auth/register", json={"token": token, "email": email, "password": password})
    r.raise_for_status()
    return r.cookies.get("netmon_session")


def make_account(server, db, email=None, plan="personalizzato", probes=None, fritz=None, devices=None,
                 first=False):
    """Account con i limiti scelti; restituisce (email, cookie, id)."""
    email = email or f"u-{secrets.token_hex(5)}@example.test"
    token = server.api_token if first else db.create_invite("prova", email=email)
    cookie = register(server.base, token, email)
    with db._conn() as c:
        uid = c.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
    if plan:
        db.set_limits(uid, probes, fritz, devices, plan)
    return email, cookie, uid
