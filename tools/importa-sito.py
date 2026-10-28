#!/usr/bin/env python3
"""Porta il sito di presentazione (netmon-sito) dentro NetMon Light: crea server/sito.py.

Uso (dalla cartella netmon):   python3 tools/importa-sito.py CARTELLA_O_ZIP_DEL_SITO

Accetta lo zip del sito (netmon-sito-<versione>.zip) oppure la sua cartella estratta (quella con
VERSION e www/). Prende le quattro pagine (www/index.html, en/, de/, fr/) e le scrive in
server/sito.py come testi Python, come fanno fonts.py e brand.py: così aggiornamento dal pannello,
copia di sicurezza e rollback le trattano come gli altri programmi del server.

Su NetMon Light il sito sta sullo stesso dominio di netmon: i link verso la dashboard
(https://dashboard.netmonhome.net/) diventano /dashboard e l'informativa /privacy. Caratteri e icone
del sito (/fonts/…, /favicon…) li serve già netmon, con gli stessi nomi: non si copiano.

Dopo l'importazione: alza la versione con tools/nuova-versione.py come per ogni modifica.
"""
import re
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "server" / "sito.py"
LANGS = {"it": "index.html", "en": "en/index.html", "de": "de/index.html", "fr": "fr/index.html"}
# link della versione con due macchine -> stesso dominio (prima il più lungo)
LINKS = (("https://dashboard.netmonhome.net/privacy", "/privacy"),
         ("https://dashboard.netmonhome.net/", "/dashboard"))


def site_dir(arg: Path, tmp: str) -> Path:
    if arg.is_file():
        with zipfile.ZipFile(arg) as z:
            for name in z.namelist():
                if name.startswith("/") or ".." in Path(name).parts:
                    sys.exit(f"Percorso non ammesso nello zip: {name}")
            z.extractall(tmp)
        arg = Path(tmp)
    for cand in (arg, *arg.iterdir()):
        if cand.is_dir() and (cand / "www" / "index.html").is_file():
            return cand
    sys.exit("Non trovo www/index.html: indica lo zip del sito o la cartella netmon-sito.")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with tempfile.TemporaryDirectory() as tmp:
        src = site_dir(Path(sys.argv[1]).resolve(), tmp)
        version = (src / "VERSION").read_text(encoding="utf-8").strip() if (src / "VERSION").is_file() else "?"
        pages = {}
        for lang, rel in LANGS.items():
            f = src / "www" / rel
            if not f.is_file():
                sys.exit(f"Manca la pagina {rel}")
            html = f.read_text(encoding="utf-8")
            for old, new in LINKS:
                html = html.replace(old, new)
            if "dashboard.netmonhome.net" in html:
                sys.exit(f"{rel}: resta un link a dashboard.netmonhome.net che non so come cambiare")
            pages[lang] = html
    if not re.fullmatch(r"[0-9.]+-?[0-9]*", version):
        version = "?"
    current = ROOT / "VERSION"
    netmon_version = current.read_text(encoding="utf-8").strip()
    body = ['"""Sito di presentazione (pagina pubblica su /, /en/, /de/, /fr/).',
            "",
            "File generato da tools/importa-sito.py dallo zip netmon-sito: non modificarlo a mano,",
            'rifai l\'importazione con la pagina nuova."""',
            f'__version__ = "{netmon_version}"',
            f'SITO_VERSION = "{version}"',
            "",
            "PAGES = {"]
    for lang, html in pages.items():
        body.append(f"    {lang!r}: {html!r},")
    body.append("}")
    OUT.write_text("\n".join(body) + "\n", encoding="utf-8")
    print(f"Scritto {OUT.relative_to(ROOT)}: sito {version}, {len(pages)} pagine "
          f"({sum(len(p) for p in pages.values()) // 1024} KB).")


if __name__ == "__main__":
    main()
