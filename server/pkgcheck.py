#!/usr/bin/env python3
"""Verifica di un pacchetto netmon.zip prima di installarlo (VM o sonda).

Uso:  python3 pkgcheck.py --target server|probe --installed VERSIONE [--extract CARTELLA] netmon.zip
Stampa un JSON {ok, version, installed, checks: [[esito, testo]...], errors: [...]} e termina
con codice 0 solo se il pacchetto è idoneo. Con --extract, e solo se idoneo, lo estrae nella
cartella indicata (che deve esistere ed essere vuota) senza seguire percorsi o collegamenti.

Lo usano la pagina (per mostrare subito l'esito) e lo script di root che installa, che
ricontrolla tutto da capo su una copia privata: la pagina non è mai considerata affidabile.
Solo libreria standard di Python. Lo stesso file sta in server/ e in probe/.

Cosa controlla:
- zip integro, dimensioni e numero di file entro i limiti (niente "bombe" di decompressione);
- ogni percorso dentro netmon/, senza "..", percorsi assoluti, collegamenti simbolici o doppioni
  (i file nascosti che il Finder del Mac aggiunge comprimendo una cartella, __MACOSX/, ._* e
  .DS_Store, vengono ignorati e non si estraggono mai);
- presenti tutti i file che servono all'installazione (server o sonda);
- VERSION nel formato 2.x.AAAAMMGG-hhmmss, uguale alla versione dichiarata in OGNI programma;
- versione PIÙ ALTA di quella installata (niente ritorni indietro né reinstallazioni);
- programmi Python senza errori di sintassi (controllati senza eseguirli).

L'origine del pacchetto non la verifica questo file: sulla VM la controlla netmon-vm-selfupdate
(root), che prima di tutto verifica la FIRMA DELL'AUTORE (file .sig fatto sul Mac con «Firma
NetMon», tools/mac) con la chiave pubblica di rilascio installata in
/usr/local/share/netmon/release-key.pub. Senza firma valida non si installa nulla, nemmeno da un
pannello /admin compromesso. Sulle sonde l'origine la garantisce la firma della VM.
"""
__version__ = "1.1.20261029-120000"
import json
import os
import re
import stat
import sys
import zipfile

MAX_ZIP = 10 * 1024 * 1024           # file caricato
MAX_TOTAL = 60 * 1024 * 1024         # tutto il contenuto decompresso
MAX_FILE = 8 * 1024 * 1024           # un singolo file decompresso
MAX_ENTRIES = 300
ROOT = "netmon/"
VERSION_FMT = re.compile(r"^\d+\.\d+\.\d{8}-\d{6}$")
PY_VERSION = re.compile(r'^__version__\s*=\s*"([^"]*)"', re.M)
SH_VERSION = re.compile(r'^NETMON_VERSION="([^"]*)"', re.M)

PROBE_PY = ["probe.py", "pinger.py", "config_web.py", "sysops.py"]
REQUIRED = {
    "server": ["VERSION"] + [f"server/{f}" for f in (
        "app.py", "auth.py", "account.py", "mfa.py", "monitor.py", "notifier.py", "vmops.py", "brand.py", "fonts.py", "i18n.py", "i18n_admin.py", "privacy.html",
        "pkgcheck.py", "requirements.txt", "env.example", "netmon-server.service", "Caddyfile",
        "installa-server.sh", "netmon-vm-upgrade", "netmon-vm-selfupdate", "netmon-vm-rollback",
        "sudoers-netmon-vm", "netmon-firma-sonde")] + [f"probe/{f}" for f in PROBE_PY],
    "probe": ["VERSION"] + [f"probe/{f}" for f in PROBE_PY + [
        "pkgcheck.py", "installa-sonda.sh", "netprobe-upgrade", "netprobe-selfupdate", "netprobe-zipupdate", "netprobe-wifi",
        "sudoers-netprobe", "netmon-probe.service", "netmon-config.service", "netmon-config.socket"]],
}


def mac_junk(name):
    """File che il Finder aggiunge a uno zip creato con «Comprimi»: non fanno parte del pacchetto."""
    base = name.rstrip("/").rsplit("/", 1)[-1]
    return name.startswith("__MACOSX/") or name == "__MACOSX/" or base.startswith("._") or base == ".DS_Store"


def version_key(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def check(path, target, installed):
    """(esito, versione, controlli, errori, zip aperto)."""
    checks, errors = [], []

    def ok(text):
        checks.append(["ok", text])

    def bad(text):
        checks.append(["bad", text])
        errors.append(text)

    size = os.path.getsize(path)
    if size > MAX_ZIP:
        bad(f"File troppo grande ({size // 1024} kB, massimo {MAX_ZIP // 1048576} MB)")
        return False, None, checks, errors, None
    try:
        zf = zipfile.ZipFile(path)
        infos = zf.infolist()
    except (zipfile.BadZipFile, OSError, ValueError):
        bad("Non è un file zip valido")
        return False, None, checks, errors, None
    ok("File zip leggibile")

    if len(infos) > MAX_ENTRIES:
        bad(f"Troppi file nel pacchetto ({len(infos)}, massimo {MAX_ENTRIES})")
    total = sum(i.file_size for i in infos)
    if total > MAX_TOTAL or any(i.file_size > MAX_FILE for i in infos):
        bad("Contenuto decompresso troppo grande: il pacchetto non è quello di netmon")
    names, seen, unsafe, junk = {}, set(), [], 0
    for i in infos:
        n = i.filename
        if mac_junk(n):
            junk += 1
            continue
        mode = (i.external_attr >> 16) & 0o170000
        if (not n.startswith(ROOT) or n.startswith("/") or "\\" in n or "\x00" in n
                or any(part in ("..", "") for part in n[len(ROOT):].rstrip("/").split("/") if n != ROOT)):
            unsafe.append(n)
        elif mode == stat.S_IFLNK:
            unsafe.append(n + " (collegamento simbolico)")
        elif n in seen:
            unsafe.append(n + " (doppione)")
        seen.add(n)
        if not i.is_dir():
            names[n[len(ROOT):]] = i
    if unsafe:
        bad("Percorsi non ammessi: " + ", ".join(unsafe[:5]) + (" …" if len(unsafe) > 5 else ""))
    else:
        ok("Tutti i file stanno nella cartella netmon/, senza percorsi pericolosi né collegamenti")
    if junk:
        checks.append(["info", f"{junk} file nascosti del Mac (__MACOSX, ._*, .DS_Store) ignorati"])

    missing = [f for f in REQUIRED[target] if f not in names]
    if missing:
        bad("Mancano file necessari: " + ", ".join(missing[:6]) + (" …" if len(missing) > 6 else ""))
    else:
        ok(f"Presenti tutti i file per {'la VM' if target == 'server' else 'la sonda'}")
    if errors:
        return False, None, checks, errors, zf

    def read(name):
        return zf.read(names[name]).decode("utf-8", "replace")

    version = read("VERSION").strip()
    if not VERSION_FMT.match(version):
        bad(f"Versione non valida nel file VERSION: {version[:40]!r}")
        return False, None, checks, errors, zf
    wrong = []
    for name, info in names.items():
        if not name.startswith(("server/", "probe/")):
            continue
        text = None
        if name.endswith(".py"):
            text = read(name)
            m = PY_VERSION.search(text)
        elif name.endswith(".sh"):
            text = read(name)
            m = SH_VERSION.search(text)
        else:
            continue
        if not m or m.group(1) != version:
            wrong.append(name)
    if wrong:
        bad("Programmi con una versione diversa da VERSION: " + ", ".join(wrong[:5]))
    else:
        ok(f"Tutti i programmi sono della versione {version}")

    if not installed or not VERSION_FMT.match(installed):
        ok("Versione installata sconosciuta: nessun confronto")
    elif version_key(version) <= version_key(installed):
        bad(f"La versione {version} non è più recente di quella installata ({installed})")
    else:
        ok(f"Versione più recente di quella installata ({installed} → {version})")

    syntax = []
    for name in names:
        if name.endswith(".py") and name.startswith(("server/", "probe/", "tools/")):
            try:
                compile(zf.read(names[name]), name, "exec")
            except (SyntaxError, ValueError) as exc:
                syntax.append(f"{name}: {exc.__class__.__name__}")
    if syntax:
        bad("Errori nei programmi: " + ", ".join(syntax[:4]))
    else:
        ok("Programmi Python senza errori di sintassi")

    return not errors, version, checks, errors, zf


def extract(zf, dest):
    """Estrazione controllata: solo file normali, percorsi ricostruiti a mano, nessun permesso speciale."""
    if os.listdir(dest):
        raise SystemExit("cartella di estrazione non vuota")
    real = os.path.realpath(dest)
    for i in zf.infolist():
        if mac_junk(i.filename):
            continue
        rel = i.filename[len(ROOT):].rstrip("/")
        if not rel:
            continue
        target = os.path.realpath(os.path.join(real, "netmon", *rel.split("/")))
        if not target.startswith(real + os.sep):
            raise SystemExit(f"percorso non ammesso: {i.filename}")
        if i.is_dir():
            os.makedirs(target, mode=0o755, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target), mode=0o755, exist_ok=True)
        with zf.open(i) as src, open(target, "xb") as out:
            out.write(src.read(MAX_FILE + 1)[:MAX_FILE])
        os.chmod(target, 0o644)


# ------------------------------------------------------------------ le sonde vanno aggiornate?
# Ogni rilascio cambia il numero di versione in tutti i file, anche quando i programmi della sonda
# non cambiano. Qui si confrontano i file della sonda di due pacchetti SENZA il numero di versione:
# se sono identici, aggiornare le sonde non serve.
UPDATE_INFO = "update-info"          # scritto da installa-server.sh nel deposito probe-dist


def _no_version(data, version):
    return data.replace(version.encode(), b"@VERSIONE@") if version else data


def probe_files(src):
    """{nome: contenuto senza numero di versione} dei file della sonda. src può essere un
    netmon.zip, la cartella di un pacchetto estratto (con VERSION e probe/) oppure il deposito del
    server con i soli programmi (probe-dist). None se non si riesce a leggere."""
    try:
        if os.path.isdir(src):
            folder = os.path.join(src, "probe")
            if os.path.isdir(folder):
                with open(os.path.join(src, "VERSION"), encoding="utf-8") as f:
                    version = f.read().strip()
                names = [n for n in sorted(os.listdir(folder))
                         if not n.startswith(".") and not n.endswith((".pyc", ".bak", "~"))
                         and os.path.isfile(os.path.join(folder, n))]
            else:
                folder, names = src, PROBE_PY
                with open(os.path.join(src, "probe.py"), encoding="utf-8") as f:
                    m = PY_VERSION.search(f.read())
                version = m.group(1) if m else ""
            out = {}
            for n in names:
                with open(os.path.join(folder, n), "rb") as f:
                    out[n] = _no_version(f.read(MAX_FILE), version)
            return out
        with zipfile.ZipFile(src) as zf:
            version = zf.read(ROOT + "VERSION")[:100].decode("utf-8", "replace").strip()
            pre = ROOT + "probe/"
            return {i.filename[len(pre):]: _no_version(zf.read(i), version) for i in zf.infolist()
                    if i.filename.startswith(pre) and not i.is_dir() and "/" not in i.filename[len(pre):]
                    and not mac_junk(i.filename)
                    and i.file_size <= MAX_FILE}
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None


def probe_changes(old, new):
    """File della sonda che cambiano tra `old` e `new` oltre al numero di versione, in ordine
    (elenco vuoto = le sonde non vanno aggiornate). None se il confronto non è possibile."""
    a, b = probe_files(old), probe_files(new)
    if not a or not b:
        return None
    # deposito con i soli programmi (server vecchio, senza pacchetto completo): confronto su quelli
    partial = os.path.isdir(old) and not os.path.isdir(os.path.join(old, "probe"))
    names = set(a) if partial else set(a) | set(b)
    return sorted(n for n in names if a.get(n) != b.get(n))


def probe_update_info(dist, new):
    """Cosa cambia per le sonde installando il pacchetto `new` su un server che ora distribuisce
    alle sonde il contenuto di `dist` (probe-dist):
      from     versione distribuita finora (None se il deposito non c'è)
      changed  file della sonda che cambiano oltre al numero di versione ([] = sonde da non
               aggiornare, None = non confrontabile)
      same_as  versioni precedenti i cui programmi della sonda sono identici a quelli di `new`:
               una sonda con una di queste versioni è già aggiornata."""
    cur = ""
    try:
        with open(os.path.join(dist, "probe.py"), encoding="utf-8") as f:
            m = PY_VERSION.search(f.read())
        cur = m.group(1) if m and VERSION_FMT.match(m.group(1)) else ""
    except OSError:
        pass
    old = os.path.join(dist, "netmon.zip")
    changed = probe_changes(old if os.path.isfile(old) else dist, new) if cur else None
    same = []
    if changed == []:
        try:
            with open(os.path.join(dist, UPDATE_INFO), encoding="utf-8") as f:
                prev = json.load(f).get("same_as") or []
        except (OSError, ValueError, AttributeError):
            prev = []
        same = [v for v in prev if isinstance(v, str) and VERSION_FMT.match(v) and v != cur][-50:] + [cur]
    return {"from": cur or None, "changed": changed, "same_as": same}


def probe_info_main(argv):
    """pkgcheck.py --probe-info PROBE_DIST PACCHETTO [FILE]: scrive in FILE il JSON di
    probe_update_info e stampa una riga per lo script che installa:
    «changed file1 file2…», «same» oppure «unknown»."""
    if len(argv) < 2:
        print(__doc__)
        return 2
    info = probe_update_info(argv[0], argv[1])
    if len(argv) > 2:
        with open(argv[2], "w", encoding="utf-8") as f:
            json.dump(info, f)
    ch = info["changed"]
    print("unknown" if ch is None else "same" if not ch else "changed " + " ".join(ch))
    return 0


def main(argv):
    if argv and argv[0] == "--probe-info":
        return probe_info_main(argv[1:])
    args = {"--target": None, "--installed": "", "--extract": None}
    path = None
    it = iter(argv)
    for a in it:
        if a in args:
            args[a] = next(it, "")
        else:
            path = a
    if args["--target"] not in REQUIRED or not path:
        print(__doc__)
        return 2
    good, version, checks, errors, zf = check(path, args["--target"], args["--installed"])
    if good and args["--extract"]:
        extract(zf, args["--extract"])
    print(json.dumps({"ok": good, "version": version, "installed": args["--installed"],
                      "checks": checks, "errors": errors}, ensure_ascii=False))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
