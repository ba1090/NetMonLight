#!/bin/bash
# netmon versione 1.1.20261027-171600
# Compila «Firma NetMon» da tools/firma/src (Go, solo libreria standard), su Linux o macOS:
#   - tools/windows/FirmaNetMon.exe                                   (Windows 10/11, 64 bit, con icona)
#   - tools/mac/Firma NetMon.app/Contents/MacOS/firma-netmon-arm64    (Mac Apple Silicon)
#   - tools/mac/Firma NetMon.app/Contents/MacOS/firma-netmon-amd64    (Mac Intel)
# L'app per il Mac sceglie da sola il programma giusto; se manca usa le finestre di sistema
# (firma-netmon-classic). Gli eseguibili restano nel repository e non entrano nello zip del pacchetto.
# Serve Go 1.22 o successivo; l'icona di Windows la inserisce go-winres, a versione fissa.
#
# Uso (dalla cartella netmon):  bash tools/firma/build.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
MACOS="$ROOT/tools/mac/Firma NetMon.app/Contents/MacOS"
cd "$HERE/src"
FLAGS=(-trimpath -buildvcs=false)

# Windows: icona e dati del programma nell'eseguibile, niente finestra del terminale
go run github.com/tc-hib/go-winres@v0.3.3 simply --icon ../icon.png --manifest gui \
  --product-name "Firma NetMon" --file-description "Firma NetMon: firma dei pacchetti netmon" \
  --product-version 1.0.0.0 --file-version 1.0.0.0 --original-filename FirmaNetMon.exe --arch amd64
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build "${FLAGS[@]}" -ldflags "-H=windowsgui -s -w" \
  -o "$ROOT/tools/windows/FirmaNetMon.exe" .
rm -f rsrc_windows_*.syso

# Mac: il linker di Go firma da solo (firma ad hoc) i programmi per Apple Silicon, come macOS richiede
for arch in arm64 amd64; do
  GOOS=darwin GOARCH=$arch CGO_ENABLED=0 go build "${FLAGS[@]}" -ldflags "-s -w" -o "$MACOS/firma-netmon-$arch" .
  chmod 755 "$MACOS/firma-netmon-$arch"
done

cd "$ROOT"
sha256sum tools/windows/FirmaNetMon.exe "$MACOS"/firma-netmon-arm64 "$MACOS"/firma-netmon-amd64 2>/dev/null \
  || shasum -a 256 tools/windows/FirmaNetMon.exe "$MACOS"/firma-netmon-arm64 "$MACOS"/firma-netmon-amd64
echo "Fatto."
