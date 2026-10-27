# NetMon Light 1.1.20261027-171600 — installazione e aggiornamento

Istruzioni rapide per la VM (una sola: pagina di stato, pannello di amministrazione, utenti e sonde)
e per la sonda (es. Raspberry Pi). Per una installazione nuova vai al **Caso 3**. I dettagli e la risoluzione
dei problemi sono in `GUIDA.md`; le novità di ogni versione in `CHANGELOG.md`.

> **Ordine obbligatorio: prima la VM, poi le sonde.** Le sonde prendono il pacchetto (e, alla
> prima installazione, la chiave con cui verificano gli aggiornamenti) dalla VM.

---

## Caso 1 · Aggiornamento normale, dal browser

Vale se VM e sonde hanno già una 1.0 e sono state aggiornate almeno una volta a mano (Caso 2).
Lo zip si carica **solo sulla VM**: le sonde lo ricevono da lì, firmato dalla tua VM.

> **Dalla 1.1 ogni pacchetto va firmato da te** con *Firma NetMon*: sul Mac l'app in `tools/mac`
> (vedi `tools/mac/LEGGIMI.md`), su Windows `tools/windows/FirmaNetMon.exe`, un solo file senza
> installazione (vedi `tools/windows/LEGGIMI.md`): la VM installa dal pannello solo pacchetti firmati con la
> tua chiave di rilascio. La prima volta crea la chiave con l'app: firmando, l'app aggiunge la tua chiave
> pubblica allo zip se non c'è ancora, e il primo pacchetto firmato la installa sulla VM. Dettagli in
> `GUIDA.md`, *Firma dell'autore*.

### 1. VM

1. Sul Mac apri **Firma NetMon** → *Firma un pacchetto netmon.zip* → scegli `netmon-light-<versione>.zip`
   (lo zip del rilascio, non il «Download ZIP» di GitHub) e scrivi la password della chiave: accanto
   allo zip compare `netmon-light-<versione>.zip.sig`.
2. `https://TUO-DOMINIO/admin` → **Server › Aggiornamento Netmon** → seleziona **insieme** lo zip e il
   suo `.sig`. Controlla l'elenco: deve dire **Firma dell'autore verificata** e **Pacchetto idoneo**
   (zip integro, file al loro posto, versione più alta di quella installata). Se il pacchetto cambia anche le sonde, sotto *Dopo, aggiorna le sonde*
   compare una nota.
3. Scegli **Installazione sulla VM** (*Adesso* o *Data e ora*) e **Dopo, aggiorna le sonde**
   (*Nessuna*, che è la scelta proposta, *Tutte* o *Quelle che scelgo*), metti la tua password e
   premi **Installa**. Il server si riavvia per qualche secondo; se non riparte, viene rimessa da
   sola la versione precedente.
4. **Finestra di rollback (4 ore).** In fondo alla sezione compare il conto alla rovescia:
   - **Conferma la nuova versione** quando hai controllato che va tutto bene;
   - **Rollback subito** per tornare alla versione precedente;
   - senza conferma, allo scadere delle 4 ore la VM **torna da sola** alla versione precedente
     (anche se nel frattempo è stata riavviata).

### 2. Sonde

Se non le hai scelte al punto 3, aggiornale con il tasto **Aggiorna netmon**:

- pagina di stato → **Stato sonda** → *Manutenzione*, una sonda alla volta;
- oppure `/admin` → **Sonde › Elenco sonde** → *Programma un aggiornamento* (adesso o a una data e
  ora; tutte o quelle selezionate).

La sonda riceve la richiesta entro circa un minuto e fa un aggiornamento completo; se non riparte,
rimette da sola la versione precedente. La pagina locale della sonda **non** avvia aggiornamenti:
mostra solo versione ed esito (sezione *Sistema*).

---

## Caso 2 · Aggiornamento a mano

Serve **la prima volta** (per installare gli script degli aggiornamenti dal browser), aggiornando
da una 1.x, oppure se il pannello non funziona. Prima la VM, poi ogni sonda.

### 1. VM

1. Carica `netmon-light-<versione>.zip` nella home della VM (Google Cloud: finestra SSH del browser → **Carica file**).
2. Estrai e aggiorna:

   ```bash
   cd ~ && rm -rf ~/netmon && unzip -q netmon-light-<versione>.zip
   sudo bash ~/netmon/server/installa-server.sh --aggiorna
   ```

3. Alla fine controlla:
   - la riga **«Impronta della chiave degli aggiornamenti: xxxx xxxx xxxx xxxx»** — annotala;
   - `Aggiornamento completato: versione <quella che avevi> → 1.1.20261027-171600`.
4. Ricarica la pagina di stato nel browser.

Account, storico, sonde e chiave del server restano. Un aggiornamento a mano chiude l'eventuale
finestra di rollback aperta (vale come conferma).
Su Google Cloud toglie anche i pacchetti Google che netmon non usa (`google-cloud-cli`,
`google-osconfig-agent`): gli aggiornamenti del sistema diventano molto più leggeri. Vedi GUIDA, A1.

### 2. Ogni sonda

1. Dal PC copia la cartella `probe` sulla sonda (PowerShell, nella cartella dove hai estratto lo zip):

   ```powershell
   scp -r .\netmon\probe tuoutente@IP_DELLA_SONDA:~
   ```

2. Sulla sonda:

   ```bash
   sudo bash ~/probe/installa-sonda.sh --aggiorna
   ```

3. Alla fine controlla:
   - **«Chiave aggiornamenti xxxx xxxx xxxx xxxx»**: deve essere **uguale** all'impronta della VM;
   - se prima la pagina locale non aveva la password, lo script ne crea una e la mostra:
     **salvala** (è anche in `/root/netmon-sonda-riepilogo.txt`).

Da qui in poi le sonde si aggiornano dal browser (Caso 1), con il pacchetto firmato dalla tua VM.

---

## Caso 3 · Installazione da zero

### 1. VM

Prerequisiti (vedi `GUIDA.md`, passi A1–A2): VM Ubuntu 24.04 o Debian 12/13 con porte TCP 80 e 443
aperte nel pannello del provider, e il dominio `netmonhome.net` (record A) che punta all'IP della VM.

```bash
cd ~ && sudo apt install -y unzip && rm -rf ~/netmon && unzip -q netmon-light-<versione>.zip
sudo bash ~/netmon/server/installa-server.sh
```

Lo script chiede: dominio (proposto `netmonhome.net`), email per l'invio degli avvisi,
bot Telegram, se attivare il firewall, e email e nome del primo amministratore. Poi mostra le
**informazioni da salvare** (copiate anche in `/root/netmon-server-riepilogo.txt`):

- indirizzo della pagina di stato e di `/admin`;
- **chiave del server** (serve **solo** per creare il primo account; non vale per le sonde);
- email e **password provvisoria** dell'amministratore;
- **impronta della chiave degli aggiornamenti** (la confronterai sulla sonda).

Poi, dal browser:

1. `https://TUO-DOMINIO` → *Primo accesso*: inserisci la **chiave del server**, la tua email e una
   password: è il tuo account.
2. **Impostazioni → Sonde → Aggiungi una sonda**: scegli il nome e copia il **token** (`sonda_…`, si
   vede una volta sola). Sotto c'è anche l'**indirizzo del server** a cui la sonda deve puntare.
3. `https://TUO-DOMINIO/admin`: accedi con email e password provvisoria, scegli la nuova password e
   attiva l'app di autenticazione. Da qui inviti gli altri utenti (*Utenti → Aggiungi utente* o
   *Codici di accesso*): si registrano con il loro codice, non con la chiave del server.

### 2. Sonda

Raspberry Pi OS Lite (o Debian/Ubuntu), collegata alla rete di casa, meglio via cavo.

1. Scarica il programma della sonda: nella pagina di stato, *Impostazioni → Sonde*, link **scarica lo
   zip della sonda** (oppure `https://TUO-DOMINIO/scarica-sonda`, dopo l'accesso; lo stesso link è
   nell'email d'invito). È sempre della versione installata sul server. Copialo sulla sonda:

   ```powershell
   scp .\netmon-sonda-*.zip tuoutente@IP_DELLA_SONDA:~
   ```

   In alternativa copia la cartella `probe` dello zip completo (`scp -r .\netmon\probe tuoutente@IP_DELLA_SONDA:~`)
   e lancia `sudo bash ~/probe/installa-sonda.sh`.

2. Sulla sonda:

   ```bash
   cd ~ && sudo apt install -y unzip && unzip -o -q netmon-sonda-*.zip
   sudo bash ~/netmon/probe/installa-sonda.sh
   ```

   Lo script chiede: **lingua** della pagina locale (1 italiano, 2 inglese, 3 tedesco, 4 francese),
   dominio del server, **token** della sonda, nome, dispositivi da pingare,
   FRITZ!Box (facoltativo) e la **password di accesso alla sonda** per la pagina locale
   (obbligatoria; con Invio ne genera una). Poi scarica la chiave degli aggiornamenti e aspetta il
   primo invio (`OK n/n`).

3. Alla fine controlla che **«Chiave aggiornamenti»** coincida con l'impronta della VM e salva
   token e password della pagina locale.

---

### Informativa privacy

Si installa con il server (`server/privacy.html`): il link *Informativa sulla privacy* è in fondo a ogni pagina.
Dettagli in GUIDA.md, *Privacy e GDPR*.

## Caso 4 · Arrivare da NetMon con più VM (gateway)

NetMon Light è una sola VM: niente gateway, niente orchestratore, niente VM probe. Per portare qui gli
utenti di un'installazione NetMon con più VM:

1. Installa NetMon Light su una VM nuova (Caso 3) e crea l'amministratore.
2. Nel pannello del vecchio gateway, per ogni utente: **Azioni ▾ › Esporta (file cifrato)**, con una
   password del file.
3. Nel pannello di NetMon Light: **Utenti › ⤒ Importa un utente**, scegli il file, scrivi la sua password e
   premi *Carica e controlla*, poi *Importa*. L'utente entra con la sua password, le sonde tengono il loro token.
4. Le sonde scrivono ancora al vecchio indirizzo (`vmN.…`): sulla sonda cambia l'indirizzo del server
   (`sudo bash ~/probe/installa-sonda.sh`, opzione 2) in `https://TUO-DOMINIO/api/report`, oppure fai
   puntare il vecchio nome DNS a questa VM e aggiungilo a `OLD_HOSTS` nel `.env` (vedi `GUIDA.md`,
   *Cambiare dominio*): le sonde ricevono il nuovo indirizzo da sole.

---

## Verifica finale (5 minuti)

| Controllo | Cosa devi vedere |
|---|---|
| `https://TUO-DOMINIO/health` | `{"ok":true,"version":"1.1.20261027-171600",...}` |
| Pagina di stato | la sonda compare in *Stato rete › Monitor dispositivi* entro un minuto, pallino verde |
| *Stato sonda* → versione | `1.1.20261027-171600`, senza scritta gialla |
| `http://IP_DELLA_SONDA:8080` | il browser chiede la password; a sinistra il menu delle sezioni; in *Server* il token appare come `••••••••`, **Mostra** lo rivela |
| Alert di prova | aggiungi un dispositivo inesistente (es. `test: 192.168.1.254`): dopo circa 3 minuti arriva l'avviso; poi rimuovilo |
| Sulla sonda | `ls /usr/local/share/netmon/update-key.pub` esiste |

---

## Disinstallare una sonda

Prima togli la sonda dal tuo account (*Impostazioni → Sonde → Elimina*:
spariscono anche storico ed eventi), poi dalla pagina locale della sonda, sezione
**Disinstalla sonda** (scrivi `DISINSTALLA`, rimetti la password e premi *Disinstalla la sonda*), oppure
sulla sonda:

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
`/usr/local/sbin`, i permessi `/etc/sudoers.d/netprobe`, l'utente `netprobe` e
`/root/netmon-sonda-riepilogo.txt`. Restano i pacchetti di sistema (Python, ping, curl, openssl…),
le reti Wi-Fi salvate (`nmcli connection show`; toglierle farebbe perdere la rete), il registro
`/var/log/netmon-installazione.log` e la cartella `~/probe`, che puoi cancellare a mano. Se è in
corso un aggiornamento o un cambio di rete Wi-Fi della sonda, lo script si ferma e chiede di riprovare.

---

## Se qualcosa non va

| Sintomo | Soluzione |
|---|---|
| Sonda: «Il server non fornisce ancora la chiave degli aggiornamenti» | Hai aggiornato prima la sonda: aggiorna la VM, poi rilancia `installa-sonda.sh --aggiorna` |
| *Aggiorna netmon* dice *Funzione non ancora installata* o *Permesso mancante* | La sonda non è mai stata aggiornata a mano con la 2.0: Caso 2, punto 2 |
| *Mancano file necessari* o percorsi `NetMon-main/…` | È il «Download ZIP» di GitHub, non il pacchetto: serve `netmon-light-<versione>.zip` (cartella `netmon/` dentro), creato con `python3 tools/nuova-versione.py` |
| Pacchetto rifiutato in *Aggiornamento Netmon* | Leggi la riga con ✘: di solito la versione non è più alta di quella installata (ogni zip deve avere una versione nuova) |
| *Manca la firma dell'autore* o *Firma dell'autore NON valida* | Seleziona insieme lo zip e il suo `.sig`; se lo zip è stato modificato o riscaricato, rifirmalo con *Firma NetMon*. L'impronta nel messaggio è quella della chiave della VM: deve essere quella dell'app. Da più computer serve la stessa chiave su tutti: *Usa la chiave di un altro computer* con la copia di riserva di quello giusto |
| *La VM non ha ancora la chiave di rilascio…* | Firma lo zip con la versione aggiornata di *Firma NetMon* (in `netmon/tools/mac` dello zip): aggiunge la tua chiave al pacchetto prima di firmarlo. Ricarica lo zip con il nuovo `.sig`. Oppure aggiorna a mano via SSH (Caso 2) |
| «Aggiorna netmon» dice *firma dell'aggiornamento non valida* | Hai reinstallato la VM (nuova chiave): rilancia `installa-sonda.sh --aggiorna` sulla sonda e accetta la nuova chiave dopo aver confrontato l'impronta |
| «Aggiorna netmon» dice *aggiornamento non firmato* | Sulla VM: `sudo bash netmon/server/installa-server.sh --aggiorna` (oppure `sudo netmon-firma-sonde`) |
| Sonda: *Permessi di riavvio e aggiornamenti* non riuscito, *cannot create regular file '/etc/sudoers.d/…'* | Manca il pacchetto `sudo` (sistema minimo o container) e lo script è vecchio: con quello nuovo l'installazione si completa e avvisa. Per le operazioni da remoto: `apt-get install -y sudo` e rilancia |
| Sonda installata senza `sudo` | Funziona, ma *Aggiorna netmon*, *Aggiorna sistema*, *Riavvia sonda*, reti Wi-Fi e *Disinstalla* dalla pagina non sono disponibili: aggiornala a mano (Caso 2, punto 2), oppure `apt-get install -y sudo` e `installa-sonda.sh --aggiorna` |
| Pagina locale: *Apri la pagina con l'indirizzo IP della sonda* | Usa `http://IP:8080`, oppure aggiungi il nome in `/etc/netprobe/web.env` con `WEB_ALLOWED_HOSTS=nome` e `sudo systemctl stop netmon-config` |
| Pagina locale: *richiede una password, che non è impostata* | `sudo bash ~/probe/installa-sonda.sh --aggiorna` (la crea e la mostra) |
| Password di accesso alla sonda dimenticata | `sudo cat /etc/netprobe/web.env` sulla sonda |
| Impostazioni → Notifiche: *Indirizzo ntfy non utilizzabile* | Serve un server ntfy raggiungibile da Internet con `https://` (es. `https://ntfy.sh/tuo-topic`) |
| Sonda con indirizzo `http://` rifiutato | Per un server su Internet serve `https://`; `http://` resta possibile solo per un server nella rete di casa |

Registri utili: `sudo journalctl -u netmon-server -f` (VM), `cat /var/lib/netmon-vm/selfupdate.log`
(ultima installazione da pacchetto e rollback sulla VM), `journalctl -u netmon-probe -f` (sonda),
`cat /var/lib/netprobe-sys/zipupdate.log` (ultimo aggiornamento completo di netmon sulla sonda).
