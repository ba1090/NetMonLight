"""Stato della VM e operazioni di sistema per il pannello di amministrazione.

Tutto viene letto da /proc e /sys, senza librerie esterne e senza privilegi. Le due operazioni
(aggiornamento dei pacchetti e riavvio) sono consentite all'utente del servizio solo da
/etc/sudoers.d/netmon-vm e da nient'altro; l'aggiornamento gira in un'unità systemd separata,
così non si interrompe se durante apt il servizio netmon-server viene riavviato.
"""
__version__ = "1.1.20261029-180000"
import json
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import threading
import time
from pathlib import Path

STATE_DIR = Path(os.getenv("VM_STATE_DIR", "/var/lib/netmon-vm"))
UPGRADE_STATUS = STATE_DIR / "upgrade.status"
UPGRADE_LOG = STATE_DIR / "upgrade.log"
UPGRADE_SCRIPT = "/usr/local/sbin/netmon-vm-upgrade"
REBOOT_CMD = ["/usr/bin/systemctl", "reboot"]
UPGRADE_CMD = ["/usr/bin/systemd-run", "--unit=netmon-vm-upgrade", "--collect", "--quiet", UPGRADE_SCRIPT]
SELFUPDATE_SCRIPT = "/usr/local/sbin/netmon-vm-selfupdate"
SELFUPDATE_CMD = ["/usr/bin/systemd-run", "--unit=netmon-vm-selfupdate", "--collect", "--quiet", SELFUPDATE_SCRIPT]
SELFUPDATE_STATUS = STATE_DIR / "selfupdate.status"
SELFUPDATE_LOG = STATE_DIR / "selfupdate.log"
# Rollback dell'ultima installazione da pacchetto: finestra di 4 ore, poi ripristino automatico.
# il timer lo arma netmon-vm-selfupdate (root), quindi qui servono solo i due comandi del pannello.
ROLLBACK_SCRIPT = "/usr/local/sbin/netmon-vm-rollback"
ROLLBACK_COMMIT_CMD = [ROLLBACK_SCRIPT, "commit"]
ROLLBACK_NOW_CMD = ["/usr/bin/systemd-run", "--unit=netmon-vm-rollback-run", "--collect", "--quiet",
                    ROLLBACK_SCRIPT, "rollback"]
ROLLBACK_STATUS = STATE_DIR / "rollback.json"       # finestra aperta (conferma/ripristino)
ROLLBACK_DONE = STATE_DIR / "rollback.status"       # esito dell'ultimo ripristino
PKGCHECK = "/usr/local/lib/netmon/pkgcheck.py"       # copia di root del verificatore dei pacchetti
SUDOERS_HINT = ("Permesso mancante: aggiorna il server con sudo bash installa-server.sh --aggiorna "
                "(installa /etc/sudoers.d/netmon-vm).")

_lock = threading.Lock()
_cpu_last = [None]          # (istante, totale, inattivo)
_net_last = [None]          # (istante, iface, rx, tx)
_cache = {}                 # chiave -> (scadenza, valore)


def _cached(key, ttl, fn):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = fn()
    _cache[key] = (now + ttl, value)
    return value


def _read(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""


# ------------------------------------------------------------------ misure
def _cpu_times():
    parts = _read("/proc/stat").split("\n", 1)[0].split()[1:]
    vals = [int(x) for x in parts[:8]] if parts else []
    if len(vals) < 5:
        return None
    idle = vals[3] + vals[4]                     # idle + iowait
    return sum(vals), idle, vals[4]


def cpu_percent():
    """Uso della CPU dall'ultima lettura (o su mezzo secondo, se è la prima)."""
    now = time.monotonic()
    cur = _cpu_times()
    if cur is None:
        return None, None
    last = _cpu_last[0]
    if last is None or now - last[0] > 300 or now - last[0] < 0.2:
        time.sleep(0.5)
        last, now, cur = (now, *cur), time.monotonic(), _cpu_times()
    _cpu_last[0] = (now, *cur)
    dt, di, dw = cur[0] - last[1], cur[1] - last[2], cur[2] - last[3]
    if dt <= 0:
        return 0.0, 0.0
    return round(100 * (dt - di) / dt, 1), round(100 * dw / dt, 1)


def meminfo():
    out = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        try:
            out[k] = int(v.split()[0]) * 1024
        except (ValueError, IndexError):
            pass
    return out


def default_iface():
    for line in _read("/proc/net/route").splitlines()[1:]:
        f = line.split()
        if len(f) > 2 and f[1] == "00000000":
            return f[0]
    return None


def net_counters(iface):
    for line in _read("/proc/net/dev").splitlines()[2:]:
        name, _, rest = line.partition(":")
        if name.strip() == iface:
            f = rest.split()
            return int(f[0]), int(f[8])
    return None


def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 53))              # nessun pacchetto inviato: solo la scelta dell'interfaccia
            return s.getsockname()[0]
    except OSError:
        return None


def os_name():
    m = re.search(r'^PRETTY_NAME="?([^"\n]+)"?', _read("/etc/os-release"), re.M)
    return m.group(1) if m else platform.system()


def cpu_model():
    text = _read("/proc/cpuinfo")
    m = re.search(r"^(model name|Hardware|Model)\s*:\s*(.+)$", text, re.M)
    return m.group(2).strip() if m else platform.machine()


def temperature():
    best = None
    for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        try:
            t = int((zone / "temp").read_text().strip()) / 1000
        except (OSError, ValueError):
            continue
        if 0 < t < 150:
            best = t if best is None else max(best, t)
    return round(best, 1) if best is not None else None


def virtualization():
    rc, out = _run(["systemd-detect-virt"], timeout=5)
    v = out.strip()
    return None if not v or v == "none" else v


def process_info():
    """Memoria, thread e durata del processo del server."""
    status = _read("/proc/self/status")
    rss = re.search(r"^VmRSS:\s+(\d+) kB", status, re.M)
    threads = re.search(r"^Threads:\s+(\d+)", status, re.M)
    up = None
    try:
        start_ticks = int(_read("/proc/self/stat").rsplit(")", 1)[1].split()[19])
        boot_up = float(_read("/proc/uptime").split()[0])
        up = boot_up - start_ticks / os.sysconf("SC_CLK_TCK")
    except (ValueError, IndexError, OSError):
        pass
    return {"rss": int(rss.group(1)) * 1024 if rss else None,
            "threads": int(threads.group(1)) if threads else None, "uptime": up}


def service_state(unit):
    rc, out = _run(["systemctl", "is-active", unit], timeout=5)
    return out.strip() or "sconosciuto"


def _version_key(v):
    return [int(x) if x.isdigit() else x for x in re.split(r"[.\-+~]", v)]


def kernel_pending():
    """Versione del kernel installata più recente, se diversa da quella in uso (serve un riavvio)."""
    running = platform.release()
    versions = [p.name[len("vmlinuz-"):] for p in Path("/boot").glob("vmlinuz-*")]
    if not versions:
        return None
    try:
        newest = max(versions, key=_version_key)
    except TypeError:
        return None
    return newest if newest != running else None


def reboot_required():
    pkgs = [p for p in _read("/var/run/reboot-required.pkgs").split() if p][:10]
    kernel = kernel_pending()
    if os.path.exists("/var/run/reboot-required") or kernel:
        return {"required": True, "kernel": kernel, "packages": pkgs}
    return {"required": False}


def pending_updates():
    """Pacchetti aggiornabili secondo gli elenchi già scaricati (apt-get simulato, senza privilegi)."""
    def check():
        rc, out = _run(["apt-get", "-s", "-o", "Debug::NoLocking=true", "--with-new-pkgs", "upgrade"], timeout=60)
        if rc != 0:
            return {"available": False}
        names, security = [], 0
        for line in out.splitlines():
            if line.startswith("Inst "):
                names.append(line.split()[1])
                if "-security" in line:
                    security += 1
        lists = [p.stat().st_mtime for p in Path("/var/lib/apt/lists").glob("*_InRelease")] or [0]
        return {"available": True, "count": len(names), "security": security, "names": names[:40],
                "lists_updated": max(lists) or None, "checked": time.time()}
    return _cached("apt", 600, check)


def forget_pending_updates():
    _cache.pop("apt", None)


def tls_expiry(host):
    """Scadenza del certificato HTTPS servito da Caddy per `host` (epoch), oppure None."""
    if not host or host in ("localhost", "127.0.0.1"):
        return None

    def check():
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection(("127.0.0.1", 443), timeout=3) as raw:
                with ctx.wrap_socket(raw, server_hostname=host) as s:
                    cert = s.getpeercert()
            return ssl.cert_time_to_seconds(cert["notAfter"])
        except (OSError, ssl.SSLError, KeyError, ValueError):
            return None
    return _cached("tls:" + host, 3600, check)


def file_size(*paths):
    total = 0
    for p in paths:
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    return total


def info(data_dir: Path, host: str = "") -> dict:
    """Istantanea dello stato della VM (chiamata in un thread: alcune letture richiedono un attimo)."""
    with _lock:
        cpu, iowait = cpu_percent()
        mem = meminfo()
        load = os.getloadavg()
        du = shutil.disk_usage("/")
        iface = default_iface()
        rx_rate = tx_rate = None
        counters = net_counters(iface) if iface else None
        now = time.monotonic()
        if counters:
            last = _net_last[0]
            if last and last[1] == iface and 1 < now - last[0] < 600:
                rx_rate = max(0, (counters[0] - last[2]) / (now - last[0]))
                tx_rate = max(0, (counters[1] - last[3]) / (now - last[0]))
            _net_last[0] = (now, iface, *counters)
    static = _cached("static", 3600, lambda: {
        "hostname": socket.gethostname(), "os": os_name(), "kernel": platform.release(),
        "arch": platform.machine(), "cpu_model": cpu_model(), "virt": virtualization(),
        "python": platform.python_version()})
    events_db = data_dir / "events.db"
    return {
        **static,
        "ts": time.time(),
        "uptime": float(_read("/proc/uptime", "0").split()[0] or 0),
        "cpus": os.cpu_count(),
        "cpu_percent": cpu, "iowait_percent": iowait,
        "load1": round(load[0], 2), "load5": round(load[1], 2), "load15": round(load[2], 2),
        "mem_total": mem.get("MemTotal"), "mem_available": mem.get("MemAvailable"),
        "swap_total": mem.get("SwapTotal"), "swap_used": (mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)) or 0,
        "disk_total": du.total, "disk_used": du.total - du.free, "disk_free": du.free,
        "temp_c": temperature(),
        "iface": iface, "ip": local_ip(),
        "rx_bytes": counters[0] if counters else None, "tx_bytes": counters[1] if counters else None,
        "rx_rate": rx_rate, "tx_rate": tx_rate,
        "tz": time.strftime("%Z"),
        "process": process_info(),
        "services": {u: service_state(u) for u in ("netmon-server", "caddy")},
        "db_events": file_size(events_db, str(events_db) + "-wal"),
        "db_auth": file_size(data_dir / "auth.db", str(data_dir / "auth.db") + "-wal"),
        "data_total": sum(file_size(p) for p in data_dir.glob("*") if p.is_file()),
        "tls_expires": tls_expiry(host),
        "reboot": reboot_required(),
        "updates": pending_updates(),
    }


# ------------------------------------------------------------------ operazioni
def can_sudo(cmd) -> bool:
    rc, _ = _run(["sudo", "-n", "-l", *cmd], timeout=10)
    return rc == 0


def permissions() -> dict:
    return _cached("perm", 60, lambda: {
        "can_reboot": can_sudo(REBOOT_CMD),
        "can_upgrade": os.path.exists(UPGRADE_SCRIPT) and can_sudo(UPGRADE_CMD),
        "can_selfupdate": os.path.exists(SELFUPDATE_SCRIPT) and os.path.exists(PKGCHECK) and can_sudo(SELFUPDATE_CMD),
        "can_rollback": os.path.exists(ROLLBACK_SCRIPT)
            and can_sudo(ROLLBACK_COMMIT_CMD) and can_sudo(ROLLBACK_NOW_CMD)})


def _unit_active() -> bool:
    rc, out = _run(["systemctl", "is-active", "netmon-vm-upgrade"], timeout=5)
    return out.strip() in ("active", "activating")


def upgrade_status() -> dict:
    try:
        st = json.loads(UPGRADE_STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {"state": "none"}
    if st.get("state") == "running" and not _unit_active() and time.time() - (st.get("started") or 0) > 60:
        st["state"], st["note"] = "error", "interrotto"
    return st


def upgrade_log(max_chars: int = 6000) -> str:
    try:
        with open(UPGRADE_LOG, encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_chars))
            text = f.read()
        return text if size <= max_chars else "…" + text[text.find("\n") + 1:]
    except OSError:
        return ""


def start_upgrade() -> tuple[bool, str]:
    if upgrade_status().get("state") == "running":
        return False, "Un aggiornamento è già in corso."
    if not os.path.exists(UPGRADE_SCRIPT) or not can_sudo(UPGRADE_CMD):
        return False, SUDOERS_HINT
    rc, _ = _run(["sudo", "-n", *UPGRADE_CMD], timeout=30)
    if rc != 0:
        return False, f"Avvio non riuscito (codice {rc})."
    forget_pending_updates()
    return True, "Aggiornamento avviato."


def reboot(delay: float = 3.0) -> tuple[bool, str]:
    """Riavvia la VM dopo `delay` secondi (il tempo di rispondere alla pagina)."""
    if not can_sudo(REBOOT_CMD):
        return False, SUDOERS_HINT

    def later():
        time.sleep(delay)
        _run(["sudo", "-n", *REBOOT_CMD], timeout=30)

    threading.Thread(target=later, daemon=True, name="riavvio-vm").start()
    return True, "Riavvio avviato."


# ------------------------------------------------------------------ installazione di un pacchetto caricato
def selfupdate_status() -> dict:
    try:
        st = json.loads(SELFUPDATE_STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {"state": "none"}
    if st.get("state") == "running" and time.time() - (st.get("started") or 0) > 900:
        rc, out = _run(["systemctl", "is-active", "netmon-vm-selfupdate"], timeout=5)
        if out.strip() not in ("active", "activating"):
            st["state"], st["note"] = "error", "interrotto"
    return st


def selfupdate_log(max_chars: int = 8000) -> str:
    try:
        text = SELFUPDATE_LOG.read_text(encoding="utf-8", errors="replace")
        return text if len(text) <= max_chars else "…" + text[-max_chars:]
    except OSError:
        return ""


def start_selfupdate() -> tuple[bool, str]:
    if selfupdate_status().get("state") == "running":
        return False, "Un'installazione è già in corso."
    if upgrade_status().get("state") == "running":
        return False, "È in corso l'aggiornamento dei pacchetti del sistema: attendi che finisca."
    if not (os.path.exists(SELFUPDATE_SCRIPT) and os.path.exists(PKGCHECK) and can_sudo(SELFUPDATE_CMD)):
        return False, ("Funzione non ancora installata: aggiorna il server una volta a mano con "
                       "sudo bash installa-server.sh --aggiorna.")
    rc, out = _run(["sudo", "-n", *SELFUPDATE_CMD], timeout=30)
    if rc != 0:
        return False, f"Avvio non riuscito (codice {rc})."
    return True, "Installazione avviata."


# ------------------------------------------------------------------ rollback dell'ultimo pacchetto installato
def rollback_status() -> dict:
    """Finestra di rollback aperta dopo l'ultima installazione, più l'esito dell'ultimo ripristino.
    I due file sono leggibili dal servizio (scritti con permessi 644 da netmon-vm-selfupdate)."""
    out = {"pending": False}
    try:
        d = json.loads(ROLLBACK_STATUS.read_text(encoding="utf-8"))
        now = time.time()
        d = dict(d)
        d["pending"] = True
        d["remaining"] = max(0, int((d.get("deadline") or 0) - now))
        d["scaduto"] = (d.get("deadline") or 0) <= now
        out = d
    except (OSError, ValueError):
        pass
    try:
        out["last"] = json.loads(ROLLBACK_DONE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return out


def rollback_commit() -> tuple[bool, str]:
    """Conferma la versione nuova: la finestra si chiude e il backup della vecchia viene tolto."""
    if not (os.path.exists(ROLLBACK_SCRIPT) and can_sudo(ROLLBACK_COMMIT_CMD)):
        return False, SUDOERS_HINT
    rc, out = _run(["sudo", "-n", *ROLLBACK_COMMIT_CMD], timeout=30)
    if rc != 0:
        return False, f"Conferma non riuscita (codice {rc}): {out.strip()}".strip()
    return True, "Versione nuova confermata: il rollback non è più disponibile."


def rollback_now() -> tuple[bool, str]:
    """Ripristina subito la versione precedente. In un'unità systemd separata: riavvia il server,
    quindi non può girare dentro il servizio (verrebbe ucciso insieme a lui)."""
    if selfupdate_status().get("state") == "running":
        return False, "Un'installazione è in corso: il rollback non è disponibile."
    if not (os.path.exists(ROLLBACK_SCRIPT) and can_sudo(ROLLBACK_NOW_CMD)):
        return False, SUDOERS_HINT
    rc, out = _run(["sudo", "-n", *ROLLBACK_NOW_CMD], timeout=30)
    if rc != 0:
        return False, f"Avvio non riuscito (codice {rc})."
    return True, "Rollback avviato: il server torna alla versione precedente."


# ------------------------------------------------------------------ dettaglio della memoria
# Cosa occupa la RAM della VM: memoria resident (VmRSS) di ogni processo, sommata per programma.
# /proc/<pid>/status e' leggibile da tutti: non servono permessi di root. La RSS conta anche le
# librerie condivise, quindi la somma puo' superare di poco la memoria usata.
KNOWN_PROGRAMS = {
    # nome del processo: (descrizione, suggerimento se non serve)
    "caddy": ("Caddy, HTTPS del pannello", ""),
    "snapd": ("snapd, pacchetti Snap", "se non usi pacchetti Snap: sudo apt purge snapd"),
    "google_guest_ag": ("agente Google della VM", ""),
    "google_osconfig": ("agente OS Config di Google", "se non usi OS Config/patch di Google: sudo apt remove google-osconfig-agent"),
    "otelopscol": ("Ops Agent, monitoraggio Google", "se non usi il monitoraggio Google: sudo apt remove google-cloud-ops-agent"),
    "fluent-bit": ("Ops Agent, log per Google", "se non usi il monitoraggio Google: sudo apt remove google-cloud-ops-agent"),
    "google_cloud_op": ("Ops Agent, monitoraggio Google", "se non usi il monitoraggio Google: sudo apt remove google-cloud-ops-agent"),
    "systemd-journal": ("registro di sistema", ""),
    "unattended-upgr": ("aggiornamenti automatici", ""),
    "packagekitd": ("PackageKit", "non serve su una VM: sudo apt purge packagekit"),
    "ModemManager": ("ModemManager", "non serve su una VM: sudo apt purge modemmanager"),
    "multipathd": ("multipath dei dischi", "non serve su una VM: sudo systemctl disable --now multipathd"),
    "udisksd": ("udisks", "non serve su una VM: sudo apt purge udisks2"),
}


def mem_detail(top: int = 12) -> dict:
    mem = meminfo()
    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", 0)
    cache = mem.get("Cached", 0) + mem.get("Buffers", 0) + mem.get("SReclaimable", 0) - mem.get("Shmem", 0)
    me = os.getpid()
    groups = {}
    try:
        pids = os.listdir("/proc")
    except OSError:
        pids = []
    for pid in pids:
        if not pid.isdigit():
            continue
        status = _read(f"/proc/{pid}/status")
        name = re.search(r"^Name:\s+(.+)$", status, re.M)
        rss = re.search(r"^VmRSS:\s+(\d+) kB", status, re.M)
        if not name or not rss:
            continue                                # thread del kernel: niente memoria propria
        key = "netmon-server" if int(pid) == me else name.group(1).strip()
        g = groups.setdefault(key, {"name": key, "rss": 0, "count": 0})
        g["rss"] += int(rss.group(1)) * 1024
        g["count"] += 1
    procs = sorted(groups.values(), key=lambda g: -g["rss"])[:top]
    for g in procs:
        desc, hint = KNOWN_PROGRAMS.get(g["name"], ("netmon, il server di questo pannello", "")
                                         if g["name"] == "netmon-server" else ("", ""))
        g.update(desc=desc, hint=hint)
    return {"total": total, "used": total - available, "available": available, "cache": max(0, cache),
            "free": mem.get("MemFree", 0), "swap_total": mem.get("SwapTotal", 0),
            "swap_used": mem.get("SwapTotal", 0) - mem.get("SwapFree", 0), "processes": procs}


def trim_self() -> tuple:
    """Restituisce al sistema la memoria libera del processo del server (Python + malloc).
    (RSS prima, RSS dopo) in byte."""
    import ctypes
    import gc
    before = process_info()["rss"]
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass                                        # non glibc: resta solo il gc
    return before, process_info()["rss"]
