#!/usr/bin/env python3
"""Porta tutto il pacchetto netmon a una nuova versione e crea lo zip da caricare.

Uso (dalla cartella netmon):   python3 tools/nuova-versione.py [versione]
Senza argomento la versione è X.Y.AAAAMMGG-hhmmss (ora italiana), con X.Y della versione attuale.
Con un argomento la versione indica esattamente (es. 1.0.20261013-163000).

Sostituisce SOLO il numero di versione attuale (letto dal file VERSION), come testo letterale,
in tutti i file del pacchetto. Non usa espressioni regolari sui sorgenti: così non può
modificare per errore il codice (com'era successo alle regex della versione in app.py).
Alla fine controlla che server e sonda si compilino, che tutti i file abbiano la stessa versione
e crea SEMPRE lo zip ../netmon-<versione>.zip, verificato con pkgcheck (sotto netmon/, sotto i
10 MB, meno di 300 file, senza .DS_Store, __pycache__ o *.pyc).

OGNI zip porta la sua versione: a ogni modifica, anche di un solo carattere, si alza la
versione. La stessa versione non viene mai re-zipata (il pannello la rifiuterebbe: accetta solo
versioni più alte dell'installata). Scrivi prima le novità nel CHANGELOG con la versione che
vuoi, poi lancia lo script.

Poi FIRMA lo zip sul tuo Mac con «Firma NetMon» (tools/mac): la VM installa dal pannello solo
pacchetti con la firma dell'autore. Il pacchetto deve contenere la chiave pubblica di rilascio in
server/release-key.pub (la crea «Firma NetMon»): senza, lo script avvisa.
"""
import json
import py_compile
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKGCHECK = ROOT / "server" / "pkgcheck.py"
ZIP_OUT = ROOT.parent                       # zip accanto alla cartella netmon
SKIP_DIRS = {".git", "__pycache__", "venv", ".hypothesis", ".pytest_cache"}   # cache dei test
SKIP_FILES = {"CHANGELOG.md"}                  # lo storico conserva le versioni passate
TEXT_EXT = {".py", ".sh", ".md", ".txt", ".service", ".socket", ".example", ""}


def build_zip(version: str, problems: list[str]) -> Path:
    """Crea ../netmon-<versione>.zip da tutto il contenuto della cartella netmon/ e lo verifica."""
    out = ZIP_OUT / f"netmon-{version}.zip"
    entries = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if SKIP_DIRS & set(rel.parts):
            continue
        # gli eseguibili di «Firma NetMon» restano nel repository: nel pacchetto sarebbero un peso inutile per
        # VM e sonde (l'app per il Mac nello zip usa le finestre di sistema)
        if (path.name in (".DS_Store", "CLAUDE.md", "FirmaNetMon.exe", "firma-netmon-arm64", "firma-netmon-amd64")
                or path.suffix in (".pyc",)
                or re.match(r"netmon-.*\.zip(\.sig)?$", path.name)):
            continue
        entries.append((path, rel))
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for path, rel in entries:
                zf.write(path, "netmon/" + rel.as_posix())
    except OSError as exc:
        problems.append(f"zip non scrivibile: {exc}")
        return out
    # verifica con il verificatore ufficiale di root: l'unico che la VM userà davvero
    res = subprocess.run([sys.executable, str(PKGCHECK), "--target", "server", str(out)],
                         capture_output=True, text=True)
    try:
        report = json.loads(res.stdout)
    except ValueError:
        report = {}
    if not report.get("ok"):
        problems.append("zip non idoneo: " + (report.get("errors") or res.stdout.strip()[:300] or "esito vuoto"))
    else:
        print(f"Zip creata e verificata: {out} ({len(entries)} file)")
    return out


# Add-on di Home Assistant (repository netmon-homeassistant, accanto a questo): la sua sonda è una
# copia dei programmi di probe/ e porta la stessa versione. Si allinea qui, a ogni rilascio, perché
# non resti indietro (va poi pubblicata anche quella, con un commit nel suo repository).
HA_ROOT = ROOT.parent / "netmon-homeassistant"
HA_FILES = ("probe.py", "config_web.py", "pinger.py", "sysops.py")


def sync_homeassistant(version: str) -> list[str]:
    """Copia i programmi della sonda nell'add-on e ne aggiorna la versione; [] se l'add-on non c'è."""
    addon = HA_ROOT / "netmon-sonda"
    if not (addon / "config.yaml").is_file():
        return []
    for name in HA_FILES:
        (addon / "probe" / name).write_bytes((ROOT / "probe" / name).read_bytes())
    cfg = addon / "config.yaml"
    text = cfg.read_bytes().decode("utf-8")
    cfg.write_bytes(re.sub(r'(?m)^version: "[^"]*"', f'version: "{version}"', text).encode("utf-8"))
    return [f"netmon-sonda/probe/{n}" for n in HA_FILES] + ["netmon-sonda/config.yaml"]


def main():
    args = sys.argv[1:]
    old = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    if args:
        new = args[0].strip()
    else:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo("Europe/Rome"))
        except Exception:  # noqa: BLE001
            now = datetime.now()
        # stesso prefisso della versione attuale (1.0.…): con un prefisso più basso il pacchetto
        # risulterebbe "più vecchio" di quello installato e verrebbe rifiutato
        prefix = old.rsplit(".", 1)[0] if re.fullmatch(r"\d+\.\d+\.\d{8}-\d{6}", old) else "1.0"
        new = prefix + "." + now.strftime("%Y%m%d-%H%M%S")
    if not re.fullmatch(r"\d+\.\d+\.\d{8}-\d{6}", new):
        sys.exit(f"Versione non valida: {new} (formato 1.0.AAAAMMGG-hhmmss)")
    if new == old:
        sys.exit("La versione è già " + new)

    changed = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.name in SKIP_FILES or SKIP_DIRS & set(path.relative_to(ROOT).parts):
            continue
        if path.suffix not in TEXT_EXT and path.name not in ("Caddyfile", "VERSION"):
            continue
        # byte per byte: su Windows read_text/write_text trasformerebbero i fine riga in CRLF, e
        # gli script della VM e della sonda (bash, sudoers, unità systemd) smetterebbero di funzionare
        try:
            text = path.read_bytes().decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if old in text:
            path.write_bytes(text.replace(old, new).encode("utf-8"))
            changed.append(str(path.relative_to(ROOT)))

    # controlli: si compila tutto e ogni programma dichiara la nuova versione
    problems = []
    for py in list((ROOT / "server").glob("*.py")) + list((ROOT / "probe").glob("*.py")):
        try:
            py_compile.compile(str(py), doraise=True, cfile=None)
        except py_compile.PyCompileError as exc:
            problems.append(f"{py.name}: {exc.msg}")
        text = py.read_text(encoding="utf-8")
        if f'__version__ = "{new}"' not in text:
            problems.append(f"{py.name}: versione non aggiornata")

    for extra in (ROOT / "probe" / "netprobe-wifi",):
        try:
            py_compile.compile(str(extra), doraise=True, cfile=None)
        except py_compile.PyCompileError as exc:
            problems.append(f"{extra.name}: {exc.msg}")

    # la pagina locale della sonda porta una copia del traduttore del server: devono restare uguali
    i18n = [re.search(r'^I18N_JS = r"""(.*?)"""', f.read_text(encoding="utf-8"), re.S | re.M)
            for f in (ROOT / "server" / "i18n.py", ROOT / "probe" / "config_web.py")]
    if not all(i18n) or i18n[0].group(1) != i18n[1].group(1):
        problems.append("I18N_JS di server/i18n.py e probe/config_web.py sono diversi: devono essere uguali")

    if (ROOT / "server" / "pkgcheck.py").read_bytes() != (ROOT / "probe" / "pkgcheck.py").read_bytes():
        problems.append("server/pkgcheck.py e probe/pkgcheck.py sono diversi: devono essere lo stesso file")

    # lo zip si crea SEMPRE, con la versione nuova; se non passa i controlli, esce con errore
    build_zip(new, problems)
    if problems:
        print("\nATTENZIONE:")
        for p in problems:
            print("  ", p)
        sys.exit(1)
    ha = sync_homeassistant(new)
    print(f"Versione {old} → {new}: {len(changed)} file aggiornati")
    for c in changed:
        print("  ", c)
    if ha:
        print(f"\nAdd-on di Home Assistant allineato ({HA_ROOT}): {len(ha)} file. Pubblicalo con un commit\n"
              "nel repository netmon-homeassistant, così Home Assistant propone l'aggiornamento della sonda.")
    if not (ROOT / "server" / "release-key.pub").is_file():
        print("\nATTENZIONE: manca server/release-key.pub (chiave pubblica di rilascio). Creala con «Firma NetMon»\n"
              "sul Mac (tools/mac) e mettila nel repository: una VM senza chiave rifiuta i pacchetti dal pannello.")
    print("\nZip: ../netmon-<versione>.zip. Firmalo sul Mac con «Firma NetMon» e carica nel pannello lo zip\n"
          "insieme al suo .sig. Ogni prossima modifica, anche minima, alza la versione.")


if __name__ == "__main__":
    main()