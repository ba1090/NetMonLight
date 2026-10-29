# NetMon Light — guida completa da zero

*Versione di netmon: 1.1.20261029-083000*

Sistema di monitoraggio della rete di casa: una **sonda** (per esempio un Raspberry Pi) pinga i dispositivi
locali e invia i risultati a un server online, che ti avvisa via email,
Telegram o ntfy quando qualcosa non risponde.

```
 CASA                                   INTERNET
┌───────────────────────────┐          ┌──────────────────────────────┐
│ Sonda (es. Raspberry Pi)  │  HTTPS   │ VM (server)                  │
│  probe.py ── ping ──> LAN │ ───────> │  Caddy (HTTPS) → app.py      │
│  config_web.py :8080      │ ogni 60s │  dashboard /dashboard        │
└───────────────────────────┘          │  alert: email/Telegram/ntfy  │
                                       └──────────────▲───────────────┘
                                                      │ controlla /health
                                          UptimeRobot (gratuito)
```

## Indice

1. Cosa serve
2. Contenuto del pacchetto
3. Parte A — Server online
4. Parte B — Notifiche
5. Parte C — Sonda
6. Parte D — Verifiche finali
7. Uso quotidiano
8. Aggiornare i file in futuro
9. Risoluzione problemi
10. Riferimento rapido

---

## 1. Cosa serve

- Una VM Linux con **Ubuntu 24.04 o Debian 12/13** (Google Cloud, Hetzner, OVH…). Basta la più piccola.
- Una **sonda**: un piccolo computer Linux sempre acceso nella rete di casa, preferibilmente
  collegato via cavo. Per esempio un **Raspberry Pi**, anche uno **Zero**, con Raspberry Pi OS;
  va bene anche un mini PC o una macchina virtuale con Debian o Ubuntu. Alcune informazioni della
  scheda *Stato sonda*, come l'alimentazione, sono disponibili solo su Raspberry Pi.

### Requisiti minimi

| | Server (VM) | Sonda |
|---|---|---|
| Sistema | Ubuntu 22.04/24.04 o Debian 12/13, 64 bit | Raspberry Pi OS Lite (Bookworm o successivo), Debian 12/13, Ubuntu 22.04+ |
| Python | 3.9 o successivo | 3.9 o successivo |
| CPU | 1 vCPU condivisa (es. Google Cloud e2-micro) | 1 core ARMv6 a 1 GHz (Raspberry Pi Zero / Zero W) |
| RAM | 512 MB (1 GB consigliato) | 512 MB |
| Disco | 10 GB (il minimo dei provider); i dati occupano circa 50–100 MB per sonda con 30 giorni di storico | scheda microSD da 8 GB (classe A1 consigliata) |
| Rete | IP pubblico, porte TCP 80 e 443 aperte | accesso a Internet in uscita (HTTPS); via cavo consigliato |

**Consumi indicativi.** Server: un processo Python di circa 60–80 MB di RAM, CPU quasi sempre
ferma. Sonda: circa 15 MB di RAM senza FRITZ!Box e 25–35 MB con il FRITZ!Box su un sistema a 32 bit;
CPU media sotto il 2% su un Raspberry Pi Zero con una decina di dispositivi. La pagina locale
occupa memoria solo mentre la usi.

**Raspberry Pi Zero.** Usa Raspberry Pi OS **Lite** (senza desktop). Lo Zero W ha solo Wi-Fi a
2,4 GHz: i tempi di risposta misurati includono il Wi-Fi, quindi se puoi usa un adattatore
USB-Ethernet (con lo Zero senza W è indispensabile). L'installazione guidata su uno Zero richiede
10–20 minuti, soprattutto per `apt update`. Il primo collegamento al FRITZ!Box richiede qualche
decina di secondi, poi la descrizione dei servizi resta in cache e i riavvii sono rapidi. Per
ridurre ancora il carico puoi alzare *Traffico: un campione ogni* (30 secondi di default) o metterlo a 0.

**Come risparmia risorse la sonda.** I ping partono direttamente dal programma, senza avviare il
comando `ping` per ogni dispositivo (il servizio ha solo il permesso `CAP_NET_RAW`, necessario a
questo; se manca usa il comando `ping`). Una sola connessione HTTPS al server resta aperta e viene
riusata. Il FRITZ!Box ha una sola connessione condivisa, con la descrizione dei servizi in cache
su disco, e i dati che cambiano di rado (modello, velocità della linea, nomi delle reti Wi-Fi) si
leggono ogni 10 minuti; mappa mesh, fibra ed elenco dei dispositivi ogni 5. Il buffer delle misure si legge a blocchi.
La pagina locale parte solo quando la apri e si chiude dopo 10 minuti di inattività. Nel
registro compare una riga `OK` solo quando cambia qualcosa, e comunque una volta all'ora.
- Il dominio **netmonhome.net**, con un record DNS verso la VM del server.
- Un account email per inviare gli alert (es. Gmail) e, consigliato, **Telegram** sul telefono.

## 2. Contenuto del pacchetto

```
netmon/
├── VERSION                   numero di versione del pacchetto
├── GUIDA.md                  questa guida
├── INSTALLAZIONE.md          istruzioni rapide di installazione e aggiornamento
├── CHANGELOG.md              novità versione per versione
├── server/                   va sulla VM, in /opt/netmon
│   ├── app.py                server web, API, pagina di stato e pannello /admin
│   ├── auth.py               account: password cifrate, sessioni, limite ai tentativi
│   ├── mfa.py                verifica in due passaggi (app di autenticazione e codice via email)
│   ├── account.py            comandi da VM: amministratori, password, elenco di account e sonde
│   ├── monitor.py            logica degli alert
│   ├── notifier.py           invio email / Telegram / ntfy
│   ├── brand.py              logo e icone (generato da tools/genera-icone.py)
│   ├── fonts.py              caratteri Roboto e Roboto Mono serviti dal server (niente Google Fonts)
│   ├── i18n.py, i18n_admin.py traduzioni (pagina utente e notifiche; pannello e avvisi agli amministratori)
│   ├── privacy.html          informativa sulla privacy, su /privacy (vedi Privacy e GDPR)
│   ├── vmops.py              stato della VM, aggiornamenti, riavvio e rollback (Server in /admin)
│   ├── pkgcheck.py           verificatore dei pacchetti netmon.zip (lo stesso della sonda)
│   ├── netmon-vm-upgrade     aggiornamento dei pacchetti della VM (apt)
│   ├── netmon-vm-selfupdate  installazione di un netmon.zip caricato dal pannello
│   ├── netmon-vm-rollback    conferma o rollback dell'ultima installazione da pacchetto
│   ├── netmon-vm-rollback-boot.service   riarma la finestra di rollback dopo un riavvio della VM
│   ├── netmon-firma-sonde    firma i programmi e il pacchetto distribuiti alle sonde
│   ├── release-key.pub       chiave pubblica di rilascio: la VM installa solo pacchetti firmati con la
│   │                         sua privata (sul Mac dell'autore, «Firma NetMon»); la crei tu, vedi sezione 8
│   ├── sudoers-netmon-vm     i soli comandi di root che il servizio può chiedere
│   ├── requirements.txt      librerie Python
│   ├── env.example           modello della configurazione (.env)
│   ├── netmon-server.service servizio systemd
│   ├── Caddyfile             modello della configurazione HTTPS
│   └── installa-server.sh    installazione e aggiornamento guidati del server
├── probe/                    va sulla sonda, in /opt/netprobe
│   ├── installa-sonda.sh     installazione, aggiornamento e disinstallazione della sonda
│   ├── probe.py              sonda (ping + invio al server)
│   ├── pinger.py             ping diretti, senza avviare il comando ping
│   ├── config_web.py         pagina locale della sonda (porta 8080)
│   ├── sysops.py             riavvio, aggiornamenti e disinstallazione comandati dalla pagina o dal server
│   ├── pkgcheck.py           verificatore dei pacchetti (uguale a quello del server)
│   ├── netprobe-upgrade      aggiornamento del sistema (apt)
│   ├── netprobe-selfupdate   aggiornamento dei soli programmi Python dal server
│   ├── netprobe-zipupdate    aggiornamento completo con il pacchetto firmato dal server
│   ├── netprobe-wifi         reti Wi-Fi della sonda (NetworkManager)
│   ├── netprobe-uninstall    disinstallazione della sonda
│   ├── sudoers-netprobe      i soli comandi di root che la sonda può chiedere
│   ├── config.yaml.example   modello della configurazione della sonda
│   ├── netmon-probe.service  servizio della sonda
│   ├── netmon-config.service servizio della pagina locale
│   └── netmon-config.socket  avvio della pagina locale solo quando la apri
└── tools/
    ├── nuova-versione.py     prepara un rilascio: alza la versione e crea la zip (solo VERSION, server/ e
    │                         probe/: test, strumenti e documenti restano nel repository)
    ├── genera-icone.py       rigenera logo e icone (brand.py) e le icone di Firma NetMon (--mac)
    ├── mac/
    │   ├── Firma NetMon.app  app per il Mac: crea la chiave di rilascio e firma i pacchetti netmon.zip, con
    │   │                     la pagina nel browser (programmi solo nel repository) o le finestre di sistema
    │   └── LEGGIMI.md        come si apre la prima volta e come si usa
    ├── windows/
    │   ├── FirmaNetMon.exe   la stessa cosa per Windows: un solo file, senza installazione (solo nel repository)
    │   └── LEGGIMI.md        come si apre la prima volta e come si usa
    └── firma/
        ├── src/              sorgenti (Go) del programma con la pagina, uguale per Mac e Windows
        └── build.sh          compila FirmaNetMon.exe e i programmi dell'app per il Mac
```

**Le credenziali, in breve.**

- **Chiave del server** (`API_TOKEN` nel `.env` della VM): serve **solo a creare il primo account** di
  una VM appena installata. Non vale per le sonde e non registra altri utenti.
- **Codice di accesso** (`accesso_…`): lo genera un amministratore per invitare un utente.
- **Token della sonda** (`sonda_…`): uno per ogni sonda, generato dal suo proprietario in
  *Impostazioni → Sonde*. È l'unica credenziale con cui una sonda si collega.
- **Password della pagina locale** della sonda (*password di accesso alla sonda*): protegge
  `http://IP_DELLA_SONDA:8080`. Se la cambi dalla pagina, almeno 12 caratteri.

**Installazione guidata.** Due script fanno tutto: `server/installa-server.sh` sulla VM e
`probe/installa-sonda.sh` sulla sonda. Controllano il sistema, installano i pacchetti, ti fanno le
domande necessarie provando subito le risposte (dominio, email, Telegram, token, dispositivi,
FRITZ!Box), avviano i servizi e alla fine mostrano in un riquadro le **informazioni da salvare**,
copiate anche in un file leggibile solo da root. L'installazione a mano, file per file, non è più
descritta: tra permessi, firme e script di sistema è facile sbagliare, e gli script fanno anche i
controlli. Le sezioni *Cosa installa lo script* dicono comunque che cosa viene messo e dove.

---

## 3. Parte A — Server online

> Tutti i comandi di questa parte vanno lanciati **sulla VM**.
> Controlla sempre dove sei con `hostname` prima di incollare i comandi.

### A1. Crea la VM e apri le porte

Crea la VM con Ubuntu 24.04 o Debian. Poi, **nel pannello del provider**, apri
in ingresso le porte **TCP 80 e 443**.

Su **Google Cloud**: Compute Engine → Istanze VM → la tua VM → *Modifica* →
sezione *Firewall* → spunta **Consenti traffico HTTP** e **Consenti traffico HTTPS** → *Salva*.

Consiglio: su Google Cloud rendi statico l'IP esterno (VPC network → Indirizzi IP →
*Promuovi a statico*), altrimenti può cambiare quando riavvii la VM.

Su Google Cloud l'installazione (anche `--aggiorna`) **toglie i pacchetti Google che netmon non usa**:
`google-cloud-cli` (il comando `gcloud`, pesante da aggiornare su una VM piccola) con i suoi componenti e
`google-osconfig-agent` (gestione patch di VM Manager). Restano `google-guest-agent`,
`google-compute-engine` e `google-compute-engine-oslogin`, che servono per l'SSH dalla console, la rete e
i metadati. Per tenerli tutti: `sudo NETMON_KEEP_GOOGLE=1 bash ~/netmon/server/installa-server.sh …`.

**robots.txt e sitemap.xml** sono pubblici su ogni indirizzo (`https://dominio/sitemap.xml`). Elencano solo
le pagine pubbliche: il sito di presentazione (`/`, `/en/`, `/de/`, `/fr/`), la dashboard e l'informativa.
Pannello e API sono esclusi.

### A2. Configura il DNS di netmonhome.net

Nel pannello DNS del dominio crea un **record A** verso l'**IP esterno della VM**:

| Nome | Punta a |
|---|---|
| `netmonhome.net` | la VM del server |

Utenti, amministratori e sonde usano tutti questo indirizzo (le sonde lo trovano anche in
*Impostazioni → Sonde*). Il DNS può impiegare
qualche minuto ad aggiornarsi: lo script di installazione controlla che il nome punti alla VM.

### A3. Installazione guidata

Dopo aver creato la VM (A1) e il record DNS (A2), carica lo zip della versione (`netmon-light-<versione>.zip`) nella home della VM (con Google Cloud:
finestra SSH del browser → **Carica file**) e lancia:

```bash
cd ~ && sudo apt install -y unzip && rm -rf ~/netmon && unzip -q netmon-light-<versione>.zip
sudo bash ~/netmon/server/installa-server.sh
```

Lo script:

1. verifica sistema operativo, file e spazio su disco;
2. installa Python, Caddy, ufw, curl e openssl;
3. chiede il **dominio** (proposto `netmonhome.net`) e controlla che punti all'IP della VM;
4. configura le **email** (con Gmail basta indirizzo e password per le app) e invia una prova;
5. configura **Telegram**: gli dai il token di @BotFather, scrivi un messaggio al bot e il chat ID
   viene trovato da solo; poi arriva un messaggio di prova. Chat ID e topic ntfy dei singoli
   utenti si impostano poi dalla pagina (*Impostazioni → Notifiche*);
6. genera la **chiave del server**, scrive `.env`, permessi, servizio e Caddyfile, chiede se attivare
   il firewall (SSH, 80 e 443) e attende il certificato HTTPS;
7. crea la **chiave di firma degli aggiornamenti** (in `/etc/netmon`, leggibile solo da root) e firma
   programmi e pacchetto della sonda: le sonde installano solo aggiornamenti firmati con questa chiave;
8. chiede email e nome del **primo amministratore** e lo crea con una password provvisoria.

Alla fine mostra pagina di stato, indirizzo di `/admin`, chiave del server (serve solo per creare il
primo account), indirizzo per la sonda, impronta della chiave degli aggiornamenti e password
provvisoria dell'amministratore, salvati anche in `/root/netmon-server-riepilogo.txt`. Se lo
rilanci su una VM già installata puoi scegliere tra **aggiornare i file** o **riconfigurare**
dominio e notifiche: account, storico e chiave restano. Con `--aggiorna` aggiorna senza domande.

### Indirizzi del server

Tutto sta sullo stesso dominio (es. `netmonhome.net`):

| Indirizzo | Cosa c'è |
|---|---|
| `https://netmonhome.net/` (e `/en/`, `/de/`, `/fr/`) | sito di presentazione: la pagina pubblica del servizio; *Accedi* porta alla dashboard |
| `https://netmonhome.net/dashboard` | dashboard degli utenti (pagina di stato): accesso, registrazione con il codice, sonde e avvisi |
| `https://netmonhome.net/admin` | pannello di amministrazione |
| `https://netmonhome.net/privacy` | informativa sulla privacy |

`/status`, l'indirizzo delle versioni precedenti, rimanda a `/dashboard` (anche i link già mandati per email).
Il sito è in `server/sito.py`, creato da `python3 tools/importa-sito.py netmon-sito-<versione>.zip` a partire
dallo zip del sito: per cambiarlo si rifà l'importazione con la pagina nuova e si alza la versione.
Caratteri e icone del sito sono quelli di netmon.

### A4. Cosa installa lo script sulla VM

| Cosa | Dove | Di chi |
|---|---|---|
| Programmi e ambiente Python | `/opt/netmon/*.py`, `/opt/netmon/venv` | root (il servizio li legge ma non li può cambiare) |
| Configurazione | `/opt/netmon/.env` (permessi 600) | utente `netmon` |
| Database e stato | `/opt/netmon/data/` (`auth.db`, `events.db`, `state.json`, `scans.json`, `inactive.json`) | utente `netmon` |
| Programmi e pacchetto per le sonde, firmati | `/opt/netmon/probe-dist/` | root |
| Servizio | `/etc/systemd/system/netmon-server.service` (utente `netmon`, memoria massima 384 MB) | root |
| Script di sistema | `/usr/local/sbin/netmon-vm-upgrade`, `netmon-vm-selfupdate`, `netmon-vm-rollback`, `netmon-firma-sonde` | root |
| Finestra di rollback dopo un riavvio | `/etc/systemd/system/netmon-vm-rollback-boot.service` | root |
| Verificatore dei pacchetti | `/usr/local/lib/netmon/pkgcheck.py` | root |
| Chiave pubblica di rilascio (firma dell'autore sui pacchetti) | `/usr/local/share/netmon/release-key.pub` | root |
| Permessi del servizio | `/etc/sudoers.d/netmon-vm` | root |
| Chiave di firma degli aggiornamenti | `/etc/netmon/update-signing.key` (solo root) e `.pub` | root |
| Stato e registri di aggiornamenti e rollback | `/var/lib/netmon-vm/` | root (leggibili dal servizio) |
| HTTPS | `/etc/caddy/Caddyfile` | root |

Il Caddyfile scritto dallo script (dominio a parte) è questo; lo stesso modello è in
`server/Caddyfile`. Lo spazio prima della `{` è obbligatorio:

```
netmonhome.net {
    encode zstd gzip
    request_body {
        max_size 10MB
    }
    header {
        Strict-Transport-Security "max-age=31536000"
        -Server
    }
    reverse_proxy 127.0.0.1:8000
}
```

Se nel Caddyfile c'è già qualcos'altro, lo script chiede se sostituirlo (salvandone una copia);
altrimenti va aggiunto a mano questo blocco. Dopo una modifica:
`sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy`.

**Regole del file `.env`**, se lo modifichi a mano (`sudo nano /opt/netmon/.env`, poi
`sudo systemctl restart netmon-server`): niente commenti sulla stessa riga di un valore
(`FAIL_THRESHOLD=3  # ...` fa fallire il servizio), niente spazi attorno al `=` e niente virgolette.

---

## 4. Parte B — Notifiche

**Chi spedisce e chi riceve.** Nel file `.env` del server c'è solo **da dove partono** i
messaggi: l'account email (`SMTP_…`) e il bot Telegram (`TELEGRAM_BOT_TOKEN`). **I destinatari
sono per persona**: ogni utente sceglie dove ricevere gli avvisi delle proprie sonde in
**Impostazioni → Notifiche** (la propria email, il proprio chat ID Telegram, il proprio topic
ntfy). Anche ogni **amministratore** può indicare la **propria chat Telegram**, in
*Amministrazione → Il tuo account → Telegram*: gli avvisi dell'amministrazione gli arriveranno lì
oltre che per email. I codici di verifica dell'accesso restano invece sempre e solo via email.
Dopo una modifica al `.env`: `sudo systemctl restart netmon-server`.

**Cosa arriva dove.** Sotto i canali c'è una tabella *tipo di avviso × canale*: per ogni tipo
(*Dispositivi*, *Sonde online/offline*, *Rete ospiti*, *Rete mesh*, *Manutenzione e aggiornamenti*, *SpeedTest*, *Controllo di sicurezza*) spunti su quali
canali riceverlo, per esempio i dispositivi solo per email e le manutenzioni su Telegram e ntfy. Gli
amministratori hanno la stessa tabella in *Il tuo account → Notifiche*, con *Allarmi ed errori*,
*Aggiornamenti e manutenzione* e *Account e impostazioni* su email e Telegram. Un tipo mai toccato
arriva su tutti i canali; gli eventi restano comunque nella pagina e nel registro.

**Interruttori dei canali.** Ogni canale (Email, Telegram, ntfy) ha il suo interruttore: spento,
su quel canale non parte nessun avviso, di nessun tipo. Chat ID, topic ntfy e spunte della tabella
restano salvati e tornano validi quando lo riaccendi.

| Canale | Alert normali | Alert critici |
|---|---|---|
| Email | sì | sì, con priorità alta |
| Telegram | sì, silenziosi | sì, con suono |
| ntfy | priorità normale | priorità massima |

Le righe `MAIL_TO`, `TELEGRAM_CHAT_ID` e `NTFY_URL` delle versioni precedenti non servono più.
Al primo avvio dopo l'aggiornamento il chat ID Telegram e il topic ntfy che c'erano nel `.env`
vengono copiati una volta sola nel primo account registrato, così gli avvisi non si
interrompono; da lì in poi si gestiscono dalla pagina.

### Email con Gmail (account che spedisce)

Le email partono in testo e in HTML, con il mittente "netmon" (si cambia nel pannello o con
`SMTP_FROM_NAME` nel `.env`) e le intestazioni complete che aiutano a non finire nello spam. Con
un account Gmail nuovo i primi messaggi possono comunque finire nella posta indesiderata:
segnalali come "non spam" e aggiungi il mittente ai contatti.

1. Attiva la verifica in due passaggi sull'account Google (myaccount.google.com/security).
2. Crea una **password per le app** (myaccount.google.com/apppasswords): 16 lettere, da scrivere
   **senza spazi**. Se cambi la password dell'account Google, quelle per le app vengono revocate.
3. Nel pannello, **Server › Invio email**: server `smtp.gmail.com`, porta 587, utente e
   mittente l'indirizzo Gmail, la password per le app, la tua password di amministratore → **Salva**.
   Non serve toccare il `.env`: la configurazione sta nel database degli account
   (`auth.db`, leggibile solo dal servizio).
4. **Invia email di prova** (stessa pagina): dice *inviata* oppure il motivo, per esempio *utente o password non accettati (535 …)* = password
   sbagliata o non per le app; *server di posta non raggiungibile* = server o porta sbagliati, o porta
   bloccata dal fornitore della VM (prova la 465).

Finché nel pannello non scegli niente valgono le righe del `.env` di ogni macchina (*Usa il .env*
torna a quelle):

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tuoindirizzo@gmail.com
SMTP_PASSWORD=la-password-per-le-app
SMTP_FROM=tuoindirizzo@gmail.com
```

Prova dal terminale di una macchina (con la configurazione in uso, pannello o `.env`; sostituisci
l'indirizzo):

```bash
sudo -u netmon bash -c 'set -a; . /opt/netmon/.env; set +a; cd /opt/netmon; /opt/netmon/venv/bin/python -c "import app; print(app.smtp_test_local(\"tua@email.it\"))"' 2>/dev/null | tail -1
```

`(True, '')` = inviata; altrimenti `(False, 'motivo')`.

Gli utenti ricevono gli avvisi all'email del proprio account (possono disattivarla in
*Impostazioni → Notifiche*).

### Telegram (consigliato: bot del server)

1. Su Telegram scrivi a **@BotFather** → `/newbot` → scegli nome e username (deve finire con `bot`). Copia il token.
2. Nel `.env`:

```
TELEGRAM_BOT_TOKEN=7412345678:AAH...
```

3. **Cosa fa ogni utente** (in *Impostazioni → Notifiche* il tasto **Istruzioni configurazione
   Telegram** apre una finestra con questi passi):
   1. apre il bot del server e preme **Avvia**: la pagina mostra il nome del bot (per esempio
      `@MonitoreEnv_bot`) con il collegamento che apre la chat. Il nome lo legge il server da
      Telegram con il token del `.env`, quindi non va scritto da nessuna parte;
   2. scrive a **@userinfobot**, che risponde con il suo **chat ID** (un numero come `123456789`);
   3. incolla il numero in *Telegram: il tuo chat ID* e preme **Invia un messaggio di prova**: deve
      arrivargli un messaggio dal bot (se il chat ID è sbagliato o non ha premuto *Avvia*, la pagina
      lo dice). Se il messaggio arriva, il chat ID viene **salvato subito**: da lì partono anche gli
      avvisi veri;
   4. nella tabella *Cosa ricevere su ogni canale* lascia spuntata la colonna Telegram per gli avvisi
      che vuole lì; se cambia qualcosa preme **Salva** in fondo alla pagina.

   Gli **amministratori** fanno lo stesso in *Amministrazione → Il tuo account → Telegram*, che
   mostra anche il nome del bot e ha lo stesso *Invia un messaggio di prova* (anche qui una prova
   riuscita salva il chat ID). Il chat ID si può
   ottenere anche aprendo `https://api.telegram.org/bot<TOKEN>/getUpdates` dopo aver scritto al bot
   (il numero in `"chat":{"id":...`). L'installazione guidata mostra il tuo nel riepilogo finale.

   In entrambe le pagine il chat ID è **coperto**: con *Mostra* lo si legge quando serve, senza
   lasciarlo in chiaro sullo schermo per tutto il tempo.

### ntfy (alternativa, nessuna configurazione sul server)

Ogni utente installa l'app ntfy e si iscrive a un topic dal nome difficile da indovinare (chi lo
conosce legge gli avvisi). In *Impostazioni → Notifiche* trova già un indirizzo creato per lui, del
tipo `https://ntfy.sh/netmon-k3f9q2x7m1c8w4za`: 16 lettere e cifre calcolate dalla sua email con una
chiave che resta sul server, quindi sempre le stesse per lui ma non ricavabili dalla sola email.
ntfy resta spento finché l'utente non lo accende; può anche scrivere un altro indirizzo o crearne
uno nuovo a caso. Con un server ntfy tuo, indica la sua base in `NTFY_BASE` nel `.env`
(es. `NTFY_BASE=https://ntfy.example.com`).

---

## 5. Parte C — Sonda

> Tutti i comandi di questa parte vanno lanciati **sulla sonda**. Gli esempi usano un Raspberry Pi
> con Raspberry Pi OS; su Debian o Ubuntu i comandi sono gli stessi.

### C1. Preparazione

Assegna alla sonda un **IP fisso** (prenotazione DHCP sul router). Se puoi,
alimenta sonda e router da un piccolo UPS.

Copia la cartella `probe` sulla sonda. Da PowerShell sul PC, nella cartella dove hai estratto lo zip:

```powershell
scp -r .\netmon\probe tuoutente@IP_DELLA_SONDA:~
```

### Installazione guidata

Prima, nella pagina di stato del server: **Impostazioni → Sonde → Aggiungi una sonda**, scegli
il nome e copia il **token** (comincia con `sonda_`). È l'unica credenziale che una sonda accetta:
la chiave del server **non vale per le sonde**. Il token vale solo per questa sonda e, se lo perdi,
ne generi uno nuovo senza toccare le altre. Poi, sulla sonda:

```bash
sudo bash ~/probe/installa-sonda.sh
```

Lo script verifica sistema e rete (e avvisa se la sonda è in Wi-Fi), installa i pacchetti e poi
chiede:

- **dominio del server**, controllando che risponda;
- **token**, controllando che il server lo accetti;
- **nome della sonda** (proposto quello del computer);
- **dispositivi**: propone il router trovato in automatico, poi nome e IP degli altri, con un
  ping di prova per ciascuno;
- **FRITZ!Box**: se ne trova uno lo propone, chiede utente e password e prova il collegamento;
- **password della pagina locale**, obbligatoria (se non la scrivi ne genera una).

Scarica anche la **chiave degli aggiornamenti** del server e ne mostra l'impronta: deve coincidere
con quella nel riepilogo della VM.

Poi scrive la configurazione con i permessi giusti, avvia i servizi e aspetta il **primo invio
al server** (`OK 4/4`). Alla fine mostra token, indirizzo e password della pagina locale, salvati
anche in `/root/netmon-sonda-riepilogo.txt`. Se incolli qualcosa che non è il token di una sonda
(per esempio la chiave del server), te lo dice subito e lo richiede.

Rilanciato su una sonda già installata permette di **aggiornare i file** (la configurazione
resta) o di **riconfigurarla**, ripartendo dai valori attuali. Con `--aggiorna` aggiorna senza
domande; con `--disinstalla` toglie netmon dalla sonda (vedi *Disinstallare la sonda*).

### C2. Cosa installa lo script sulla sonda

| Cosa | Dove | Di chi |
|---|---|---|
| Programmi e ambiente Python (con `fritzconnection`) | `/opt/netprobe/` | root |
| Configurazione (dispositivi, server, token, FRITZ!Box) | `/etc/netprobe/config.yaml` (permessi 640) | utente `netprobe` |
| Password della pagina locale | `/etc/netprobe/web.env` (permessi 600) | utente `netprobe` |
| Misure non ancora inviate, cache del FRITZ!Box | `/var/lib/netprobe/` | utente `netprobe` |
| Stato e registri di aggiornamenti, Wi-Fi | `/var/lib/netprobe-sys/` | root (leggibili dalla sonda) |
| Servizi | `netmon-probe.service` (memoria massima 96 MB) e `netmon-config.socket` / `.service` (64 MB) in `/etc/systemd/system/` | root |
| Script di sistema | `/usr/local/sbin/netprobe-upgrade`, `-selfupdate`, `-zipupdate`, `-wifi`, `-uninstall` | root |
| Permessi della sonda (solo se c'è `sudo`) | `/etc/sudoers.d/netprobe` | root |
| Chiave per verificare gli aggiornamenti | `/usr/local/share/netmon/update-key.pub` | root |
| Verificatore dei pacchetti | `/usr/local/lib/netmon/pkgcheck.py` | root |
| Riepilogo dell'installazione | `/root/netmon-sonda-riepilogo.txt` | root |

**Senza `sudo`.** Il pacchetto `sudo` è **facoltativo**. Se sulla sonda non c'è (installazioni minime,
container), l'installazione lo segnala, salta i permessi e si completa: la sonda controlla i
dispositivi, legge il FRITZ!Box, usa la pagina locale e invia i dati come sempre. Non sono
disponibili, e rispondono *Permesso mancante*: **Aggiorna netmon** dal server, **Aggiorna sistema** e
**Riavvia sonda** (dal server e dalla pagina locale), le **reti Wi-Fi** da *Stato sonda* e
**Disinstalla sonda** dalla pagina locale (da terminale `installa-sonda.sh --disinstalla` funziona lo
stesso). *Stato sonda* lo mostra: *Aggiornamenti dal server: non disponibili*. Gli aggiornamenti di
netmon si fanno allora a mano, copiando la nuova cartella `probe` e lanciando da root
`installa-sonda.sh --aggiorna`. Per attivare tutto: `apt-get install -y sudo` e di nuovo
`installa-sonda.sh --aggiorna`.

Sonda e pagina locale girano come utente `netprobe`, senza privilegi. Alla sonda è concesso solo il
permesso `CAP_NET_RAW` (per i ping diretti) e il gruppo `video` (per leggere temperatura e
alimentazione del Raspberry Pi con `vcgencmd`). La pagina locale parte solo quando la apri
(`netmon-config.socket`) e si chiude dopo 10 minuti di inattività.

### C3. FRITZ!Box (facoltativo)

Sul FRITZ!Box: abilita l'**accesso per le applicazioni** (TR-064; nell'interfaccia del FRITZ!Box sta
in *Rete domestica → Rete → Impostazioni di rete*) e crea un **utente dedicato** (*Sistema → Utenti
FRITZ!Box*), per esempio `netmon`, con il permesso *Impostazioni FRITZ!Box* (serve anche per leggere
la rete ospiti). Poi, nella pagina locale della sonda, sezione **FRITZ!Box**: spunta *Collega il FRITZ!Box*, inserisci indirizzo,
utente e password, premi *Prova collegamento* e salva. Nella pagina di stato del server
compare il riquadro FRITZ!Box con stato della linea, IP pubblico, banda istantanea,
velocità della linea e numero di client collegati a ogni rete Wi-Fi, alla rete ospiti e
via cavo. Le credenziali restano sulla sonda.
Quali voci mostrare, o se nascondere del tutto il riquadro, si sceglie da **Impostazioni** →
scheda *Visualizzazione* → *Riquadro FRITZ!Box*.

**Altri FRITZ!Box.** Nella stessa sezione della pagina locale, sotto *Altri FRITZ!Box*, puoi
aggiungerne altri (fino a 4 con il limite predefinito: lo decide l'amministratore, vedi *Limiti per
utente*), ognuno con nome, indirizzo, utente, password e un ruolo:

- **Solo Wi-Fi**: un ripetitore (FRITZ!Repeater) o un secondo FRITZ!Box nella stessa casa. Il
  riquadro mostra i client collegati alle sue reti Wi-Fi e alla sua rete ospiti, il modello e da
  quanto è acceso. Internet, traffico e dispositivi li conosce già il FRITZ!Box principale.
- **Principale**: un FRITZ!Box in un altro posto che la sonda riesce a raggiungere, per esempio
  con la VPN tra i due FRITZ!Box. Il riquadro è completo come quello del primo, con il suo
  storico del traffico separato.

Ogni FRITZ!Box ha il suo riquadro nella pagina *Stato rete › FRITZ!Box*, riordinabile come gli
altri. Gli avvisi sui nuovi ospiti restano legati al primo FRITZ!Box. Per sicurezza i FRITZ!Box si
aggiungono, si modificano e si tolgono **solo dalla pagina locale della sonda**: la password resta
sulla sonda e non passa dal server. La pagina del server lo ricorda sotto i riquadri, con il
collegamento alla pagina locale di ogni sonda (che si apre solo dalla stessa rete della sonda).

**Metriche del FRITZ!Box.** Con il FRITZ!Box collegato, la sonda legge il traffico
ogni pochi secondi (30 di default; si cambia da **Impostazioni** → *Controlli* → *Traffico: un campione ogni*, 0 per
disattivarlo) e invia i campioni al server tutti insieme con il report normale: il numero di
richieste verso la VM non cambia. Le velocità sono calcolate dai contatori di byte del router,
quindi sono medie reali sull'intervallo e includono anche i picchi brevi. Se il server non è
raggiungibile, i campioni finiscono nel buffer con le altre misure. Nel riquadro FRITZ!Box (sul telefono i pulsanti mostrano
solo l'icona: il nome compare tenendoci il dito o passandoci sopra) il
pulsante **Traffico** (frecce giù e su) apre lo storico del **traffico Internet** (download e upload, medie, picchi e byte
scambiati) e il pulsante **Altri grafici** (grafico a più linee) lo storico delle **metriche** del FRITZ: scegli la *Metrica* dal menu e
vedi l'andamento nel tempo su 1 ora, 6 ore, 24 ore, 7 o 30 giorni. Le metriche disponibili sono
velocità di download e upload, la linea (picchi massimi), i dispositivi via cavo, gli ospiti
Wi-Fi e i clienti di ciascuna rete Wi-Fi (per ogni rete un grafico con media, minimo e massimo
nel periodo). Lo storico delle metriche FRITZ è campionato a ogni controllo della sonda.

**Rete mesh.** Con un FRITZ!Box principale che gestisce la rete mesh (FRITZ!Repeater, altri
FRITZ!Box come repeater), la sonda legge ogni 5 minuti la **mappa mesh** del FRITZ!Box: per i
repeater basta il FRITZ!Box principale, non serve collegarli alla sonda. Nel riquadro FRITZ!Box
compare la casella **Mesh** (nodi e dispositivi) e, in fondo, la sezione **Rete mesh**, chiusa
finché non la apri. Chiusa mostra una riga di riepilogo, con il pallino giallo e il motivo se
qualcosa non va (*repeater lento*, *N dispositivi con segnale debole*). Aperta mostra un nodo per riga: il
collegamento di ogni repeater verso il nodo da cui dipende (cavo, oppure Wi-Fi con la banda, la
velocità attuale su quella possibile e la percentuale) e i dispositivi agganciati a quel nodo,
con banda e, passandoci sopra, velocità e segnale. In giallo i collegamenti Wi-Fi sotto un quarto
della velocità possibile e i dispositivi con segnale debole (sotto −75 dBm o, se il FRITZ non
misura il segnale, collegati a meno di 30 Mbit/s): mostrano comunque la loro banda, e accanto al nome
del nodo c'è, in giallo, quanti sono (*N con segnale debole*). In **Altri grafici**, la *Metrica* **Collegamento
mesh · nome** mostra nel tempo la velocità del collegamento di ogni repeater. Se un repeater è
collegato alla sonda anche come FRITZ!Box *Solo Wi-Fi* (stesso nome, oppure unico repeater di
quel modello), il suo riquadro mostra anche **Collegamento alla mesh**, i dispositivi **Via cavo**
attaccati al repeater (dalla mappa mesh) e la **banda in uso**, media dell'ultimo minuto letta dai
contatori della porta LAN del repeater. Se il repeater è collegato alla mesh via cavo, la porta LAN
porta tutto il suo traffico: compaiono *Download ora* e *Upload ora*, e il riquadro ha il pulsante **Traffico**
con lo storico del **traffico del repeater** (download e upload insieme, medie, picchi e dati scambiati,
un campione al minuto), come quello del FRITZ!Box principale; le stesse velocità sono anche in
*Altri grafici*. Se è collegato via Wi-Fi, la porta LAN porta solo il traffico dei dispositivi via cavo:
compaiono *Via cavo · download* e *Via cavo · upload*.

**Fibra.** Sui FRITZ!Box in fibra (per esempio il 5590 Fiber) la sezione **Fibra** del riquadro
mostra lo stato della linea in fibra letto dal FRITZ!Box ogni 5 minuti: stato, potenza ottica
ricevuta e trasmessa, tipo di fibra e gli altri valori che il FRITZ!OS mette a disposizione. I
nomi dei valori cambiano con modello e versione del FRITZ!OS: quelli riconosciuti sono tradotti,
gli altri compaiono con il nome del FRITZ; sotto ogni valore c'è sempre il nome originale. Il
numero di serie non viene mostrato. Se la linea in fibra non è in uso (Internet arriva da un'altra
porta e il FRITZ risponde con tutti i valori a 0 o *Unknown*), la sezione non compare.

**Clienti Wi-Fi di casa.** Con più FRITZ!Box collegati alla stessa sonda (per esempio un
FRITZ!Repeater aggiunto come *Solo Wi-Fi*), il riquadro del primo FRITZ!Box ha il pulsante **Client Wi-Fi** (onde Wi-Fi e dispositivi):
apre il grafico **cumulativo** dei clienti Wi-Fi, con uno strato per ogni FRITZ!Box e uno per gli
ospiti, impilati: l'altezza totale è il numero di dispositivi Wi-Fi in casa. Sopra, media,
massimo e ultimo valore del totale; toccando le voci della legenda si nascondono gli strati e il
totale si ricalcola. I clienti di un FRITZ si contano sulle sue reti (2,4, 5 e 6 GHz insieme), quindi
nessun dispositivo è contato due volte; un repeater non collegato alla sonda non compare.

**Dispositivi in rete.** Sotto i riquadri, nella pagina *Stato rete › FRITZ!Box*, la sezione
**Dispositivi in rete** elenca i dispositivi che il FRITZ!Box conosce: nome, IP, collegamento (cavo
con porta LAN, oppure Wi-Fi con banda e repeater a cui è agganciato), segnale in dBm con le tacche
e velocità del collegamento. È la velocità negoziata del collegamento, non il traffico: il
FRITZ!Box non dà il traffico del singolo dispositivo. L'elenco si aggiorna ogni 5 minuti, insieme
alla mappa mesh. I filtri in alto mostrano Wi-Fi, cavo, segnale debole (sotto −75 dBm) e i
dispositivi **non monitorati**, cioè non ancora tra i dispositivi pingati dalla sonda; la casella
in fondo aggiunge quelli non collegati, con l'ultima volta che il server li ha visti. Il pulsante
**+ Monitora** apre *Dispositivi* della sonda con una riga già compilata (nome e IP attuale): basta
salvare. Come gli altri riquadri, la sezione si chiude con la freccia accanto al titolo (chiusa mostra
solo quanti dispositivi sono collegati). Gli indirizzi MAC restano sulla sonda e non vengono inviati al server.

Mesh, fibra e dispositivi in rete si nascondono, come le altre voci, da **Impostazioni → Visualizzazione → Riquadro
FRITZ!Box** (*Rete mesh*, *Stato della fibra*, *Dispositivi in rete*). Per leggerli l'utente del FRITZ!Box deve avere il
permesso *Impostazioni FRITZ!Box*.

**Più sonde nella stessa rete.** In **Impostazioni → Visualizzazione** puoi attivare
*Nome sonda* (tra le colonne dei dispositivi) e *Nome sonda* (nel
riquadro FRITZ!Box): accanto a ogni dispositivo e nella testata di ogni riquadro FRITZ!Box compare
un'etichetta con il nome della sonda di provenienza. Colonne e contenuto del riquadro FRITZ!Box
restano salvati nel tuo account: ogni dispositivo da cui accedi mostra la stessa pagina.

Ogni sonda ha la sua sezione con i propri ping e il proprio riquadro FRITZ!Box. Per cambiarne
l'ordine premi **⇅ Ordine** in alto (in *Stato rete › Monitor dispositivi* o *› FRITZ!Box*) e sposta le
sezioni con ▲▼ o trascinandole, poi **Salva ordine**. In *› FRITZ!Box* le sezioni si riducono alle sole
intestazioni (i riquadri FRITZ!Box mostrano sempre la sonda di provenienza). In *› Monitor dispositivi* restano
aperte e ogni dispositivo ha le sue ▲▼: nello stesso passaggio riordini anche i dispositivi dentro ogni sonda,
e **Salva ordine** salva tutto insieme. L'ordine è salvato nel tuo account sul server, quindi è lo stesso su
PC e telefono; le sonde aggiunte dopo compaiono in fondo.

**Periodo personalizzato.** In ogni grafico, oltre a 1 ora…30 giorni, *Personalizzato* permette
di scegliere data e ora di inizio e fine (fino a 400 giorni). La granularità dei punti si adatta
alla durata, per avere sempre circa 100-150 punti.

**Temperatura, CPU, memoria e disco della sonda.** Nella scheda *Stato sonda*, accanto al nome di ogni sonda, ci
sono i pulsanti dei suoi storici (sul telefono solo le icone), con gli stessi periodi degli altri grafici:

- **Temperatura** (un termometro): minima, media e massima, e il carico della CPU nel punto selezionato. La scala
  si adatta ai valori. Compare solo se la sonda misura la temperatura (per esempio un Raspberry Pi).
- **CPU** (un processore): il carico medio di un minuto diviso per i processori, in percentuale. Oltre il 100% ci
  sono processi in coda: la sonda fa fatica.
- **Memoria** (un banco di memoria): quella usata dai programmi, in percentuale, senza la cache che il sistema
  libera quando serve.
- **Disco** (un disco): lo spazio occupato sulla scheda SD o sul disco della sonda, in percentuale.

CPU, memoria e disco hanno la scala fissa da 0 a 100% e si registrano dalla versione 1.1 di ottobre 2026 in poi
(anche per le sonde senza sensore di temperatura); prima di allora il grafico è vuoto.

**Voci dei grafici.** Sotto ogni grafico le voci della legenda sono pulsanti: toccandole
mostri o nascondi la relativa linea, e la scala verticale si adatta alle sole voci visibili.
Traffico: Download, Upload, Media download, Media upload (linee tratteggiate con la media del
periodo). Ping: Media, Minimo–massimo, Pacchetti persi, Media del periodo (spenta di default).
Nel grafico delle metriche FRITZ!Box si sceglie invece una sola metrica alla volta dal menu
*Metrica*, e la scala si adatta a quella metrica.
La scelta resta salvata nel browser.

**Leggere un punto dei grafici.** In tutti i grafici (ping e traffico) clicca o tocca un
punto, oppure trascina, per vedere sotto il grafico i valori di quell'intervallo. Con il
grafico selezionato puoi spostarti tra i punti con le frecce ← →.

**Avvisi della rete mesh.** Da **Impostazioni** → scheda *Notifiche*, sezione *Rete mesh*, puoi
farti avvisare (spento di default) quando un repeater **esce dalla mesh** (non compare nella mappa
per circa 10 minuti: spento, staccato o fuori portata; avviso critico) e quando torna, e quando il
suo **collegamento Wi-Fi resta lento** (sotto un quarto della velocità possibile per circa 15
minuti) e quando torna normale (sopra il 35%). Il tipo di avviso *Rete mesh* ha i suoi canali in
*Impostazioni → Notifiche*, come gli altri.

**Notifica dei nuovi ospiti Wi-Fi.** Da **Impostazioni** → scheda *Notifiche* puoi farti avvisare quando un
dispositivo si collega alla rete ospiti del FRITZ!Box. L'avviso arriva sugli stessi canali
degli altri alert, con priorità normale, e riporta nome del dispositivo, IP e ora di
collegamento (nel fuso orario scelto nel tuo account; se non ne hai scelto uno, quello del server, `TIMEZONE`
nel `.env`, di solito l'ora italiana).
L'ora è quella in cui la sonda lo rileva, quindi al massimo un intervallo di controllo dopo
il collegamento effettivo. Per leggere la rete ospiti l'utente del FRITZ!Box deve avere il
permesso *Impostazioni FRITZ!Box*.
Un dispositivo conta come nuovo se non si vedeva da almeno il numero di minuti indicato
(30 di default): così un telefono che si scollega e ricollega per risparmio energetico non
genera avvisi ripetuti. Chi era già collegato quando attivi la funzione non viene segnalato.

### C4. Pagina locale della sonda

Da un PC o telefono collegato alla rete di casa: `http://IP_DELLA_SONDA:8080`. La pagina accetta
solo connessioni dalla rete locale e si apre con l'**indirizzo IP** della sonda (o con un nome
locale come `raspberrypi.local` o `sonda.fritz.box`); altri nomi vengono rifiutati per sicurezza.
Per un nome diverso aggiungi in `/etc/netprobe/web.env` la riga `WEB_ALLOWED_HOSTS=nome1,nome2`
e poi `sudo systemctl stop netmon-config` (riparte da sola alla visita successiva).

La lingua della pagina (italiano, inglese, tedesco o francese) si sceglie durante l'installazione e si
cambia con il selettore in alto a destra; resta in `config.yaml` (`language`).

Come la pagina di stato, ha un **menu a sinistra** (pulsante **☰**) con le sezioni, e ne mostra una
alla volta; in alto il percorso, per esempio *Sonda Casa › Dispositivi*. Ogni sezione ha il suo
indirizzo (`#server`, `#dispositivi`…), quindi si può salvare nei segnalibri. Su telefono il menu
parte chiuso e si richiude da solo dopo la scelta.

- **Nome della sonda**: il nome mostrato nella pagina di stato. Si cambia anche da lì
  (*Impostazioni → Sonde → Rinomina*): i due lati restano sincronizzati da soli.
- **Server**: indirizzo del server, **token** della sonda, ogni quanto chiedere al server se ci sono
  configurazioni nuove (*Controllo configurazioni dal server*, 60 secondi; 0 = solo all'invio dei
  risultati) e *Prova collegamento*. Indirizzo e token restano solo sulla sonda: il server non può
  cambiarli.
- **FRITZ!Box**: il FRITZ!Box principale e gli *Altri FRITZ!Box* (vedi C3), con *Prova collegamento*.
- **Dispositivi**: aggiungi, rinomina, rimuovi e prova (*Prova*, *Prova tutti*) i dispositivi da
  pingare. Sotto, i **limiti del tuo account** (dispositivi e FRITZ!Box aggiuntivi) e cosa succede se
  li superi.
- **Sistema**: versioni installata e sul server, esito e registro dell'ultimo aggiornamento comandato
  dal server, e **Riavvia la sonda**. Gli aggiornamenti si comandano solo dalla pagina di stato o da
  `/admin` (vedi *Riavvio e aggiornamento*).
- **Password di accesso alla sonda**: cambia la password della pagina (minimo 8 caratteri, senza
  spazi, virgolette, `\` e `$`, che li interpreterebbe systemd). Vale subito, senza riavviare niente:
  al prossimo aggiornamento della pagina il browser chiede quella nuova.
- **Backup e ripristino**: vedi *Backup e ripristino*.
- **Disinstalla sonda**: toglie netmon dalla sonda (vedi *Disinstallare la sonda*).

Le modifiche di Nome, Server, FRITZ!Box e Dispositivi si salvano tutte insieme con **Salva
modifiche** nella barra in basso; la sonda usa la nuova configurazione dal controllo successivo,
senza riavvii. Frequenza dei controlli, soglie e notifiche si impostano invece dalla pagina di stato
(*Impostazioni*).

**Password.** Il browser chiede utente e password: l'utente può essere qualsiasi, conta solo la
password. Dopo 10 password sbagliate dallo stesso indirizzo la pagina si blocca per qualche minuto.
Senza password la pagina non si apre e spiega come impostarla: `sudo bash ~/probe/installa-sonda.sh
--aggiorna` ne crea una e la mostra. Se l'hai dimenticata: `sudo cat /etc/netprobe/web.env` sulla
sonda. Token e password del FRITZ!Box compaiono come `••••••••`: il pulsante **Mostra** li rivela.

---

## 6. Parte D — Verifiche finali

1. **Pagina di stato**: `https://netmonhome.net`. Sulla VM appena installata compare
   *Primo accesso*: inserisci la **chiave del server** (`API_TOKEN`, è nel riepilogo) e crea il tuo
   account con email e password (vedi *Registrazione*). Gli altri utenti si registrano con un
   **codice di accesso** generato in `/admin`. Salva la pagina tra i preferiti del telefono.
2. **Alert normale**: aggiungi dalla pagina locale un dispositivo inesistente (es. `test: 192.168.1.254`). Dopo circa 3 minuti arriva l'avviso. Poi rimuovilo.
3. **Alert critico**: sulla sonda `sudo systemctl stop netmon-probe`. Dopo 1,5 intervalli la sonda diventa gialla, dopo 3 intervalli rossa, con tutti i dispositivi gialli, e arriva l'alert critico. Poi `sudo systemctl start netmon-probe` e arriva il ripristino.
4. **Amministrazione**: `https://netmonhome.net/admin` con l'email dell'amministratore e la
   password provvisoria del riepilogo: scegli la nuova password e attiva l'app di autenticazione.
5. **Controllo del server**: registra `https://netmonhome.net/health` su [UptimeRobot](https://uptimerobot.com) (gratuito, controllo ogni 5 minuti). Così vieni avvisato anche se si ferma la VM.

---

## 7. Uso quotidiano

**Pagina di stato (server)** — si aggiorna da sola ogni 15 secondi.

L'email dell'account e **Esci** (esce da questo dispositivo) stanno nel **menu a sinistra**, sotto
*Impostazioni*; nel pannello di amministrazione, sotto *Server*, con il nome dell'amministratore. Per uscire da
tutti i dispositivi: *Impostazioni → Account e backup → Esci*.

Le sezioni (*Dashboard*, *Stato rete*, *Stato sonda*, *Impostazioni*; nel pannello di
amministrazione *Amministrazione*, *Sonde*, *Server*; nella pagina locale della sonda le sue sezioni)
stanno in un **menu a sinistra**, che si apre e si chiude con il pulsante **☰** in alto a
sinistra. In alto resta scritta solo la sezione in cui ti trovi. Su schermo largo il menu è aperto e
affianca il contenuto; su telefono parte chiuso, si apre sopra la pagina e si richiude da solo appena
scegli una sezione (o toccando fuori, o con Esc). La scelta di tenerlo aperto o chiuso resta
ricordata in quel browser.

Le schede con sezioni (*Stato rete*; nel pannello *Amministrazione*, *Sonde*, *Server*) sono **a tendina**: toccando
il nome si aprono o si chiudono le sue sezioni (la freccia accanto lo indica), senza cambiare pagina; per aprire una
pagina si tocca la sezione. È aperta la scheda della pagina in cui sei; quelle aperte o chiuse a mano restano come
le hai lasciate in quel browser.

Nella pagina di stato e nel pannello di amministrazione la **barra blu in alto resta sempre in vista**
mentre scorri, con ☰ e il titolo della sezione. Su telefono, quando scendi lungo una pagina
compare in basso a destra il tasto tondo **⌃ Torna su**, che riporta all'inizio.

Nel **pannello di amministrazione** il menu è ad albero: sotto ogni scheda (*Amministrazione*, *Sonde*,
*Server*) ci sono, rientrate, le sue sezioni (per esempio *Server* → *Stato VM*, *Manutenzione della VM*,
*Aggiornamento Netmon*, *Registro amministrativo*; in *Sonde* → *Conservazione dei dati*). La pagina
mostra **una sezione alla volta**, sempre aperta; in alto c'è il percorso (*Server › Manutenzione della VM*).
Toccando il nome di una scheda si torna all'ultima sua sezione che avevi aperto; aprendo `/admin` senza nulla in fondo si parte invece sempre da *Utenti*. L'indirizzo porta la
sezione (per esempio `#vm/registro-amministrativo`), quindi si può salvare nei segnalibri.

Anche nella pagina di stato il menu è ad albero: sotto *Stato rete* ci sono, rientrate, **FRITZ!Box**,
**Monitor dispositivi**, **Eventi** e **Mappa**, e la pagina ne mostra una alla volta (in alto il percorso, per esempio
*Stato rete › Monitor dispositivi*). Il pulsante **⇅ Ordine** in alto cambia l'ordine delle sonde e dei
dispositivi dentro ognuna (in *Monitor dispositivi*) o dei riquadri FRITZ!Box (in *FRITZ!Box*); l'ordine resta
nel tuo account.

**Prima sonda: procedura guidata.** Un account senza sonde trova sulla **Dashboard** il riquadro *Collega la
tua prima sonda*, in quattro passi: **Nome** (crea la sonda; se ce n'è già una creata e mai collegata propone
di continuare con quella, con un token nuovo; in fondo si può anche collegare una sonda già installata con il
suo token), **Prepara** (cosa serve e il pulsante per scaricare il programma della sonda), **Installa** (il
comando da lanciare sulla sonda, con **dominio del server** e **token** da copiare con un tocco) e
**Collegamento**, che aspetta da solo il primo invio e dice quando la sonda è collegata. Passo e token restano
anche ricaricando la pagina, finché resta aperta quella scheda del browser.

**Mappa.** Sotto *Stato rete* c'è la pagina **Mappa** (fino al 18 ottobre 2026 si chiamava *Grafici*), con l'albero **Server, sonde e dispositivi**: il
tuo server (la VM) con nome e indirizzo, le tue sonde e, collegati a ogni sonda, i suoi dispositivi.
- Ogni sonda ha nome, IP nella rete di casa, quanti dispositivi rispondono e quanto tempo fa è arrivato
  l'ultimo report.
- **Latenza sonda-VM**: a metà del collegamento tra server e sonda (sul telefono, nella riga della sonda)
  c'è quanto ha impiegato l'ultimo report ad arrivare al server ed essere confermato, in millisecondi. La
  misura la sonda e la manda con il report successivo: serve una sonda aggiornata a questa versione (le
  altre non mostrano il valore).
- Ogni dispositivo ha nome, indirizzo e tempo di risposta (*giù* se non risponde).
- Colori: **verde** collegata o risponde; **giallo** in ritardo o in verifica; **rosso tratteggiato**
  offline o non risponde; **grigio tratteggiato** in pausa o con modifiche in attesa.
- Toccando una sonda si chiudono o si aprono i suoi dispositivi; il browser ricorda la scelta.
- Su schermo largo: server a sinistra, sonde al centro, dispositivi a destra. Sul telefono: un albero
  rientrato, dall'alto verso il basso.
- Si muovono solo dei pallini lenti tra il server e le sonde; con *Riduci movimento* attivo nel sistema
  restano fermi. Nomi lunghi: il testo si rimpicciolisce e, se serve, si accorcia con «…» (il nome intero
  compare passandoci sopra).
- Il triangolo accanto al titolo chiude e riapre il riquadro, come le altre sezioni.

**Impostazioni già compilate.** In *Impostazioni → Controlli* e *Notifiche* ogni campo mostra sempre un
valore: quello scelto, oppure quello predefinito (controllo ogni 60 s, 2 pacchetti con attesa di 1 s, 2 ping
contemporanei, traffico ogni 30 s, alert dopo 3 controlli falliti, sonda in ritardo dopo 1,5 intervalli e
irraggiungibile dopo 3, priorità bassa dopo 5 controlli, ospite nuovo dopo 30 minuti). Finché non c'è una
sonda, o finché la sonda non ha mandato il primo report, i valori si vedono ma non si cambiano. In
*Visualizzazione* le colonne *Indirizzo IP* e *Ultimo RTT* sono attive di base.

Aprendo l'indirizzo **senza nulla in fondo** (per esempio `https://netmonhome.net/`) si atterra
**sempre sulla Dashboard**, e aprendo `https://netmonhome.net/admin` **sempre su Amministrazione ›
Utenti**, qualunque sezione fosse aperta l'ultima volta. Ogni sezione ha il suo indirizzo, che la
pagina scrive da sola: `#dashboard`, `#rete/fritzbox`, `#rete/sonde`, `#rete/eventi`, `#sonda` per
*Stato sonda* e `#impostazioni` (nel pannello per esempio `#vm/stato-vm`). Per atterrare altrove basta
aggiungere quell'indirizzo ai segnalibri.

**Dashboard.** La voce **Dashboard** del menu (la prima) mostra lo stato d'insieme di tutti i
dispositivi di tutte le sonde: in alto i conteggi (totale, rispondono, in verifica, non rispondono,
in pausa) e sotto un riquadro per ogni dispositivo con la spia di stato, l'ultimo ping e il grafico
dell'andamento del ping nelle ultime 24 ore (linea verde, gialla o rossa secondo lo stato attuale;
i tratti in cui il dispositivo non rispondeva restano vuoti). Toccando un riquadro si apre lo
storico completo dei ping di quel dispositivo, come dal pulsante con il battito accanto al suo nome.

**Gruppi per sonda.** Con più sonde i dispositivi sono divisi in un gruppo per sonda: in testa al
gruppo il nome della sonda con il suo **colore** (quadratino e bordo in alto), la spia della sonda
e un riassunto (*N dispositivi · tutti rispondono*, oppure quanti non rispondono o sono in verifica).
Così due dispositivi con lo stesso nome su sonde diverse non si confondono. La freccia ▼ / ▶ chiude
e riapre il gruppo: chiuso resta solo la testata, con «chiuso» nel riassunto; la scelta è salvata
nel tuo account. Il colore lo assegna NetMon in base alla posizione della sonda; si cambia in
*Impostazioni → Sonde → Colore* (otto colori, oppure *Automatico*). Con una sola sonda non c'è testata.

Anche i **conteggi** in alto si possono toccare: *Rispondono*, *In verifica*, *Non rispondono* o
*In pausa* aprono **Stato rete › Monitor dispositivi** con i soli dispositivi in quello stato
(restano visibili solo le sonde che ne hanno); *Totale dispositivi* apre la stessa pagina senza filtro.

Il filtro si sceglie anche direttamente in **Monitor dispositivi**: in cima alla pagina la barra
**Mostra:** ha un pulsante per stato (*Tutti*, *Rispondono*, *In verifica*, *Non rispondono*,
*In pausa*), ognuno con quanti dispositivi ci sono in quel momento. Il pulsante del filtro attivo è
evidenziato; toccandolo di nuovo, o toccando *Tutti*, il filtro si toglie. Il filtro resta anche
quando la pagina si aggiorna da sola.

Sopra i gruppi ci sono, all'inizio, due riquadri affiancati (sul telefono uno sotto l'altro); posizione e
dimensione si cambiano con *Ordine*:

- **Uso della linea**, se a una sonda è collegato un **FRITZ!Box**: in alto i numeri *Adesso* (velocità
  attuale, con la media delle 24 ore) e *Linea (FRITZ!Box)* (capacità della linea, con il picco delle 24 ore),
  sotto un grafico delle ultime 24 ore con download (area) e upload (linea arancione) sovrapposti, sulla stessa
  scala, con orari. Con più sonde con FRITZ!Box un
  menu a tendina sceglie quale mostrare. **Storico** apre lo storico del traffico Internet.
- **SpeedTest**, se almeno una sonda sa fare lo speedtest: per ogni sonda l'ultimo risultato (download,
  upload, ping, e quanto si discosta dalla media dei 7 giorni) e un grafico degli ultimi 7 giorni con
  **download** (linea piena) e **upload** (tratteggiato) insieme, un colore per sonda. Il menu a tendina
  mostra *Tutte le sonde* oppure *SpeedTest* di una sola sonda. Le soglie degli avvisi sono le linee rosse
  tratteggiate (*minimo ↓*, *minimo ↑*) e i test sotto soglia sono punti rossi. In fondo l'orario del
  prossimo test periodico, **Storico** e **Avvia ora**, che chiede subito uno speedtest alle sonde mostrate.
  **Storico** apre lo stesso grafico a 24 ore, 7 o 30 giorni: cliccando o toccando un punto (oppure con le
  frecce ◀ ▶ della tastiera) sotto il grafico compaiono i valori di quel test — sonda, download, upload,
  ping, **collegamento** (Wi-Fi o cavo) e se era periodico o avviato a mano. La tabella sotto riporta gli
  stessi dati per gli ultimi test; il collegamento è registrato dai test di questa versione in poi (prima
  «—»). Vedi *SpeedTest*.
- **Disponibilità**: una riga di caselle per ogni dispositivo scelto, una casella ogni mezz'ora (*24 ore*)
  o ogni 4 ore (*7 giorni*); sul telefono e con il riquadro piccolo o medio le caselle sono la metà, più
  larghe; nel piccolo restano solo nomi e caselle (la percentuale è nel suggerimento della riga). **Verde**: tutti i ping risposti; **giallo**: qualche ping perso; **rosso**: nessuna risposta;
  **grigio**: nessun dato (dispositivo in pausa, sonda spenta, dispositivo appena aggiunto). A destra la
  percentuale di ping risposti nel periodo, gialla sotto il 99% e rossa sotto il 95%. Un tocco su una
  casella apre lo storico dei ping di quel dispositivo in quel momento. Il pulsante **Dispositivi** sceglie
  quali seguire (con *Tutti*, *Solo priorità Alta*, *Nessuno*); finché non scegli, sono quelli a
  priorità *Alta*. Scelta e periodo restano nel tuo account.

Il pulsante **Visualizza** sta nella barra in alto a destra della pagina, nello stesso punto del
pulsante *Ordine* di *Stato rete*, e apre il menu per scegliere cosa mostrare e cosa nascondere:
riepilogo, uso della linea, SpeedTest, disponibilità, ogni sonda e ogni singolo dispositivo. La scelta è salvata nel tuo
account: è la stessa su ogni dispositivo da cui accedi. In cima alla pagina compare il riepilogo
di quanto è nascosto. Indirizzo diretto:
`#dashboard`.

Accanto a *Visualizza* c'è **⇅ Ordine**, che apre tutti i gruppi e permette di sistemare la pagina:

- i riquadri dei dispositivi mostrano le frecce ◀ ▶ (e si possono anche trascinare) per spostarli
  dentro il loro gruppo;
- ogni blocco (*Uso della linea*, *SpeedTest*, *Disponibilità* e ogni gruppo di sonda) ha le frecce ▲ ▼ per spostarlo
  prima o dopo gli altri: per esempio *Uso della linea* e *SpeedTest* possono andare sotto i ping;
- *Uso della linea*, *SpeedTest* e ogni dispositivo hanno i pulsanti **P M G** per la dimensione:
  *Piccolo* (largo come il riquadro di un dispositivo; per *Uso della linea* e *SpeedTest* solo i numeri,
  senza grafici), *Medio* (largo il doppio) e *Grande* (tutta la riga per *Uso della linea* e
  *SpeedTest*; per un dispositivo il doppio in larghezza e in altezza, con il grafico più grande).
  I riquadri piccoli riempiono i posti liberi accanto a quelli più grandi.

*Salva ordine* conferma, *Annulla* lascia tutto com'era. Ordine e dimensioni sono salvati nel tuo
account, uguali su ogni dispositivo; i dispositivi nuovi compaiono in fondo al loro gruppo, piccoli.
Sullo schermo stretto le colonne diventano due e sul telefono una: lì ogni riquadro occupa tutta la
larghezza, ma resta l'ordine scelto.

**Pulsanti nella sezione di ogni sonda** (*Stato rete › Monitor dispositivi*), accanto al nome:

- **Modifica ▾**, con due voci:
  - *Aggiungi o modifica dispositivi*: apre la finestra *Dispositivi* per aggiungere, rinominare o
    rimuovere i dispositivi controllati (fino al limite del tuo account, vedi *Limiti per utente*),
    sceglierne la priorità di notifica e, per ogni dispositivo nuovo, chiedere il controllo approfondito delle
    porte (vedi *Controllo di sicurezza dei dispositivi*);
  - *Rimuovi dispositivi*: su ogni dispositivo compare un «－» rosso; premuto (con conferma) toglie quel
    dispositivo. Finché la modalità è attiva, accanto a *Modifica* c'è **Fine rimozione** per chiuderla.

  L'ordine dei dispositivi si cambia con **⇅ Ordine** in alto, insieme a quello delle sezioni.
- **SpeedTest**: vedi *SpeedTest*.

Accanto a ogni dispositivo: il menu della **priorità** (vedi *Priorità delle notifiche*), **⏸**
per metterlo in pausa (vedi *Mettere in pausa*), **🛡** per il controllo di sicurezza (vedi *Controllo di
sicurezza dei dispositivi*) e il **battito** per lo storico dei ping.

**Riquadri a tendina e spiegazioni.**

- **▾** accanto al titolo di ogni riquadro della pagina di stato (sonda, FRITZ!Box, eventi) lo chiude a
  tendina; lo stato resta ricordato nel browser.
- Nel pannello di amministrazione le sezioni non si chiudono a tendina, perché se ne vede una alla volta.

**Impostazioni** (ultima voce del menu, indirizzo `#impostazioni`): una pagina a sé, divisa in
schede, con una riga sottile e una barretta colorata che separano le parti:

- *Visualizzazione*: colonne dei dispositivi (IP, ultimo RTT, nome sonda) e voci del riquadro
  FRITZ!Box;
- *Sonde*: le tue sonde (rinomina, pausa, nuovo token, elimina), *Aggiungi una sonda* e *Collega una
  sonda esistente*;
- *Controlli*: ping, traffico del FRITZ!Box e soglie degli alert, sonda per sonda;
- *Notifiche*: i tuoi canali (email, Telegram, ntfy), la tabella *tipo di avviso × canale*, la
  priorità bassa e la rete ospiti;
- *Account e backup*: backup, password, uscita da questo o da tutti i dispositivi, eliminazione
  dell'account.

Con più sonde, in *Controlli* e *Notifiche* si sceglie la sonda da un menu.

Accanto a ogni dispositivo il pulsante con il **battito** apre lo storico dei ping: minimo, media, massimo
e percentuale di pacchetti persi, con grafico su 1 ora, 6 ore, 24 ore, 7 o 30 giorni. La banda
chiara indica l'intervallo min-max, la linea la media, le barre rosse i controlli senza risposta.
I campioni restano in `events.db` per il periodo scelto dall'amministratore (vedi *Conservazione
dei dati*); per i periodi più lunghi di 30 giorni usa *Personalizzato* con le date.

Le modifiche alla configurazione arrivano alla sonda in due modi: con la risposta al report
successivo e, più in fretta, con l'interrogazione periodica del server (impostazione
*Controllo configurazioni dal server* nella pagina locale, 60 secondi di default, 0 per
disattivarla). Fino all'applicazione, accanto al nome della sonda compare l'etichetta
*modifiche in attesa*.

**Pagina locale della sonda** — gestisce indirizzo del server, token, nome della sonda, FRITZ!Box e
l'elenco dei dispositivi, con il pulsante *Prova* per il ping immediato (vedi C4). Resta utile quando
il server non è raggiungibile.

Entrambe le pagine possono modificare i dispositivi: ogni salvataggio incrementa una revisione
e vince sempre quella più recente. Indirizzo del server e token restano solo locali: il server
non può cambiarli.

**Se il server non è raggiungibile**

La sonda continua a pingare e mette da parte le misure in `/var/lib/netprobe/buffer.jsonl`
(fino a 5000 controlli, circa una settimana a 120 s). Appena il server torna disponibile le
invia tutte, a blocchi di 200 e in ordine cronologico, prima del report corrente, e svuota il
buffer man mano che il server le accetta. Lo storico risulta quindi completo, con i periodi in
cui i dispositivi erano raggiungibili e quelli in cui non lo erano. Le misure recuperate
popolano solo lo storico: non generano alert tardivi.

**Ping contemporanei.** Da Impostazioni → *Controlli* scegli quanti dispositivi pingare
nello stesso momento (2 di default; 1 = uno alla volta, a rotazione). Gli avvii sono comunque
distanziati di 0,2 s e l'ordine di partenza ruota a ogni ciclo. Troppi ping insieme possono
gonfiare l'RTT misurato, soprattutto se la sonda è in Wi-Fi; la finestra mostra quanto
dura un giro di controlli e avvisa se si avvicina all'intervallo.

**Colori**

| | Dispositivo | Sonda |
|---|---|---|
| 🟢 | risponde | report regolari |
| 🟡 | 1–2 ping falliti, sonda offline (stato sconosciuto), oppure *non risponde al ping, porta … aperta* (vedi *Controllo di sicurezza*: nessun avviso) | nessun report da 1,5 intervalli |
| 🔴 | 3 ping falliti consecutivi (parte l'alert) | nessun report da 3 intervalli (alert critico) |

Le soglie si impostano dalla pagina di stato del server, **Impostazioni** → scheda *Controlli*:

- **Ping falliti prima dell'alert**: quanti controlli falliti servono perché un dispositivo diventi rosso.
- **Proporzionali all'intervallo** (impostazione iniziale): giallo dopo 1,5 intervalli, rosso dopo 3.
  Se cambi la frequenza dei controlli, le soglie si adattano da sole: con 60 s sono 90 s e 3 minuti, con 120 s sono 3 e 6 minuti.
- **Fisse in secondi**: valori assoluti, indipendenti dall'intervallo.

**Durante un aggiornamento della sonda** (aggiornamento di netmon o del sistema, anche automatico o programmato, e
riavvio chiesto dal pannello) entrambe le soglie si allungano di **un ciclo**, e di **due** sulle sonde poco potenti
(Raspberry Pi Zero o con un solo processore): la sonda si ferma per installare e ripartire, e non deve risultare in
ritardo né far partire l'avviso «non comunica» per questo. Con 60 s: in ritardo dopo 2 minuti e 30 secondi e
irraggiungibile dopo 4 minuti (3 e 30 secondi e 5 minuti su un Pi Zero). Il margine vale finché la sonda non
conferma la fine dell'operazione, al massimo per 3 ore.

**Subito dopo la ripartenza** i primi cicli sono i più lenti (primo collegamento al FRITZ!Box, mappa mesh,
elenco dei dispositivi), soprattutto su un Pi Zero. Per questo, per **5 minuti** dopo che la sonda ha confermato
l'aggiornamento o il riavvio, e per 5 minuti dopo ogni ripartenza del suo programma (anche aggiornata a mano,
riavviata dalla pagina locale o al ritorno della corrente), non risulta in ritardo e l'avviso «non comunica» non
parte: la pagina scrive *in ripartenza dopo l'aggiornamento* (o *in ripartenza*). Il silenzio si conta sempre
dall'ultimo report, quindi una sonda che non torna davvero viene segnalata al più 5 minuti più tardi del solito.

Il dialogo mostra un'anteprima con i tempi risultanti. I valori nel `.env` del server
(`STALE_FACTOR`, `HEARTBEAT_FACTOR`, `FAIL_THRESHOLD`, `DEFAULT_INTERVAL`) restano solo
come riserva, per sonde che non comunicano le proprie soglie.

**Alert**

| Evento | Priorità |
|---|---|
| Un dispositivo non risponde da 3 controlli consecutivi | normale |
| Il dispositivo torna raggiungibile | normale |
| Nessun dispositivo risponde, ma la sonda comunica | critica |
| La sonda non invia dati da 3 minuti (blackout, internet giù) | critica |
| Problema critico ancora in corso | promemoria ogni 60 min |

---

## Verifica in due passaggi: dispositivi riconosciuti

Nel modulo del codice c'è **«Non chiedermi il codice su questo dispositivo per 15 giorni»**.
Spuntandola, sui prossimi accessi da quel browser si entra con la **sola password**: il secondo
fattore è già stato dato una volta e non viene richiesto di nuovo fino alla scadenza.

Cosa **non** cambia: la password serve sempre, a ogni accesso. Il segno vale solo per
quell'account su quel browser — un altro amministratore sullo stesso computer deve dare il suo
codice. E decade da solo quando cambia qualcosa che lo riguarda: **cambio della password**,
**cambio dell'app di autenticazione**, o password provvisoria riassegnata da un altro
amministratore. Uscire con *Esci* invece lo conserva: è il senso della funzione.

Se il dispositivo non è tuo (un computer condiviso, un internet point) **non spuntarla**: chi ha
quel browser e indovina la password entrerebbe senza secondo fattore.

## Nuovi amministratori dal pannello

In *Amministrazione → Amministratori → Nuovo amministratore* si crea un amministratore senza
passare dalla VM: email, nome facoltativo, **la tua** password di amministratore e **il codice
della tua app** di autenticazione. La password provvisoria del nuovo account compare lì **una
volta sola** e non viene inviata per email: consegnala tu su un canale che ritieni sicuro. Al
primo accesso dovrà cambiarla e attivare l'app di autenticazione.

Il codice dell'app serve perché la password da sola non basta: chi trovasse il pannello aperto, o
la password annotata da qualche parte, potrebbe crearsi un secondo account e restare dentro per
sempre, anche dopo che la password è stata cambiata. Il codice invece richiede il telefono, in
quel momento. Vale il codice dell'app, non quello di riserva via email: quello arriva in una
casella di posta, cioè il canale che un secondo fattore dovrebbe tenere fuori. Ogni codice vale
una volta sola: se hai appena usato quello per entrare, aspetta che ne compaia uno nuovo.

Un amministratore può fare tutto quello che puoi fare tu, compreso creare altri amministratori e
installare un pacchetto: valuta chi aggiungi. Un pacchetto però si installa solo se è **firmato con la
tua chiave di rilascio** (vedi *Firma dell'autore*), che sta sul tuo Mac e non nel pannello. Dalla VM
resta possibile con `account.py crea-admin EMAIL`.

### Password dimenticata

La password provvisoria si vede una volta sola e **il server non la conserva**: non c'è nessun
posto dove andarla a rileggere. Se chi la riceve la perde prima di usarla, in *Amministrazione →
Amministratori → Password dimenticata* gliene dai una nuova: scegli l'amministratore, metti la
tua password e il codice della tua app. Vale anche per un amministratore che si è chiuso fuori:
la nuova password azzera anche il blocco.

Le sessioni aperte di quell'amministratore si chiudono, i suoi dispositivi riconosciuti decadono
e al primo accesso dovrà sceglierne una sua. Come alla creazione, la password nuova si legge lì
una volta sola e non viene spedita per email; agli amministratori arriva un avviso che è successo.

Se ha perso **anche il telefono**, spunta *Ha perso anche il telefono*: dovrà configurare di nuovo
l'app di autenticazione. Finché non lo fa, il suo accesso è protetto dalla sola password che gli
hai dato, quindi consegnagliela con la stessa attenzione.

La tua password non si cambia da lì ma da *La tua password*, poco sotto: la tua la scegli tu,
invece di riceverne una provvisoria. Dalla VM si fa la stessa cosa con `account.py crea-admin EMAIL`
(su un amministratore che esiste già rimette la password provvisoria); `account.py password` invece
è per gli **utenti** della pagina di stato, non per gli amministratori.

### Eliminare un amministratore

Nell'elenco degli amministratori, in fondo a ogni riga, c'è **Elimina**. Chiede conferma, **la tua
password** e **il codice della tua app**: come per la creazione, perché togliere gli altri è il
modo più diretto per restare l'unico ad avere le chiavi della VM.

Le sue sessioni si chiudono subito, i suoi dispositivi riconosciuti decadono e la pagina `/admin`
non lo riconosce più. Riceve un'email che glielo dice, e agli altri amministratori arriva
l'avviso. **Utenti, sonde e dati non vengono toccati**: gli amministratori non possiedono sonde.

Sulla tua riga il tasto non c'è, e il server rifiuta comunque di eliminarti da solo: resteresti
senza amministratori, e il pannello ripartirebbe dall'installazione guidata — cioè il primo che
arriva diventa amministratore. Se vuoi andartene, fatti eliminare da un altro amministratore, o
usa la VM: `account.py elimina-admin EMAIL`.

## Mettere in pausa il ping verso un dispositivo

Accanto a ogni dispositivo, il tasto **⏸** ferma il ping verso quel dispositivo soltanto. Serve per
quello che sai già spento o staccato: la stufa d'estate, il computer dell'ufficio in ferie, la
telecamera di una stanza in ristrutturazione.

**La sonda smette proprio di mandargli pacchetti**: non ci sono né misure né avvisi, e il grafico
non si riempie di un mese di rosso che non significa niente. È la differenza con la priorità
**Mai**, che continua a misurare in silenzio: lì il dispositivo lo stai ancora guardando, qui no.

Scegli per quanto (da 4 ore a un mese, oppure *finché non lo riprendo*) e, volendo, una nota per
ricordarti il perché. Il dispositivo **resta nell'elenco**, con la spia spenta e scritto fino a
quando è fermo: alla scadenza torna da solo, oppure lo riprendi con **▶**. In tutti e due i casi la
sonda ricomincia a pingarlo al controllo successivo, senza che tu debba toccare la configurazione.

Lo storico di prima della pausa resta dov'è: non si cancella niente, semplicemente in quel periodo
non ci sono misure.

**Modifiche in attesa.** Un dispositivo appena aggiunto (dalla pagina locale della sonda o dal
pannello) oppure appena ripreso da una pausa compare subito nell'elenco con la spia spenta e la
scritta **modifiche in attesa**: la configurazione lo prevede, ma la sonda non ha ancora fatto
il primo ping. Al primo report la scritta sparisce e lo stato diventa quello normale; se dopo un
paio di minuti è ancora *modifiche in attesa*, la sonda non ha ancora ricevuto la configurazione
nuova (controlla che sia online).

**L'ultimo dispositivo attivo non si può fermare**: una sonda senza niente da pingare non è una
configurazione valida. Per fermare tutto c'è la pausa della sonda (Impostazioni → Sonde).

## Priorità delle notifiche

Non tutto quello che si controlla ha la stessa importanza: che non risponda l'allarme di casa è
un'altra cosa rispetto alla lavatrice. Nell'elenco dei dispositivi, accanto a ognuno, c'è un menu
con quattro scelte:

| Priorità | Quando arriva la notifica |
|---|---|
| **Alta** | al **primo** controllo fallito |
| **Normale** | dopo la soglia della sonda (predefinita: 3 controlli) — è il comportamento di sempre |
| **Bassa** | dopo **N volte** i controlli della normale (×2, ×3, ×4…), che decidi tu |
| **Mai** | mai |

Il moltiplicatore della priorità **bassa** si sceglie in *Impostazioni → Notifiche → Priorità di
notifica* e vale per tutti i dispositivi di quella sonda impostati su *Bassa*. Esempio: con
*Controlli falliti prima dell'alert* a 4 (scheda *Controlli*), la normale avvisa dopo 4 controlli
falliti e la bassa ×2 dopo 8, ×3 dopo 12; sotto la scelta la pagina scrive il numero esatto. Se
cambi la soglia normale, la bassa la segue. Il predefinito è ×2; si può cambiare con `LOW_FACTOR`
nel `.env` del server, che vale per le sonde che non hanno scelto. Una soglia bassa scelta con le
versioni precedenti (un numero fisso di controlli) diventa il multiplo più vicino per eccesso,
almeno ×2.

Due cose da sapere:

- **«Mai» non spegne il monitoraggio.** Il dispositivo continua a essere misurato, compare
  nell'elenco e diventa rosso quando non risponde: a tacere è solo la notifica. Serve per le cose
  che vuoi poter guardare senza esserne avvisato. Per lo stesso motivo, quando torna su non arriva
  nessun avviso di ripristino.
- **La priorità bassa non può avvisare prima di quella normale.** Se imposti una soglia più bassa
  di quella della sonda, viene usata quella della sonda: altrimenti un dispositivo di poco conto
  verrebbe segnalato prima di uno importante.

Il menu si colora quando la priorità non è quella normale (rosso per *Alta*, giallo per *Bassa*,
barrato per *Mai*), così si vede a colpo d'occhio quali dispositivi hanno un trattamento speciale.
Passandoci sopra, il suggerimento dice dopo quanti controlli arriverebbe davvero la notifica.

La priorità si sceglie **subito**, già nella finestra *Dispositivi* (un menu accanto a nome e indirizzo di ogni
riga), e si cambia **sempre**, anche per un dispositivo appena aggiunto che la sonda non ha ancora misurato o per
uno in pausa: vale appena la sonda comincia (o torna) a controllarlo. Mettendo un dispositivo in pausa la sua
priorità resta.

L'impostazione sta **sul server**, non sulla sonda: si cambia dalla pagina di stato e ha effetto
subito, senza toccare né riavviare le sonde.

## Riavvio e aggiornamento

**Aggiornare netmon sulle sonde.** Il server conserva i programmi e il pacchetto completo della sonda
della sua stessa versione, firmati dalla VM (in `/opt/netmon/probe-dist`, preparati da
`installa-server.sh`, anche quando l'installazione parte da `/admin`). Quando una sonda ha una
versione diversa, la si aggiorna con:

- il tasto **Aggiorna netmon (versione)** nella pagina di stato, scheda **Stato sonda** →
  *Manutenzione*;
- `/admin` → **Sonde** → *Programma un aggiornamento* (adesso o a una data e ora, una, alcune o
  tutte le sonde);
- oppure subito dopo l'installazione di un pacchetto sulla VM (*Dopo, aggiorna le sonde*);
- **da sole**, con gli **aggiornamenti automatici** (attivi di partenza): quando il server ha una versione nuova,
  le sonde rimaste indietro ricevono l'aggiornamento senza che nessuno lo chieda. Il server controlla ogni 10
  minuti; aggiorna solo sonde in linea, non in pausa e senza un'altra operazione in corso, al massimo 20 per
  volta e con un tentativo ogni 6 ore per sonda. L'esito compare come per gli altri aggiornamenti, con
  *aggiornamento automatico* come richiedente.

Ogni utente può **spegnere gli aggiornamenti automatici** delle sue sonde in *Impostazioni → Sonde →
Aggiornamenti delle sonde* (si salva con **Salva**). Allora le sue sonde restano alla versione attuale finché
non le aggiorna lui, e anche gli aggiornamenti di *tutte* le sonde programmati in `/admin` le saltano
(l'esito dice quante e quali); in `/admin` → **Sonde** sono segnate *aggiornamenti automatici spenti
dall'utente*. Se l'amministratore le sceglie una per una, invece, si aggiornano. La sonda su Home Assistant
non riceve aggiornamenti dal server: si aggiorna da Home Assistant.

In generale, una sonda **gestita da un altro sistema** (lo dice lei al server, con il nome del sistema)
si aggiorna, si riavvia e cambia rete Wi-Fi da lì: gli aggiornamenti programmati la saltano sempre (l'esito
dice quante e quali), il server non le manda comandi, in `/admin` → **Sonde** è segnata con il nome del
sistema e in *Stato sonda* i pulsanti di manutenzione lasciano il posto a dove farlo.

Gli aggiornamenti si comandano **solo da qui**: la pagina locale della sonda non li avvia, né quello
di netmon né quello del sistema operativo. La sua sezione **Sistema** mostra le due versioni
(installata e sul server), l'esito e il registro dell'ultimo aggiornamento comandato dal server, e
permette solo di **riavviare** la sonda.

La richiesta arriva alla sonda entro un controllo (circa un minuto). L'aggiornamento è **completo**,
come `sudo bash installa-sonda.sh --aggiorna`: programmi, script di sistema, permessi e servizi. La
sonda scarica `netmon.zip` con il suo token e lo accetta solo se è **firmato dalla VM** (con la chiave
ricevuta all'installazione) e più recente di quello installato; lo script di root
`/usr/local/sbin/netprobe-zipupdate` ricontrolla firma e pacchetto su una copia privata prima di
installarlo. Se dopo l'installazione la sonda non riparte, viene **rimessa la versione precedente** e
l'errore viene segnalato. L'esito, con il registro, compare in *Stato sonda* e negli *Ultimi eventi*.

Se la sonda ha già la versione del server, aggiornarla non ha effetto e il pannello lo segnala. Per
sicurezza non si torna mai a una versione **precedente** a quella installata, e un aggiornamento non
firmato (o firmato con un'altra chiave) viene rifiutato. Se reinstalli la VM da zero la chiave
cambia: rilancia `installa-sonda.sh --aggiorna` sulle sonde e accetta la nuova chiave dopo aver
confrontato l'impronta.

**Aggiornamenti completi o solo programmi.** Una sonda installata con una versione precedente
all'aggiornamento completo riceve dal server solo i programmi Python
(`/usr/local/sbin/netprobe-selfupdate`): script di sistema e permessi nuovi non arrivano. In *Stato
sonda* la voce *Aggiornamenti dal server* dice *completi* oppure *solo programmi*, e in `/admin` (*Sonde ›
Elenco sonde*) la versione ha l'etichetta *solo programmi*. Per passare agli aggiornamenti completi
basta una volta `sudo bash ~/probe/installa-sonda.sh --aggiorna` sulla sonda.

**Aggiornare il sistema della sonda.** Scheda **Stato sonda** → *Manutenzione*: **Aggiorna
sistema** (esegue `apt update` e `apt upgrade`, compresi i nuovi pacchetti richiesti come un
nuovo kernel) e **Riavvia sonda**. Finché la richiesta è in attesa puoi annullarla. Durante
l'aggiornamento vedi lo stato, al termine l'esito e il registro completo, e un avviso se è
consigliato un riavvio. L'esito finisce anche negli *Ultimi eventi*. L'aggiornamento gira in
un'unità systemd separata: la sonda continua a funzionare, e se durante l'aggiornamento il suo
servizio si riavvia, apt non viene interrotto. Ogni richiesta ha un identificativo salvato su disco
prima di essere eseguita, così dopo un riavvio non viene ripetuta.

**Server (VM): solo dal pannello di amministrazione.** Pagina `/admin` → **Server** (vedi *Utenti,
account e sonde*). Gli utenti della pagina di stato non possono né riavviare né aggiornare la VM.

**Permessi.** Servizi e pagine girano con utenti senza privilegi. I file in `/etc/sudoers.d/`
consentono solo questi comandi, e nient'altro:

- sonda (`/etc/sudoers.d/netprobe`): riavvio, aggiornamento del sistema, aggiornamento di netmon
  (programmi e pacchetto completo), reti Wi-Fi e disinstallazione;
- VM (`/etc/sudoers.d/netmon-vm`): riavvio, aggiornamento del sistema, installazione da pacchetto,
  conferma e rollback dell'ultimo aggiornamento.

Li installano `installa-sonda.sh` e `installa-server.sh` (anche con `--aggiorna`). Se mancano, i
pulsanti lo segnalano con *Permesso mancante* o *Funzione non ancora installata*: basta rilanciare lo
script con `--aggiorna`. Sulla sonda servono il pacchetto `sudo`, che è facoltativo (vedi *Senza
`sudo`* in C2): senza, la sonda funziona ma le operazioni da remoto no.

## Vedere gli eventi più vecchi

Il riquadro **Ultimi eventi** mostra gli eventi a pagine da 25, i più recenti per primi; il totale è
accanto al titolo (per esempio "57 eventi"). Oltre i 25 compare in fondo una barra con **‹ Precedenti** /
**Successivi ›** e la scelta di 25, 50, 100 o 200 per pagina. La pagina scelta resta anche quando la
pagina si aggiorna da sola; ricaricandola si torna alla prima. Le stesse pagine ci sono negli elenchi
di log del pannello di amministrazione (*Registro aggiornamenti sonde*, *Registro amministrativo*). Per periodi lunghi c'è anche la conservazione dei
dati (*Impostazioni → Account e backup → Conservazione dei dati*, da salvare con **Salva** in fondo alla pagina e la password attuale, oppure quella predefinita del server in
`/admin` → *Sonde › Conservazione dei dati*), che decide fino a quando restano.

## Filtrare ed eliminare gli eventi

In cima al riquadro **Ultimi eventi** c'è il **filtro**: scrivi un testo qualsiasi (per esempio il
nome di un dispositivo; maiuscole e minuscole non contano) oppure tocca uno o più **tag**, cioè le
parole tra parentesi quadre all'inizio degli eventi, come *CRITICO*, *ALERT*, *OK*, *MANUTENZIONE*.
Accanto a ogni tag c'è quanti eventi lo hanno. Testo e tag si possono usare insieme (per esempio
*ALERT* + «router»); con più tag compaiono gli eventi che ne hanno uno qualsiasi. Il filtro vale su
tutti gli eventi, non solo su quelli della pagina, e accanto al titolo compare per esempio
"8 di 57 eventi". **Azzera filtro** torna all'elenco completo.

Nel riquadro **Ultimi eventi** il pulsante **Gestisci** mostra una casella accanto a ogni
evento: selezionane alcuni (anche toccando la riga) ed elimina con **Elimina selezionati**,
oppure usa **Elimina tutti** per svuotare l'intero registro, compresi gli eventi più vecchi non
mostrati (il totale è indicato accanto al titolo, per esempio "57 eventi"). Con un filtro attivo,
**Seleziona tutti quelli visibili** sceglie gli eventi filtrati della pagina e il pulsante diventa
**Elimina tutti i filtrati**: toglie tutti gli eventi che corrispondono al filtro, anche quelli
delle pagine successive, e lascia gli altri. Viene sempre chiesta una conferma. L'eliminazione riguarda solo il registro degli eventi: storico dei ping,
traffico e stato dei dispositivi non cambiano. Durante la selezione l'aggiornamento automatico
della pagina è in pausa.

## SpeedTest

Accanto al nome di ogni sonda, in *Stato rete › Monitor dispositivi*, il pulsante **SpeedTest** chiede alla sonda di
misurare la velocità della linea. La sonda lo esegue **alla fine del suo prossimo ciclo dei ping** (quindi
entro un intervallo di controllo) e il risultato arriva con il report di quel ciclo: sotto il nome compare
*SpeedTest ↓ download ↑ upload Mbit/s · ping ms (ora)*, e negli *Ultimi eventi* una riga *[SPEEDTEST]*.

La misura usa i server di velocità di Cloudflare (`speed.cloudflare.com`): latenza, poi download e upload
con 4 connessioni in parallelo, al massimo 8 secondi ciascuno. La velocità si calcola **escludendo i primi
2 secondi**, quando le connessioni stanno ancora accelerando; in upload contano solo i dati già arrivati al
server, non quelli fermi nel buffer della sonda. Dura circa 15–20 secondi e consuma **circa 150 MB** (120 in
download, 30 in upload) sulle linee fino a circa 100 Mbit/s; sulle linee più veloci il limite cresce con la
velocità, fino a circa 1 GB a 1 Gbit/s: da tenere presente su linee a consumo come LTE.
Tra uno speedtest e il successivo serve almeno un minuto; una richiesta non eseguita entro 15 minuti
(sonda spenta) scade. Su un Raspberry Pi Zero il risultato può fermarsi sotto la velocità reale delle
linee molto veloci (oltre 200–300 Mbit/s), perché lo limita il processore della sonda.
I risultati restano anche nel database (tabella `speedtests`), con la stessa conservazione dei dati.

### SpeedTest periodici

In **Impostazioni › Controlli**, riquadro **SpeedTest periodici**, si sceglie per ogni sonda se fare lo
speedtest da solo e ogni quanto: *Ogni ora*, *Ogni 3 ore*, *Ogni 6 ore*, *2 volte al giorno*, *Ogni giorno*,
*Ogni settimana* oppure *Personalizzato* (*ogni N minuti, ore o giorni a partire dalle HH:MM*), con l'orario
da cui partire. Si possono attivare solo alcune sonde. Accanto a ogni sonda il consumo stimato al mese e
l'orario del prossimo test. Se la sonda è collegata in **Wi-Fi** compare un avviso (anche nel riquadro
SpeedTest della Dashboard): la velocità misurata
dipende anche dalla qualità del Wi-Fi e da quanti dispositivi lo stanno usando, non solo dalla linea, quindi i test periodici sono consigliati solo con la sonda collegata
via cavo. Le scelte si salvano con **Salva** in fondo alla pagina, insieme alle altre impostazioni. I test li programma il server, quindi funzionano con ogni sonda che ha il
pulsante SpeedTest; una sonda in pausa, offline o con uno speedtest già in corso salta il turno.

Il **piano** dell'account limita la frequenza: *basso* al massimo uno al giorno per sonda, *medio* ogni 6
ore, *alto* e senza piano ogni ora. Le frequenze non consentite non si possono scegliere.

Con **due o più sonde attive** compare **Sfalsamento tra le sonde** (nessuno, 5, 15, 30 minuti, 1 o 2 ore):
se le sonde sono sulla stessa linea i test non partono insieme e non si rubano banda; ognuna parte dopo
la precedente, in ordine di creazione. Il disegno sotto mostra gli orari delle prossime 24 ore.

**Avvisi sulla velocità**: *Download sotto* N Mbit/s, *Upload sotto* N Mbit/s e *Download sotto il* N %
della media degli ultimi 7 giorni, attivabili insieme. L'avviso *[SPEEDTEST] sonda: velocità bassa* parte
dopo **2 test di fila** sotto una soglia e compare negli *Ultimi eventi* e sulla Dashboard; quando un test
torna sopra compare *velocità tornata normale*. **I test periodici non mandano notifiche** e non scrivono
un evento ogni volta: si vedono nel riquadro e nello storico della Dashboard. Le notifiche (sui canali scelti
per *SpeedTest* in *Notifiche*) arrivano solo per gli speedtest avviati a mano, con il risultato e, se la
velocità è bassa, l'avviso.

## Controllo di sicurezza dei dispositivi

Nella riga di ogni dispositivo, in *Stato rete › Monitor dispositivi*, lo **scudo 🛡** apre il controllo
di sicurezza: la sonda prova le porte TCP dei dispositivi di casa (Telnet, FTP, SSH, pagine web, MQTT,
RTSP delle telecamere, SMB, RDP, VNC, ADB, database…) e dice quali sono aperte e quali sono **a rischio**.
Prima di partire scegli il **tipo di controllo** (la pagina ricorda l'ultimo usato):

| Tipo | Cosa prova | Durata |
|---|---|---|
| **Veloce** | circa 30 porte, solo quelle dei servizi a rischio | meno di un minuto |
| **Standard** | circa 50 porte, le più usate dai dispositivi di casa | un paio di minuti |
| **Approfondito** | tutte le porte da 1 a 1024 e oltre 90 altre note, più di 1100; segnala anche le porte aperte con un servizio non riconosciuto (rischio basso, «controlla che sia voluto») | fino a 15 minuti |

Con **Controlla ora** parte subito. Una sonda fa **un controllo alla volta**: se ne è già in corso un
altro (anche di un altro dispositivo), il pulsante diventa **Metti in coda** e il controllo parte da solo
appena finisce quello prima; la finestra dice la posizione in coda, e **Togli dalla coda** lo annulla
finché non è partito. Con **Controlla ogni giorno** la sonda lo ripete da sola una volta ogni 24 ore
(controllo standard). Le sonde con i programmi più vecchi fanno sempre il controllo standard: per
scegliere il tipo aggiorna netmon sulla sonda.

| Rischio | Esempi |
|---|---|
| **Alto** (bordo rosso) | Telnet aperto, MQTT o Redis che accettano chiunque senza password, VNC senza password, video della telecamera che si apre senza password, debug di Android (ADB), RDP, FTP anonimo |
| **Medio** (bordo giallo) | pannello web con login senza HTTPS (la password viaggia in chiaro), SMB, FTP, SNMP, certificato HTTPS scaduto o protocollo TLS vecchio |
| **Basso / Informazione** | SSH, pagine web, stampanti, servizi normali da sapere |

Il colore dello scudo dice lo stato (passandoci sopra col mouse lo dice anche a parole):

| Scudo | Stato |
|---|---|
| contorno grigio chiaro | mai controllato |
| blu, lampeggia | controllo in corso o in coda |
| verde con la spunta | ultimo controllo senza rischi alti o medi |
| giallo con «!» | rischio medio |
| rosso con «!» | rischio alto |
| contorno rosso | ultimo controllo non riuscito |

**Controllo approfondito di un dispositivo nuovo** (si sceglie dispositivo per dispositivo, non per tutti).
Nella finestra *Dispositivi*, sotto **ogni** riga aggiunta compare la sua casella *Controllo approfondito delle
porte dopo il salvataggio*, spenta: spunti solo quelle dei dispositivi che vuoi controllare e, appena salvi,
la sonda fa il controllo **approfondito** di ciascuno (fino a 15 minuti; con più dispositivi
nuovi uno alla volta, gli altri in coda). Vale anche per i dispositivi aggiunti con **+ Monitora** da
*Dispositivi in rete*. L'esito arriva negli *Ultimi eventi* e nello scudo, come un controllo chiesto a mano.

**Porte aperte quando il ping fallisce** (spento all'inizio, si sceglie dispositivo per dispositivo).
Alcuni dispositivi smettono di rispondere al ping pur funzionando (telecamere, PC con il firewall,
dispositivi in risparmio energetico). Nella finestra dello scudo, la casella **Se il ping fallisce, prova
le porte aperte** fa sì che, quando il ping di quel dispositivo non risponde, la sonda provi le porte
trovate aperte dall'**ultimo controllo** riuscito (le prime 5): se una accetta la connessione il dispositivo
è acceso, risulta **giallo** con *non risponde al ping, porta 80 aperta* e **non parte l'avviso**; se non
risponde nessuna porta conta come un ping fallito, come sempre. La casella si attiva solo dopo un controllo
che abbia trovato almeno una porta aperta, e un controllo nuovo aggiorna le porte da provare. Solo
connessioni TCP che si chiudono subito, solo indirizzi della rete di casa, al massimo 8 secondi per giro.
Lo storico dei ping (e la *Disponibilità*) registra comunque il ping perso.

Ogni controllo lascia una riga *[SICUREZZA]* negli
*Ultimi eventi*. Gli avvisi sono del tipo *Controllo di sicurezza* (si sceglie su quali canali in
*Impostazioni → Notifiche*, come gli altri tipi):

- un controllo chiesto da te con **Controlla ora** ti manda sempre l'esito, anche quando non trova
  rischi o non riesce;
- il controllo **giornaliero** avvisa solo se compare un rischio alto o medio **nuovo** rispetto al
  controllo precedente: lo stesso servizio già segnalato non viene ripetuto ogni giorno.

Cosa fa e cosa no:

- controlla **solo indirizzi della rete di casa** (IP privati): un indirizzo pubblico viene rifiutato dalla
  sonda stessa, qualunque cosa chieda il server, quindi non può essere usata per scansionare Internet;
- poche connessioni alla volta, con pause brevi: alcuni dispositivi IoT economici si bloccano con le
  scansioni aggressive;
- ai servizi trovati fa solo **domande innocue** (intestazione, certificato, «serve una password?»), mai
  tentativi di indovinare password o di sfruttare difetti;
- non confronta le versioni con l'elenco delle vulnerabilità note (CVE): su un Raspberry Pi Zero sarebbe
  troppo pesante e darebbe molti falsi allarmi. Segnala configurazioni pericolose, che sono la causa più
  comune dei problemi dei dispositivi di casa;
- solo porte TCP: i servizi UDP (per esempio UPnP sulla 1900 o SNMP sulla 161) non vengono provati.

Un controllo alla volta per sonda; tra due controlli dello stesso dispositivo dalla pagina serve almeno un
minuto. Serve una sonda aggiornata a questa versione: con una sonda vecchia lo scudo non compare.
Risultati e scelte «ogni giorno» stanno sul server in `data/scans.json` (solo l'ultimo controllo di ogni
dispositivo); esportando l'utente verso un altro server non vengono portati con sé, basta riattivarli.

## Scheda Stato sonda

La voce **Stato sonda** del menu mostra, per ogni sonda, i dati inviati a ogni controllo:

- **Salute**: temperatura (arancione da 70 °C, rossa da 80 °C), alimentazione (su Raspberry Pi, da
  `vcgencmd get_throttled`: problemi in corso o avvenuti dall'avvio), carico della CPU,
  memoria, disco, swap in uso.
- **Rete**: collegamento Wi-Fi o via cavo, interfaccia, IP e MAC; in Wi-Fi anche rete, banda,
  segnale in dBm con valutazione e velocità di collegamento; via cavo la velocità della porta.
- **Sistema**: da quanto è acceso, modello, sistema operativo, kernel.
- **Sonda netmon**: versione, da quanto è in esecuzione, memoria usata, misure in attesa di
  invio, età dei dati, tipo di aggiornamenti dal server (*completi* o *solo programmi*).
- **Manutenzione**: *Aggiorna netmon*, *Aggiorna sistema* e *Riavvia sonda* (vedi *Riavvio e
  aggiornamento*).

Il pallino accanto al nome riassume lo stato: giallo o rosso se un valore è fuori norma.
Il link `https://<dominio>/dashboard#sonda` apre direttamente questa scheda.
Su Raspberry Pi l'alimentazione si legge con `vcgencmd`, tramite il gruppo `video` già impostato in
`netmon-probe.service`; su altro hardware quella voce semplicemente non compare.

### Reti Wi-Fi della sonda

Le reti Wi-Fi si gestiscono in **Impostazioni → Sonde**: comando **Reti Wi-Fi** della sonda (nel menu
**Azioni ▾** quando i comandi non stanno su una riga, per esempio sul telefono). La finestra elenca le reti
salvate sulla sonda (quella in uso è segnata *in uso*) e l'esito dell'ultima operazione. In *Stato sonda*
il riquadro **Reti Wi-Fi** le mostra soltanto, con il pulsante *Gestisci in Impostazioni*. Il proprietario può:

- **Aggiungi rete Wi-Fi** → *Aggiungi*: la sonda impara la rete e la usa quando **non trova più quella
  attuale** (per esempio prima di cambiare router o di spostarla): finché la rete attuale funziona resta
  lì. Prima di salvarla la cerca con una scansione e l'esito dice se la vede (canale, banda e segnale)
  oppure perché potrebbe non vederla: troppo lontana, nascosta (va spuntato *Rete nascosta*), solo a
  5 GHz con una scheda che va solo a 2,4 GHz (Raspberry Pi Zero, Pi 3 e precedenti), oppure sui canali 12
  e 13 con il paese Wi-Fi della sonda non impostato (`sudo raspi-config` → *Localisation* → *WLAN
  Country*). La **password** non si può provare senza collegarsi: per provarla usa *Collegati subito*.
  Quando la sonda deve scegliere (all'avvio o se perde la rete) preferisce le reti aggiunte da qui.
- **Aggiungi rete Wi-Fi** → *Collegati subito*: la sonda ci passa adesso. Se non si collega, o se da lì
  il server non risponde entro un minuto, **torna da sola alla rete di prima** e toglie quella nuova;
  l'esito compare in *Manutenzione* e negli eventi.
- **Rimuovi**: toglie una rete salvata. Quella in uso non si può togliere.

Serve la password del tuo account. La password della rete passa dal server solo per essere
consegnata: resta in memoria (mai su disco) e viene cancellata appena la sonda prende in carico la
richiesta; se il server si riavvia prima, la richiesta va ripetuta. Sulla sonda la scrive in
NetworkManager lo script di root `/usr/local/sbin/netprobe-wifi`, che non la riporta nel registro.

Richiede **NetworkManager** (standard su Raspberry Pi OS da Bookworm in poi) e una sonda aggiornata
con il pacchetto completo (aggiornamento dal server o `installa-sonda.sh --aggiorna`), che installa
script e permesso. Le reti vengono salvate come WPA2 (anche le reti miste WPA2/WPA3), come WPA3 se la
scansione le vede solo WPA3, oppure aperte.

## Utenti, account e sonde

Il server può ospitare **più utenti**, e ognuno vede solo le proprie sonde.

**Amministrazione (pagina separata).** L'amministrazione del server è una pagina a sé,
**https://netmonhome.net/admin**, con un accesso proprio. Gli amministratori sono account
separati dagli utenti: entrano solo in `/admin` e non nella pagina di stato; gli utenti della
pagina di stato, di qualsiasi tipo, non possono entrare in `/admin`. La sessione di
amministrazione dura al massimo 8 ore e usa un cookie inviato solo alle funzioni di
amministrazione. Nella pagina di stato non c'è nessun collegamento all'amministrazione.

Gli amministratori sono **nominali**: ognuno accede con la propria **email**, che serve anche
per il codice di riserva della verifica in due passaggi. L'installazione guidata chiede email e
nome del primo amministratore e lo crea con una **password provvisoria**, mostrata nel
riepilogo finale. Per crearne uno in qualsiasi momento, sulla VM:

```bash
sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py crea-admin mario.rossi@gmail.com --nome "Mario Rossi"
sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py elimina-admin mario.rossi@gmail.com
```

Il comando mostra la password provvisoria una sola volta. Si fa anche dal pannello, in
*Amministratori → Nuovo amministratore* (vedi «Nuovi amministratori dal pannello»): lì serve la
tua password **e** il codice della tua app. Se avevi creato l'utenza generica `admin`, crea quella
nominale con la tua email ed elimina la vecchia con `elimina-admin admin`.

**Primo accesso a `/admin`.** Email e password provvisoria, poi la pagina chiede nell'ordine:

1. una **nuova password** (almeno 10 caratteri, diversa da quella provvisoria);
2. di **attivare l'app di autenticazione**: installa sul telefono Google Authenticator,
   Microsoft Authenticator, Aegis o simili, inquadra il QR code (o scrivi la chiave mostrata
   sotto) e inserisci il codice a 6 cifre. Finché non la attivi non si entra.

Arriva un'email di conferma all'indirizzo dell'amministratore.

**Accessi successivi (verifica in due passaggi).** Dopo email e password la pagina chiede il
codice a 6 cifre dell'app, che cambia ogni 30 secondi. Un codice vale una volta sola.

- **Codice via email (riserva).** Se non hai il telefono: *Non hai il telefono? Ricevi un codice
  via email*. Arriva un codice di 6 cifre, valido 10 minuti; se ne può chiedere uno al minuto e
  al massimo 5 all'ora. Serve che l'email del server sia configurata (`SMTP_…` nel `.env`).
- **Cambiare telefono.** Nel pannello, *Il tuo account → App di autenticazione → Cambia
  telefono o chiave*: con la tua password ottieni un nuovo QR code; l'app vecchia vale finché
  non confermi la nuova con un suo codice. Arriva un'email di avviso.
- **Telefono perso e niente email.** Se c'è un altro amministratore, dal suo pannello:
  *Amministratori → Password dimenticata*, spuntando *Ha perso anche il telefono*. Altrimenti,
  dalla VM, rigenera la password e azzera l'app: al prossimo accesso la configuri di nuovo.

  ```bash
  sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py crea-admin mario.rossi@gmail.com --azzera-mfa
  ```

La sessione a metà (password giusta, codice da inserire) dura al massimo 15 minuti; quella
completa 8 ore.

**Blocco dell'amministratore.** Le **password sbagliate non bloccano l'account** e non chiudono le
sessioni: altrimenti chiunque conosca l'email di un amministratore potrebbe tenerlo fuori dal
pannello. Sono limitate a 5 per indirizzo IP ogni 15 minuti (più un tetto di 100 da qualunque
indirizzo): oltre, la pagina risponde *Troppi tentativi* solo a chi sta sbagliando.
L'account si blocca invece dopo **5 codici di verifica sbagliati di fila** (ci si arriva solo con
la password giusta, quindi è il segnale che qualcun altro la conosce): le sessioni si chiudono e
l'amministratore riceve un'email. Il blocco dura 15 minuti, raddoppia a ogni blocco ravvicinato
fino a 24 ore e scade da solo. Per sbloccarlo subito: dal pannello di un altro amministratore,
*Amministratori → Password dimenticata*; oppure dalla VM, `account.py crea-admin EMAIL` (nuova
password provvisoria, blocco azzerato).

Nella pagina `/admin`:

- **Utenti**: tutti gli account della pagina di stato — **tutti uguali**: ognuno vede e riceve solo gli
  avvisi delle sue sonde, più l'avviso quando il server va in manutenzione —, con lo stato (*attivo ora*, *sessione aperta*, *non collegato*, *bloccato*; gli invitati non ancora
  registrati compaiono come *invitato*), il **Piano**, la **Scadenza**, registrazione e ultima attività
  (la data; l'ora passando sopra), sessioni aperte, **Sonde** (collegate / consentite), **FRITZ!Box**
  (collegati a tutte le sue sonde / massimo per l'account) e **Dispositivi** (configurati su tutte le sue
  sonde, compresi quelli in pausa / massimo per l'account). Un clic sull'intestazione di una colonna ordina l'elenco (un secondo clic inverte
  l'ordine; la scelta resta nel browser). Le azioni su un utente stanno nel menu del pulsante **Azioni ▾** in fondo alla sua
  riga (per quelle delicate serve la tua password di amministratore):
  - **Limiti**: vedi *Limiti per utente*.
  - **Scadenza**: vedi *Scadenza dell'account*.
  - **Prepara sonde** (non per gli account bloccati): per configurare una sonda e spedirla all'utente
    pronta da accendere. La finestra elenca le sonde dell'account (collegata, con l'ultimo contatto,
    oppure *non ancora collegata*) e quante ne può avere. Con un nome e la tua password, **Crea la
    sonda** la aggiunge al suo account (entro il limite di sonde; se è pieno, alzalo in *Limiti*) e
    mostra, con il tasto *Copia*, il **token** (una sola volta), il **dominio** da dare all'installazione
    della sonda o all'app di Home Assistant (es. `vm1.netmonhome.net`) e l'**indirizzo del server** per
    la pagina locale della sonda, sezione *Server*. L'utente vede subito la sonda in *Impostazioni →
    Sonde*, *non ancora collegata*: appena la accende in rete si collega da sola. **Nuovo token** su una
    sonda dell'elenco ne crea un altro (per esempio se quello di prima è andato perso): il vecchio smette
    subito di valere, e se la sonda è già collegata il pannello chiede conferma. Vale solo per account
    già registrati: a chi non ha ancora un account le sonde non si preparano.
  - **Reinvia codice**: manda all'email dell'utente un nuovo codice di accesso (vale 7 giorni). Con
    quello rientra nel suo account scegliendo una nuova password; sonde, storico e impostazioni
    restano. Finché non lo usa vale la password di prima. Serve a chi ha perso la password o il
    primo invito; i codici non usati che aveva prima smettono di valere.
  - **Blocca**: l'utente non può più accedere e le sue sessioni si chiudono; tentando l'accesso
    vede *Questo account è stato bloccato dall'amministratore del server*. Le sue sonde continuano
    a misurare, ma senza inviargli avvisi. **Sblocca** gli restituisce l'accesso.
  - **Elimina**: *solo l'account* (le sonde restano senza proprietario con il loro storico,
    ricollegabili con il loro token, per **30 giorni**: vedi *Utenti non attivi*) oppure *l'account e
    tutti i suoi dati* (sonde, storico, traffico ed eventi). In tutti e due i casi l'utente riceve
    un'**email** che gli dice che l'account è stato eliminato e, se i dati restano, fino a quando.
- **Utenti non attivi** (sotto Utenti, compare solo se ce n'è almeno uno): gli account eliminati
  senza cancellarne i dati, anche quelli che l'utente ha eliminato da solo. Per ognuno: VM, quando e
  da chi è stato eliminato, quante sonde ha lasciato e **quando i dati vengono cancellati da soli**
  (30 giorni dopo). **Elimina i dati** (con la tua password) li cancella subito. Le sonde che nel
  frattempo qualcuno ha ricollegato al suo account con il token restano a lui. Le sonde senza
  proprietario non passano più al primo account che si registra sul server.
  - **Esporta (file cifrato)**: l'utente con sonde e storico in un file cifrato, da importare su un altro
    server netmon con **⤒ Importa un utente** (sopra la tabella). Si apre solo con la password del file.
- **Codici di accesso** (o **＋ Aggiungi utente** nella tabella Utenti): per ospitare qualcuno generi un codice (`accesso_…`). Se indichi la sua
  **email**, il server gliela manda in automatico con un link che apre la registrazione già
  compilata (codice ed email inseriti: sceglie solo la password); il codice vale **solo per
  quell'indirizzo** e per una registrazione. Il codice nel link sta dopo il `#`, quindi non arriva
  al server e non finisce nei registri. Senza email, lo consegni tu. Puoi aggiungere una nota per
  ricordare a chi l'hai dato, il numero di registrazioni consentite (1, 5, 10 o senza limite) e
  la validità (1, 7, 30 giorni o senza scadenza). Il codice si vede **una sola volta**: sul
  server resta solo la sua impronta. L'elenco mostra stato (*valido*, *scaduto*, *esaurito*),
  utilizzi e chi l'ha usato per ultimo. **Elimina** lo rende inutilizzabile; gli account già
  creati con quel codice restano.
- **Registrazione**: ci si registra **solo con un codice di accesso**. La chiave del server non
  registra nessuno, tranne il primo account in assoluto di una macchina appena installata: è un
  segreto condiviso, lo conosce chiunque l'abbia usata per installare una sonda, mentre un codice
  è personale, si revoca e dice chi ha invitato chi.
- **Email da confermare**: chi si registra con la chiave del server o con un codice non legato a
  un'email riceve un link di conferma, da aprire nel browser in cui ha fatto l'accesso. Finché non
  lo apre, a quell'indirizzo non parte nessun avviso (Telegram e ntfy funzionano subito). Il link si
  richiede di nuovo da Impostazioni → Notifiche. Con un invito inviato via email l'indirizzo è
  già confermato.
- **Amministratori**: elenco degli amministratori, creazione ed eliminazione, password provvisoria
  per chi l'ha persa. Qui c'è solo quello che riguarda **gli altri**.
- **Il tuo account**: quello che riguarda **te** e basta — il tuo nome, la tua **lingua** (italiano,
  inglese, tedesco o francese: pannello e avvisi che ricevi via email e Telegram) e il tuo **fuso
  orario** (gli orari del pannello; *Default* usa quello del server), la tua password, la tua app di autenticazione e la tua chat Telegram. Prima dell'accesso il
  pannello usa la lingua scelta l'ultima volta su quel browser, oppure quella del browser.

La chiave del server **non si rigenera dalla pagina**: si cambia solo sulla VM, nel `.env` (vedi
«Chiave del server» più avanti).

**Server › Stato VM.** Nel menu di `/admin` la voce **Server** raccoglie *Stato VM*, *Manutenzione
della VM*, *Aggiornamento Netmon* e *Registro amministrativo* (indirizzo diretto `/admin#vm`). *Stato
VM* mostra, aggiornati ogni 20 secondi:

- **Salute**: uso della CPU, carico medio, memoria, swap, disco (in giallo oltre l'85%, in rosso
  oltre il 95%) e temperatura, se la VM la espone;
- **Rete**: indirizzo IP, traffico attuale e dall'avvio, giorni alla scadenza del certificato
  HTTPS (Caddy lo rinnova da solo; in giallo sotto i 14 giorni vuol dire che il rinnovo non va);
- **Sistema**: da quanto è accesa, sistema operativo, kernel, processore, fuso orario;
- **Aggiornamenti**: pacchetti da aggiornare (quanti di sicurezza, con l'elenco), data
  dell'ultimo `apt update`, se è consigliato un riavvio (per esempio per un nuovo kernel),
  ultimo aggiornamento e ultimo riavvio dal pannello (con chi l'ha chiesto);
- **netmon**: versione, memoria e durata del servizio, stato di Caddy, dimensione dei database,
  sonde collegate.

**Server › Manutenzione della VM** (serve la tua password di amministratore):

- **Aggiorna sistema**: `apt update`, `apt upgrade` (con i nuovi pacchetti richiesti, come un nuovo
  kernel) e `apt autoremove`, in un'unità systemd separata e a priorità bassa (CPU e disco): pagina
  e sonde continuano a funzionare e il registro si segue in tempo reale. Su una VM con una sola CPU
  condivisa la pagina può comunque rallentare finché apt non ha finito: non riavviare a metà. *Ricontrolla gli aggiornamenti disponibili*
  rilegge l'elenco (il conteggio usa gli elenchi scaricati dall'ultimo `apt update`).
- **Riavvia la VM**: pagina di stato e avvisi si fermano per un paio di minuti; le sonde
  conservano le misure e le inviano quando il server torna. La pagina aspetta e si aggiorna da
  sola. Non è possibile durante un aggiornamento.

Ogni richiesta finisce nel registro del servizio (`journalctl -u netmon-server`) con l'email
dell'amministratore.

**Conservazione dei dati.** `/admin` → *Sonde › Conservazione dei dati*: per quanto tempo il
server tiene lo storico **degli account che non hanno scelto la loro** e delle sonde senza account (ogni
utente può scegliere la sua, vedi sotto), in **giorni, settimane o mesi** (un mese = 30 giorni, al massimo dieci anni),
oppure **Conserva tutto**. Vale per ping dei dispositivi, traffico, temperatura delle sonde ed eventi
delle sonde. Il registro amministrativo dura un anno (`ADMIN_EVENTS_DAYS` nel `.env`, 0 = sempre). Quello che diventa più vecchio si elimina da solo, una volta all'ora.

- **Accorciando** il periodo, quello che ne resta fuori si elimina **subito** e non si recupera: la pagina
  chiede conferma dicendo quanti giorni restano, serve la tua password e alla fine dice quante righe ha
  tolto. Agli amministratori arriva un avviso con chi l'ha cambiato.
- **Allungando** non si perde niente, e non c'è conferma. Le misure già eliminate non tornano.
- **Conserva tutto**: niente si elimina per età. Restano comunque attivi il tetto agli eventi di ogni
  sonda (5000) e lo stop allo storico quando il disco è quasi pieno (`MIN_FREE_MB`), che impediscono a una
  sonda difettosa di riempire il disco.

Le misure che una sonda manda in ritardo (dal suo buffer, dopo un periodo senza collegamento) vengono
accettate solo se rientrano nel periodo conservato. Finché nessuno sceglie dal pannello vale
`RETENTION_DAYS` del `.env` (30 giorni se manca).

La pulizia usa l'indice che il database ha già per lo storico, a pezzi: anche con mesi di dati ci mette
pochi millesimi di secondo e non blocca i report delle sonde mentre lavora.

**Aggiornamento Netmon (VM).** *Server › Aggiornamento Netmon*: seleziona **insieme** il file
`netmon-light-<versione>.zip` della nuova versione (quello del rilascio, non lo zip «Download ZIP» di GitHub, che ha una
cartella sbagliata) e la sua firma `netmon-light-<versione>.zip.sig`, fatta con *Firma NetMon* sul Mac o su Windows (vedi
*Firma dell'autore* qui sotto). Vengono caricati e controllati subito, e l'elenco dei controlli
dice se il pacchetto è **idoneo**: firma dell'autore valida per la chiave di rilascio della VM, zip integro, tutti i file al loro posto dentro `netmon/` (niente percorsi che escono dalla
cartella né collegamenti), tutti i programmi della stessa versione, versione **più alta** di quella installata,
nessun errore nei programmi. Se è idoneo scegli, poi conferma con la tua password:

- **Installazione sulla VM**: *Adesso* oppure *Data e ora*;
- **Dopo, aggiorna le sonde**: *Nessuna*, *Tutte* oppure *Quelle che scelgo* (elenco con versione e stato).
  Parte sempre da *Nessuna*: le sonde si aggiornano solo se lo scegli. Se il pacchetto cambia anche
  le sonde, sotto compare una nota che lo dice.

**Le sonde vanno aggiornate?** Ogni rilascio cambia il numero di versione di tutti i file, anche quando i
programmi della sonda restano gli stessi. Per questo il server confronta i file della sonda del nuovo pacchetto
con quelli che distribuiva finora, senza contare il numero di versione, e te lo dice:

- **Sonde DA AGGIORNARE**, con l'elenco dei file che cambiano: la scelta resta su *Nessuna* (sotto
  compare una nota), e se confermi così la domanda di conferma te lo ricorda;
- **aggiornamento NON necessario**: cambia solo il numero di versione. Le sonde restano alla versione che hanno
  e non compaiono tra quelle *da aggiornare* (né nel pannello né nella pagina di stato), e *Tutte* le salta.

L'avviso compare tra i controlli del pacchetto caricato, nell'email agli amministratori quando programmi
l'installazione e in quella di fine installazione. Aggiornando a mano sulla VM lo stampa `installa-server.sh
--aggiorna` alla fine.

All'ora scelta il pacchetto viene ricontrollato e installato come
`installa-server.sh --aggiorna`, da uno script di sistema che **ricontrolla tutto** da capo. Il server si riavvia
per qualche secondo (se hai scelto *Adesso* la pagina si ricarica da sola con la nuova versione); se non riparte
viene rimessa quella precedente. Solo se la VM si aggiorna bene partono le sonde scelte, con l'aggiornamento
completo firmato dalla VM; se la VM non si aggiorna, l'aggiornamento delle sonde viene annullato.

> **Finestra di rollback (dalla 2.0).** Dopo un'installazione riuscita la VM tiene in riserva la
> copia dei **file** della versione precedente per **4 ore**. Il riquadro del rollback, in fondo ad
> *Aggiornamento Netmon*, mostra il conto alla rovescia con **Conferma la nuova versione**
> (la tieni: il rollback non è più possibile) e **Rollback subito** (torni alla precedente: il
> server si riavvia per qualche secondo). Se le 4 ore passano senza conferma, la VM **torna da
> sola** alla versione precedente; se la VM viene riavviata durante le 4 ore, il conto alla
> rovescia riprende all'avvio (e se è già scaduto il ripristino parte subito). Se la versione
> precedente non riparte, vengono rimessi i file della versione nuova e il riquadro segnala che il
> rollback non è riuscito. Il riquadro mostra versione precedente e nuova, ora di scadenza e tempo
> rimasto (in rosso se già scaduta). Un aggiornamento fatto a mano con `installa-server.sh --aggiorna`
> chiude la finestra aperta (vale come conferma). Il database (account, eventi, misure)
> **resta della versione nuova**: il ripristino rimette solo i file, e le versioni recenti
> aggiungono solo colonne al database, quindi quella vecchia ci gira sopra. Un nuovo aggiornamento
> conferma da solo qualunque rollback ancora in corso. Per tornare alla versione precedente servono
> *Rollback subito* o la scadenza: un pacchetto più vecchio non si può installare.

Le programmazioni compaiono nella tabella sotto *Programma una manutenzione della VM* e si annullano finché non
partono (annullando la VM si annullano anche le sonde). Avvisi: amministratori via email, proprietari delle sonde
sui loro canali, subito e un'ora prima; con *Adesso* nessun avviso, solo il registro eventi. Un pacchetto caricato e non programmato vale un'ora; *Annulla* lo scarta.

**Un solo riepilogo agli amministratori.** Un aggiornamento lanciato dal pannello (pacchetto sul server con le
sue sonde, oppure *Aggiorna tutte le sonde*) è una sola campagna: il server non manda un'email per ogni
programmazione o per ogni sonda non riuscita. Agli amministratori arrivano al massimo
tre email, ognuna con l'elenco di tutto quello che riguarda l'aggiornamento: **alla programmazione** (cosa
verrà aggiornato, versione e sonde: tutte o quelle scelte), **un'ora prima** (se programmato con più di un'ora
di anticipo) ed **esito finale**, quando VM e sonde hanno finito, oppure dopo 4 ore al massimo. L'esito dice per ogni
VM com'è andata e, per le sonde, quante sono aggiornate, quali non sono riuscite (con l'email del proprietario) e
quali sono ancora in attesa perché spente o non collegate. Il titolo è *[OK] … completato* oppure *[ALERT] … N
problemi*. Con *Adesso* il riepilogo finale arriva solo se qualcosa non è andato. Gli utenti ricevono i loro
avvisi di manutenzione come prima. Le VM ancora alla versione precedente mandano le loro email come prima, finché
non vengono aggiornate.

**Firma dell'autore (dalla 1.1).** Un pacchetto installato dal pannello esegue codice **come root sulla VM** e,
attraverso gli aggiornamenti firmati dalla VM, **sulle sonde di tutti gli utenti**. Per questo la VM installa solo
pacchetti **firmati con la tua chiave di rilascio**: la chiave privata sta solo sul tuo computer (cifrata con una
password, in *Firma NetMon*: l'app per il Mac, `tools/mac`, o `FirmaNetMon.exe` per Windows, `tools/windows`;
lo stesso formato, quindi una copia di riserva vale su tutti e due), la VM ha solo quella pubblica
(`/usr/local/share/netmon/release-key.pub`). Chi rubasse la password del pannello, o una sessione aperta, non
potrebbe installare un pacchetto suo. La firma la ricontrolla `netmon-vm-selfupdate` (root) sulla sua copia
privata, prima di ogni altro controllo; quella mostrata nel pannello serve solo a vedere subito l'esito.

- **La prima volta**: con *Firma NetMon* crei la chiave (vedi `tools/mac/LEGGIMI.md`). Quando firmi un
  pacchetto che non contiene ancora una chiave pubblica, l'app ci aggiunge la tua
  (`server/release-key.pub`) prima di firmarlo; puoi anche metterla nel repository, così ogni zip la ha già.
  Il primo pacchetto con la chiave, firmato con l'app, la installa sulla VM (*Prima chiave di rilascio di questa VM: …* tra i controlli: confronta
  l'impronta con quella dell'app). Da lì in poi la VM accetta solo pacchetti firmati con quella chiave.
  L'impronta della chiave installata è in alto a destra nella sezione (*chiave di rilascio abcd ef01 …*).
- **Senza chiave**: se la VM non ha ancora una chiave e il pacchetto non ne contiene una, il pannello lo
  rifiuta. Resta l'aggiornamento a mano sulla VM (`sudo bash netmon/server/installa-server.sh --aggiorna`),
  che chi entra via SSH come root può sempre fare.
- **Cambiare chiave**: metti la nuova chiave pubblica in `server/release-key.pub` e firma quel pacchetto con
  la chiave **vecchia**: installandolo la VM passa alla nuova. In alternativa, a mano via SSH con
  `installa-server.sh --aggiorna`.
- **Chiave o password perse**: dal pannello non si installa più nulla. Crea una chiave nuova e installa a
  mano, via SSH, un pacchetto che la contiene. Per evitarlo salva una copia di riserva dall'app.
- **Passaggio alla 1.1**: la prima installazione della 1.1 dal pannello di una 1.0 non è ancora verificata
  (la fa lo script della 1.0). Conferma la nuova versione nella finestra di rollback appena hai controllato
  che funziona: un rollback rimetterebbe lo script della 1.0, senza la verifica della firma.

La **prima volta** la funzione va installata a mano (`installa-server.sh --aggiorna`): installa lo script di
sistema, il verificatore e il permesso relativo. Da lì in poi si aggiorna tutto dalla pagina.

**Programmare una manutenzione della VM.** Sotto *Manutenzione della VM*, *Programma una manutenzione della
VM*: scegli **cosa** (aggiornamento del sistema operativo oppure riavvio), data e ora, e premi *Programma*
(serve la password nel campo sopra).

- **Aggiornamento del sistema operativo**: all'ora stabilita parte lo stesso aggiornamento del pulsante
  *Aggiorna sistema* (`apt update` e `apt upgrade`); alla fine la VM si riavvia da sola **solo se serve**
  (per esempio per un nuovo kernel).
- **Riavvio della VM**: riavvia e basta, senza aggiornare nulla. Utile per programmare un fermo in un orario
  in cui non dà fastidio. Non ha una fase "in corso" da seguire — a riavviarsi è il server stesso — quindi
  l'esito viene scritto prima di lanciarlo e la programmazione risulta già conclusa al ritorno.

In entrambi i casi, se programmati per una data e un'ora, gli amministratori ricevono un'email subito e un
promemoria un'ora prima, e gli utenti con almeno una sonda vengono avvisati della manutenzione sui loro canali.
Con *Adesso* non parte nessun avviso. Si può avere una sola manutenzione della
VM in attesa; finché non parte si annulla dalla tabella sotto il pulsante. Il riavvio programmato richiede il
permesso di riavvio in `/etc/sudoers.d/netmon-vm`: se manca, il pulsante resta disattivato.

**Sonde › Elenco sonde.** Tutte le sonde collegate a un account, di tutti gli utenti: account, stato (in linea, in
ritardo, offline, **in pausa**), versione di netmon (in giallo quelle da aggiornare), ultimo report e operazione
in corso o programmata. *In pausa* è la sonda che il suo proprietario ha messo a tacere apposta (Impostazioni
→ Sonde): spiega perché una sonda muta non ha fatto scattare nessun avviso, che altrimenti sembrerebbe un
guasto del monitoraggio. Passandoci sopra si legge fino a quando e perché. Il campo in alto filtra per nome,
account o versione; il menu accanto per stato (anche *In pausa*, *Da aggiornare* e *Con un'operazione in
corso*). Con le caselle scegli le sonde; la casella nell'intestazione
seleziona tutte quelle mostrate dal filtro.

Sotto la tabella, *Programma un aggiornamento*:

- **Aggiornamento**: *netmon* (porta le sonde alla versione del server; quelle già aggiornate vengono
  saltate) oppure *Sistema operativo (apt)*, dopo il quale ogni sonda si riavvia da sola solo se serve;
- **Sonde**: tutte oppure quelle selezionate;
- **Quando**: adesso oppure data e ora.

Le sonde ricevono il comando al controllo successivo; quelle spente o scollegate appena tornano in linea.
L'elenco *Registro aggiornamenti sonde*, in fondo a *Sonde › Elenco sonde* sotto *Programma un aggiornamento*, mostra quelli in attesa (con *Annulla*) e gli ultimi eseguiti con
l'esito. Gli esiti di ogni sonda arrivano nel registro eventi, come per il tasto *Aggiorna* della scheda
*Stato sonda*. Nella colonna *Operazione* di ogni sonda, **Registro** apre il registro dell'ultima
operazione (lo stesso della scheda *Stato sonda* dell'utente): se un aggiornamento non riesce, la causa è
lì. Una sonda che ha già la versione del server non conta come errore: l'esito è «completato».

**Avvisi degli aggiornamenti programmati.** Valgono solo per gli aggiornamenti programmati per una **data e
un'ora**. Con **Adesso**, e con i pulsanti *Aggiorna sistema* e *Riavvia la VM* della scheda *Stato VM*, non
parte nessuna notifica, né agli utenti né agli amministratori: l'operazione compare solo nel registro eventi
(il registro amministrativo e, per le sonde, i loro *Ultimi eventi*). Se però l'aggiornamento non riesce, gli
amministratori ricevono comunque l'allarme. Appena programmi un aggiornamento per una data e un'ora: ogni utente riceve un avviso
sui suoi canali (email, Telegram, ntfy) con l'elenco delle sue sonde interessate, gli amministratori
un'email con tutto (anche per la VM). Se è programmato con più di un'ora di anticipo arriva anche un
promemoria un'ora prima; se lo annulli, arriva l'annullamento. Programmazione e annullamento compaiono
anche negli *Ultimi eventi* della pagina di stato.

**Filtri.** Anche la tabella *Amministrazione › Utenti* ha un campo per filtrare per email o stato
(attivo ora, bloccato…).

**Memoria della VM.** In *Server › Stato VM*, sotto *Salute*, **Dettaglio memoria** mostra quanta RAM usano
i programmi, quanta è cache del disco (si libera da sola quando serve) e quanta è libera, con i programmi
che occupano di più. Per quelli tipici delle VM Google che spesso non servono (Ops Agent, snapd,
ModemManager…) c'è il comando per toglierli, da lanciare a mano sulla VM se non li usi. **Libera la
memoria del server** restituisce al sistema la memoria che netmon non usa più; lo fa anche da solo ogni
ora. La percentuale *Memoria* esclude già la cache: svuotarla non la farebbe scendere.

**Registro amministrativo e avvisi agli amministratori.** In *Server › Registro amministrativo* c'è il registro
di ciò che riguarda il server e non una singola sonda: aggiornamenti programmati (VM e sonde) con il loro
esito, installazioni da pacchetto, aggiornamenti di una sonda non riusciti, **riavvii dopo un arresto
imprevisto** del server (crash, memoria esaurita, VM spenta di colpo), errori interni (al massimo un avviso
ogni 6 ore) e nuovi account. Ognuno di questi arriva anche **via email a tutti gli amministratori**. Gli
utenti non li vedono: nei loro *Ultimi eventi* ci sono solo le loro sonde.

**Avvisi di manutenzione agli utenti.** Quando programmi per una data e un'ora un aggiornamento della VM (del
sistema o di netmon da pacchetto) o il suo riavvio, **tutti gli utenti con almeno una sonda** ricevono un avviso sui loro
canali (email, Telegram, ntfy) e lo vedono negli *Ultimi eventi*: quando, e che per qualche minuto pagina e
avvisi non saranno disponibili. Arrivano anche il promemoria un'ora prima e l'eventuale annullamento. Nessun
dettaglio tecnico: quelli restano agli amministratori.

**Aggiungere un utente, rimandare il codice, cambiare l'email.** In *Amministrazione › Utenti* il tasto
**＋ Aggiungi utente** crea un invito (email, nota, validità). Finché la persona non si registra
compare nella tabella con lo stato *invitato* e, nel menu **Azioni ▾** della riga, **Reinvia codice**,
**Cambia mail**, **Dettagli del codice** ed **Elimina codice**. Lo stesso menu c'è in *Codici di accesso*;
lì, sui codici già usati per registrarsi, il menu ha anche le azioni sull'account di chi l'ha usato. *Cambia mail* serve per l'indirizzo sbagliato: il codice
di prima smette di funzionare e il nuovo parte verso il nuovo indirizzo; non si può su un invito già
usato né verso un'email già registrata.

**Rimandare un codice di accesso.** Sui codici legati a un'email c'è il pulsante **Reinvia codice**,
per chi non ha ricevuto l'invito o l'ha perso. Attenzione a cosa fa davvero: il codice di prima
**non si può recuperare**, perché il server ne conserva solo l'impronta. Quindi *Reinvia codice* ne crea
uno nuovo con le stesse impostazioni (stessa email, stessa nota, stessi utilizzi) e **cancella il
vecchio**: se la persona aveva ancora il vecchio link, da quel momento non funziona più. Se il
vecchio era scaduto, il nuovo riparte con 7 giorni; altrimenti conserva la scadenza che restava.

**Nuovo codice a chi ha già l'account.** Se il codice è per l'email di un account che esiste già (per
esempio *Reinvia codice* dopo che la persona si era registrata), nella tabella *Utenti* la riga del codice
ha lo stato *nuovo codice per l'account*. Chi lo usa **non crea un secondo account**: rientra nel suo, con
la password che sceglie in quel momento; sonde, storico e impostazioni restano. Le sue altre sessioni si
chiudono, come a ogni cambio password, e gli amministratori ricevono l'avviso *Account riattivato*. Se
l'account è bloccato il codice non lo sblocca.

**Dettagli di un codice.** Dal **2.0**, cliccando un codice nella tabella si apre un riquadro con
tutte le sue impostazioni: nota, email, stato (valido/scaduto/esaurito), chi e quando l'ha creato,
scadenza, utilizzi (con l'ultima registrazione), e gli **ultimi quattro caratteri** — il codice
completo non si vede mai, per lo stesso motivo di sopra. Da lì partono gli stessi tasti
*Reinvia codice*, *Cambia mail* ed *Elimina* della riga.

**Conservazione scelta dall'utente.** Ogni utente sceglie per quanto tenere lo storico delle sue sonde in
*Impostazioni → Account e backup → Conservazione dei dati*: **Default** (quella del server), un numero di
**giorni, settimane o mesi**, oppure **tutto, senza scadenza**. Può allungarla o accorciarla quando vuole
(serve la sua password); accorciando, quello che ne resta fuori si elimina subito. Nello stesso riquadro
**Elimina lo storico adesso** cancella tutte le misure e gli eventi delle sue sonde (password e la parola
ELIMINA): sonde, configurazione e account restano. L'informativa sulla privacy mostra all'utente collegato
la durata che vale per lui.

**Limiti per utente.** Ogni riga della tabella *Utenti* ha il tasto **Limiti**: quante **sonde** può
collegare quell'account, quanti **FRITZ!Box** e quanti **dispositivi monitorati** **in tutto**, cioè sommando
tutte le sue sonde (ogni FRITZ!Box conta, il primo di ogni sonda compreso). Dal 19 ottobre 2026 i limiti sono
totali per l'account; prima FRITZ!Box e dispositivi erano per ogni sonda (i valori scelti a mano allora sono
stati convertiti in totali moltiplicandoli per le sonde dell'account).

Il campo **Piano** li sceglie in un colpo solo:

| Piano | Sonde | FRITZ!Box in tutto | Dispositivi in tutto |
|---|---|---|---|
| Basso | 1 | 1 | 5 |
| Medio | 2 | 2 | 15 |
| Alto | 4 | 4 | 45 |
| Personalizzato | scelte a mano | scelti a mano | scelti a mano |
| Nessun piano | a scelta (predefinito 50) | 50 | 500 |

**Come si dividono tra le sonde.** Le sonde si servono **in ordine di creazione**: la prima usa quello che le
serve, la seconda quello che resta, e così via. Esempio con *Medio* (15 dispositivi): se la prima sonda ne ha
10, la seconda può averne 5. Ogni sonda riceve dal server la sua parte (la pagina locale della sonda e la
finestra *Dispositivi* non lasciano andare oltre) e la riceve di nuovo da sola quando cambiano le altre. Il
server, comunque, non tiene i FRITZ!Box e i dispositivi oltre il limite anche se una sonda li manda.

Con *Basso*, *Medio* e *Alto* i tre campi sono bloccati sui valori del piano. **I nuovi account nascono con
il piano Basso** (si cambia con `NEW_USER_PLAN` nel `.env`: `medio`, `alto`, oppure vuoto per nessun piano);
gli account che c'erano già restano come sono. Abbassando il numero di sonde, quelle già collegate oltre il
limite continuano a funzionare: semplicemente non se ne possono aggiungere altre. Il piano ha la sua colonna
(*Piano*) nella tabella *Utenti*, come la *Scadenza*. Gli account con
numeri scelti prima dei piani risultano *Personalizzato*.

**Scadenza dell'account.** Dal menu **Azioni ▾** di un utente, **Scadenza…**: *Attiva la scadenza
dell'account* e scegli il giorno (scade alla fine di quel giorno, nel fuso orario dell'utente). L'utente
riceve un'**email subito** (con la data) e un **promemoria 7 giorni prima**; se la data è a meno di 7
giorni basta la prima. Se sposti una scadenza già attiva l'email dice da quale data a quale
(*Scadenza dell'account spostata*). Tutte queste email hanno la data anche nell'oggetto, così non si
confondono tra loro quando il programma di posta le raggruppa. Alla scadenza l'account si **blocca da solo** (entro 5 minuti): l'utente riceve
l'email *Account scaduto*, gli amministratori l'avviso *[INFO] Account scaduto*, le sessioni si chiudono e
all'accesso compare *Questo account è scaduto*. Come con *Blocca*, le sonde continuano a misurare e lo
storico resta, ma niente avvisi. La colonna *Scadenza* mostra la data (in rosso *scaduto il …*), e l'utente vede
la data in *Impostazioni → Account e backup → Account*.

Per rinnovare un account scaduto sposta più avanti la scadenza (parte una nuova email) oppure toglila
(togli la spunta): l'account si sblocca da solo. *Sblocca* da solo non basta finché la data è passata.
Un account bloccato a mano con *Blocca* resta bloccato anche se cambi la scadenza.

*Se si superano i limiti*: a limite raggiunto la pagina di stato (finestra *Dispositivi*) e la
pagina locale della sonda non lasciano aggiungere altro, e il server rifiuta un salvataggio con più
dispositivi. Se l'amministratore abbassa un limite quando l'utente ne ha già di più, i FRITZ!Box
oltre il limite (delle sonde più recenti) smettono di essere letti e **gli ultimi dispositivi della lista**
(nell'ordine scelto con *Ordine*; quelli in pausa non contano) smettono di essere controllati: non
compaiono più nella pagina di stato né in quella della sonda, ma restano salvati sul server e
tornano da soli se il limite si alza o se se ne tolgono altri. La sonda resta modificabile:
togliere o rinominare dispositivi è sempre possibile.

La pagina dell'utente mostra quanto gli resta — *Massimo 50 sonde per il tuo account: 3 collegate.
Ogni sonda può controllare fino a 30 dispositivi.* — e aggiunge il limite delle FRITZ!Box alla nota
del riquadro *FRITZ!Box*. Anche la pagina locale della sonda, sotto *Dispositivi*, riporta i limiti
dell'account e cosa succede se si superano.

**Chiave del server.** È l'`API_TOKEN` del file `.env`. Serve **solo a creare il primo account in
assoluto** di una macchina appena installata. Non vale per registrarsi (serve un codice di accesso)
e **non vale per le sonde**, che si collegano solo con il loro token personale. Non si rigenera dalla
pagina: si cambia sulla VM, modificando `API_TOKEN` nel `.env` e riavviando il servizio; le sonde
non se ne accorgono.

Se una sonda prova a collegarsi con la chiave del server viene rifiutata, e agli amministratori
arriva l'avviso *Una sonda usa ancora la chiave del server* con il suo nome. Per rimetterla in
funzione il proprietario genera un token nella pagina (Impostazioni → Sonde: *Aggiungi una
sonda*, oppure *Nuovo token* se è già in elenco) e lo inserisce nella pagina locale della sonda,
sezione *Server → Token*. Per vedere dalla VM quali sonde usano il loro token:
`sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py sonde`, colonna *Token*.

**Ritrovare la chiave del server.** È salvata solo sulla VM, nel file `/opt/netmon/.env`,
leggibile solo con i permessi di amministratore:

```bash
sudo grep '^API_TOKEN=' /opt/netmon/.env
```

Il valore dopo `API_TOKEN=` è la chiave in uso. Se modifichi il file, riavvia il servizio
(`sudo systemctl restart netmon-server`) perché la nuova chiave venga letta.

**Registrazione.** Nella schermata di accesso, *Non hai un account? Registrati*: codice di
accesso, email e password (almeno 10 caratteri). Solo per il primo account di una macchina appena
installata, al posto del codice si usa la chiave del server. Poi si
accede con email e password; con
*Ricordami* la sessione dura 30 giorni, altrimenti 12 ore. Dopo 5 tentativi sbagliati l'accesso
si blocca per 15 minuti. Contano anche i tentativi ancora in corso: mandarne molti insieme non
aggira il limite. Con un codice di accesso sbagliato la risposta è sempre *Codice di accesso non
valido*, anche se l'email ha già un account: così non si può scoprire chi è registrato.

**Grafici e Dashboard.** Lo storico si legge senza fermare il resto del server: mentre si
calcola un grafico lungo (per esempio 30 giorni), i report delle sonde continuano ad arrivare.
Ogni account calcola al massimo 2 grafici alla volta e ne mette in coda fino a 8; oltre, la
pagina risponde *Troppe richieste di grafici insieme* e basta riprovare poco dopo.

**Token delle sonde.** Ogni sonda ha un token personale legato al suo proprietario: una sonda
non può scrivere dati al posto di un'altra. Il token si genera **solo nella pagina**
(Impostazioni → Sonde) e si inserisce nella pagina locale della sonda; il server non ne assegna
più da solo. È l'unica credenziale che una sonda accetta.

**Un token, un dispositivo.** Ogni sonda manda al server un proprio identificativo (un numero
casuale salvato sulla sonda, legato alle sue schede di rete: un'immagine della scheda SD copiata su
un altro dispositivo ne crea uno nuovo). Il primo dispositivo che usa un token ne diventa il
titolare e i suoi dati vengono sempre tenuti; se con lo stesso token si presenta un secondo
dispositivo, i suoi dati vengono **scartati** (non entrano nello storico, non fanno partire avvisi,
non ricevono configurazione né comandi) e:

- l'utente riceve l'avviso *Due dispositivi usano il token della sonda «…»* sui suoi canali e negli
  *Ultimi eventi*, ripetuto ogni 12 ore finché il secondo dispositivo continua a provare;
- in *Dashboard* (in cima) e in *Stato rete › Monitor dispositivi* (sotto il nome della sonda) un
  riquadro giallo indica i due dispositivi, con nome e IP locale, finché il secondo ha provato negli
  ultimi 30 minuti. **Aggiungi una sonda** porta a *Impostazioni → Sonde* per creare il token del
  secondo dispositivo; **Usa il nuovo dispositivo** (dopo una sostituzione) fa diventare titolare il
  secondo, e da lì vengono scartati i dati del primo, se resta acceso;
- la pagina locale del secondo dispositivo mostra, nella sezione *Server*, *Token già in uso da
  un'altra sonda…*; le sue misure restano nel suo buffer e arrivano al server se diventa titolare;
- nel pannello, *Utenti* segnala l'account con *⚠ token doppio* e un riepilogo in cima, senza
  notifiche all'amministrazione.

Un **nuovo token** (da *Impostazioni → Sonde* o dal pannello) azzera il titolare: lo diventa il
primo dispositivo che usa il token nuovo. Le sonde di versioni precedenti, che non mandano
l'identificativo, non vengono controllate.

**Impostazioni → Sonde**:

- **Scarica lo zip della sonda** (link sotto *Crea sonda*, oppure `/scarica-sonda`): il programma da
  installare sulla sonda, solo la parte della sonda e sempre nella versione installata sul server.
  Si scarica solo dopo l'accesso; il link è anche nell'email d'invito (aperto senza accesso, porta
  alla pagina di accesso e dopo scarica lo zip). L'email d'invito riporta anche il **dominio da
  configurare sulla sonda** (quello della VM dell'utente, per esempio `vm1.netmonhome.net`) e il link
  alla guida PDF per usare **Home Assistant** come sonda (repository `netmon-homeassistant`).
- **Aggiungi una sonda**: scegli il nome e ricevi il token (mostrato una sola volta) e l'**indirizzo
  del server** a cui la sonda deve mandare i dati (quello della tua VM, es.
  `https://vm1.netmonhome.net/api/report`), ognuno con il suo tasto *Copia*: vanno nella pagina
  locale della nuova sonda, sezione *Server*. Lo stesso riquadro compare con *Nuovo token*.
- **Collega una sonda esistente**: per una sonda rimasta senza proprietario (per esempio dopo
  l'eliminazione di un account che ha lasciato le sue sonde sul server). Inserisci il suo token,
  che trovi nella sua pagina locale.
- **Rinomina**: il nuovo nome compare subito e arriva alla sonda al controllo successivo. Lo
  storico non cambia, perché ogni sonda ha un identificativo interno indipendente dal nome.
- **Colore**: il colore della sonda nella *Dashboard* (gruppo della sonda) e nei grafici dello
  *SpeedTest*. Otto colori a scelta oppure *Automatico* (secondo la posizione della sonda); il pallino
  accanto al nome della sonda mostra quello attuale.
- **Metti in pausa**: per i periodi in cui sai già che la sonda non può rispondere — casa chiusa,
  corrente staccata, lavori sulla linea. In pausa la sonda **non manda nessun avviso**, né per sé
  né per i suoi dispositivi, e non scrive niente negli *Ultimi eventi*: altrimenti la pagina si
  riempirebbe di righe rosse per una cosa che sai già. I dati invece **continuano ad arrivare e a
  essere salvati**: lo storico non ha buchi, e nella pagina la sonda resta visibile con la spia
  gialla e la scritta *in pausa*.

  Scegli per quanto (da 4 ore a un mese, oppure *finché non la riprendo*) e, se vuoi, una nota per
  ricordarti il perché: te la ritrovi scritta accanto alla sonda. Alla scadenza riprende da sola,
  oppure la riprendi quando vuoi con lo stesso tasto.

  Quando la pausa finisce, **lo stato della sonda riparte da zero**: quello che era rotto prima
  viene segnalato di nuovo, invece di restare zitto perché «non è cambiato niente». E la sonda ha
  il tempo di rifarsi viva prima di essere dichiarata muta.
- **Reti Wi-Fi**: le reti salvate sulla sonda, da aggiungere, provare o togliere (vedi *Reti Wi-Fi della sonda*).
- **Nuovo token**: il vecchio smette subito di funzionare; va inserito il nuovo nella sonda.
- **Elimina**: rimuove la sonda con storico ed eventi (serve la password).

Quando i comandi non stanno sulla riga della sonda (schermo stretto, telefono) sono raccolti nel pulsante
**Azioni ▾**.

**Notifiche.** Ognuno riceve solo gli avvisi delle proprie sonde, sui propri canali: email al
proprio indirizzo (se sul server è configurato l'invio) e, se li indica in **Impostazioni →
Notifiche**, il proprio chat ID Telegram (con il bot del server) e il proprio topic ntfy.

**Lingua.** La pagina utente e le notifiche (email, Telegram, ntfy) sono in **italiano**, **inglese**,
**tedesco** o **francese**. Prima dell'accesso la pagina si apre nella lingua del browser (italiano
se il browser usa un'altra lingua) e la si cambia con il selettore in alto nella schermata di accesso;
la lingua scelta al momento della **registrazione** diventa quella dell'account. Poi si cambia da
**Impostazioni → Account e backup → Lingua**: vale su ogni dispositivo da cui accedi e per tutte le
notifiche. Gli account esistenti restano in italiano finché non scelgono un'altra lingua. Gli eventi
salvati si mostrano nella lingua di chi guarda (quando il testo è riconosciuto); i nomi scelti da te
(dispositivi, sonde, reti) non si traducono mai. Il pannello di amministrazione ha la sua lingua,
scelta da ogni amministratore in *Il tuo account* (vedi sotto).
Per chi sviluppa: i testi stanno in italiano nel codice e le traduzioni in `server/i18n.py` (pagina utente
e notifiche) e `server/i18n_admin.py` (pannello e avvisi agli amministratori);
`python3 tools/i18n-estrai.py server --mancanti` e `python3 tools/i18n-estrai.py admin --mancanti` elencano
quelli nuovi ancora da tradurre.

**Fuso orario.** Nello stesso riquadro (**Impostazioni → Account e backup → Lingua e fuso orario**) scegli
il fuso degli orari: pagina (eventi, grafici, ultimo controllo) e notifiche (per esempio l'ora di
collegamento di un ospite o di un aggiornamento programmato). Accanto a ogni fuso c'è l'ora attuale.
*Default* usa quello impostato sulla VM (`TIMEZONE` nel `.env`, di solito
Europe/Rome). Vale su ogni dispositivo da cui accedi.

**Account.** In *Account e backup* puoi cambiare password, uscire da questo dispositivo o da
tutti. Tutti gli account sono in `/opt/netmon/data/auth.db` (permessi 600): password come
impronta scrypt con sale casuale, sessioni e token delle sonde solo come impronta SHA-256.

**Eliminare l'account.** Da **Impostazioni** → *Account e backup* → *Elimina account*, con
la password attuale:

- **Elimina solo l'account**: cancella email, password e sessioni. Le tue sonde restano sul
  server con i loro dati, senza proprietario, per **30 giorni**: con un nuovo account puoi
  ricollegarle con il loro token. Dopo vengono cancellate.

In tutti e due i casi ricevi un'email di conferma.
- **Elimina l'account e tutti i dati** (serve anche scrivere ELIMINA): cancella in più le tue
  sonde con storico, traffico, temperatura ed eventi, e ne revoca i token. Gli altri utenti non
  vengono toccati.

**Password dimenticata** (sulla VM):

```bash
# mostra amministratori e utenti, l'ultimo accesso e le sessioni aperte
sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py elenco
# UTENTE della pagina di stato: nuova password, scelta da te
sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py password nome@dominio.it
# AMMINISTRATORE: nuova password provvisoria (e blocco azzerato). Lo stesso comando della creazione:
# su un amministratore che esiste già non ne crea un altro. Si fa anche dal pannello, in
# "Amministratori → Password dimenticata".
sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py crea-admin nome@dominio.it
# oppure ricomincia da capo: al prossimo accesso torna la schermata "Primo accesso"
sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py reset
```

## Backup e ripristino

**Dalla pagina di stato (VM)**: **Impostazioni** → scheda *Account e backup* → *Scarica backup*. Scarica un file
`netmon-server-DATA.json` con, per ogni sonda, dispositivi, ordine, frequenza, soglie e
impostazioni delle notifiche. Non contiene segreti.

**Dalla pagina locale della sonda**: sezione *Backup e ripristino* → **Scarica backup**.
Il file `netmon-sonda-NOME-DATA.json` contiene la configurazione completa, compresi token del
server e password del FRITZ!Box: conservalo in un posto sicuro.

**Ripristino** (solo dalla pagina locale della sonda): **Ripristina da file…** accetta
entrambi i tipi di backup.

- Backup della sonda: ripristina tutto, collegamento al server e FRITZ!Box compresi.
- Backup del server: ripristina dispositivi, ordine, frequenza e soglie; collegamento al
  server e FRITZ!Box restano quelli attuali. Se il file contiene più sonde, la pagina usa
  quella con lo stesso nome o ti chiede quale scegliere.

Il ripristino incrementa la revisione della configurazione, quindi la sonda lo applica al
controllo successivo e lo comunica al server. Le impostazioni delle notifiche sugli ospiti
sono gestite dal server e non vengono ripristinate dalla sonda: se servono, riattivale da Impostazioni → *Notifiche*.

## Privacy e GDPR

Se dai account ad altre persone, sei il titolare del trattamento dei loro dati. netmon aiuta così:

- **Scarica i miei dati** (*Impostazioni → Account e backup → I tuoi dati*): ogni utente scarica da solo uno
  zip con tutto ciò che il server tiene di lui (art. 15 e 20): `account.json` (email, lingua, notifiche,
  preferenze, sessioni), `sonde.json` (configurazione, avvisi, pause, ultimo stato) e, per ogni sonda, lo storico
  in CSV (eventi, ping, traffico, FRITZ!Box, SpeedTest, sistema). Password, token e codici non ci sono.
- **Eliminazione dell'account** (art. 17): con l'account si tolgono anche l'email dal registro amministrativo
  («Nuovo account: …» diventa «(account eliminato)») e dagli inviti; un invito ancora valido per
  quell'indirizzo si revoca. I database sovrascrivono i dati cancellati (`secure_delete`), quindi non restano
  leggibili nei file.
- **Durate**: storico secondo *Conservazione dei dati*, registro amministrativo un anno (`ADMIN_EVENTS_DAYS`),
  registro di sistema 30 giorni e al massimo 200 MB (lo imposta `installa-server.sh` in
  `/etc/systemd/journald.conf.d/netmon.conf`), sonde senza account 30 giorni (`ORPHAN_DAYS`).
- **Nessun servizio esterno nella pagina**: i caratteri (Roboto, licenza SIL OFL 1.1) li servono il server e la
  sonda; prima arrivavano da Google Fonts, che riceveva l'IP di ogni visitatore.
- **Informativa** (art. 13): `server/privacy.html`, si installa con il server ed è su `https://TUO-DOMINIO/privacy`.
  Il link *Informativa sulla privacy* sta sempre in fondo a ogni pagina (pagina di stato, pannello `/admin` e le
  loro schermate di accesso, pagina locale della sonda, che apre l'informativa del suo server), in piccolo.
  È in italiano, inglese, tedesco e francese (fa fede l'italiano), con un selettore della lingua in alto: si apre
  nella lingua dell'account o del browser, oppure in quella della sonda. Contiene: titolare indicato come gestore del servizio, senza nome (info.netmonitor@gmail.com), un solo
  server con account, sonde e storico, controlli di sicurezza, server su
  Google Cloud nell'UE, email con Brevo (UE), nessuna copia di sicurezza, **fase di prova** fino a nuova
  comunicazione con cancellazione dei dati entro 30 giorni dalla fine. La durata dello storico la scrive il server al
  posto di `__NETMON_CONSERVAZIONE_IT__` (e `_EN`, `_DE`, `_FR`), quindi resta giusta anche se cambi *Conservazione dei dati*; se cambi le
  altre durate nel `.env`, aggiorna la sezione 6 in tutte e quattro le lingue. Per cambiarla senza un aggiornamento, metti la tua versione in
  `/opt/netmon/data/privacy.html`: ha la precedenza e gli aggiornamenti non la toccano.

Restano a te le parti organizzative: contratto sul trattamento dei dati (art. 28) con chi ospita la VM e con il
servizio email, un breve registro dei trattamenti (art. 30) e cosa fare in caso di violazione (art. 33).

## 8. Aggiornare i file in futuro

**Versione.** Ogni file del pacchetto riporta la versione, nel formato `1.1.aaaammgg-hhmmss` (data e ora
italiana del rilascio). La numerazione è ripartita da `1.0` il 12 ottobre 2026 (prima era `2.1.…` e `2.0.…`);
dal 14 ottobre 2026 è `1.1`, con la firma dell'autore sui pacchetti. Per sapere se è tutto allineato:

- **Server**: in fondo alla pagina di stato e alla pagina `/admin` (`netmon 2.0.…`), oppure
  aprendo `https://netmonhome.net/health`.
- **Sonde**: *Stato sonda* → *Sonda netmon* → *Versione*. Se è diversa da quella del server
  compare in giallo con la scritta *aggiorna la sonda*. Anche la pagina locale della sonda la
  mostra, nella sezione *Sistema* e in fondo alla pagina.
- **File per file**, sulla VM o sulla sonda:

  ```bash
  grep -H '__version__ = ' /opt/netmon/*.py        # VM
  grep -H '__version__ = ' /opt/netprobe/*.py      # sonda
  ```

L'aggiornamento guidato mostra alla fine *versione vecchia → nuova*.

**Preparare un rilascio.** Lo script `tools/nuova-versione.py` (da dentro la cartella
`netmon`) alza la versione in **tutti** i file e crea **sempre** la zip `../netmon-light-<versione>.zip`,
controllata da `pkgcheck.py` (contenuto, link, sintassi, versione uguale in ogni programma). Lo zip
contiene solo ciò che serve a installare e aggiornare: `VERSION`, `server/` e `probe/`. Test,
strumenti (*Firma NetMon*, questo script) e documenti restano nel repository. Il pacchetto che la VM
prepara per le sonde contiene a sua volta solo `VERSION` e `probe/`:

```bash
python3 tools/nuova-versione.py      # versione con data e ora italiana di adesso, e zip nuova
```

Senza argomento usa l'ora italiana: una versione scritta a mano con l'ora UTC può risultare più
vecchia dell'ultima e il pannello la rifiuterebbe. Il nome dello zip è sempre uguale alla versione
che contiene.

**Ogni zip porta la sua versione**: a ogni modifica, anche di un solo carattere, si alza la
versione (il pannello accetta solo versioni più alte dell'installata). Scrivi prima le novità
nel CHANGELOG con la versione che vuoi, poi lancia lo script, così pacchetto e CHANGELOG
restano allineati.

**Firmare il rilascio.** Lo zip va firmato sul tuo computer con *Firma NetMon*:
- **Mac** (`tools/mac/Firma NetMon.app`) e **Windows** (`tools/windows/FirmaNetMon.exe`, un solo file senza
  installazione): si apre una pagina nel browser, servita solo al tuo computer; scegli lo zip, scrivi la
  password e premi *Firma*: il browser scarica il `.sig` (e lo zip con la tua chiave, se non la conteneva
  ancora). Su un Mac troppo vecchio per i programmi compilati, l'app usa invece le finestre di sistema e
  scrive il `.sig` accanto allo zip. *Firma NetMon* si prende dal repository: lo zip del pacchetto non la
  contiene.

Nel pannello carichi i due file insieme. Lo script avvisa se nel repository
manca `server/release-key.pub` (la chiave pubblica che la VM usa per verificare la firma).

**Dal pannello (normale).** Si aggiorna tutto dal browser: `/admin` → *Server ›
Aggiornamento Netmon* per la VM (vedi *Aggiornamento Netmon (VM)*, con la finestra di rollback di 4
ore), poi le sonde con *Aggiorna netmon* (vedi *Riavvio e aggiornamento*).

**Con gli script, sulla VM e sulla sonda.** Servono la prima volta (per installare script e
permessi degli aggiornamenti dal pannello), aggiornando da una 1.x, o se il pannello non funziona.
Prima la VM, poi le sonde:

```bash
cd ~ && rm -rf ~/netmon && unzip -q netmon-light-<versione>.zip
sudo bash ~/netmon/server/installa-server.sh --aggiorna   # sulla VM
```

```bash
sudo bash ~/probe/installa-sonda.sh --aggiorna            # sulla sonda, dopo aver copiato la nuova cartella probe
```

Copiano i file, aggiornano librerie e permessi e riavviano i servizi: configurazione, account e
storico restano. Un aggiornamento a mano sulla VM chiude l'eventuale finestra di rollback aperta.

**Non copiare file singoli.** Tutti i file di un pacchetto hanno la stessa versione, sono di root
e (per la sonda) firmati dalla VM: un file copiato a mano da un'altra versione rompe i controlli di
versione e di firma, e gli aggiornamenti successivi lo rifiutano. Aggiorna sempre l'intero
pacchetto, con il pannello o con gli script.

---

### Disinstallare la sonda

Prima togli la sonda dal tuo account (*Impostazioni → Sonde → Elimina*:
spariscono anche storico ed eventi), poi **dalla pagina locale della sonda**, sezione
**Disinstalla sonda**: scrivi `DISINSTALLA`, rimetti la password di accesso alla sonda e premi
**Disinstalla la sonda** (la pagina smette di rispondere pochi secondi dopo; una copia della
configurazione resta in `/root` sulla sonda, per averla sul PC usa prima *Scarica backup*).
In alternativa, sulla sonda:

```bash
sudo bash ~/probe/installa-sonda.sh --disinstalla
```

Lo script elenca cosa toglie, chiede se tenere una copia della configurazione in `/root` (contiene
token e password, leggibile solo da root) e procede solo se scrivi `DISINSTALLA`. Toglie: i servizi
`netmon-probe` e `netmon-config` (fermati, disattivati e tolti da `/etc/systemd/system`),
`/opt/netprobe` (programmi e ambiente Python), `/etc/netprobe` (configurazione, token e password),
`/var/lib/netprobe` e `/var/lib/netprobe-sys` (misure non inviate, cache, registri),
`/usr/local/share/netmon` (chiave degli aggiornamenti), `/usr/local/lib/netmon` (verificatore;
resta se sulla stessa macchina c'è anche il server netmon), gli script `netprobe-*` in
`/usr/local/sbin` (compreso `netprobe-uninstall`, che fa la disinstallazione in entrambi i casi), i permessi `/etc/sudoers.d/netprobe`, l'utente `netprobe` e
`/root/netmon-sonda-riepilogo.txt`. Restano i pacchetti di sistema (Python, ping, curl, openssl…),
le reti Wi-Fi salvate (`nmcli connection show`; toglierle farebbe perdere la rete), il registro
`/var/log/netmon-installazione.log` e la cartella `~/probe`, che puoi cancellare a mano. Se è in
corso un aggiornamento o un cambio di rete Wi-Fi della sonda, lo script si ferma e chiede di riprovare.

### Esportare e importare un utente

*Utenti → Azioni ▾ → Esporta (file cifrato)* scarica un file `.netmon` con l'utente, le sue sonde e tutto lo
storico, **cifrato con una password che scegli tu** (almeno 12 caratteri; *Genera* propone sei parole a caso,
facili da dettare). Senza quella password il file non si apre e non si legge nulla, nemmeno l'email: non la
salvano né il server né il file, quindi comunicala a chi importa per un canale diverso da quello del file.
Cifratura: AES-256-GCM a blocchi, con la chiave ricavata dalla password con scrypt; un file modificato o
troncato viene rifiutato.

*Utenti → ⤒ Importa un utente* lo carica con la sua password (sbagliandola si riprova senza ricaricare il
file); anche gli zip in chiaro delle versioni precedenti si importano ancora, con un avviso. L'utente entra
con la stessa password e le sonde continuano con il loro token; restano in pausa per un'ora, il tempo di
puntarle al nuovo indirizzo (`sudo bash ~/netmon/probe/installa-sonda.sh`, opzione **2) Riconfigurare**,
oppure il vecchio nome DNS verso questa VM con `OLD_HOSTS`, vedi *Cambiare dominio*). Serve per portare un
utente da un altro server netmon (anche da una VM di un'installazione NetMon con gateway) o come copia di
sicurezza.

Se **l'account esiste già**, *Importa un utente* porta **solo lo storico** (misure, eventi, traffico,
speedtest, FRITZ!Box): account, sonde, token e impostazioni restano quelli del server. Per ogni sonda del
backup scegli su quale sonda dell'account va il suo storico (proposta: stessa sonda o stesso nome;
*Non importare* per saltarla), poi **Unisci** (aggiunge ciò che manca, ripeterlo non crea doppioni) oppure
**Sovrascrivi** (nel periodo coperto dal backup valgono i dati del backup).

### Cambiare dominio

Per esempio da `netmon-public.com` a `netmonhome.net`. Le sonde stanno a casa degli utenti e hanno in
`config.yaml` l'indirizzo del server: il vecchio nome resta attivo e le rimanda al nuovo, così passano da sole.

1. Nel DNS del nuovo dominio crea il record A verso la VM. **Non togliere** quello vecchio.
2. Sulla VM: `sudo bash ~/netmon/server/installa-server.sh`, scelta **2) Riconfigurare**, e scrivi il nuovo dominio.

L'installatore scrive i nomi precedenti in `OLD_HOSTS` nel `.env` e li lascia nel Caddyfile accanto a quello
nuovo, con il loro certificato. Chi arriva a un vecchio nome è rimandato al nuovo indirizzo: i browser con un
reindirizzamento permanente (gli utenti rientrano una volta, perché la sessione vale per il nome), le sonde con
una risposta «spostata» (410 con il nuovo indirizzo), e scrivono il nuovo indirizzo in `config.yaml` da sole.
Vale per le sonde con i programmi dal 13 ottobre 2026 (pomeriggio) in poi; le più vecchie si aggiornano prima,
oppure si cambia l'indirizzo a mano (`installa-sonda.sh`, **2) Riconfigurare**). Il record DNS vecchio si
toglie quando in *Sonde › Elenco sonde* tutte le sonde scrivono di nuovo: allora cancella la riga `OLD_HOSTS=`
dal `.env` e rilancia lo stesso comando del passo 2.

## 9. Risoluzione problemi

| Sintomo | Causa e soluzione |
|---|---|
| `netmon-server` fallisce con *Result: resources* | Manca `/opt/netmon/.env`. È un file nascosto: controlla con `ls -la /opt/netmon`. Per ricrearlo rilancia `sudo bash netmon/server/installa-server.sh` e scegli *Riconfigurare*. |
| `netmon-server` fallisce con *exit-code* | `sudo journalctl -u netmon-server -n 30` mostra l'errore. Se hai modificato il `.env` a mano, controlla che non ci siano commenti sulla stessa riga di un valore. |
| La sonda riceve `500` | Errore del server: guarda `sudo journalctl -u netmon-server -n 50`. Per rimettere a posto file e permessi: `sudo bash netmon/server/installa-server.sh --aggiorna`. |
| La sonda riceve `401` | Il token non è valido, oppure è la chiave del server (che non vale per le sonde). Genera un token nella pagina, Impostazioni → Sonde, e inseriscilo nella pagina locale della sonda, sezione *Server*. |
| La sonda riceve `429` | Troppi report in poco tempo: di solito una copia di `probe.py` lanciata a mano oltre al servizio. Vedi la riga *IP e RTT* qui sotto. |
| *Aggiornamento Netmon*: *Mancano file necessari* o *Percorsi non ammessi: NetMon-main/…* | Hai caricato il «Download ZIP» di GitHub, che ha la cartella `NetMon-main/` invece di `netmon/` (e il codice di `main`, non quello della PR). Serve lo zip del rilascio `netmon-light-<versione>.zip`, creato da `python3 tools/nuova-versione.py`. I file nascosti del Mac (`__MACOSX/`, `._*`, `.DS_Store`) non sono un problema: vengono ignorati. |
| *Aggiornamento Netmon*: *Manca la firma dell'autore* | Hai selezionato solo lo zip: seleziona insieme lo zip e il suo `.sig` (tieni premuto ⌘ sul Mac). Il `.sig` lo crea *Firma NetMon* accanto allo zip. |
| *Aggiornamento Netmon*: *Firma dell'autore NON valida* | Lo zip è stato modificato dopo la firma (riscaricalo e rifirmalo), oppure è firmato con una chiave diversa da quella della VM: l'impronta nel messaggio è quella della VM, confrontala con quella di *Firma NetMon*. Firmi da più computer (Mac e Windows)? Devono avere la stessa chiave: sul computer giusto *Salva una copia di riserva*, sull'altro *Usa la chiave di un altro computer* (vedi `tools/windows/LEGGIMI.md`, *Firmare da più computer*). |
| *La VM non ha ancora la chiave di rilascio e il pacchetto non la contiene* | Firma lo zip con la versione aggiornata di *Firma NetMon* (in `tools/mac` del repository: lo zip non contiene gli strumenti): aggiunge la tua chiave pubblica al pacchetto e poi lo firma. Ricarica lo zip con il **nuovo** `.sig`. Oppure aggiorna a mano via SSH con `installa-server.sh --aggiorna`. |
| Caddy non parte o `reload` fallisce | `sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`. Errore tipico: manca lo spazio prima della `{` (vedi A4). |
| Caddy: *Timeout during connect (likely firewall problem)* | Porte 80/443 chiuse nel pannello del provider (passo A1) o nel firewall della VM: `sudo ufw status`, poi `sudo ufw allow 80,443/tcp`. |
| **Oracle Cloud**: HTTPS va ma `http://dominio` resta senza risposta, o niente risponde | Nella console, *Networking → Virtual Cloud Networks →* VCN *→ Security Lists* della subnet della VM: regole *Ingress* da `0.0.0.0/0` per TCP 80 e 443 (*Source Port* vuota; anche nel *Network Security Group*, se la VM ne ha uno). Sulle immagini Oracle l'installatore apre 80 e 443 nel loro firewall (`iptables`, `/etc/iptables/rules.v4`) senza installare `ufw`, che disinstallerebbe `netfilter-persistent`. Controllo: `sudo iptables -L INPUT -n --line-numbers` (80 e 443 prima del `REJECT`). |
| Il sito va in timeout dal browser | Come sopra. Prova anche da rete mobile per escludere la rete dell'ufficio. |
| Installazione della sonda: *Permessi di riavvio e aggiornamenti* fallisce con *cannot create regular file '/etc/sudoers.d/…'* | Sul sistema manca il pacchetto `sudo` (installazioni minime, container) e lo script è di una versione precedente: con quello nuovo l'installazione si completa lo stesso e dice cosa non funziona (vedi *Senza `sudo`* in C2). Per avere anche le operazioni da remoto: `apt-get install -y sudo` e rilancia l'installazione. |
| *Stato sonda*: *Aggiornamenti dal server: non disponibili* | Sulla sonda manca `sudo`: `apt-get install -y sudo`, poi `installa-sonda.sh --aggiorna`. Fino ad allora la sonda si aggiorna solo a mano. |
| *Unit netmon-probe.service not found* | Sei sulla VM invece che sulla sonda (controlla `hostname`), oppure la sonda non è installata: `sudo bash ~/probe/installa-sonda.sh`. |
| IP e RTT mostrano "—" | Sulla sonda gira una versione vecchia di `probe.py`, o una copia lanciata a mano. Controlla con `ps aux \| grep [p]robe.py`, chiudi le copie manuali e riavvia il servizio (`sudo systemctl restart netmon-probe`). |
| Un dispositivo resta *modifiche in attesa* | La sonda non ha ancora ricevuto la configurazione: controlla che sia online. Se l'account ha raggiunto il limite di dispositivi, quelli oltre il limite non vengono controllati (vedi *Limiti per utente*). |
| *Aggiorna netmon* dice *Funzione non ancora installata* o *Permesso mancante* | Sulla sonda: `sudo bash ~/probe/installa-sonda.sh --aggiorna`, una volta. |
| Nessuna notifica | Sulla VM lancia `sudo journalctl -u netmon-server --since "-1 day" | grep -E "ALERT|Avviso|Invio"`. Per ogni avviso trovi *Avviso «…» inviato via email/telegram*, oppure il motivo per cui non è partito (*nessun canale attivo per questo tipo*, *Invio telegram fallito: …*). Gli avvisi degli amministratori compaiono nel registro come *Avviso amministrativo «…» inviato*. Per l'email, l'utente deve averla **confermata** (Impostazioni → Notifiche). Gli avvisi di aggiornamento arrivano solo per gli aggiornamenti **programmati**. |

**Sonde vecchie senza account.** Una sonda rimasta senza proprietario (per esempio dopo
l'eliminazione di un account che ha lasciato le sue sonde sul server) non la vede nessuno e non manda
avvisi. Si ricollega a un account con *Impostazioni → Sonde → Collega una sonda esistente* e il suo
token; altrimenti, dopo 30 giorni ferma, viene eliminata da sola con il suo storico (`ORPHAN_DAYS`
nel `.env`, 0 = mai). Per vedere tutte le sonde note al server, a chi appartengono e se usano il loro
token:

```bash
sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py sonde
```

**Rimuovere una sonda**: dalla pagina di stato, *Impostazioni → Sonde → Elimina* (con storico ed
eventi). Non modificare a mano `state.json` o i database: account, token e storico sono legati tra
loro.

**La sonda si blocca** (esempio con Raspberry Pi)

I servizi netmon hanno un limite di memoria (96 MB la sonda, 64 MB la pagina locale):
se lo superassero verrebbero riavviati, senza bloccare il sistema. Le cause tipiche di un
blocco sono l'alimentazione, la temperatura o la scheda SD. Controlli dopo il riavvio:

```bash
vcgencmd get_throttled          # 0x0 = nessun problema di alimentazione o temperatura
vcgencmd measure_temp
free -h
sudo journalctl -b -1 -p warning --no-pager | tail -50   # avvisi del boot precedente
sudo dmesg | grep -iE "voltage|mmc|oom|error" | tail -20
```

Per avere i log del boot precedente il diario di sistema deve essere persistente:
`sudo mkdir -p /var/log/journal && sudo systemctl restart systemd-journald`.

Per far ripartire la sonda da sola in caso di blocco, attiva il watchdog hardware:
in `/etc/systemd/system.conf` imposta `RuntimeWatchdogSec=15` e riavvia.

**Log utili**

```bash
sudo journalctl -u netmon-server -f     # VM
sudo journalctl -u caddy -f             # VM
journalctl -u netmon-probe -f           # sonda
journalctl -u netmon-config -f          # sonda
```

---

## 10. Riferimento rapido

| Cosa | Dove |
|---|---|
| File del server | VM: `/opt/netmon/` |
| Configurazione del server | VM: `/opt/netmon/.env` |
| Stato ed eventi | VM: `/opt/netmon/data/` |
| HTTPS | VM: `/etc/caddy/Caddyfile` |
| File della sonda | sonda: `/opt/netprobe/` |
| Configurazione della sonda | sonda: `/etc/netprobe/config.yaml` |
| Buffer delle misure | sonda: `/var/lib/netprobe/buffer.jsonl` |
| Password di accesso alla sonda (pagina locale) | sonda: `/etc/netprobe/web.env` |
| Chiave di firma degli aggiornamenti | VM: `/etc/netmon/update-signing.key` (solo root) |
| Chiave pubblica di rilascio (firma dell'autore sui pacchetti) | VM: `/usr/local/share/netmon/release-key.pub` |
| Chiave privata di rilascio | Mac: `~/Library/Application Support/NetMon Firma/`; Windows: `%APPDATA%\NetMon Firma\` (*Firma NetMon*) |
| Chiave per verificare gli aggiornamenti | sonda: `/usr/local/share/netmon/update-key.pub` |
| Log e stato degli aggiornamenti della sonda | sonda: `/var/lib/netprobe-sys/` (anche `zipupdate.log`) |
| Registro dell'aggiornamento da pacchetto della VM | VM: `/var/lib/netmon-vm/selfupdate.log` |
| Verificatore dei pacchetti | VM e sonda: `/usr/local/lib/netmon/pkgcheck.py` |
| Pagina di stato | `https://<dominio>` (email e password; la chiave del server solo per il primo account) |
| Pannello di amministrazione | `https://<dominio>/admin` |
| Stato e registri di rollback della VM | VM: `/var/lib/netmon-vm/rollback.json`, `rollback.status`, `selfupdate.log` |
| Registro della disinstallazione della sonda | sonda: `/root/netmon-disinstallazione.log` |
| Account e token delle sonde | VM: `/opt/netmon/data/auth.db` (gestione con `account.py`) |
| Chiave del server (solo per il primo account) | VM: `sudo grep '^API_TOKEN=' /opt/netmon/.env` |
| Controllo salute del server | `https://<dominio>/health` |
| Pagina locale della sonda | `http://<ip-sonda>:8080` (solo LAN) |
| Riepiloghi delle installazioni | VM: `/root/netmon-server-riepilogo.txt`; sonda: `/root/netmon-sonda-riepilogo.txt` |
