#!/usr/bin/env bash
# netmon · installazione guidata del server (VM)
#
# Uso, dalla VM, nella cartella dove hai estratto netmon.zip:
#   sudo bash netmon/server/installa-server.sh              installazione o riconfigurazione
#   sudo bash netmon/server/installa-server.sh --aggiorna   solo aggiornamento dei file
#
# NetMon Light: una sola VM con pagina di stato, pannello di amministrazione, utenti e sonde.
#
# Verifica il sistema, installa i pacchetti, chiede le informazioni necessarie (dominio,
# notifiche), prova email/Telegram/ntfy, configura HTTPS e alla fine mostra le informazioni
# da conservare. Si può rilanciare quando si vuole: configurazione, account e storico restano.
NETMON_VERSION="1.1.20261029-120000"

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

# le domande leggono dal terminale anche se lo script arriva da una pipe
TTY=/dev/tty
NONINT=${NETMON_NONINTERACTIVE:-0}     # 1 = lanciato dal pannello: nessuna domanda, valori predefiniti
ask() {            # ask "domanda" [predefinito] → $REPLY
  local q=$1 def=${2-}
  [ "$NONINT" = 1 ] && { REPLY=$def; return 0; }
  if [ -n "$def" ]; then printf '  %s? %s%s [%s]: ' "$B" "$q" "$N" "$def"; else printf '  %s? %s%s: ' "$B" "$q" "$N"; fi
  IFS= read -r REPLY < "$TTY" || REPLY=
  REPLY=$(printf '%s' "$REPLY" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
  [ -z "$REPLY" ] && REPLY=$def
  return 0
}
ask_secret() {     # ask_secret "domanda" → $REPLY (non mostrato)
  printf '  %s? %s%s: ' "$B" "$1" "$N"
  IFS= read -rs REPLY < "$TTY" || REPLY=
  printf '\n'
}
yes_no() {         # yes_no "domanda" s|n → 0 = sì
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
run() {            # run "descrizione" comando... → output nel registro, errore = stop
  local what=$1; shift
  printf '  %s…%s %s' "$D" "$N" "$what"
  echo "=== $(date '+%F %T') · $what: $*" >> "$LOG"
  if "$@" >> "$LOG" 2>&1; then printf '\r  %s✔%s %s\n' "$G" "$N" "$what"
  else printf '\r  %s✘%s %s\n' "$R" "$N" "$what"; tail -n 15 "$LOG" | sed 's/^/      /'; die "Passaggio non riuscito: $what"; fi
}

# ------------------------------------------------------------------ percorsi
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEST=/opt/netmon
FILES=(app.py auth.py account.py mfa.py monitor.py notifier.py vmops.py brand.py fonts.py sito.py i18n.py i18n_admin.py privacy.html pkgcheck.py requirements.txt env.example netmon-server.service)
SUMMARY=/root/netmon-server-riepilogo.txt

MODE=install
case "${1-}" in
  --aggiorna) MODE=update ;;
  "") ;;
  *) printf '\n  Opzione sconosciuta: %s (NetMon Light ha solo --aggiorna).\n\n' "$1"; exit 1 ;;
esac

printf '\n%snetmon · installazione guidata del server · versione %s%s\n' "$B" "$NETMON_VERSION" "$N"
OLD_VERSION=$(grep -o '__version__ = "[^"]*"' /opt/netmon/app.py 2>/dev/null | cut -d'"' -f2)
printf '%sOgni passaggio viene annotato in %s%s\n' "$D" "$LOG" "$N"

# ------------------------------------------------------------------ 1. verifiche
step "Verifica del sistema"
[ "$(id -u)" -eq 0 ] || { printf '\n  Lancia lo script con sudo:  sudo bash %s\n\n' "$0"; exit 1; }
: > "$LOG" && chmod 600 "$LOG"

. /etc/os-release 2>/dev/null || true
if [[ "${ID:-}" =~ ^(debian|ubuntu)$ || "${ID_LIKE:-}" == *debian* ]]; then
  ok "Sistema: ${PRETTY_NAME:-$ID}"
else
  warn "Sistema non previsto (${PRETTY_NAME:-sconosciuto}): la guida considera Ubuntu 24.04 o Debian 12/13."
  yes_no "Continuare comunque" n || exit 1
fi
command -v apt-get >/dev/null || die "apt-get non trovato: serve una distribuzione Debian o Ubuntu."
command -v systemctl >/dev/null || die "systemd non trovato."

missing=()
for f in "${FILES[@]}" Caddyfile netmon-vm-upgrade sudoers-netmon-vm netmon-firma-sonde netmon-vm-selfupdate netmon-vm-rollback netmon-vm-rollback-boot.service; do [ -f "$HERE/$f" ] || missing+=("$f"); done
[ ${#missing[@]} -eq 0 ] || die "Mancano dei file accanto allo script: ${missing[*]}. Estrai di nuovo netmon.zip."
ok "File del server presenti"

free_mb=$(df -Pm / | awk 'NR==2 {print $4}')
[ "${free_mb:-0}" -ge 500 ] && ok "Spazio libero: ${free_mb} MB" || warn "Poco spazio libero su disco (${free_mb} MB): ne servono almeno 500."

envget() { [ -f "$DEST/.env" ] && sed -n "s/^$1=//p" "$DEST/.env" | tail -n1; }

# Dominio cambiato: i nomi precedenti di questa macchina (OLD_HOSTS nel .env) restano nel Caddyfile e
# netmon li rimanda al nuovo indirizzo; le sonde lo ricevono e lo salvano da sole. Stampa l'elenco
# aggiornato: quelli già presenti, più l'indirizzo attuale (PUBLIC_URL) se diverso dal nuovo.
old_hosts_for() {
  local new=${1,,} prev h out=
  prev=$(envget PUBLIC_URL); prev=${prev#https://}; prev=${prev#http://}; prev=${prev%%/*}; prev=${prev%%:*}
  for h in $(envget OLD_HOSTS | tr ',' ' ') $prev; do
    h=${h,,}
    [[ "$h" =~ ^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$ ]] && [ "$h" != "$new" ] || continue
    [[ ",$out," == *",$h,"* ]] || out=${out:+$out,}$h
  done
  printf '%s' "$out"
}
old_hosts_note() {
  [ -n "${OLD_HOSTS:-}" ] || return 0
  ok "Il vecchio indirizzo ($OLD_HOSTS) resta attivo e rimanda a https://$1: sonde e browser passano da soli"
  info "Tieni il vecchio nome nel DNS finché tutte le sonde non risultano sul nuovo indirizzo."
}
# Nomi del sito nel Caddyfile: il dominio e quelli precedenti
site_names() { local n=$1 h o=${OLD_HOSTS:-}; for h in ${o//,/ }; do n="$n, $h"; done; printf '%s' "$n"; }
# Primo nome del sito nel Caddyfile (quello attuale)
caddy_domain() { awk 'NF && $1 !~ /^#/ && $NF == "{" {sub(/,$/, "", $1); print $1; exit}' /etc/caddy/Caddyfile 2>/dev/null || true; }

if [ -f "$DEST/.env" ]; then
  ok "Trovata un'installazione esistente in $DEST"
  if [ "$MODE" = install ]; then
    echo
    echo "  Cosa vuoi fare?"
    echo "    1) Aggiornare i file del server (configurazione, account e storico restano) — consigliato"
    echo "    2) Riconfigurare: dominio e notifiche da capo (account, storico e chiave restano)"
    echo "    3) Uscire"
    while :; do ask "Scelta" 1; case "$REPLY" in 1) MODE=update; break ;; 2) MODE=reconfigure; break ;; 3) exit 0 ;; esac; done
  fi
elif [ "$MODE" = update ]; then
  die "Nessuna installazione in $DEST da aggiornare: lancia lo script senza --aggiorna."
fi

# ------------------------------------------------------------------ aggiornamento semplice
secure_dest() {
  # Programmi e ambiente Python sono di root: il servizio (utente netmon) li esegue ma non li può
  # cambiare. Se fossero suoi, chi prendesse il controllo del servizio potrebbe modificare ciò
  # che root esegue al prossimo aggiornamento (pip, file copiati) e diventare root.
  # Al servizio restano solo data/ e il file .env.
  mkdir -p "$DEST" && chown root:root "$DEST" && chmod 755 "$DEST" || return 1
  # installazioni precedenti, quando la cartella era del servizio: via i collegamenti (root ci
  # scriverebbe attraverso) e l'ambiente Python, che viene ricreato da root
  find "$DEST" -mindepth 1 -maxdepth 1 -type l ! -name data ! -name .env -delete || return 1
  rm -rf "$DEST/__pycache__"
  if [ -e "$DEST/venv" ] && [ "$(stat -c %U "$DEST/venv" 2>/dev/null)" != root ]; then rm -rf "$DEST/venv" || return 1; fi
  if [ ! -d "$DEST/data" ]; then mkdir "$DEST/data" || return 1; fi
}

install_files() {
  run "Cartella dei programmi (di root)" secure_dest
  # install (non cp): toglie il file di destinazione prima di scrivere e fissa proprietario e permessi
  run "Copia dei file in $DEST" bash -c 'dest=$1; cd "$2" && shift 2 && for f in "$@"; do
    install -m 644 -o root -g root -- "$f" "$dest/$f" || exit 1; done' _ "$DEST" "$HERE" "${FILES[@]}"
  if [ ! -x "$DEST/venv/bin/python" ]; then run "Ambiente Python" python3 -m venv "$DEST/venv"; fi
  run "Librerie Python" "$DEST/venv/bin/pip" install --quiet --upgrade -r "$DEST/requirements.txt"
  # moduli precompilati da root: il servizio non può più scrivere __pycache__ accanto ai programmi
  run "Precompilazione" "$DEST/venv/bin/python" -m compileall -q -l "$DEST"
  # il riavvio della VM dalla pagina non esiste più: tolgo l'eventuale permesso lasciato da versioni vecchie
  if [ -e /etc/sudoers.d/netmon ]; then run "Rimozione del vecchio permesso di riavvio della VM" rm -f /etc/sudoers.d/netmon; fi
  # scheda Server del pannello di amministrazione: aggiornamento dei pacchetti e riavvio, e nient'altro
  command -v sudo >/dev/null || run "Pacchetto sudo" apt-get install -y sudo
  command -v openssl >/dev/null || run "Pacchetto openssl (firma degli aggiornamenti)" apt-get install -y openssl
  run "Script di aggiornamento della VM" install -m 755 -o root -g root "$HERE/netmon-vm-upgrade" /usr/local/sbin/
  run "Permessi di aggiornamento e riavvio della VM (solo amministratori)" bash -c 'install -m 440 -o root -g root "$1" /etc/sudoers.d/.netmon-vm.tmp \
    && visudo -cf /etc/sudoers.d/.netmon-vm.tmp && mv /etc/sudoers.d/.netmon-vm.tmp /etc/sudoers.d/netmon-vm \
    || { rm -f /etc/sudoers.d/.netmon-vm.tmp; false; }' _ "$HERE/sudoers-netmon-vm"
  run "Programma di firma degli aggiornamenti delle sonde" install -m 755 -o root -g root "$HERE/netmon-firma-sonde" /usr/local/sbin/
  # aggiornamento da pacchetto caricato dal pannello: script e verificatore di root (fuori da /opt/netmon)
  run "Installazione di netmon da pacchetto caricato" install -m 755 -o root -g root "$HERE/netmon-vm-selfupdate" /usr/local/sbin/
  # rollback dell'ultimo pacchetto installato: finestra di 4 ore, poi ripristino automatico
  run "Rollback degli aggiornamenti da pacchetto" install -m 755 -o root -g root "$HERE/netmon-vm-rollback" /usr/local/sbin/
  # il timer della finestra è transitorio: all'avvio della VM questa unità lo riarma
  run "Rollback dopo il riavvio della VM" bash -c 'install -m 644 -o root -g root "$1" /etc/systemd/system/ \
    && systemctl daemon-reload && systemctl enable --quiet netmon-vm-rollback-boot.service' _ "$HERE/netmon-vm-rollback-boot.service"
  # aggiornamento a mano (non dal pannello) con una finestra di rollback aperta: la finestra si
  # chiude, altrimenti allo scadere il timer rimetterebbe la versione di prima di quella installata ora
  if [ "$NONINT" != 1 ] && [ -f /var/lib/netmon-vm/rollback.json ]; then
    run "Chiusura della finestra di rollback aperta" bash -c 'systemctl stop netmon-vm-rollback.timer >/dev/null 2>&1; \
      systemctl reset-failed netmon-vm-rollback.timer >/dev/null 2>&1; \
      rm -rf /var/lib/netmon-vm/rollback.json /var/lib/netmon-vm/rollback.status /var/lib/netmon-vm/selfupdate-backup'
  fi
  run "Verificatore dei pacchetti" bash -c 'install -d -m 755 -o root -g root /usr/local/lib/netmon && install -m 644 -o root -g root "$1" /usr/local/lib/netmon/pkgcheck.py' _ "$HERE/pkgcheck.py"
  release_key

  run "Servizio netmon-server" install -m 644 -o root -g root "$HERE/netmon-server.service" /etc/systemd/system/
  # Il registro di sistema contiene email e indirizzi IP (accessi, account): si tiene 30 giorni
  # (GDPR, limitazione della conservazione) e non oltre 200 MB.
  run "Registro di sistema: 30 giorni" bash -c 'install -d -m 755 /etc/systemd/journald.conf.d \
    && printf "[Journal]\nMaxRetentionSec=30day\nSystemMaxUse=200M\n" > /etc/systemd/journald.conf.d/netmon.conf \
    && { systemctl restart systemd-journald || true; }'
  # programmi della sonda della stessa versione: le sonde li scaricano con il tasto "Aggiorna netmon"
  local PD="$HERE/../probe"
  if [ -f "$PD/probe.py" ] && [ -f "$PD/pinger.py" ] && [ -f "$PD/config_web.py" ] && [ -f "$PD/sysops.py" ]; then
    # Le sonde vanno aggiornate? Confronto (senza il numero di versione) tra i file della sonda di
    # questo pacchetto e quelli che il server distribuiva finora, prima di sostituirli. L'esito
    # resta in probe-dist/update-info: lo leggono il pannello e la pagina di stato.
    local pinfo; pinfo=$(mktemp)
    if [ -f "$DEST/probe-dist/probe.py" ]; then
      PROBE_OLD_VERSION=$(sed -n 's/^__version__ *= *"\([^"]*\)".*/\1/p' "$DEST/probe-dist/probe.py" 2>/dev/null | head -n1)
      PROBE_NEED=$(python3 "$HERE/pkgcheck.py" --probe-info "$DEST/probe-dist" "$HERE/.." "$pinfo" 2>>"$LOG") || PROBE_NEED=unknown
      [ -n "$PROBE_NEED" ] || PROBE_NEED=unknown
    fi
    run "Programmi per l'aggiornamento delle sonde" bash -c 'rm -rf "$1" && mkdir -p "$1" \
      && cp -- "$2/probe.py" "$2/pinger.py" "$2/config_web.py" "$2/sysops.py" "$1/"' _ "$DEST/probe-dist" "$PD"
    [ -s "$pinfo" ] && install -m 644 -o root -g root "$pinfo" "$DEST/probe-dist/update-info"
    rm -f "$pinfo"
    ok "Versione per le sonde: $(grep -o '__version__ = "[^"]*"' "$PD/probe.py" | cut -d'"' -f2)"
    PROBE_DIST_OK=1
    # pacchetto completo (aggiornamento completo delle sonde dal server): rifatto da questa cartella
    echo "=== $(date '+%F %T') · pacchetto completo per le sonde" >> "$LOG"
    if python3 - "$HERE/.." "$DEST/probe-dist/netmon.zip" >> "$LOG" 2>&1 <<'EOF'
import os, stat, sys, zipfile
src, out = os.path.realpath(sys.argv[1]), sys.argv[2]
top = ["VERSION", "probe"]          # alla sonda serve solo questo: niente server, strumenti o documenti
files = []
for t in top:
    p = os.path.join(src, t)
    if os.path.islink(p) or not os.path.exists(p):
        continue
    if os.path.isfile(p):
        files.append(t)
        continue
    for d, dirs, names in os.walk(p):
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x != "__pycache__"
                         and not os.path.islink(os.path.join(d, x)))
        for n in sorted(names):
            f = os.path.join(d, n)
            if n.startswith(".") or n.endswith((".pyc", ".bak", "~")) or not stat.S_ISREG(os.lstat(f).st_mode):
                continue
            files.append(os.path.relpath(f, src))
if "VERSION" not in files:
    sys.exit("VERSION mancante")
with zipfile.ZipFile(out + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(os.path.join(src, f), "netmon/" + f.replace(os.sep, "/"))
os.replace(out + ".tmp", out)
EOF
    then ok "Pacchetto completo per le sonde"; else warn "Pacchetto completo non creato: le sonde useranno l'aggiornamento dei soli programmi."; fi
  else
    warn "Cartella probe non trovata accanto a server: le sonde non potranno aggiornarsi dal server."
    warn "Estrai tutto netmon.zip (cartelle server e probe insieme) e rilancia con --aggiorna."
  fi
  gce_slim
}

# VM di Google Cloud: tolgo i pacchetti Google che netmon non usa e che rendono pesanti gli
# aggiornamenti (google-cloud-cli ricompila migliaia di file Python a ogni versione). Restano
# google-guest-agent, google-compute-engine e google-compute-engine-oslogin: chiavi ssh, accesso
# dalla console, rete e metadati. Per tenerli: NETMON_KEEP_GOOGLE=1 prima del comando.
GCE_EXTRA="google-cloud-cli google-cloud-sdk google-osconfig-agent"
gce_slim() {
  [ "${NETMON_KEEP_GOOGLE:-0}" = 1 ] && return 0
  local pk have=()
  for pk in $GCE_EXTRA $(dpkg-query -W -f '${Package}\n' 'google-cloud-cli-*' 'google-cloud-sdk-*' 2>/dev/null); do
    dpkg-query -W -f '${Status}' "$pk" 2>/dev/null | grep -q "install ok installed" && have+=("$pk")
  done
  [ ${#have[@]} -gt 0 ] || return 0
  # con un aggiornamento del sistema in corso apt è occupato: aspetto un po', poi lascio perdere
  if DEBIAN_FRONTEND=noninteractive apt-get remove -y -o DPkg::Lock::Timeout=300 "${have[@]}" >>"$LOG" 2>&1; then
    ok "Pacchetti Google non necessari rimossi: ${have[*]}"
  else
    warn "Pacchetti Google non rimossi (apt occupato?): ${have[*]}. Riprova più tardi con --aggiorna."
  fi
}

caddy_compress() {
  # installazioni precedenti: aggiunge la compressione al blocco di netmon nel Caddyfile
  local CF=/etc/caddy/Caddyfile
  [ -f "$CF" ] && grep -q "reverse_proxy 127.0.0.1:8000" "$CF" && ! grep -q "encode " "$CF" || return 0
  cp -p "$CF" "$CF.bak-$(date +%Y%m%d-%H%M%S)"
  sed -i 's/^\([[:space:]]*\)reverse_proxy 127.0.0.1:8000/\1encode zstd gzip\n\1reverse_proxy 127.0.0.1:8000/' "$CF"
  if caddy validate --config "$CF" --adapter caddyfile >> "$LOG" 2>&1; then
    run "Compressione in Caddy" systemctl reload caddy
  else
    cp -p "$(ls -t "$CF".bak-* | head -n1)" "$CF"; warn "Compressione non aggiunta: il Caddyfile è rimasto com'era."
  fi
}

PROBE_DIST_OK=0
PROBE_NEED=first          # first (prima installazione) | same | unknown | "changed file1 file2…"
PROBE_OLD_VERSION=
probe_alert() {
  # avviso finale: dopo questo aggiornamento della VM le sonde vanno aggiornate oppure no
  case "$PROBE_NEED" in
    changed*)
      warn "${B}Sonde DA AGGIORNARE:${N} con questa versione cambiano i file della sonda (${PROBE_NEED#changed })."
      info "Pannello /admin → scheda Sonde → Programma un aggiornamento → netmon"
      info "(oppure, su ogni sonda: sudo bash probe/installa-sonda.sh --aggiorna)." ;;
    same)
      ok "${B}Sonde: aggiornamento NON necessario.${N} I programmi della sonda sono identici a quelli della"
      info "versione ${PROBE_OLD_VERSION:-precedente}: cambia solo il numero di versione." ;;
    unknown)
      warn "Sonde: non riesco a confrontare i loro programmi con quelli distribuiti finora."
      info "Per sicurezza aggiornale dal pannello /admin, scheda Sonde." ;;
  esac
}
release_key() {
  # Chiave pubblica di rilascio (server/release-key.pub): con quella netmon-vm-selfupdate verifica la
  # firma dell'autore sui pacchetti caricati dal pannello. La privata sta solo sul Mac dell'autore
  # (tools/mac, «Firma NetMon»). Si installa o si cambia solo se:
  #   - la VM non ne ha ancora una (primo pacchetto con la chiave);
  #   - il pacchetto è stato verificato con la chiave attuale (NETMON_PKG_VERIFIED=1, da
  #     netmon-vm-selfupdate): cambio di chiave firmato con la chiave vecchia;
  #   - l'installazione è fatta a mano (root via SSH, non dal pannello).
  local KEY=/usr/local/share/netmon/release-key.pub SRC="$HERE/release-key.pub" fp
  if [ ! -f "$SRC" ]; then
    if [ -f "$KEY" ]; then
      ok "Chiave di rilascio: resta quella installata"
    else
      warn "Il pacchetto non contiene la chiave di rilascio (server/release-key.pub): dal pannello"
      info "/admin non si potranno installare pacchetti finché non ne arriva uno firmato con la chiave."
    fi
    return 0
  fi
  if ! openssl pkey -pubin -in "$SRC" -noout >/dev/null 2>&1; then
    warn "server/release-key.pub del pacchetto non è una chiave pubblica valida: non installata"
    return 0
  fi
  if [ -f "$KEY" ] && ! cmp -s "$SRC" "$KEY" && [ "$NONINT" = 1 ] && [ "${NETMON_PKG_VERIFIED:-0}" != 1 ]; then
    warn "Chiave di rilascio diversa da quella installata in un pacchetto non verificato: resta quella installata"
    return 0
  fi
  run "Chiave di rilascio (firma dei pacchetti)" bash -c 'install -d -m 755 -o root -g root /usr/local/share/netmon \
    && install -m 644 -o root -g root "$1" /usr/local/share/netmon/.release-key.pub.tmp \
    && mv -f /usr/local/share/netmon/.release-key.pub.tmp /usr/local/share/netmon/release-key.pub' _ "$SRC"
  fp=$(openssl pkey -pubin -in "$KEY" -outform DER 2>/dev/null | sha256sum | cut -c1-16 | sed 's/..../& /g;s/ $//')
  ok "Impronta della chiave di rilascio: $fp (deve essere quella mostrata da «Firma NetMon» sul Mac)"
}

fix_perms() {
  # tutto di root (programmi, ambiente Python, programmi per le sonde firmati da netmon-firma-sonde);
  # al servizio solo i dati e il suo file .env (-h: mai attraverso un collegamento)
  run "Permessi" bash -c 'chown root:root "$1" && chmod 755 "$1" \
    && find "$1" -mindepth 1 -maxdepth 1 ! -name data ! -name .env -exec chown -hR root:root {} + \
    && chown -hR netmon:netmon "$1/data" && chown -h netmon:netmon "$1/.env" \
    && find "$1" -maxdepth 1 -type f -name ".env*" -exec chmod 600 {} +' _ "$DEST"
  if [ "$PROBE_DIST_OK" = 1 ]; then
    run "Firma dei programmi per le sonde" /usr/local/sbin/netmon-firma-sonde "$DEST/probe-dist"
    UPDATE_FP=$(openssl pkey -pubin -in /etc/netmon/update-signing.pub -outform DER 2>/dev/null | sha256sum | cut -c1-16 | sed 's/..../& /g;s/ $//')
    ok "Impronta della chiave degli aggiornamenti: $UPDATE_FP"
  fi
}

caddy_hsts() {
  # HSTS e rimozione dell'intestazione Server (installazioni precedenti).
  # Le due righe vanno dentro il blocco di netmon, quindi poco prima del suo reverse_proxy.
  local CF=/etc/caddy/Caddyfile
  [ -f "$CF" ] && grep -q "reverse_proxy 127.0.0.1:8000" "$CF" && ! grep -q "Strict-Transport-Security" "$CF" || return 0
  cp -p "$CF" "$CF.bak-$(date +%Y%m%d-%H%M%S)"
  sed -i 's/^\([[:space:]]*\)reverse_proxy 127.0.0.1:8000/\1header {\n\1    Strict-Transport-Security "max-age=31536000"\n\1    -Server\n\1}\n\1reverse_proxy 127.0.0.1:8000/' "$CF"
  if caddy validate --config "$CF" --adapter caddyfile >> "$LOG" 2>&1; then
    run "HTTPS bloccato in HTTP (HSTS) in Caddy" systemctl reload caddy
  else
    cp -p "$(ls -t "$CF".bak-* | head -n1)" "$CF"; warn "HSTS non aggiunto: il Caddyfile è rimasto com'era."
  fi
}

caddy_body_limit() {
  # limite alla dimensione delle richieste (installazioni precedenti: lo aggiunge al blocco di netmon)
  local CF=/etc/caddy/Caddyfile
  [ -f "$CF" ] && grep -q "reverse_proxy 127.0.0.1:8000" "$CF" && ! grep -q "max_size" "$CF" || return 0
  cp -p "$CF" "$CF.bak-$(date +%Y%m%d-%H%M%S)"
  sed -i 's/^\([[:space:]]*\)reverse_proxy 127.0.0.1:8000/\1request_body {\n\1    max_size 10MB\n\1}\n\1reverse_proxy 127.0.0.1:8000/' "$CF"
  if caddy validate --config "$CF" --adapter caddyfile >> "$LOG" 2>&1; then
    run "Limite alla dimensione delle richieste in Caddy" systemctl reload caddy
  else
    cp -p "$(ls -t "$CF".bak-* | head -n1)" "$CF"; warn "Limite non aggiunto: il Caddyfile è rimasto com'era."
  fi
}

public_url_env() {
  # indirizzo pubblico per i link nelle email (inviti): scritto una volta nel .env
  local dom
  grep -q '^PUBLIC_URL=' "$DEST/.env" 2>/dev/null && return 0
  dom=$(caddy_domain)
  [[ "$dom" == *.* && "$dom" != *tuodominio* ]] || return 0
  printf 'PUBLIC_URL=https://%s\n' "$dom" >> "$DEST/.env"
  ok "Indirizzo pubblico per i link nelle email: https://$dom"
}

# Firewall di Oracle Cloud: 80 e 443 accettate prima del REJECT finale della catena INPUT, subito e
# all'avvio (netfilter-persistent salva le regole in /etc/iptables/rules.v4).
oracle_fw() {
  local p pos
  for p in 80 443; do
    iptables -C INPUT -p tcp -m state --state NEW -m tcp --dport "$p" -j ACCEPT 2>/dev/null && continue
    pos=$(iptables -L INPUT -n --line-numbers | awk '$2 == "REJECT" {print $1; exit}')
    if [ -n "$pos" ]; then
      iptables -I INPUT "$pos" -p tcp -m state --state NEW -m tcp --dport "$p" -j ACCEPT || return 1
    else
      iptables -A INPUT -p tcp -m state --state NEW -m tcp --dport "$p" -j ACCEPT || return 1
    fi
  done
  cp -p /etc/iptables/rules.v4 "/etc/iptables/rules.v4.bak-$(date +%Y%m%d-%H%M%S)"
  netfilter-persistent save
}

wait_local_health() {
  local i
  for i in $(seq 1 30); do
    curl -fsS --max-time 2 http://127.0.0.1:8000/health 2>/dev/null | grep -q '"ok"' && return 0
    sleep 1
  done
  return 1
}

if [ "$MODE" = update ]; then
  STEPS=3
  step "Aggiornamento dei file"
  install_files
  public_url_env
  fix_perms
  caddy_compress
  caddy_body_limit
  caddy_hsts
  step "Riavvio del server"
  run "Riavvio" bash -c "systemctl daemon-reload && systemctl restart netmon-server"
  if wait_local_health; then ok "Il server risponde"; else
    journalctl -u netmon-server -n 20 --no-pager | sed 's/^/      /'; die "Il server non risponde dopo l'aggiornamento."; fi
  printf '\n  %sAggiornamento completato:%s versione %s → %s%s%s. Ricarica la pagina di stato nel browser.\n\n' \
    "$G$B" "$N" "${OLD_VERSION:-precedente}" "$B" "$NETMON_VERSION" "$N"
  probe_alert
  echo
  exit 0
fi

# ------------------------------------------------------------------ 2. pacchetti
step "Installazione dei pacchetti"
export DEBIAN_FRONTEND=noninteractive
run "Aggiornamento elenco pacchetti" apt-get update
# Immagini di Oracle Cloud: il firewall è iptables con le regole in /etc/iptables/rules.v4, caricate da
# netfilter-persistent. ufw è in conflitto con quel pacchetto (installarlo lo disinstalla, e le regole di
# Oracle non si caricano più all'avvio): lì si aprono 80 e 443 nel firewall di Oracle, senza ufw.
ORACLE_FW=0
if dpkg-query -W -f '${Status}' netfilter-persistent 2>/dev/null | grep -q "install ok installed" \
   && [ -f /etc/iptables/rules.v4 ]; then
  ORACLE_FW=1
fi
FW_PKG=ufw; [ "$ORACLE_FW" = 1 ] && FW_PKG=
run "Python, Caddy, firewall e strumenti" apt-get install -y python3 python3-venv caddy $FW_PKG curl ca-certificates openssl
python3 - <<'EOF' >> "$LOG" 2>&1 || die "Serve Python 3.9 o successivo."
import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)
EOF
ok "Python $(python3 -c 'import platform; print(platform.python_version())')"

busy=$(ss -ltnpH 2>/dev/null | awk '$4 ~ /:(80|443)$/' | grep -v caddy || true)
[ -z "$busy" ] || { warn "Le porte 80/443 sono già usate da un altro programma:"; echo "$busy" | sed 's/^/      /'; yes_no "Continuare comunque" n || exit 1; }

# ------------------------------------------------------------------ 3. domande
step "Informazioni necessarie"

# IP pubblico della VM: prima dai metadati di Google Cloud, poi da un servizio esterno
PUBIP=$(curl -fsS --max-time 2 -H "Metadata-Flavor: Google" \
  http://169.254.169.254/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip 2>/dev/null || true)
[[ "$PUBIP" =~ ^[0-9.]+$ ]] || PUBIP=$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)
[[ "$PUBIP" =~ ^[0-9.]+$ ]] && ok "IP pubblico della VM: $PUBIP" || { PUBIP=; warn "Non riesco a leggere l'IP pubblico della VM."; }

echo
info "Serve un dominio che punti a questa VM (es. netmonhome.net): nel DNS crea un record A verso"
info "l'IP pubblico di questa VM e apri le porte 80 e 443 (vedi guida, passo A2)."
OLD_DOMAIN=$(caddy_domain)
[[ "$OLD_DOMAIN" == *.* && "$OLD_DOMAIN" != *tuodominio* ]] || OLD_DOMAIN=netmonhome.net
while :; do
  ask "Dominio del server" "$OLD_DOMAIN"
  DOMAIN=${REPLY,,}; DOMAIN=${DOMAIN#http://}; DOMAIN=${DOMAIN#https://}; DOMAIN=${DOMAIN%%/*}
  [[ "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$ ]] || { warn "Non sembra un dominio valido (es. netmonhome.net)."; continue; }
  DNSIP=$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1; exit}')
  if [ -z "$PUBIP" ] || [ "$DNSIP" = "$PUBIP" ]; then
    [ -n "$DNSIP" ] && ok "$DOMAIN punta a $DNSIP"
    [ -z "$DNSIP" ] && warn "$DOMAIN non risulta ancora nel DNS."
    break
  fi
  warn "$DOMAIN punta a ${DNSIP:-nessun indirizzo}, ma la VM ha IP $PUBIP: correggi il record A nel DNS."
  yes_no "Usare comunque $DOMAIN (HTTPS non funzionerà finché il DNS non è corretto)" n && break
done
OLD_HOSTS=$(old_hosts_for "$DOMAIN")

# --- email
echo
info "Email: gli alert arrivano via email. Con Gmail serve una \"password per le app\""
info "(Account Google → Sicurezza → Verifica in due passaggi → Password per le app)."
SMTP_HOST=$(envget SMTP_HOST); SMTP_PORT=$(envget SMTP_PORT); SMTP_USER=$(envget SMTP_USER)
SMTP_PASSWORD=$(envget SMTP_PASSWORD); SMTP_FROM=$(envget SMTP_FROM)
[[ "$SMTP_USER" == tuoindirizzo* ]] && { SMTP_USER=; SMTP_PASSWORD=; SMTP_FROM=; }
EMAIL_ON=0
if yes_no "Configurare le email" s; then
  while :; do
    ask "Server SMTP" "${SMTP_HOST:-smtp.gmail.com}"; SMTP_HOST=$REPLY
    ask "Porta" "${SMTP_PORT:-587}"; SMTP_PORT=$REPLY
    ask "Indirizzo che invia (utente SMTP)" "$SMTP_USER"; SMTP_USER=$REPLY
    if [ -n "$SMTP_PASSWORD" ]; then
      ask_secret "Password per le app (Invio = lascia quella attuale)"; [ -n "$REPLY" ] && SMTP_PASSWORD=$REPLY
    else ask_secret "Password per le app"; SMTP_PASSWORD=$REPLY; fi
    SMTP_PASSWORD=${SMTP_PASSWORD// /}          # Google la mostra a gruppi di 4: gli spazi non servono
    SMTP_FROM=$SMTP_USER
    printf '  %s…%s Invio di una email di prova' "$D" "$N"
    if err=$(SMTP_HOST="$SMTP_HOST" SMTP_PORT="$SMTP_PORT" SMTP_USER="$SMTP_USER" SMTP_PASSWORD="$SMTP_PASSWORD" MAIL_TO="$SMTP_USER" \
      python3 - 2>&1 <<'EOF'
import os, smtplib, ssl
from email.message import EmailMessage
e = os.environ
m = EmailMessage()
m["Subject"] = "netmon: email di prova"
m["From"] = e["SMTP_USER"]
m["To"] = e["MAIL_TO"]
m.set_content("Se leggi questo messaggio, le email degli alert di netmon funzionano.")
port = int(e["SMTP_PORT"])
ctx = ssl.create_default_context()
if port == 465:
    s = smtplib.SMTP_SSL(e["SMTP_HOST"], port, timeout=20, context=ctx)
else:
    s = smtplib.SMTP(e["SMTP_HOST"], port, timeout=20); s.starttls(context=ctx)
s.login(e["SMTP_USER"], e["SMTP_PASSWORD"])
s.send_message(m); s.quit()
EOF
    ); then
      printf '\r  %s✔%s Email di prova inviata a %s\n' "$G" "$N" "$SMTP_USER"; EMAIL_ON=1; break
    else
      printf '\r  %s✘%s Email non inviata: %s\n' "$R" "$N" "$(echo "$err" | tail -n1)"
      yes_no "Riprovare con altri dati" s || { warn "Email non configurate: puoi farlo più avanti (guida, Parte B)."; SMTP_USER=; SMTP_PASSWORD=; SMTP_FROM=; break; }
    fi
  done
fi

# --- Telegram
echo
info "Telegram (consigliato): il bot del server da cui partono i messaggi. Gli alert critici"
info "arrivano con suono; ogni utente indica poi il proprio chat ID nella pagina."
TG_TOKEN=$(envget TELEGRAM_BOT_TOKEN); TG_CHAT=; botname=
TG_ON=0
if yes_no "Configurare Telegram" s; then
  info "Su Telegram scrivi a @BotFather, invia /newbot e scegli nome e username (deve finire con \"bot\")."
  while :; do
    if [ -n "$TG_TOKEN" ]; then ask "Token del bot" "$TG_TOKEN"; else ask "Token del bot (es. 7412345678:AAH...)"; fi
    TG_TOKEN=$REPLY
    botname=$(printf 'url = "https://api.telegram.org/bot%s/getMe"\n' "$TG_TOKEN" | curl -fsS --max-time 10 --config - 2>/dev/null \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["result"]["username"] if d.get("ok") else "")' 2>/dev/null || true)
    [ -n "$botname" ] && { ok "Bot trovato: @$botname"; break; }
    warn "Token non valido."; yes_no "Riprovare" s || { TG_TOKEN=; break; }
  done
  if [ -n "$TG_TOKEN" ]; then
    while :; do
      info "Apri la chat con @$botname, premi Avvia (o scrivi un messaggio qualsiasi), poi torna qui."
      ask "Premi Invio quando hai scritto al bot" ""
      found=$(printf 'url = "https://api.telegram.org/bot%s/getUpdates"\n' "$TG_TOKEN" | curl -fsS --max-time 10 --config - 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin); seen = []
for u in d.get("result", []):
    m = u.get("message") or u.get("my_chat_member") or {}
    c = m.get("chat") or {}
    if c.get("id") and c["id"] not in [x[0] for x in seen]:
        seen.append((c["id"], c.get("first_name") or c.get("title") or ""))
for i, n in seen[-1:]:
    print(i, n)' 2>/dev/null || true)
      if [ -n "$found" ]; then
        TG_CHAT=${found%% *}; ok "Chat trovata: ${found#* } (ID $TG_CHAT)"
      else
        warn "Il bot non ha ancora ricevuto messaggi."
        yes_no "Riprovare" s && continue
        ask "Oppure inserisci a mano il chat ID (Invio per saltare)" ""; TG_CHAT=$REPLY
      fi
      [ -z "$TG_CHAT" ] && { TG_TOKEN=; warn "Telegram non configurato."; break; }
      if printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$TG_TOKEN" | curl -fsS --max-time 10 --config - \
           -d chat_id="$TG_CHAT" --data-urlencode text="✅ netmon: messaggio di prova, Telegram funziona." >/dev/null 2>&1; then
        if yes_no "Ti è arrivato il messaggio di prova su Telegram" s; then TG_ON=1; break; fi
      else warn "Invio non riuscito a $TG_CHAT."; fi
      TG_CHAT=
      yes_no "Riprovare" s || { TG_TOKEN=; warn "Telegram non configurato."; break; }
    done
  fi
fi
[ "$TG_ON" = 1 ] || { TG_TOKEN=; TG_CHAT=; }


[ "$EMAIL_ON$TG_ON" = 00 ] && warn "Né email né Telegram configurati: gli alert si vedranno solo nella pagina."
info "Chat ID Telegram e topic ntfy sono personali: ognuno li indica in ⚙ Impostazioni → Notifiche."

# --- firewall
echo
UFW_ON=0
if [ "$ORACLE_FW" = 1 ]; then
  info "Firewall di Oracle Cloud (iptables, /etc/iptables/rules.v4): apro lì le porte 80 e 443, senza ufw."
  info "Servono anche le regole Ingress TCP 80 e 443 da 0.0.0.0/0 nella Security List della VCN (console di Oracle)."
elif ufw status 2>/dev/null | grep -q "Status: active"; then
  UFW_ON=1; info "Firewall ufw già attivo: aggiungo le porte 80 e 443."
elif yes_no "Attivare il firewall della VM (ufw) lasciando aperti SSH, 80 e 443" s; then
  UFW_ON=1
fi

# ------------------------------------------------------------------ 4. installazione
step "Installazione del server"
id netmon >/dev/null 2>&1 || run "Utente di servizio netmon" useradd --system --home "$DEST" --shell /usr/sbin/nologin netmon
install_files

API_TOKEN=$(envget API_TOKEN)
if [ -z "$API_TOKEN" ] || [ "$API_TOKEN" = cambia-questo-token ]; then
  API_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))'); NEW_KEY=1
else NEW_KEY=0; fi

# .env: parte dal modello (o dal file attuale) e sostituisce solo i valori raccolti; niente commenti in riga
BASE="$DEST/env.example"; [ -f "$DEST/.env" ] && { BASE="$DEST/.env"; cp -p "$DEST/.env" "$DEST/.env.bak-$(date +%Y%m%d-%H%M%S)"; }
V_API_TOKEN="$API_TOKEN" V_SMTP_HOST="${SMTP_HOST:-smtp.gmail.com}" V_SMTP_PORT="${SMTP_PORT:-587}" \
V_SMTP_USER="$SMTP_USER" V_SMTP_PASSWORD="$SMTP_PASSWORD" V_SMTP_FROM="$SMTP_FROM" \
V_TELEGRAM_BOT_TOKEN="$TG_TOKEN" V_DATA_DIR="$DEST/data" V_PUBLIC_URL="https://$DOMAIN" V_OLD_HOSTS="$OLD_HOSTS" \
python3 - "$BASE" "$DEST/.env" <<'EOF' >> "$LOG" 2>&1 || die "Scrittura del file .env non riuscita."
import os, sys
vals = {k[2:]: v.replace("\n", "") for k, v in os.environ.items() if k.startswith("V_")}
out, done = [], set()
for line in open(sys.argv[1], encoding="utf-8").read().splitlines():
    key = line.split("=", 1)[0].strip()
    if "=" in line and not line.lstrip().startswith("#") and key in vals:
        out.append(f"{key}={vals[key]}"); done.add(key)
    else:
        out.append(line)
out += [f"{k}={v}" for k, v in vals.items() if k not in done]
tmp = sys.argv[2] + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")
os.chmod(tmp, 0o600)
os.replace(tmp, sys.argv[2])
EOF
ok "Configurazione scritta in $DEST/.env"
fix_perms

if [ "$UFW_ON" = 1 ]; then
  sshport=$(ss -ltnpH 2>/dev/null | awk '/sshd/ {n=split($4,a,":"); print a[n]; exit}')
  run "Firewall: SSH" ufw allow "${sshport:-22}/tcp"
  run "Firewall: 80 e 443" ufw allow 80,443/tcp
  run "Firewall attivo" ufw --force enable
fi
[ "$ORACLE_FW" = 1 ] && run "Firewall di Oracle: porte 80 e 443" oracle_fw

# ------------------------------------------------------------------ 5. avvio e HTTPS
step "Avvio e HTTPS"
run "Avvio del servizio netmon-server" bash -c "systemctl daemon-reload && systemctl enable netmon-server && systemctl restart netmon-server"
if wait_local_health; then ok "Il server risponde in locale"; else
  journalctl -u netmon-server -n 25 --no-pager | sed 's/^/      /'; die "Il server non si avvia: vedi le righe sopra."; fi

if :; then
  CF=/etc/caddy/Caddyfile
  if [ -f "$CF" ] && ! grep -qE "reverse_proxy 127.0.0.1:80(00|80)" "$CF" && grep -qvE '^\s*(#|$)' "$CF" \
     && ! grep -q "root \* /usr/share/caddy" "$CF"; then
    warn "Il Caddyfile contiene già altre configurazioni:"; sed 's/^/      /' "$CF"
    yes_no "Sostituirlo (ne salvo una copia)" s || die "Aggiungi a mano il blocco per $DOMAIN (guida, passo A4)."
  fi
  mkdir -p /etc/caddy
  [ -f "$CF" ] && cp -p "$CF" "$CF.bak-$(date +%Y%m%d-%H%M%S)"
  printf '# netmon · scritto da installa-server.sh\n%s {\n    encode zstd gzip\n    request_body {\n        max_size 10MB\n    }\n    header {\n        Strict-Transport-Security "max-age=31536000"\n        -Server\n    }\n    reverse_proxy 127.0.0.1:8000\n}\n' "$(site_names "$DOMAIN")" > "$CF"
  run "Controllo del Caddyfile" caddy validate --config "$CF" --adapter caddyfile
  run "Avvio di Caddy" bash -c "systemctl enable caddy && (systemctl reload caddy || systemctl restart caddy)"
  old_hosts_note "$DOMAIN"

  HTTPS_OK=0
  # Un dominio che non si risolve non avrà mai un certificato: niente attesa, si va avanti subito.
  if ! getent hosts "$DOMAIN" > /dev/null 2>&1; then
    warn "$DOMAIN non si risolve ancora: salto l'attesa del certificato HTTPS (Caddy riprova da solo)."
    HTTPS_SKIP=1
  else
    printf '  %s…%s Attendo il certificato HTTPS (fino a 2 minuti)' "$D" "$N"
  fi
  for i in $(seq 1 40); do
    [ "${HTTPS_SKIP:-0}" = 1 ] && break
    if curl -fsS --max-time 5 "https://$DOMAIN/health" 2>/dev/null | grep -q '"ok"'; then HTTPS_OK=1; break; fi
    sleep 3
  done
  if [ "$HTTPS_OK" = 1 ]; then printf '\r  %s✔%s HTTPS attivo: https://%s                \n' "$G" "$N" "$DOMAIN"
  elif [ "${HTTPS_SKIP:-0}" = 1 ]; then :
  else
    printf '\r  %s!%s HTTPS non ancora raggiungibile.                    \n' "$Y" "$N"
    journalctl -u caddy -n 8 --no-pager -o cat 2>/dev/null | sed 's/^/      /'
    warn "Controlla: porte TCP 80 e 443 aperte nel pannello del provider (Google Cloud: Consenti"
    warn "traffico HTTP e HTTPS), e che $DOMAIN punti a ${PUBIP:-questa VM}. Caddy riprova da solo."
  fi
fi

# amministratore della pagina /admin (account separati dagli utenti): se non ce n'è nessuno
# lo creo io, con password provvisoria da cambiare al primo accesso
acct() { runuser -u netmon -- "$DEST/venv/bin/python" "$DEST/account.py" "$@"; }
ADMIN_USER=; ADMIN_PW=
ACCOUNTS=$(acct elenco 2>>"$LOG" || true)      # letto tutto prima di cercare (con pipefail grep -q interromperebbe il comando)
if grep -q "^Amministratori: nessuno" <<< "$ACCOUNTS"; then
  echo
  info "Creo l'amministratore della pagina https://$DOMAIN/admin, con una password provvisoria"
  info "che ti verrà chiesto di cambiare al primo accesso."
  info "L'amministratore è nominale: accede con la sua email, che riceve anche il codice di riserva"
  info "della verifica in due passaggi."
  while :; do
    ask "Email dell'amministratore" "$SMTP_USER"; ADMIN_USER=${REPLY,,}
    [[ "$ADMIN_USER" =~ ^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$ ]] && break
    warn "Non sembra un'email valida."
  done
  ask "Nome e cognome (facoltativo)" ""; ADMIN_NAME=$REPLY
  if ADMIN_PW=$(acct crea-admin "$ADMIN_USER" --nome "$ADMIN_NAME" --solo-password 2>>"$LOG") && [ -n "$ADMIN_PW" ]; then
    ok "Amministratore \"$ADMIN_USER\" creato"
  else
    ADMIN_PW=; warn "Amministratore non creato: crealo poi con account.py crea-admin (vedi guida)."
  fi
fi

# ------------------------------------------------------------------ 6. riepilogo
step "Fatto"
probe_alert
channels=()
[ "$EMAIL_ON" = 1 ] && channels+=("email (partono da $SMTP_USER, a ciascuno la sua)")
[ "$TG_ON" = 1 ] && channels+=("Telegram con il bot @$botname")
[ ${#channels[@]} -eq 0 ] && channels=("nessuno (solo pagina)")
CHANNELS=$(printf '%s, ' "${channels[@]}"); CHANNELS=${CHANNELS%, }

cat > "$SUMMARY" <<EOF
netmon · server — informazioni da conservare ($(date '+%d/%m/%Y %H:%M'), versione $NETMON_VERSION)

Sito ................... https://$DOMAIN
Dashboard utenti ....... https://$DOMAIN/dashboard
Amministrazione ........ https://$DOMAIN/admin
Chiave del server ...... $API_TOKEN
Indirizzo per la sonda . https://$DOMAIN/api/report
Notifiche .............. $CHANNELS
Chiave aggiornamenti ... ${UPDATE_FP:-non creata}  (impronta: la sonda la mostra quando la installi)
$([ "$TG_ON" = 1 ] && echo "Tuo chat ID Telegram ... $TG_CHAT  (da inserire nella pagina: Impostazioni → Notifiche)")
$([ -n "$ADMIN_PW" ] && printf 'Amministratore ......... %s\nPassword provvisoria ... %s  (da cambiare al primo accesso)\n' "$ADMIN_USER" "$ADMIN_PW")

La chiave del server serve solo a creare il primo account (Primo accesso nella pagina di
stato). Non vale per le sonde, che usano il token generato in Impostazioni → Sonde, e non
registra altri utenti: per ospitare qualcuno genera un codice di accesso da /admin.
Si ritrova sempre con:
  sudo grep '^API_TOKEN=' /opt/netmon/.env

Comandi utili:
  stato del server   sudo systemctl status netmon-server
  registro           sudo journalctl -u netmon-server -f
  aggiornare         sudo bash netmon/server/installa-server.sh --aggiorna
  account            sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py elenco
  nuovo admin        sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py crea-admin
EOF
chmod 600 "$SUMMARY"

line=$(printf '%.0s─' $(seq 1 66))
printf '\n  %s┌%s┐%s\n' "$Y" "$line" "$N"
printf '  %s│%s %-64s %s│%s\n' "$Y" "$N$B" "INFORMAZIONI DA SALVARE (es. nel gestore delle password)" "$N$Y" "$N"
printf '  %s└%s┘%s\n' "$Y" "$line" "$N"
printf '  Sito                 %s%s%s\n' "$B" "https://$DOMAIN" "$N"
printf '  Dashboard utenti     %s%s%s\n' "$B" "https://$DOMAIN/dashboard" "$N"
printf '  Amministrazione      %s%s%s\n' "$B" "https://$DOMAIN/admin" "$N"
printf '  Chiave del server    %s%s%s%s\n' "$B$Y" "$API_TOKEN" "$N" "$([ "$NEW_KEY" = 0 ] && echo "  (invariata)")"
printf '  Indirizzo sonda      %s\n' "https://$DOMAIN/api/report"
printf '  Notifiche            %s\n' "$CHANNELS"
printf '  Chiave aggiornamenti %s  (impronta)\n' "${UPDATE_FP:-non creata}"
[ "$TG_ON" = 1 ] && printf '  Tuo chat ID Telegram %s%s%s  (da inserire in ⚙ Impostazioni → Notifiche)\n' "$B" "$TG_CHAT" "$N"
if [ -n "$ADMIN_PW" ]; then
  printf '  Amministratore       %s%s%s\n' "$B" "$ADMIN_USER" "$N"
  printf '  Password provvisoria %s%s%s  (da cambiare al primo accesso)\n' "$B$Y" "$ADMIN_PW" "$N"
fi
printf '\n  %sUna copia è in %s (leggibile solo da root).%s\n' "$D" "$SUMMARY" "$N"

cat <<EOF

  ${B}Prossimi passi${N}
    1. Dashboard https://$DOMAIN/dashboard: crea il tuo account (il primo si registra con la
       chiave del server) e in ⚙ Impostazioni → Sonde → Aggiungi una sonda ricevi il token.
    2. Sulla sonda lancia:  sudo bash probe/installa-sonda.sh
    3. Amministrazione https://$DOMAIN/admin$([ -n "$ADMIN_PW" ] && echo ": accedi come $ADMIN_USER con la password
       provvisoria e scegline una nuova"). Lì generi i codici di accesso per chi vuoi ospitare.
    4. Consigliato: registra https://$DOMAIN/health su UptimeRobot, per sapere se la VM si ferma.

EOF
