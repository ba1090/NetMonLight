#!/usr/bin/env bash
# netmon · installazione guidata della sonda (es. Raspberry Pi)
#
# Uso, dalla sonda, dopo aver copiato la cartella probe:
#   sudo bash probe/installa-sonda.sh              installazione o riconfigurazione
#   sudo bash probe/installa-sonda.sh --aggiorna   solo aggiornamento dei file
#   sudo bash probe/installa-sonda.sh --disinstalla  toglie netmon dalla sonda (chiede conferma)
#
# Verifica il sistema, installa i pacchetti, chiede server, token, dispositivi e FRITZ!Box
# (provandoli subito), avvia i servizi, controlla il primo invio al server e alla fine
# mostra le informazioni da conservare.
NETMON_VERSION="1.1.20261027-171500"

set -uo pipefail

# ------------------------------------------------------------------ aspetto e domande
if [ -t 1 ]; then
  B=$'\e[1m'; D=$'\e[2m'; R=$'\e[31m'; G=$'\e[32m'; Y=$'\e[33m'; C=$'\e[36m'; N=$'\e[0m'
else B=; D=; R=; G=; Y=; C=; N=; fi

LOG=/var/log/netmon-installazione.log
STEP=0; STEPS=6
step() { STEP=$((STEP+1)); printf '\n%s━━ %d/%d · %s ━━%s\n' "$B$C" "$STEP" "$STEPS" "$1" "$N"; }
ok()   { printf '  %s✔%s %s\n' "$G" "$N" "$*"; }
info() { printf '  %s·%s %s\n' "$D" "$N" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$*"; }
die()  { printf '\n  %s✘ %s%s\n' "$R" "$*" "$N"; printf '  Dettagli nel registro: %s\n\n' "$LOG"; exit 1; }

TTY=/dev/tty
NONINT=${NETMON_NONINTERACTIVE:-0}     # 1 = lanciato da netprobe-zipupdate: nessuna domanda, valori predefiniti
ask() {
  local q=$1 def=${2-}
  [ "$NONINT" = 1 ] && { REPLY=$def; return 0; }
  if [ -n "$def" ]; then printf '  %s? %s%s [%s]: ' "$B" "$q" "$N" "$def"; else printf '  %s? %s%s: ' "$B" "$q" "$N"; fi
  IFS= read -r REPLY < "$TTY" || REPLY=
  REPLY=$(printf '%s' "$REPLY" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
  [ -z "$REPLY" ] && REPLY=$def
  return 0
}
ask_secret() {
  [ "$NONINT" = 1 ] && { REPLY=; return 0; }
  printf '  %s? %s%s: ' "$B" "$1" "$N"
  IFS= read -rs REPLY < "$TTY" || REPLY=
  printf '\n'
}
yes_no() {
  local def=$2 hint
  [ "$NONINT" = 1 ] && { [ "$def" = s ]; return; }
  [ "$def" = s ] && hint="S/n" || hint="s/N"
  while :; do
    printf '  %s? %s%s [%s]: ' "$B" "$1" "$N" "$hint"
    IFS= read -r REPLY < "$TTY" || REPLY=
    REPLY=${REPLY:-$def}
    case "${REPLY,,}" in s|si|sì|y|yes) return 0 ;; n|no) return 1 ;; esac
  done
}
run() {
  local what=$1; shift
  printf '  %s…%s %s' "$D" "$N" "$what"
  echo "=== $(date '+%F %T') · $what: $*" >> "$LOG"
  if "$@" >> "$LOG" 2>&1; then printf '\r  %s✔%s %s\n' "$G" "$N" "$what"
  else printf '\r  %s✘%s %s\n' "$R" "$N" "$what"; tail -n 15 "$LOG" | sed 's/^/      /'; die "Passaggio non riuscito: $what"; fi
}

# ------------------------------------------------------------------ percorsi
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEST=/opt/netprobe
ETC=/etc/netprobe
CFG=$ETC/config.yaml
VPY=$DEST/venv/bin/python
FILES=(probe.py pinger.py config_web.py sysops.py pkgcheck.py)
SUMMARY=/root/netmon-sonda-riepilogo.txt
SYSDIR=/var/lib/netprobe-sys                      # log e stato degli aggiornamenti (di root)
KEYDIR=/usr/local/share/netmon
KEYFILE=$KEYDIR/update-key.pub                    # chiave pubblica per verificare gli aggiornamenti
UPDATE_FP=
NAME_RE='^[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}$'

MODE=install
[ "${1-}" = "--aggiorna" ] && MODE=update

# ------------------------------------------------------------------ disinstallazione
# Toglie tutto ciò che questo script installa: servizi, programmi, configurazione, dati, script di
# sistema, permessi e utente. Lascia i pacchetti di sistema (Python, ping, curl… possono servire ad
# altro) e le reti Wi-Fi (sono connessioni di sistema: toglierle farebbe perdere la rete alla sonda).
if [ "${1-}" = "--disinstalla" ]; then
  [ "$(id -u)" -eq 0 ] || { printf '\n  Lancia lo script con sudo:  sudo bash %s --disinstalla\n\n' "$0"; exit 1; }
  [ "$NONINT" = 1 ] && { echo "La disinstallazione non si fa senza conferma." >&2; exit 2; }
  : > "$LOG" && chmod 600 "$LOG"
  OLD_VERSION=$(grep -o '__version__ = "[^"]*"' /opt/netprobe/probe.py 2>/dev/null | cut -d'"' -f2)
  printf '\n%snetmon · disinstallazione della sonda%s%s\n\n' "$B" "${OLD_VERSION:+ (versione $OLD_VERSION)}" "$N"
  # sulla stessa macchina c'è anche il server netmon: il verificatore dei pacchetti è condiviso
  SERVER_HERE=0; [ -f /opt/netmon/app.py ] && SERVER_HERE=1
  UNITS=(netmon-probe.service netmon-config.socket netmon-config.service)
  RUNS=(netprobe-upgrade netprobe-selfupdate netprobe-zipupdate netprobe-wifi)
  echo "  Verranno eliminati:"
  echo "    · i servizi ${UNITS[*]} (fermati, disattivati e tolti da /etc/systemd/system)"
  echo "    · programmi e ambiente Python: /opt/netprobe"
  echo "    · configurazione, con token del server e password del FRITZ!Box e della pagina locale: /etc/netprobe"
  echo "    · misure non ancora inviate, cache, registri degli aggiornamenti: /var/lib/netprobe, /var/lib/netprobe-sys"
  echo "    · chiave per verificare gli aggiornamenti: /usr/local/share/netmon"
  if [ "$SERVER_HERE" = 1 ]; then
    echo "    · (il verificatore /usr/local/lib/netmon resta: lo usa anche il server netmon installato qui)"
  else
    echo "    · verificatore dei pacchetti: /usr/local/lib/netmon"
  fi
  echo "    · script di sistema netprobe-* in /usr/local/sbin (compreso netprobe-uninstall) e i permessi /etc/sudoers.d/netprobe"
  echo "    · l'utente di servizio netprobe e il riepilogo $SUMMARY"
  echo
  echo "  Restano: i pacchetti di sistema (Python, ping, curl, openssl…), le reti Wi-Fi salvate,"
  echo "  il registro $LOG e la cartella da cui hai lanciato lo script ($HERE)."
  echo "  Sul server la sonda resta nel tuo account: toglila da Impostazioni → Sonde → Elimina."
  echo
  for u in "${RUNS[@]}"; do
    if systemctl is-active --quiet "$u" 2>/dev/null; then
      die "È in corso un'operazione della sonda ($u): aspetta che finisca e riprova."
    fi
  done
  KEEP=""
  if [ -f "$CFG" ] && yes_no "Tenere una copia della configurazione (contiene token e password) in /root" s; then
    KEEP=1
  fi
  printf '  %s? Per confermare scrivi DISINSTALLA%s: ' "$B" "$N"
  IFS= read -r REPLY < "$TTY" || REPLY=
  [ "$REPLY" = DISINSTALLA ] || { echo; info "Annullato: non è stato tolto niente."; echo; exit 0; }
  echo
  # la parte che toglie i file è la stessa del tasto della pagina locale: netprobe-uninstall
  UNINST="$HERE/netprobe-uninstall"
  [ -f "$UNINST" ] || UNINST=/usr/local/sbin/netprobe-uninstall
  [ -f "$UNINST" ] || die "Manca netprobe-uninstall accanto allo script: copia di nuovo la cartella probe."
  if [ -n "$KEEP" ]; then
    run "Disinstallazione (registro in /root/netmon-disinstallazione.log)" bash "$UNINST" --conferma
  else
    run "Disinstallazione (registro in /root/netmon-disinstallazione.log)" bash "$UNINST" --conferma --senza-copia
  fi
  KEEP=$(sed -n 's/.*Copia della configurazione: //p' /root/netmon-disinstallazione.log 2>/dev/null | tail -n1)
  echo
  ok "netmon è stato tolto dalla sonda."
  [ -n "$KEEP" ] && info "Configurazione salvata in $KEEP (solo root può leggerla)."
  info "Puoi cancellare anche la cartella dello script:  rm -rf $HERE"
  info "Le reti Wi-Fi salvate si vedono con  nmcli connection show"
  echo
  exit 0
fi

printf '\n%snetmon · installazione guidata della sonda · versione %s%s\n' "$B" "$NETMON_VERSION" "$N"
OLD_VERSION=$(grep -o '__version__ = "[^"]*"' /opt/netprobe/probe.py 2>/dev/null | cut -d'"' -f2)
printf '%sOgni passaggio viene annotato in %s%s\n' "$D" "$LOG" "$N"

# ------------------------------------------------------------------ 1. verifiche
step "Verifica del sistema"
[ "$(id -u)" -eq 0 ] || { printf '\n  Lancia lo script con sudo:  sudo bash %s\n\n' "$0"; exit 1; }
: > "$LOG" && chmod 600 "$LOG"

. /etc/os-release 2>/dev/null || true
if [[ "${ID:-}" =~ ^(debian|ubuntu|raspbian)$ || "${ID_LIKE:-}" == *debian* ]]; then
  ok "Sistema: ${PRETTY_NAME:-$ID}"
else
  warn "Sistema non previsto (${PRETTY_NAME:-sconosciuto}): la guida considera Raspberry Pi OS, Debian o Ubuntu."
  yes_no "Continuare comunque" n || exit 1
fi
command -v apt-get >/dev/null || die "apt-get non trovato: serve Raspberry Pi OS, Debian o Ubuntu."
command -v systemctl >/dev/null || die "systemd non trovato."
MODEL=$(tr -d '\0' 2>/dev/null < /proc/device-tree/model || true)
[ -n "$MODEL" ] && ok "Hardware: $MODEL"

missing=()
for f in "${FILES[@]}" netprobe-upgrade netprobe-selfupdate netprobe-zipupdate netprobe-wifi netprobe-uninstall sudoers-netprobe netmon-probe.service netmon-config.service netmon-config.socket; do
  [ -f "$HERE/$f" ] || missing+=("$f")
done
[ ${#missing[@]} -eq 0 ] || die "Mancano dei file accanto allo script: ${missing[*]}. Copia di nuovo la cartella probe."
ok "File della sonda presenti"

GW=$(ip -4 route show default 2>/dev/null | awk '{print $3; exit}')
LANIP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')
IFACE=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}')
[ -n "$LANIP" ] && ok "Rete: $LANIP su $IFACE, router $GW" || die "La sonda non ha una connessione di rete."
[[ "$IFACE" == wl* ]] && warn "La sonda è collegata in Wi-Fi: se puoi, usa il cavo (misure più stabili)."

if [ -f "$CFG" ]; then
  ok "Trovata un'installazione esistente"
  if [ "$MODE" = install ]; then
    echo
    echo "  Cosa vuoi fare?"
    echo "    1) Aggiornare i file della sonda (configurazione e dispositivi restano) — consigliato"
    echo "    2) Riconfigurare: server, token, dispositivi e FRITZ!Box da capo"
    echo "    3) Uscire"
    while :; do ask "Scelta" 1; case "$REPLY" in 1) MODE=update; break ;; 2) MODE=reconfigure; break ;; 3) exit 0 ;; esac; done
  fi
elif [ "$MODE" = update ]; then
  die "Nessuna sonda installata da aggiornare: lancia lo script senza --aggiorna."
fi

install_files() {
  command -v openssl >/dev/null || run "Pacchetto openssl (verifica degli aggiornamenti)" apt-get install -y openssl
  run "Copia dei programmi in $DEST" env DEST_DIR="$DEST" bash -c 'mkdir -p "$DEST_DIR" "$1" && cd "$2" && shift 2 && cp -- "$@" "$DEST_DIR/"' \
    _ "$ETC" "$HERE" "${FILES[@]}"
  run "Script di aggiornamento del sistema" install -m 755 -o root -g root "$HERE/netprobe-upgrade" /usr/local/sbin/
  run "Script di aggiornamento di netmon dal server" install -m 755 -o root -g root "$HERE/netprobe-selfupdate" /usr/local/sbin/
  run "Aggiornamento da pacchetto caricato" install -m 755 -o root -g root "$HERE/netprobe-zipupdate" /usr/local/sbin/
  run "Gestione delle reti Wi-Fi" install -m 755 -o root -g root "$HERE/netprobe-wifi" /usr/local/sbin/
  run "Disinstallazione dalla pagina locale" install -m 755 -o root -g root "$HERE/netprobe-uninstall" /usr/local/sbin/
  run "Verificatore dei pacchetti" bash -c 'install -d -m 755 -o root -g root /usr/local/lib/netmon && install -m 644 -o root -g root "$1" /usr/local/lib/netmon/pkgcheck.py' _ "$HERE/pkgcheck.py"
  # permessi di riavvio e aggiornamento, controllati prima di attivarli (sudo ignora i nomi con il punto)
  # Permessi per le operazioni da remoto: FACOLTATIVI. Senza il pacchetto sudo (sistemi minimi,
  # container) la sonda misura e invia lo stesso; mancano solo le operazioni che servono root.
  # Lo script non installa sudo da solo: lo dice, e lo ripete alla fine (sudo_notice).
  if ! command -v sudo >/dev/null || ! command -v visudo >/dev/null; then
    NO_SUDO=1
    warn "Pacchetto sudo assente: salto i permessi per le operazioni da remoto (la sonda funziona lo stesso)."
  elif ! bash -c 'install -d -m 750 -o root -g root /etc/sudoers.d \
      && install -m 440 -o root -g root "$1" /etc/sudoers.d/.netprobe.tmp \
      && visudo -cf /etc/sudoers.d/.netprobe.tmp && mv /etc/sudoers.d/.netprobe.tmp /etc/sudoers.d/netprobe \
      || { rm -f /etc/sudoers.d/.netprobe.tmp; false; }' _ "$HERE/sudoers-netprobe" >> "$LOG" 2>&1; then
    NO_SUDO=1
    warn "Permessi per le operazioni da remoto non installati (dettagli in $LOG): la sonda funziona lo stesso."
  else
    ok "Permessi di riavvio e aggiornamenti"
  fi
  # log e stato degli aggiornamenti: da ora in una cartella di root (quelli vecchi vengono spostati)
  install -d -m 755 -o root -g root "$SYSDIR"
  for f in upgrade.log upgrade.status selfupdate.log selfupdate.status; do
    old=/var/lib/netprobe/$f
    if [ -f "$old" ] && [ ! -L "$old" ] && [ ! -e "$SYSDIR/$f" ]; then install -m 644 -o root -g root "$old" "$SYSDIR/$f"; fi
    rm -f "$old" "$old.tmp"
  done
  rm -rf /var/lib/netprobe/update-backup
  # moduli precompilati: avvio più rapido (la pagina locale parte a ogni visita)
  run "Precompilazione" "$VPY" -m compileall -q "$DEST"
  run "Servizi netmon-probe e netmon-config" cp "$HERE/netmon-probe.service" "$HERE/netmon-config.service" \
    "$HERE/netmon-config.socket" /etc/systemd/system/
  # la pagina locale ora parte solo quando serve: tolgo l'avvio fisso delle versioni precedenti
  rm -f /etc/systemd/system/multi-user.target.wants/netmon-config.service
}

key_fp() { openssl pkey -pubin -in "$1" -outform DER 2>/dev/null | sha256sum | cut -c1-16 | sed 's/..../& /g;s/ $//'; }

install_update_key() {   # $1 = indirizzo del server (https://dominio)
  local tmp fp
  # l'indirizzo viene da config.yaml, scrivibile dalla sonda: niente che curl possa leggere come opzione
  # (in un'espressione tra parentesi quadre la ] va per prima: «\]» non è un carattere di escape)
  local re='^https?://[][A-Za-z0-9.:-]+(/[A-Za-z0-9._~/-]*)?$'
  [[ "$1" =~ $re ]] || { warn "Indirizzo del server non valido: $1"; return 1; }
  tmp=$(mktemp)
  if curl -fsS --max-time 10 --url "$1/api/update-key" -o "$tmp" 2>>"$LOG" && openssl pkey -pubin -in "$tmp" -noout 2>>"$LOG"; then
    fp=$(key_fp "$tmp")
    if [ -f "$KEYFILE" ] && ! cmp -s "$tmp" "$KEYFILE"; then
      warn "La chiave degli aggiornamenti del server è cambiata: $(key_fp "$KEYFILE") → $fp"
      info "Succede se hai reinstallato la VM. Confronta l'impronta con quella nel riepilogo del server"
      info "(sudo grep 'Chiave aggiornamenti' /root/netmon-server-riepilogo.txt sulla VM)."
      if ! yes_no "Accettare la nuova chiave" n; then
        rm -f "$tmp"; warn "Chiave invariata: gli aggiornamenti dal server saranno rifiutati finché non la accetti."
        UPDATE_FP=$(key_fp "$KEYFILE"); return 0
      fi
    fi
    install -d -m 755 -o root -g root "$KEYDIR"
    install -m 644 -o root -g root "$tmp" "$KEYFILE"
    UPDATE_FP=$fp
    ok "Chiave degli aggiornamenti del server installata (impronta $fp)"
  else
    warn "Il server non fornisce ancora la chiave degli aggiornamenti: aggiorna prima il server"
    warn "(installa-server.sh --aggiorna), poi rilancia qui con --aggiorna. Fino ad allora il tasto"
    warn "«Aggiorna netmon» non installa nulla sulla sonda (per sicurezza)."
    [ -f "$KEYFILE" ] && UPDATE_FP=$(key_fp "$KEYFILE")
  fi
  rm -f "$tmp"
}

NO_SUDO=0
sudo_notice() {   # senza sudo: cosa non funziona e come rimediare (fine installazione e aggiornamento)
  [ "$NO_SUDO" = 1 ] || return 0
  printf '\n  %s! Senza sudo (o senza i suoi permessi)%s la sonda controlla i dispositivi, legge il FRITZ!Box\n' "$Y$B" "$N"
  echo "    e invia i dati come sempre, ma queste funzioni NON sono disponibili (rispondono «Permesso mancante»):"
  echo "      · Aggiorna netmon dal server (Stato sonda, /admin, dopo un aggiornamento della VM)"
  echo "      · Aggiorna sistema (apt) e Riavvia sonda, dal server e dalla pagina locale"
  echo "      · reti Wi-Fi della sonda (Stato sonda → Reti Wi-Fi)"
  echo "      · Disinstalla sonda dalla pagina locale (da terminale resta: installa-sonda.sh --disinstalla)"
  echo "    Gli aggiornamenti di netmon vanno fatti a mano: copia la nuova cartella probe e lancia"
  echo "    installa-sonda.sh --aggiorna da root. Per attivarle: apt-get install -y sudo, poi"
  echo "    rilancia installa-sonda.sh --aggiorna."
}

gen_web_password() { "$VPY" -c 'import secrets; print(secrets.token_urlsafe(9))'; }

write_web_password() {   # $1 = password
  ( umask 077; printf 'WEB_PASSWORD=%s\n' "$1" > "$ETC/web.env" )
  chown netprobe:netprobe "$ETC/web.env"; chmod 600 "$ETC/web.env"
}

# Caratteri che systemd non sa leggere in un file ambiente (spazi, virgolette, \ e $).
# Il confronto sta in una variabile e non dentro [[ =~ ]]: scritto lì, il "$[:space:]" del
# pattern veniva letto da bash come espansione aritmetica, dava errore a ogni digitazione
# («:space:: syntax error») e il ciclo veniva interrotto, facendo cadere la password
# nella generazione automatica.
WEB_PW_BAD='[[:space:]"'\''\\$]'

web_pw_check() {   # $1 = password proposta: 0 = accettabile
  local p=$1
  [[ "$p" =~ $WEB_PW_BAD ]] && { warn "Senza spazi, virgolette, \\ e \$ (li interpreterebbe systemd)."; return 1; }
  [ "${#p}" -ge 8 ] || { warn "Almeno 8 caratteri."; return 1; }
  return 0
}

start_services() {
  run "$1" bash -c "systemctl daemon-reload && systemctl stop netmon-config.service 2>/dev/null; \
    systemctl enable netmon-probe netmon-config.socket && systemctl restart netmon-config.socket netmon-probe"
}

# valori attuali (riconfigurazione e aggiornamento): letti dal config.yaml esistente
cfgget() { [ -f "$CFG" ] && "$VPY" -c 'import sys,yaml; v=(yaml.safe_load(open(sys.argv[1])) or {}).get(sys.argv[2]); print("" if v is None else v)' "$CFG" "$1" 2>/dev/null; }

fritz_lib() {   # solo se manca: pip su un Raspberry Pi Zero è lento
  "$VPY" -c "import fritzconnection" >/dev/null 2>&1 || run "Libreria FRITZ!Box (fritzconnection)" "$DEST/venv/bin/pip" install --quiet fritzconnection
  "$VPY" -c "import fritzconnection" >/dev/null 2>&1 && ok "Libreria FRITZ!Box presente"
}

if [ "$MODE" = update ]; then
  STEPS=3
  step "Aggiornamento dei file"
  [ -x "$VPY" ] || run "Ambiente Python" python3 -m venv --system-site-packages "$DEST/venv"
  fritz_lib
  install_files
  CUR_URL=$(cfgget server_url); CUR_BASE=${CUR_URL%/api/report}
  [ -n "$CUR_BASE" ] && { install_update_key "$CUR_BASE" || true; }
  # la pagina locale ora richiede sempre una password: se manca ne genero una
  NEW_WEB_PASS=
  if ! { [ -f "$ETC/web.env" ] && grep -q '^WEB_PASSWORD=.' "$ETC/web.env"; }; then
    NEW_WEB_PASS=$(gen_web_password); write_web_password "$NEW_WEB_PASS"
    ok "Password della pagina locale creata (prima non era impostata)"
  fi
  step "Riavvio dei servizi"
  start_services "Riavvio"
  sleep 3
  systemctl is-active --quiet netmon-probe && ok "Sonda attiva" || warn "La sonda non è attiva: sudo journalctl -u netmon-probe -n 30"
  printf '\n  %sAggiornamento completato:%s versione %s → %s%s%s\n' \
    "$G$B" "$N" "${OLD_VERSION:-precedente}" "$B" "$NETMON_VERSION" "$N"
  [ -n "$UPDATE_FP" ] && printf '  Chiave aggiornamenti  %s\n' "$UPDATE_FP"
  if [ -n "$NEW_WEB_PASS" ]; then
    LANIP_NOW=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')
    printf '\n  %sPagina locale http://%s:8080 — ora protetta da password:%s %s%s%s\n' "$B" "$LANIP_NOW" "$N" "$B$Y" "$NEW_WEB_PASS" "$N"
    printf '  (utente qualsiasi; salvala nel gestore delle password. Copia in %s)\n' "$SUMMARY"
    [ -f "$SUMMARY" ] && printf '\nPassword pagina locale . %s  (creata il %s)\n' "$NEW_WEB_PASS" "$(date '+%d/%m/%Y')" >> "$SUMMARY"
    [ -f "$SUMMARY" ] || { printf 'Password pagina locale . %s\n' "$NEW_WEB_PASS" > "$SUMMARY"; chmod 600 "$SUMMARY"; }
  fi
  sudo_notice
  echo
  exit 0
fi

# ------------------------------------------------------------------ 2. pacchetti
step "Installazione dei pacchetti"
export DEBIAN_FRONTEND=noninteractive
run "Aggiornamento elenco pacchetti" apt-get update
run "Python, ping e strumenti di rete" apt-get install -y python3 python3-venv python3-requests python3-yaml \
  iputils-ping iproute2 iw curl ca-certificates openssl
[ -x "$VPY" ] || run "Ambiente Python della sonda" python3 -m venv --system-site-packages "$DEST/venv"
fritz_lib

# ------------------------------------------------------------------ 3. domande
step "Informazioni necessarie"


# --- server
OLD_URL=$(cfgget server_url); OLD_HOST=${OLD_URL%/api/report}; OLD_HOST=${OLD_HOST#https://}
[[ "$OLD_HOST" == *tuodominio* ]] && OLD_HOST=
while :; do
  ask "Dominio del server (es. vm1.netmonhome.net)" "$OLD_HOST"
  SCHEME=https; [[ "$REPLY" == http://* ]] && SCHEME=http     # http:// solo se scritto esplicitamente
  HOST=${REPLY#http://}; HOST=${HOST#https://}; HOST=${HOST%%/*}
  [ -n "$HOST" ] || continue
  BASE="$SCHEME://$HOST"
  if [ "$SCHEME" = http ]; then
    hname=${HOST%:*}
    if [[ "$hname" =~ ^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.|127\.) || "$hname" == localhost || "$hname" =~ \.(local|lan|home|home\.arpa|internal|fritz\.box)$ ]]; then
      warn "Con http:// i dati viaggiano senza cifratura: va bene solo per un server nella rete di casa."
    else
      warn "Per un server su Internet serve https:// (con http:// token e dati viaggerebbero in chiaro)."; continue
    fi
  fi
  if curl -fsS --max-time 10 "$BASE/health" 2>/dev/null | grep -q '"ok"'; then ok "Server raggiungibile: $BASE"; break; fi
  warn "$BASE/health non risponde (server spento, dominio errato o HTTPS non ancora attivo)."
  yes_no "Usarlo comunque" n && break
done
SERVER_URL="$BASE/api/report"

# --- token
echo
info "Token della sonda: nella pagina di stato apri ⚙ Impostazioni → Sonde → Aggiungi una sonda."
info "Comincia con sonda_. La chiave del server non vale per le sonde."
OLD_TOKEN=$(cfgget token); [[ "$OLD_TOKEN" == INCOLLA* ]] && OLD_TOKEN=
while :; do
  if [ -n "$OLD_TOKEN" ]; then ask "Token (Invio = lascia quello attuale)" ""; TOKEN=${REPLY:-$OLD_TOKEN}
  else ask "Token"; TOKEN=$REPLY; fi
  [ -n "$TOKEN" ] || continue
  # La chiave del server viene rifiutata dal server stesso: meglio dirlo subito e chiaramente,
  # invece di lasciare un 401 che sembra un errore di battitura.
  if [[ "$TOKEN" != sonda_* ]]; then
    warn "Questo non è il token di una sonda (quelli cominciano con sonda_)."
    warn "La chiave del server non vale per le sonde: genera il token nella pagina di stato, ⚙ Impostazioni → Sonde."
    OLD_TOKEN=; continue
  fi
  # 401 = token rifiutato; qualsiasi altra risposta vuol dire che il server lo accetta
  code=$(printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" | curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
         --config - "$BASE/api/probe-config?probe=verifica-installazione" 2>/dev/null || echo 000)
  case "$code" in
    401) warn "Il server rifiuta questo token: ricontrollalo (maiuscole e minuscole contano)." ;;
    000) warn "Non riesco a verificare il token (server non raggiungibile)."; yes_no "Usarlo comunque" n && break ;;
    *)   ok "Token della sonda accettato"; TOKEN_KIND=personale; break ;;
  esac
done
TOKEN_KIND=${TOKEN_KIND:-da verificare}

# --- lingua della pagina locale (si cambia poi in alto nella pagina)
echo
OLD_LANG=$(cfgget language)
case "$OLD_LANG" in en) DEF_LANG=2 ;; de) DEF_LANG=3 ;; fr) DEF_LANG=4 ;; *) DEF_LANG=1 ;; esac
info "Lingua della pagina locale · Page language · Sprache der Seite · Langue de la page"
info "1 Italiano · 2 English · 3 Deutsch · 4 Français"
while :; do
  ask "Lingua / Language" "$DEF_LANG"
  case "$REPLY" in 1) LANG_CODE=it; break ;; 2) LANG_CODE=en; break ;; 3) LANG_CODE=de; break ;; 4) LANG_CODE=fr; break ;; esac
  warn "Scegli 1, 2, 3 o 4."
done

# --- nome
echo
OLD_NAME=$(cfgget probe_name)
DEF_NAME=${OLD_NAME:-$(hostname -s | sed 's/[^A-Za-z0-9 _.-]//g' | cut -c1-40)}
[ "$TOKEN_KIND" = personale ] && info "Con il token della sonda vale il nome scelto nella pagina; questo si usa finché non arriva."
while :; do
  ask "Nome della sonda" "${DEF_NAME:-Casa}"; NAME=$REPLY
  [[ "$NAME" =~ $NAME_RE ]] && break
  warn "Usa lettere, numeri, spazi, punti o trattini (massimo 40 caratteri, inizia con lettera o numero)."
done

# --- dispositivi
echo
info "Dispositivi da controllare con il ping: nome e indirizzo IP (o hostname)."
info "Dopo l'installazione li gestisci anche dalla pagina del server (pulsante ＋)."
declare -A DEV=(); ORDER=()
OLD_DEVS=$([ -f "$CFG" ] && "$VPY" -c 'import sys,yaml; d=(yaml.safe_load(open(sys.argv[1])) or {}).get("devices") or {}; [print(k+"\t"+str(v)) for k,v in d.items()]' "$CFG" 2>/dev/null)
if [ -n "$OLD_DEVS" ] && yes_no "Mantenere i $(echo "$OLD_DEVS" | wc -l) dispositivi già configurati" s; then
  while IFS=$'\t' read -r k v; do DEV[$k]=$v; ORDER+=("$k"); done <<< "$OLD_DEVS"
elif [ -n "$GW" ] && yes_no "Aggiungere il router ($GW) come \"router\"" s; then
  DEV[router]=$GW; ORDER+=(router)
fi
pingtest() { ping -c 1 -W 1 "$1" >/dev/null 2>&1; }
while :; do
  [ ${#ORDER[@]} -gt 0 ] && info "Dispositivi: ${ORDER[*]}"
  ask "Nome di un altro dispositivo (Invio per finire)" ""
  dname=$REPLY
  if [ -z "$dname" ]; then
    [ ${#ORDER[@]} -gt 0 ] && break
    warn "Serve almeno un dispositivo."; continue
  fi
  [[ "$dname" =~ $NAME_RE ]] || { warn "Nome non valido: lettere, numeri, spazi, punti o trattini."; continue; }
  [ -n "${DEV[$dname]+x}" ] && { warn "\"$dname\" c'è già."; continue; }
  ask "Indirizzo IP o hostname di $dname" ""; dhost=$REPLY
  [[ "$dhost" =~ ^[A-Za-z0-9][A-Za-z0-9.:-]{0,252}$ ]] || { warn "Indirizzo non valido."; continue; }
  if pingtest "$dhost"; then ok "$dname ($dhost) risponde"
  else warn "$dname ($dhost) ora non risponde al ping: lo aggiungo comunque."; fi
  DEV[$dname]=$dhost; ORDER+=("$dname")
done

# --- FRITZ!Box
echo
FRITZ_ON=false; F_HOST=$(cfgget fritz_host); F_USER=$(cfgget fritz_user); F_PASS=$(cfgget fritz_password); F_MODEL=
probe_fb=${F_HOST:-$GW}
if [ -n "$probe_fb" ] && curl -fsS --max-time 3 "http://$probe_fb:49000/tr64desc.xml" 2>/dev/null | grep -qi fritz; then
  ok "Trovato un FRITZ!Box su $probe_fb"; fb_def=s
else fb_def=n; fi
if yes_no "Collegare un FRITZ!Box (stato della linea, traffico, client Wi-Fi e ospiti)" "$fb_def"; then
  info "Sul FRITZ!Box: Rete domestica → Rete → Impostazioni di rete → abilita \"Accesso per applicazioni\","
  info "poi Sistema → Utenti FRITZ!Box → crea un utente con il permesso \"Impostazioni FRITZ!Box\"."
  while :; do
    ask "Indirizzo del FRITZ!Box" "${F_HOST:-${GW:-192.168.178.1}}"; F_HOST=$REPLY
    ask "Utente del FRITZ!Box" "${F_USER:-netmon}"; F_USER=$REPLY
    if [ -n "$F_PASS" ]; then ask_secret "Password (Invio = lascia quella attuale)"; [ -n "$REPLY" ] && F_PASS=$REPLY
    else ask_secret "Password"; F_PASS=$REPLY; fi
    printf '  %s…%s Prova del collegamento' "$D" "$N"
    if F_MODEL=$(F_HOST="$F_HOST" F_USER="$F_USER" F_PASS="$F_PASS" "$VPY" - 2>&1 <<'EOF'
import os
from fritzconnection import FritzConnection
e = os.environ
fc = FritzConnection(address=e["F_HOST"], user=e["F_USER"], password=e["F_PASS"], timeout=10)
info = fc.call_action("DeviceInfo1", "GetInfo")
print(info.get("NewModelName", "FRITZ!Box"), "· FRITZ!OS", info.get("NewSoftwareVersion", "?"))
EOF
    ); then
      F_MODEL=$(echo "$F_MODEL" | tail -n1)
      printf '\r  %s✔%s Collegato: %s\n' "$G" "$N" "$F_MODEL"; FRITZ_ON=true; break
    else
      last=$(echo "$F_MODEL" | tail -n1); F_MODEL=
      printf '\r  %s✘%s Collegamento non riuscito: %s\n' "$R" "$N" "$last"
      [[ "$last" == *401* || "$last" == *uthoriz* ]] && info "Utente o password errati, oppure l'utente non ha il permesso \"Impostazioni FRITZ!Box\"."
      yes_no "Riprovare" s || { warn "FRITZ!Box non collegato: puoi farlo dopo dalla pagina locale della sonda."; break; }
    fi
  done
fi

# --- pagina locale
echo
info "La pagina locale http://$LANIP:8080 permette di modificare la configurazione dalla rete di casa."
WEB_PASS=; WEB_NEW=0
info "La pagina è protetta da una password (obbligatoria): il browser la chiede al primo accesso."
if [ -f "$ETC/web.env" ] && grep -q '^WEB_PASSWORD=.' "$ETC/web.env" && yes_no "Mantenere la password attuale della pagina locale" s; then
  WEB_PASS=$(sed -n 's/^WEB_PASSWORD=//p' "$ETC/web.env")
else
  while :; do
    ask_secret "Password della pagina locale (Invio = ne genero una io)"
    if [ -z "$REPLY" ]; then WEB_PASS=$(gen_web_password); WEB_NEW=1; break; fi
    web_pw_check "$REPLY" || continue
    p1=$REPLY; ask_secret "Ripeti la password"
    [ "$p1" = "$REPLY" ] && { WEB_PASS=$p1; break; }
    warn "Le due password non coincidono."
  done
fi

# ------------------------------------------------------------------ 4. installazione
step "Installazione della sonda"
id netprobe >/dev/null 2>&1 || run "Utente di servizio netprobe" useradd --system --no-create-home --shell /usr/sbin/nologin netprobe
install_files

[ -f "$CFG" ] && cp -p "$CFG" "$CFG.bak-$(date +%Y%m%d-%H%M%S)"
devs_tsv=$(for k in "${ORDER[@]}"; do printf '%s\t%s\n' "$k" "${DEV[$k]}"; done)
DEVS="$devs_tsv" C_SERVER="$SERVER_URL" C_TOKEN="$TOKEN" C_NAME="$NAME" C_FRITZ="$FRITZ_ON" \
C_FHOST="${F_HOST:-}" C_FUSER="${F_USER:-}" C_FPASS="${F_PASS:-}" C_LANG="${LANG_CODE:-it}" \
"$VPY" - "$CFG" <<'EOF' >> "$LOG" 2>&1 || die "Scrittura di config.yaml non riuscita."
import os, sys, yaml
e, path = os.environ, sys.argv[1]
old = {}
if os.path.exists(path):
    old = yaml.safe_load(open(path, encoding="utf-8")) or {}
devices = dict(line.split("\t", 1) for line in e["DEVS"].splitlines() if "\t" in line)
cfg = {
    "server_url": e["C_SERVER"], "token": e["C_TOKEN"], "probe_name": e["C_NAME"],
    "config_poll": old.get("config_poll", 60),
    # frequenza e soglie: si cambiano dalla pagina del server (⚙ Impostazioni → Controlli)
    "interval": old.get("interval", 60), "ping_count": old.get("ping_count", 2),
    "ping_timeout": old.get("ping_timeout", 1), "ping_parallel": old.get("ping_parallel", 2),
    "fail_threshold": old.get("fail_threshold", 3), "alert_mode": old.get("alert_mode", "proporzionale"),
    "stale_factor": old.get("stale_factor", 1.5), "offline_factor": old.get("offline_factor", 3),
    "stale_seconds": old.get("stale_seconds", 90), "offline_seconds": old.get("offline_seconds", 180),
    "devices": devices,
    "fritz_enabled": e["C_FRITZ"] == "true", "traffic_interval": old.get("traffic_interval", 30),
    "fritz_host": e["C_FHOST"], "fritz_user": e["C_FUSER"], "fritz_password": e["C_FPASS"],
    "language": e.get("C_LANG") or "it",          # lingua della pagina locale
}
if "config_rev" in old:
    cfg["config_rev"] = old["config_rev"]
if old.get("fritz_more"):             # altri FRITZ!Box aggiunti dalla pagina locale: restano
    cfg["fritz_more"] = old["fritz_more"]
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    f.write("# netmon · scritto da installa-sonda.sh — modificabile dalla pagina locale (porta 8080)\n")
    yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
os.chmod(tmp, 0o640)
os.replace(tmp, path)
EOF
ok "Configurazione scritta in $CFG (${#ORDER[@]} dispositivi)"

[ -n "$WEB_PASS" ] || { WEB_PASS=$(gen_web_password); WEB_NEW=1; }
write_web_password "$WEB_PASS"
ok "Password della pagina locale impostata"
run "Permessi" bash -c 'chown -R netprobe:netprobe "$1" && chmod 750 "$1" && chmod 640 "$2"' _ "$ETC" "$CFG"
install_update_key "$BASE"

# ------------------------------------------------------------------ 5. avvio e verifica
step "Avvio e primo invio"
START=$(date +%s)
start_services "Avvio dei servizi"

printf '  %s…%s Attendo il primo invio al server (fino a 90 secondi)' "$D" "$N"
FIRST=; ERR=
for i in $(seq 1 45); do
  out=$(journalctl -u netmon-probe --since "@$START" -o cat --no-pager 2>/dev/null)
  if echo "$out" | grep -q "Primo invio al server riuscito"; then
    FIRST=$(echo "$out" | grep -m1 -oE 'OK [0-9]+/[0-9]+.*' || echo ok); break
  fi
  ERR=$(echo "$out" | grep -m1 -iE '401|403|500|errore|error|traceback' || true)
  systemctl is-active --quiet netmon-probe || { ERR=${ERR:-"il servizio si è fermato"}; break; }
  sleep 2
done
if [ -n "$FIRST" ]; then
  printf '\r  %s✔%s Dati inviati al server: %s                    \n' "$G" "$N" "$FIRST"
else
  printf '\r  %s!%s Nessun invio riuscito finora.                          \n' "$Y" "$N"
  [ -n "$ERR" ] && info "Ultimo messaggio: $ERR"
  journalctl -u netmon-probe --since "@$START" -n 8 -o cat --no-pager 2>/dev/null | sed 's/^/      /'
  warn "Se vedi 401 il token non è valido; con 500 controlla il server. Le misure restano nel buffer."
fi
web=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8080/ 2>/dev/null || echo 000)
[[ "$web" =~ ^(200|401)$ ]] && ok "Pagina locale attiva: http://$LANIP:8080" || warn "La pagina locale non risponde: sudo journalctl -u netmon-config -n 20"

NEW_TOKEN=$(cfgget token)
TOKEN_NOTE=

# ------------------------------------------------------------------ 6. riepilogo
step "Fatto"
devlist=$(for k in "${ORDER[@]}"; do printf '    %-20s %s\n' "$k" "${DEV[$k]}"; done)
{
  echo "netmon · sonda \"$NAME\" — informazioni da conservare ($(date '+%d/%m/%Y %H:%M'), versione $NETMON_VERSION)"
  echo
  echo "Server ................. $BASE"
  echo "Token della sonda ...... $NEW_TOKEN"
  echo "Pagina locale .......... http://$LANIP:8080"
  echo "Password pagina locale . $WEB_PASS"
  echo "Chiave aggiornamenti ... ${UPDATE_FP:-non installata} (impronta, deve coincidere con quella del server)"
  echo "FRITZ!Box .............. $([ "$FRITZ_ON" = true ] && echo "$F_HOST, utente $F_USER ($F_MODEL)" || echo "non collegato")"
  echo
  echo "Dispositivi:"
  echo "$devlist"
  [ -n "$TOKEN_NOTE" ] && { echo; echo "$TOKEN_NOTE"; }
  echo
  echo "Comandi utili:"
  echo "  stato        systemctl status netmon-probe netmon-config.socket"
  echo "  registro     sudo journalctl -u netmon-probe -f"
  echo "  aggiornare   sudo bash probe/installa-sonda.sh --aggiorna"
} > "$SUMMARY"
chmod 600 "$SUMMARY"

line=$(printf '%.0s─' $(seq 1 66))
printf '\n  %s┌%s┐%s\n' "$Y" "$line" "$N"
printf '  %s│%s %-64s %s│%s\n' "$Y" "$N$B" "INFORMAZIONI DA SALVARE (es. nel gestore delle password)" "$N$Y" "$N"
printf '  %s└%s┘%s\n' "$Y" "$line" "$N"
printf '  Sonda                %s%s%s\n' "$B" "$NAME" "$N"
printf '  Token della sonda    %s%s%s\n' "$B$Y" "$NEW_TOKEN" "$N"
printf '  Pagina locale        %shttp://%s:8080%s\n' "$B" "$LANIP" "$N"
printf '  Password pagina      %s%s%s%s\n' "$B$Y" "$WEB_PASS" "$N" "$([ "$WEB_NEW" = 1 ] && echo "  (generata ora)")"
printf '  Chiave aggiornamenti %s\n' "${UPDATE_FP:-non installata}"
printf '  FRITZ!Box            %s\n' "$([ "$FRITZ_ON" = true ] && echo "collegato ($F_MODEL)" || echo "non collegato")"
printf '  Dispositivi          %s\n' "${#ORDER[@]}"
[ -n "$TOKEN_NOTE" ] && printf '\n  %s➜ %s%s\n' "$B" "$TOKEN_NOTE" "$N"
printf '\n  %sUna copia è in %s (leggibile solo da root).%s\n' "$D" "$SUMMARY" "$N"
cat <<EOF

  ${B}Prossimi passi${N}
    1. Apri $BASE: la sonda compare in Stato rete entro un minuto.
    2. Frequenza dei controlli e soglie degli alert: ⚙ Impostazioni → Controlli.
    3. Consigliato: assegna alla sonda un IP fisso ($LANIP) dal router (prenotazione DHCP).

EOF
sudo_notice
if [ "$NO_SUDO" = 1 ]; then echo; fi
