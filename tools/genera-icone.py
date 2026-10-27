#!/usr/bin/env python3
"""Genera server/brand.py con il logo di netmon (SVG) e le sue versioni PNG.

Uso (dalla cartella netmon, su un computer con Playwright e Chromium):
    python3 tools/genera-icone.py          # server/brand.py e icona dell'app per il Mac
    python3 tools/genera-icone.py --mac    # solo le icone di «Firma NetMon»: AppIcon.icns (Mac) e
                                           # tools/firma/icon.png (Windows, la usa tools/firma/build.sh)
Con un Chromium già installato altrove:  CHROMIUM=/percorso/chrome python3 tools/genera-icone.py

Il disegno del logo sta QUI (LOGO, FAVICON, TOUCH): per cambiarlo si modifica questo file e si
rilancia. Le PNG servono dove l'SVG non funziona: email (Gmail e Outlook non mostrano SVG),
icona della schermata Home di iPhone e Android, favicon.ico dei browser vecchi.
La pagina locale della sonda ha una copia del solo FAVICON (non può importare file del server):
se cambi il disegno, aggiorna anche LOGO_SVG, FAVICON_SVG e FAVICON_PNG in probe/config_web.py.
"""
import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Logo «maglia con la casa al centro» su fondo blu oceano: sei dispositivi sui vertici di un esagono,
# come in una rete mesh, collegati alla sonda di casa (la casetta azzurra al centro).
OCEAN, NODE, CORE = "#174A72", "#FFFFFF", "#7FB8E0"


def mesh(r, node, spoke, ring, k):
    """Esagono di raggio r centrato in (32, 32): bordo tenue, raggi, sei nodi bianchi e al centro una
    casetta azzurra su un tondo blu (k: scala della casetta)."""
    from math import cos, pi, sin
    pts = [(32 + r * sin(i * pi / 3), 32 - r * cos(i * pi / 3)) for i in range(6)]
    xy = [f"{x:.2f} {y:.2f}" for x, y in pts]
    house = [(0, -7.5), (-8, -.5), (-5.4, -.5), (-5.4, 7), (5.4, 7), (5.4, -.5), (8, -.5)]
    hp = "L".join(f"{32 + k * x:.2f} {32 + k * y:.2f}" for x, y in house)
    return (f'<path d="M{"L".join(xy)}Z" fill="none" stroke="{NODE}" stroke-opacity=".45" stroke-width="{ring}" '
            f'stroke-linejoin="round"/>'
            f'<path d="{"".join(f"M32 32L{p}" for p in xy)}" stroke="{NODE}" stroke-width="{spoke}" stroke-linecap="round"/>'
            + "".join(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{node}" fill="{NODE}"/>' for x, y in pts)
            + f'<circle cx="32" cy="32" r="{9 * k:.2f}" fill="{OCEAN}"/>'
            + f'<path d="M{hp}Z" fill="{CORE}" stroke="{CORE}" stroke-width="{1.5 * k:.2f}" stroke-linejoin="round"/>')


LOGO = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" rx="14" fill="{OCEAN}"/>{mesh(20, 4, 1.8, 1.8, 1)}</svg>')

# Per 16-32 px: esagono e casetta più grandi, tratti più spessi, altrimenti si impastano
FAVICON = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
           f'<rect width="64" height="64" rx="12.5" fill="{OCEAN}"/>{mesh(23, 5.5, 3, 3, 1.35)}</svg>')

# Schermata Home del telefono: quadrato pieno (gli angoli li arrotonda il sistema), disegno più
# piccolo per restare nella zona visibile
TOUCH = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
         f'<rect width="64" height="64" fill="{OCEAN}"/>{mesh(16, 3.3, 1.5, 1.5, .8)}</svg>')

# App «Firma NetMon» per il Mac (tools/mac): forma arrotondata standard di macOS (riquadro di 824 su
# 1024 px, con un'ombra leggera), il logo e in basso a destra un pennino su un tondo bianco: la firma.
MAC_ICON = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            '<defs><filter id="sh" x="-20%" y="-20%" width="140%" height="140%">'
            '<feDropShadow dx="0" dy=".7" stdDeviation=".9" flood-color="#000" flood-opacity=".28"/></filter>'
            '<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="#1E5C8C"/><stop offset="1" stop-color="{OCEAN}"/></linearGradient></defs>'
            '<rect x="6.25" y="6.25" width="51.5" height="51.5" rx="11.6" fill="url(#bg)" filter="url(#sh)"/>'
            f'<g transform="translate(-3 -3)">{mesh(15.5, 3.2, 1.6, 1.6, .8)}</g>'
            '<g filter="url(#sh)"><circle cx="45" cy="45" r="9.3" fill="#FFFFFF"/></g>'
            f'<g transform="translate(45 45) rotate(45)" fill="{OCEAN}">'
            '<path d="M0 -6.6L3.9 -1.4L2.3 3.6L0 6.2L-2.3 3.6L-3.9 -1.4Z"/>'
            '<path d="M0 -.6V5.4" stroke="#FFFFFF" stroke-width=".75" stroke-linecap="round"/>'
            '<circle cx="0" cy="-1.1" r="1.05" fill="#FFFFFF"/></g>'
            f'<path d="M37.6 52.3c1.4-1.3 2.6-1.4 3.6-.5s2.2.9 3.5-.4" fill="none" stroke="{CORE}" stroke-width="1.1" '
            'stroke-linecap="round"/></svg>')
MAC_ICNS = ROOT / "tools" / "mac" / "Firma NetMon.app" / "Contents" / "Resources" / "AppIcon.icns"
WIN_PNG = ROOT / "tools" / "firma" / "icon.png"            # 256 px: tools/firma/build.sh ne fa l'icona di FirmaNetMon.exe
# tipo dell'elemento .icns → lato in px (tutti PNG, letti da macOS 10.7 in poi)
ICNS_TYPES = [(b"icp4", 16), (b"icp5", 32), (b"ic11", 32), (b"ic12", 64), (b"ic07", 128), (b"ic13", 256),
              (b"ic08", 256), (b"ic14", 512), (b"ic09", 512), (b"ic10", 1024)]

# nome → (disegno, lato in px)
PNGS = {"FAVICON_32": (FAVICON, 32), "LOGO_EMAIL": (LOGO, 96), "TOUCH_180": (TOUCH, 180)}


def render(svg, size, page):
    page.set_viewport_size({"width": size, "height": size})
    page.set_content('<html><body style="margin:0;background:transparent">'
                     + svg.replace("<svg ", f'<svg width="{size}" height="{size}" ', 1) + "</body></html>")
    return page.locator("svg").screenshot(omit_background=True)


def write_icns(page):
    """AppIcon.icns: un PNG per ogni misura, nel formato di Apple (intestazione 'icns' + elementi)."""
    import struct
    sizes = {}
    body = b""
    for kind, size in ICNS_TYPES:
        png = sizes.setdefault(size, render(MAC_ICON, size, page))
        body += kind + struct.pack(">I", 8 + len(png)) + png
    MAC_ICNS.parent.mkdir(parents=True, exist_ok=True)
    MAC_ICNS.write_bytes(b"icns" + struct.pack(">I", 8 + len(body)) + body)
    print(f"Scritto {MAC_ICNS.relative_to(ROOT)} ({len(sizes)} misure, da 16 a 1024 px)")
    WIN_PNG.parent.mkdir(parents=True, exist_ok=True)
    WIN_PNG.write_bytes(sizes[256])
    print(f"Scritto {WIN_PNG.relative_to(ROOT)} (256 px, per l'eseguibile di Windows)")


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("Serve Playwright:  pip install playwright && playwright install chromium")
    only_mac = "--mac" in sys.argv[1:]
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
        page = browser.new_page()
        write_icns(page)
        if not only_mac:
            for name, (svg, size) in PNGS.items():
                out[name] = base64.b64encode(render(svg, size, page)).decode()
        browser.close()
    if only_mac:
        return

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    lines = [
        '"""Logo di netmon: SVG per le pagine, PNG per email, telefono e browser vecchi.',
        "",
        "File generato da tools/genera-icone.py: non modificarlo a mano (cambia il disegno là e rilancialo).",
        '"""',
        f'__version__ = "{version}"',
        "import base64",
        "",
        f"LOGO_SVG = {LOGO!r}",
        f"FAVICON_SVG = {FAVICON!r}",
        "",
    ]
    for name, data in out.items():
        chunks = [data[i:i + 96] for i in range(0, len(data), 96)]
        lines.append(f"{name}_PNG = base64.b64decode(")
        lines += [f'    "{c}"' for c in chunks]
        lines.append(")")
        lines.append("")
    (ROOT / "server" / "brand.py").write_text("\n".join(lines), encoding="utf-8")
    print("Scritto server/brand.py:", ", ".join(f"{n} ({PNGS[n][1]} px)" for n in out))


if __name__ == "__main__":
    main()
