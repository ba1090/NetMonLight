# Storico delle versioni di netmon

Formato della versione: `1.1.AAAAMMGG-hhmmss` (data e ora del rilascio). La numerazione riparte da 1.0 il 12 ottobre 2026, con il repository NetMon (prima era `2.1.…` e `2.0.…`); dal 14 ottobre 2026 è `1.1`, con la firma dell'autore sui pacchetti. Il numero attuale è nel
file `VERSION`; per un nuovo rilascio: `python3 tools/nuova-versione.py` (vedi in fondo).

Una voce per giorno, dalla più recente, con lo stato a fine giornata: ciò che è stato aggiunto e
cambiato o tolto nello stesso giorno è riportato una volta sola. Tra parentesi l'ultima versione del
giorno e quante ne sono uscite.

## 29 ottobre 2026 (1.1.20261029-180000 · 9 versioni) — NetMon Light

- **Sonde più nuove del server** (da NetMon): una sonda con programmi più recenti di quelli che il server
  distribuisce (per esempio aggiornata a mano con un pacchetto più nuovo) risulta aggiornata: niente più
  *Aggiorna netmon* nella dashboard, *da aggiornare* nel pannello o aggiornamenti programmati che la sonda
  rifiuterebbe comunque. *Server, pagina utente, pannello.*
- **Chiave di firma delle sonde nel backup completo**: il backup del pannello contiene anche la chiave con cui la
  VM firma gli aggiornamenti delle sonde, e il ripristino la rimette (con i programmi delle sonde rifirmati).
  Spostando il server su una VM nuova con *Backup e ripristino*, le sonde continuano ad aggiornarsi dal
  pannello: prima andavano aggiornate una per una in SSH. La chiave resta di root: la legge e la scrive solo il
  nuovo `netmon-chiave-sonde` (due comandi concessi al servizio con sudo). Ogni backup avvisa gli
  amministratori con l'impronta della chiave, e le operazioni restano nel registro della VM. Chi ha il file e
  la sua password può firmare aggiornamenti per le sonde: va custodito come una password. *Server, pannello.*
- **Indirizzo completo della sonda** nella procedura *Collega la tua prima sonda* (passo *Installa*, con
  *Copia*) e nella mail d'invito, oltre al dominio: `https://dominio/api/report`, da scrivere così com'è nella
  pagina locale della sonda, in `config.yaml` o in Home Assistant. *Pagina utente, email.*
- **I nuovi account nascono con il piano Alto** (4 sonde, 4 FRITZ!Box, 45 dispositivi) invece di Basso.
  Vale per le installazioni nuove; su una VM già installata il piano dei nuovi account resta quello scritto nel
  `.env` (`NEW_USER_PLAN`). Gli account esistenti non cambiano: si cambiano da *Utenti › Limiti*. *Server.*
- **Primo account con un codice di accesso**: sul server ancora senza utenti la registrazione accettava solo la
  chiave del server, e un codice creato dal pannello dava *Chiave del server non valida*. Ora vale anche il
  codice di accesso. *Server.*
- **Sicurezza, dopo un test con gli attacchi più noti** (nessuna vulnerabilità trovata; questi i rinforzi):
  - *CSP con le impronte degli script*: sito, dashboard, pannello, informativa e pagina locale della sonda non
    permettono più script scritti nella pagina in generale (`'unsafe-inline'`), ma solo i loro, ognuno con la
    sua impronta SHA-256: anche con un difetto futuro un testo arrivato dalla rete non diventa codice.
  - *Schermata d'accesso unica*: risposta e tempi uguali per ogni email anche quando scattano i limiti del
    pannello, così non si scopre quali indirizzi sono di un amministratore.
  - *Tentativi distribuiti*: oltre 50 password sbagliate in un'ora da almeno 5 indirizzi per lo stesso account,
    avviso agli amministratori (al massimo ogni 6 ore per account), senza bloccare il proprietario.
  - *Importa un utente*: dal file solo i campi previsti dell'account e delle sonde (mai il segno di primo
    utente, i codici di conferma in sospeso o l'autorizzazione della chiave del server); piano, limiti,
    scadenza e blocco si vedono prima di importare; file malformati o con token di sonde già in uso qui sono
    rifiutati prima di cominciare (prima: «Errore interno»).
  - *Prove*: `tests/security/test_attacchi.py` rifà gli attacchi a ogni modifica (93 prove).
  *Server, pannello, sonda.*
- **Indirizzo del server della sonda cambiato dalla pagina** (da NetMon): in *Impostazioni → Sonde* il nuovo
  comando *Indirizzo del server* (con la password dell'account) manda la sonda a un altro server, per esempio
  dopo un cambio di dominio o un backup completo ripristinato su un'altra VM. La sonda prova il nuovo indirizzo
  con il suo token e ci passa solo se quel server la riconosce, dopo averlo detto a quello attuale; altrimenti
  resta dov'è e la pagina dice il motivo. Solo `https://` verso Internet (`http://` nella rete di casa),
  *Annulla* finché la sonda non l'ha presa in carico, scadenza dopo 30 minuti. Non vale per le sonde gestite da
  un altro sistema (Home Assistant: opzioni dell'add-on). Serve la sonda aggiornata. *Sonda, pagina utente,
  server.*
- **Una sola schermata d'accesso per utenti e amministratori**: il modulo *Accedi* di `/dashboard` riconosce
  l'utenza. Le credenziali di un utente aprono la dashboard, quelle di un amministratore portano al pannello
  `/admin`, che prosegue con il codice dell'app o con il cambio della password provvisoria. Tentativi e blocchi
  restano quelli del pannello. `/admin` senza accesso, o dopo *Esci*, porta alla schermata d'accesso; con la
  stessa email per utente e amministratore decide la password. Sul server senza utenti il primo accesso con la
  chiave del server lascia il link *Hai già un account? Accedi* per gli amministratori. *Pagina utente,
  pannello, server.*
- **Backup completo del server e ripristino dal pannello** (*Server › Backup e ripristino*): un file cifrato con
  la password scelta da chi lo scarica (come i file di trasferimento) con utenti, amministratori, sonde, storico,
  codici di accesso e impostazioni del pannello; restano fuori `.env` e chiavi della VM. Il ripristino mostra
  prima cosa contiene il backup, chiede `RIPRISTINA` e la password, prepara i file e riavvia il servizio: all'avvio
  i dati di adesso vanno in `data/prima-del-ripristino-<data>/` e quelli del backup prendono il loro posto. Avviso
  agli amministratori a ogni backup e ripristino. Tradotto in inglese, tedesco e francese. *Pannello, server.*
- **Disponibilità sul telefono** (da NetMon 1.1.20261028-232258): gli orari sotto le caselle non si accavallano più;
  quelli che toccherebbero il precedente si nascondono («ora» resta) e si ricalcolano a ogni cambio di larghezza.
  *Pagina utente.*
- **Installazione su Oracle Cloud**: sulle immagini con il firewall di Oracle (`netfilter-persistent`,
  `/etc/iptables/rules.v4`) l'installatore non installa più `ufw`, che disinstallava `netfilter-persistent` e
  lasciava le regole di Oracle senza caricamento all'avvio: apre 80 e 443 prima del `REJECT` di `iptables` e le
  salva. Ricorda le regole *Ingress* nella *Security List* della VCN. *Server, documenti.*
- **Sonda**: la domanda sul dominio propone `netmonhome.net` come esempio (prima `vm1.netmonhome.net`, delle più
  VM); `config.yaml.example` aggiornato (indirizzo e token della sonda). *Sonda.*

## 28 ottobre 2026 (1.1.20261028-190000 · 2 versioni) — NetMon Light

- **Sito di presentazione sulla stessa VM**: la pagina pubblica di netmonhome.net (sito 1.0.20261024-231919) ora
  la serve netmon su `/`, `/en/`, `/de/` e `/fr/`, con le sue intestazioni di sicurezza e la cache del browser;
  *Accedi* e *Privacy* portano a `/dashboard` e `/privacy` dello stesso dominio. Le pagine stanno in
  `server/sito.py`, creato da `tools/importa-sito.py` a partire dallo zip del sito, e si aggiornano con
  netmon (pannello o `--aggiorna`, rollback compreso). `robots.txt` e `sitemap.xml` comprendono le quattro
  lingue. *Server, sito.*
- **Dashboard degli utenti su `/dashboard`**: la pagina di stato si apre da `/dashboard`; `/status` rimanda lì
  (anche i link d'invito e di conferma già mandati per email). Inviti, conferme e *scarica la sonda* portano a
  `/dashboard`. Il pannello resta su `/admin`. *Server, documenti.*
Allineata a NetMon 1.1.20261028-173944: le novità di NetMon dal 27 ottobre sera, senza le parti per più VM.

- **Pulsanti sempre leggibili**: controllati uno per uno (pagina utente, pannello, pagina locale della sonda; tema chiaro e scuro; computer e telefono; normale e al passaggio del mouse) misurando il
  contrasto tra scritta e sfondo. Corretti i pulsanti selezionati in tema scuro (filtri di *Monitor dispositivi*
  e *Dispositivi in rete*, periodo della *Disponibilità*, dimensione dei riquadri della Dashboard), che avevano la
  scritta bianca su azzurro chiaro; il filtro *Segnale debole* e lo scudo giallo (rischio medio), poco leggibili
  su bianco. Ora ogni scritta di pulsante ha un contrasto di
  almeno 4,5:1 e ogni icona di almeno 3:1. *Pagina utente.*
- **«Salva ordine» più visibile**: i pulsanti principali della barra in alto (*Salva ordine* di *⇅ Ordine* e della
  Dashboard) hanno la scritta in grassetto e un alone chiaro; passandoci sopra restano pieni (prima lo sfondo
  diventava trasparente e la scritta blu scuro spariva sulla barra). *Pagina utente.*
- **Un solo «⇅ Ordine» per sezioni e dispositivi**: tolta la voce *Riordina i dispositivi* dal menu *Modifica ▾*
  delle sonde. In *Stato rete › Monitor dispositivi* il pulsante **⇅ Ordine** in alto lascia le sezioni aperte e
  dà le frecce ▲▼ anche a ogni dispositivo: **Salva ordine** salva insieme l'ordine delle sonde e quello dei
  dispositivi. In *› FRITZ!Box* resta com'era (solo le sezioni). *Pagina utente.*
- **«1 non risponde»** invece di «1 non rispondono» nel riepilogo della mappa. *Pagina utente.*
- **Controllo approfondito delle porte per i dispositivi nuovi**, scelto dispositivo per dispositivo: nella
  finestra *Dispositivi* ogni riga aggiunta (anche con *+ Monitora*) ha la sua casella, spenta, *Controllo
  approfondito delle porte dopo il salvataggio*: salvando, la sonda controlla solo i dispositivi spuntati
  (uno alla volta, gli altri in coda).
  *Pagina utente.*
- **Porte aperte quando il ping fallisce**: nella finestra dello scudo 🛡, per i dispositivi scelti (spento
  all'inizio), *Se il ping fallisce, prova le porte aperte*: quando il ping non risponde la sonda prova le
  porte trovate aperte dall'ultimo controllo (le prime 5). Se una risponde il dispositivo è acceso: giallo con
  «non risponde al ping, porta 80 aperta» e nessun avviso; altrimenti conta come un ping fallito. Solo rete di
  casa, al massimo 8 secondi per giro. Serve la sonda aggiornata. *Sonda, pagina utente, server.*
- **5 minuti di tolleranza dopo un aggiornamento o una ripartenza della sonda**: dopo che la sonda ha
  confermato un aggiornamento o un riavvio, e dopo ogni ripartenza del suo programma (anche aggiornata a mano o
  al ritorno della corrente), per 5 minuti non risulta «in ritardo» e l'avviso «non comunica» non parte. I primi
  cicli dopo l'avvio sono i più lenti, soprattutto su un Raspberry Pi Zero, e facevano comparire ritardi inutili.
  La pagina scrive *in ripartenza dopo l'aggiornamento*. Una sonda che non torna davvero viene segnalata al
  più 5 minuti più tardi del solito. *Server.*
- **Documentazione allineata**: GUIDA, INSTALLAZIONE e README dicono cosa contiene ora lo zip (e che *Firma NetMon*
  si prende dal repository), la tolleranza dopo gli aggiornamenti e le nuove prove automatiche.
- **Pacchetti più leggeri**: lo zip del rilascio contiene solo ciò che serve a installare e aggiornare la
  VM e le sonde (`VERSION`, `server/`, `probe/`): test, strumenti (*Firma NetMon*, script di
  rilascio) e documenti restano nel repository. Da 1,4 a 1,0 MB. Il pacchetto completo che la VM prepara
  per le sonde contiene solo `VERSION` e `probe/`: da circa 1,1 MB a 250 KB, e la sonda non scarica né
  controlla più il codice del server (su un Raspberry Pi Zero erano secondi di processore pieno durante
  l'aggiornamento). *Server, rilascio.*
- **La pagina non torna più in cima a ogni aggiornamento**: in *Stato rete › Monitor dispositivi* e
  *› FRITZ!Box* l'aggiornamento automatico (ogni 15 secondi) ricostruiva le sezioni e riportava la pagina
  all'inizio. Ora resta dov'eri; anche la ricerca di *Dispositivi in rete* tiene il cursore mentre scrivi.
  *Pagina utente.*
- **Dispositivi in rete richiudibile**: come gli altri riquadri si chiude con la freccia accanto al titolo (da
  chiusa resta il numero dei collegati). *Pagina utente.*

## 27 ottobre 2026 (1.1.20261027-171600 · 3 versioni) — NetMon Light

- **Zip del rilascio `netmon-light-<versione>.zip`**: `tools/nuova-versione.py` crea lo zip con il nome di NetMon Light (prima `netmon-<versione>.zip`); dentro resta la cartella `netmon/`, quindi installazione e aggiornamento non cambiano. *Strumenti, documenti.*
- **Dispositivi in rete** (da NetMon 1.1.20261027-160153): nella pagina *Stato rete › FRITZ!Box*, sotto i
  riquadri, l'elenco dei dispositivi che il FRITZ!Box conosce, con nome, IP, collegamento (cavo con porta LAN, o
  Wi-Fi con banda e repeater), segnale in dBm con le tacche e velocità del collegamento (non il traffico, che il
  FRITZ!Box non dà per dispositivo). Filtri Wi-Fi, Cavo, Segnale debole (sotto −75 dBm) e Non monitorati, ricerca
  per nome o IP e casella per mostrare anche i non collegati con «visto … fa». **+ Monitora** apre *Dispositivi*
  della sonda con nome e IP già compilati. Sul telefono le righe diventano schede. Si aggiorna ogni 5 minuti con la
  mappa mesh; si nasconde da *Visualizzazione → Riquadro FRITZ!Box → Dispositivi in rete*. Gli indirizzi MAC
  restano sulla sonda: al server arrivano solo nome, IP e collegamento. Tradotto in inglese, tedesco e francese.
  *Sonda, pagina utente, server.*
- **NetMon Light: una sola VM per tutto.** Pagina di stato degli utenti, pannello di amministrazione (admin e
  utenti) e sonde dei vari utenti stanno sulla stessa VM. Tolti il gateway (`gateway/`, pagina d'accesso
  comune e smistamento), l'orchestratore (`ROLE=orchestratore`) e le VM probe (`VM_ID`, `GATEWAY_SECRET`,
  `GATEWAY_URL`): niente più rotte `/internal/*`, `/api/vm/*`, `/api/admin/vms*`, `/api/admin/probes/all`,
  `/api/admin/schedules/all` né inoltro del pannello alle VM (`X-Netmon-VM`). *Server.*
- **Pannello senza parti per più VM**: via *Server › Tutte le VM* (mappa, elenco, *Collega una VM*), la barra
  delle macchine, la colonna *VM* in utenti, utenti non attivi e sonde, la scelta della VM per inviti e
  importazioni, *Sposta su un'altra VM* e l'installazione del pacchetto a cascata sulle VM. Restano
  *Esporta (file cifrato)* e *Importa un utente*, anche per portare utenti da un'installazione NetMon con
  gateway. Invio email, conservazione dei dati ed email di prova valgono per il server. *Pannello.*
- **Installazione**: `installa-server.sh` ha solo l'installazione guidata e `--aggiorna` (tolti
  `--orchestratore` e `--dietro-gateway`); `env.example` senza le variabili delle più VM. *Server.*
- **Documenti**: README, INSTALLAZIONE (Caso 4: arrivare da NetMon con più VM) e GUIDA (nuove sezioni
  *Esportare e importare un utente* e *Cambiare dominio*; tolto il capitolo sulle più VM); informativa sulla
  privacy con un solo server. *Documenti, informativa.*

## 26 ottobre 2026 (1.1.20261027-171600 · 3 versioni)

- **Trasferimento degli utenti cifrato con una password**: *Utenti → Esporta (file cifrato)* chiede una password
  del file (almeno 12 caratteri, con indicatore di robustezza; *Genera* propone sei parole a caso, *Copia* la
  copia) e scarica un file `.netmon` illeggibile senza di essa, nemmeno l'email dell'utente. Nessuno la salva,
  né il server né il file. Cifratura AES-256-GCM a blocchi da 1 MB con chiave da scrypt (N = 2^17); un file
  modificato, troncato o con blocchi scambiati viene rifiutato. Lo zip in chiaro non resta sul server.
  *Importa un utente* chiede la password del file; sbagliandola si riprova senza ricaricare il file. Gli zip
  delle versioni precedenti si importano ancora, con l'avviso «file non cifrato». Anche lo **spostamento tra VM**
  dal gateway fa viaggiare il file cifrato, con una password casuale che non esce dal server. Nuova dipendenza
  `cryptography` 50.0.2, installata dall'aggiornamento. *Pannello, server.*
- **Traduzioni complete in inglese, tedesco e francese**: verificate confrontando ogni testo di pagina utente
  e pannello (pulsanti, menu, suggerimenti, finestre) nelle quattro lingue. Restavano in italiano soprattutto
  le frasi composte: la conservazione dei dati («tutto, senza scadenza (default)»), le frequenze dello
  SpeedTest fuori dal piano, la tabella *Cosa ricevere su ogni canale* per i lettori di schermo, i gruppi della
  Dashboard («4 dispositivi · 1 non risponde»), il suggerimento della priorità, «ultimo report … fa», i conteggi
  di quanto è nascosto e il limite dei FRITZ!Box. Tradotte anche le email agli utenti su scadenza ed
  eliminazione dell'account, i messaggi del pannello su aggiornamenti, invio email e VM, e alcuni messaggi
  della pagina locale della sonda. Il traduttore della pagina ora traduce frase per frase i suggerimenti fatti di
  più frasi. Resta «Riconfigurare», nome dell'opzione dello script d'installazione della sonda (solo in
  italiano). *Pagina utente, pannello, sonda, server.*
- **Pagina locale della sonda: stesso traduttore del server**: la copia del traduttore nella pagina della
  sonda non era stata aggiornata insieme a quella del server, e lo script di rilascio si era fermato (pacchetto
  1.1.20261027-171600 da non usare). Ora sono di nuovo identiche. *Sonda.*

## 25 ottobre 2026 (1.1.20261025-142050 · 2 versioni)

- **«Come il server» diventa «Default»**: nella pagina utente (*Conservazione dei dati*, con «(default)» nella riga
  *Adesso*, e *Fuso orario*) e nel pannello (*Orari del pannello*). Cambia solo la scritta, non il comportamento.
  *Pagina utente, pannello.*
- **Cambio dell'ora legale: speedtest periodici all'ora scelta**: i turni contavano in secondi dall'ora di
  partenza, così dopo il ritorno all'ora solare il test delle 3:00 partiva alle 2:00 (e in primavera
  sarebbe partito alle 4:00). Ora, con frequenze di ore intere, seguono l'orologio di casa nel fuso
  dell'account; nell'ora ripetuta un test non parte due volte. Le programmazioni esistenti tornano da
  sole all'ora giusta, senza doverle salvare di nuovo. Le misure non erano toccate: sono salvate in ora
  universale, senza ore doppie né sovrascritte. *Server.*
- **Disponibilità a 7 giorni: nome di tutti i giorni**: dopo il cambio d'ora i giorni precedenti restavano
  senza etichetta (le loro caselle non cominciano più alle 0:00). *Pagina utente.*

## 24 ottobre 2026 (1.1.20261024-232906 · 1 versione)

- **Sicurezza: schema dell'API non più pubblico**: il server rispondeva a chiunque su `/openapi.json` con
  l'elenco completo delle sue rotte (149), comprese quelle interne del gateway che senza la sua chiave
  rispondono 404 apposta. Ora risponde 404 anche lì, come `/docs` e `/redoc`; una prova di sicurezza lo
  controlla. Dalla revisione completa del codice (server, gateway, sonda: SQL, comandi di sistema, XSS,
  accessi, file, reindirizzamenti, librerie) non sono emerse altre falle sfruttabili. *Server.*

## 23 ottobre 2026 (1.1.20261023-211355 · 2 versioni)

- **Dashboard: riquadro «Disponibilità»**: una riga di caselle per ogni dispositivo scelto, una ogni
  mezz'ora (*24 ore*) o ogni 4 ore (*7 giorni*); verde se ha risposto a tutti i ping, giallo se ne ha persi
  qualcuno, rosso se non rispondeva, grigio senza dati. A destra la percentuale di ping risposti. Un tocco su
  una casella apre lo storico dei ping di quel momento. Il pulsante *Dispositivi* sceglie quali seguire
  (*Tutti*, *Solo priorità Alta*, *Nessuno*): all'inizio quelli a priorità *Alta*. Si sposta, si ridimensiona
  e si nasconde come gli altri riquadri; scelta e periodo restano nell'account. Sul telefono le caselle sono
  la metà, più larghe; nel formato piccolo restano solo nomi e caselle. *Pagina utente, server.*

## 22 ottobre 2026 (1.1.20261022-110533 · 1 versione)

- **Sonde gestite da un altro sistema**: una sonda avviata con `NETMON_MANAGED_BY=<nome del sistema>` lo dice al
  server (`managed_by` nei dati di sistema). Riavvio, aggiornamenti, reti Wi-Fi e disinstallazione li fa quel
  sistema: gli aggiornamenti programmati dal pannello la saltano (l'esito dice quali), la pagina e il server non le
  mandano più comandi che fallivano sempre (con avvisi «non riuscito» e consigli su sudo e `installa-sonda.sh`),
  *Stato sonda* dice da dove aggiornarla e riavviarla, in `/admin` → **Sonde** è segnata con il nome del sistema.
  Nella pagina locale spariscono *Riavvia la sonda* e *Disinstalla sonda*. *Sonda, pagina locale, pagina utente,
  pannello.*
- **Notifiche: un interruttore per canale**: in *Impostazioni → Notifiche* Email, Telegram e ntfy hanno ognuno il
  suo riquadro con un interruttore. Spento, su quel canale non parte nessun avviso di nessun tipo; chat ID, topic
  ntfy e spunte della tabella *Cosa ricevere su ogni canale* restano salvati e tornano validi quando lo riaccendi
  (nella tabella la colonna del canale spento è in grigio). Il primo chat ID scritto e una prova Telegram riuscita
  accendono Telegram da soli. *Pagina utente, server.*
- **ntfy: indirizzo già pronto**: chi non ha ancora un topic ne trova uno creato per lui,
  `https://ntfy.sh/netmon-` seguito da 16 lettere e cifre calcolate dalla sua email con una chiave che resta sul
  server (sempre le stesse per lui, ma non ricavabili dalla sola email: su ntfy.sh chi conosce un topic ne legge
  i messaggi). ntfy resta spento finché l'utente non lo accende. Nuovi pulsanti *Copia*, *Crea un nuovo indirizzo*
  e *Invia una notifica di prova*. Con un server ntfy proprio: `NTFY_BASE` nel `.env`. *Pagina utente, server.*

## 21 ottobre 2026 (1.1.20261021-214800 · 23 versioni)

- **Menu laterale a tendina**: toccando *Stato rete* (nel pannello *Amministrazione*, *Sonde*, *Server*) le sue
  sezioni si aprono o si chiudono, con una freccia che lo indica, invece di cambiare pagina. È aperta la scheda della
  pagina in cui sei; le altre restano come le lasci. *Pagina utente, pannello.*
- **Grafici senza la nota «N campioni · un punto ogni …»** sotto: resta solo l'eventuale messaggio d'errore.
  *Pagina utente.*
- **Email ed «Esci» nel menu laterale**: nella pagina utente l'email dell'account e il pulsante *Esci* sono passati
  dalla barra in alto al menu laterale, sotto *Impostazioni* (sul telefono la barra si accorcia e l'email ora si
  vede). Lo stesso nel pannello: nome dell'amministratore ed *Esci* sotto *Server*. *Pagina utente, pannello.*
- **Corretto: mappa della rete, sonde che non si aprivano al primo tocco**: in *Stato rete › Mappa*, dopo
  l'aggiornamento automatico della pagina (ogni 30 secondi) il tocco su una sonda non faceva niente e il cambio
  compariva solo all'aggiornamento successivo, come se fosse lento. Ora si apre e si chiude subito, a ogni tocco.
  Sui telefoni il primo tocco non viene più preso come «passaggio del mouse». *Pagina utente.*
- **Stato sonda: storici di temperatura, CPU, memoria e disco**: accanto al nome di ogni sonda ci sono i pulsanti
  *Temperatura*, *CPU*, *Memoria* e *Disco* con icone disegnate (sul telefono solo le icone; il termometro sostituisce
  l'emoji 🌡). Il server ora salva a ogni report, oltre a temperatura e carico, il carico della CPU, la memoria usata e
  lo spazio su disco in percentuale, anche per le sonde senza sensore di temperatura. Gli storici hanno gli stessi
  periodi degli altri grafici, minimo, media e massimo e la scala fissa da 0 a 100%. Anche l'export dei dati li
  comprende. *Pagina utente, server.*
- **Priorità dei dispositivi sempre modificabile**: per un dispositivo appena aggiunto o in pausa la priorità non
  si poteva cambiare (bisognava aspettare che la sonda lo misurasse, con il rischio di dimenticarsene), e mettendo un
  dispositivo in pausa la sua priorità tornava *Normale*. Ora si sceglie già nella finestra *Dispositivi* (menu accanto
  a nome e indirizzo), si cambia sempre e vale appena la sonda lo controlla; con la pausa resta. *Pagina utente, server.*
- **Pulsanti dei grafici riconoscibili**: nel riquadro FRITZ!Box le emoji 📊 📶 📈 sono diventati pulsanti con
  icona disegnata e nome, *Traffico*, *Client Wi-Fi* e *Altri grafici* (sul telefono solo l'icona, il nome resta nel
  suggerimento). Lo storico dei ping di ogni dispositivo ha ora la sua icona, un battito, invece della stessa 📈 degli
  altri grafici. Le icone seguono il colore della pagina, anche nel tema scuro. *Pagina utente.*
- **Dashboard: grafici vuoti spiegati**: se la richiesta dei grafici falliva, la pagina cancellava il messaggio
  d'errore e restava solo la linea tratteggiata, senza dire perché. Ora in cima compare «Grafici non disponibili (…):
  riprovo al prossimo aggiornamento», e sotto un grafico vuoto c'è il motivo («grafico non disponibile» oppure
  «nessuna misura salvata nelle ultime 24 ore»). Il punto singolo di una sonda appena collegata ora si vede anche in
  Safari. *Pagina utente.*
- **«Sonde e monitoraggio» diventa «Monitor dispositivi»**: nuovo nome della pagina in *Stato rete* (menu, titoli,
  guide e traduzioni: *Device monitor*, *Geräte-Monitor*, *Moniteur des appareils*). L'indirizzo `#rete/sonde` resta
  lo stesso. Nelle guide di Home Assistant anche il pulsante per aggiungere dispositivi è ora *Modifica ▾*.
  *Pagina utente, guide.*
- **Sonde in aggiornamento: un ciclo in più prima dell'avviso**: mentre una sonda installa un aggiornamento (di
  netmon o del sistema, anche automatico o programmato) o si riavvia, le soglie «in ritardo» e «non comunica» si
  allungano di un ciclo, di due sulle sonde poco potenti (Raspberry Pi Zero, un solo processore), che ripartono più
  lentamente. Niente più avvisi «non comunica» durante un aggiornamento normale. *Server.*
- **Aggiornamenti programmati: un solo riepilogo agli amministratori**: un aggiornamento lanciato dal pannello
  (pacchetto su più VM con le loro sonde, o *Aggiorna tutte le sonde*) mandava un'email per ogni programmazione, per
  il promemoria di ognuna, per l'esito di ogni VM e per ogni sonda non riuscita: con molte sonde, centinaia di email.
  Ora è una campagna unica e gli amministratori ricevono al massimo tre email, con l'elenco per VM di tutto: alla
  programmazione, un'ora prima ed esito finale (aggiornate, non riuscite con l'email del proprietario, in attesa).
  Gli avvisi agli utenti restano come prima. *Pannello, server.*
- **Un token, un dispositivo**: ogni sonda manda un proprio identificativo e il primo dispositivo che usa un token
  ne diventa il titolare. Se un secondo dispositivo usa lo stesso token, i suoi dati vengono scartati (risposta 409,
  niente storico, avvisi, configurazione né comandi) e l'utente riceve un avviso su tutti i canali, ripetuto ogni
  12 ore; in Dashboard e in Stato rete un riquadro giallo mostra i due dispositivi con *Aggiungi una sonda* e
  *Usa il nuovo dispositivo* (sostituzione). La pagina locale del secondo dispositivo mostra il motivo; nel
  pannello, *Utenti* segnala l'account con *⚠ token doppio*, senza notifiche. Un nuovo token azzera il titolare.
  *Sonda, pagina utente, pannello.*
- **Connessioni al database chiuse subito**: il server lasciava aperta ogni connessione a `auth.db` ed
  `events.db` finché passava il garbage collector di Python. Sotto carico (molte sonde e pagine aperte) se ne
  accumulavano migliaia: in una prova con 150 sonde, dopo pochi minuti 10.000 file aperti, «unable to open
  database file» e quasi 2 GB di memoria, ben oltre il limite del servizio (384 MB), quindi riavvii continui.
  Con Python 3.13 (Debian 13) il problema è più rapido. Ora il `with` chiude la connessione. *Server.*
- **Report delle sonde più robusti**: alcuni valori malformati facevano fallire con errore 500 l'intero report
  (e i suoi avvisi): velocità del FRITZ!Box come testo, elenco ospiti o reti Wi-Fi non in forma di elenco, banda
  di un repeater non numerica, porte del controllo di sicurezza non in elenco. Ora quei valori vengono scartati e
  il resto del report arriva. Anche un periodo personalizzato dei grafici con «nan» non dà più errore 500. *Server.*
- **Indirizzi dei dispositivi: server e sonda d'accordo**: la pagina accettava indirizzi come `0:` o `..`, che
  la sonda rifiuta; e con un dispositivo non valido la sonda scarta tutta la configurazione arrivata dal server,
  senza che nessuno se ne accorga. Ora il server accetta solo IP veri (come la sonda); nomi e indirizzi con un
  «a capo» finale sono rifiutati da entrambi. *Server, sonda.*
- **Prove automatiche** (`tests/`, vedi `tests/LEGGIMI.md`): sicurezza delle API, isolamento tra account,
  salvataggio dei dati, XSS nel browser, sonda e pagina locale, più VM dietro il gateway, casi d'uso da 0 a 50
  sonde e prove di carico prolungate.
- **Aggiornamento Netmon, conferma più leggibile**: il riquadro del rollback elenca a punti le macchine da
  confermare (gateway e ogni VM), ognuna con versione precedente e nuova, ora di scadenza e tempo rimasto, e sotto
  una nota breve su cosa fanno *Conferma la nuova versione* (tutte) e *Rollback subito* (solo la macchina scelta).
  Scegliendo una VM in alto l'elenco mostra solo quella (prima restavano le righe lette dal gateway). *Pannello.*
- **Rete mesh, banda anche per i segnali deboli**: i dispositivi con segnale debole restano in giallo ma mostrano
  la banda (2,4 o 5 GHz) al posto della scritta «segnale debole»; quanti sono lo dice, in giallo, la riga di ogni
  nodo («N con segnale debole») e il riepilogo della sezione («N dispositivi con segnale debole»). *Pagina utente.*
- **SpeedTest, download e upload nello stesso grafico**: nella Dashboard e nello *Storico SpeedTest* c'è un solo
  grafico, download a linea piena e upload tratteggiato nel colore della sonda, con le soglie «minimo ↓» e
  «minimo ↑». Nello storico un clic o un tocco su un punto (o le frecce della tastiera) mostra i valori di quel test,
  come negli altri storici. Ogni test registra se la sonda era in **Wi-Fi o via cavo**: si vede nel riquadro dei
  valori e nella nuova colonna *Collegamento* della tabella (anche nell'export dei dati). Allineati il menu
  delle sonde e i pulsanti 24 ore / 7 giorni / 30 giorni. *Pagina utente.*
- **Sonde preparate dal pannello**: in *Utenti*, il menu *Azioni ▾* di un account registrato e non bloccato ha
  *Prepara sonde…*: crea una sonda nel suo account (entro il limite) e mostra token, dominio e indirizzo del server
  da scrivere sulla sonda prima di spedirla; *Nuovo token* rigenera il token di una sonda dell'account. L'utente la
  vede subito in *Impostazioni → Sonde*, «non ancora collegata». Con più VM l'azione va alla VM dell'utente.
  *Pannello.*
- **Dashboard divisa per sonda, con colori, ordine e dimensioni**: con più sonde i dispositivi sono raggruppati
  per sonda, con una testata colorata (nome, spia della sonda, quanti dispositivi e quanti non rispondono) che si
  chiude e si riapre con ▼ / ▶. Il colore della sonda si sceglie in *Impostazioni → Sonde → Colore* (otto colori o
  *Automatico*) ed è lo stesso nei grafici dello SpeedTest. Con *⇅ Ordine* si spostano i gruppi, *Uso della linea*
  e *SpeedTest* (anche sotto i ping) e si sceglie la dimensione di questi due e di ogni dispositivo: *Piccolo*,
  *Medio* o *Grande*. Tutto è salvato nell'account. *Pagina utente.*
- **Stato rete › FRITZ!Box, testo più breve**: senza FRITZ!Box la pagina dice solo «0 FRITZ!Box collegati. Limite del
  tuo account: N.»; con i FRITZ!Box lo stesso conteggio compare nella nota in fondo. *Pagina utente.*
- **Un solo pulsante Modifica per i dispositivi della sonda**: in *Stato rete › Sonde e monitoraggio* i pulsanti
  ＋, － e ⇅ accanto al nome della sonda sono diventati *Modifica ▾*, con le voci *Aggiungi o modifica dispositivi*,
  *Rimuovi dispositivi* e *Riordina i dispositivi*. Mentre la rimozione è attiva compare *Fine rimozione*. *Pagina utente.*
- **Corretto: riga «nascosto» della Dashboard**: contava tutte le scelte salvate, anche quelle su sonde eliminate o
  su dispositivi rinominati o tolti (per esempio «1 sonda nascosta, 9 dispositivi nascosti» con l'unica sonda in
  vista), e segnalava «uso della linea nascosto» anche senza FRITZ!Box. Ora conta solo sonde e dispositivi che
  esistono, non conta due volte i dispositivi di una sonda nascosta, segnala la linea solo se c'è un FRITZ!Box e
  segnala anche SpeedTest nascosto. *Pagina utente.*
- **Impostazioni → Controlli, allarmi più chiari**: la frase sui dispositivi («va in allarme dopo N controlli falliti
  di fila») sta ora sotto il suo campo, e quella sulla sonda (in ritardo, irraggiungibile) sotto la sua sezione, con
  una riga che spiega che l'allarme sulla sonda non dipende dai controlli falliti dei dispositivi. Prima le due frasi
  stavano insieme sotto la sezione della sonda e sembrava che il primo campo dovesse cambiarne i tempi. *Pagina utente.*
- **Reti Wi-Fi in Impostazioni**: si gestiscono in *Impostazioni → Sonde* con il comando *Reti Wi-Fi* della sonda,
  in una finestra con le reti salvate e l'esito dell'ultima operazione. In *Stato sonda* restano visibili in sola
  lettura, con il pulsante *Gestisci in Impostazioni*. *Pagina utente.*
- **Comandi delle sonde nel menu Azioni**: in *Impostazioni → Sonde*, quando *Metti in pausa*, *Rinomina*,
  *Reti Wi-Fi*, *Nuovo token* ed *Elimina* non stanno sulla riga della sonda (schermo stretto, telefono) sono
  raccolti nel pulsante *Azioni ▾*. *Pagina utente.*
- **Reti Wi-Fi della sonda, esito utile**: aggiungendo una rete la sonda prima la cerca con una scansione e l'esito
  dice se la vede (canale, banda, segnale) oppure i motivi possibili per cui non la vede: troppo lontana, nascosta,
  solo 5 GHz con una scheda a 2,4 GHz, canali 12–13 con il paese Wi-Fi non impostato. Prima l'esito era sempre
  «aggiunta» anche se la sonda non avrebbe mai potuto collegarsi. *Sonda.*
- **Reti solo WPA3**: salvate con la sicurezza giusta (SAE) invece che come WPA2, che non si collegava. Una rete
  protetta senza password viene rifiutata subito; per una rete aperta la password non viene salvata. *Sonda.*
- Nella finestra della rete Wi-Fi, *Aggiungi* spiega che la rete si usa quando non si trova più quella attuale e
  che la password si prova solo con *Collegati subito*. *Pagina utente.*

## 20 ottobre 2026 (1.1.20261020-110337 · 1 versione)

- **Aggiornamenti automatici delle sonde**: quando il server ha una versione nuova, le sonde rimaste indietro si
  aggiornano da sole (controllo ogni 10 minuti; solo sonde in linea, non in pausa e libere; al massimo 20 per volta
  e un tentativo ogni 6 ore per sonda). Ogni utente li può spegnere in *Impostazioni → Sonde* (attivi di partenza):
  allora le sue sonde restano alla versione attuale e anche gli aggiornamenti di *tutte* le sonde fatti in /admin le
  saltano, mentre quelle scelte una per una dall'amministratore si aggiornano. In /admin → Sonde sono segnate.
  *Server, pagina utente, pannello.*

## 19 ottobre 2026 (1.1.20261019-172210 · 16 versioni)

- **Corretto: una VM senza sonde non si aggiornava** se nell'aggiornamento di netmon si sceglieva di aggiornare anche
  *Tutte* le sonde: la VM rifiutava l'intera installazione con «Nessuna sonda collegata a cui inviarlo». Ora la VM si
  aggiorna lo stesso e l'esito riporta solo l'avviso «Nessuna sonda da aggiornare su questa VM». Dal gateway, alle
  VM senza sonde non si chiede più di aggiornarle: così l'aggiornamento parte anche verso le VM con una versione
  precedente a questa. *Server, pannello.*
- **Dominio netmonhome.net**: guida, istruzioni di installazione e script usano come esempio netmonhome.net per il
  server (o il gateway) e vm1.netmonhome.net, vm2.… per le VM di utenti e sonde. Lo script del server propone
  netmonhome.net come dominio; quello della sonda mostra vm1.netmonhome.net come esempio. *Documentazione, script.*
- **Tolto DuckDNS**: il passo A2 della guida spiega ora i record DNS di netmonhome.net, e lo script del server non
  offre più di aggiornare un sottodominio DuckDNS (se il dominio non punta alla VM chiede di correggere il record A).
  *Documentazione, script del server.*
- **Email d'invito più completa**: riporta il dominio da configurare sulla sonda (quello della VM dell'utente,
  senza https://, come lo chiedono lo script della sonda e l'app di Home Assistant) e, negli inviti, il link alla
  guida PDF per usare Home Assistant come sonda. *Server.*
- **SpeedTest senza test ancora fatti**: il riquadro della Dashboard non mostra più due grafici vuoti ma come
  cominciare (*Avvia ora* o i test periodici in *Impostazioni → Controlli*). *Pagina utente.*
- **Sonda per Home Assistant allineata**: `tools/nuova-versione.py` copia a ogni rilascio i programmi della sonda
  nell'add-on (repository `netmon-homeassistant` accanto a questo) e ne aggiorna la versione. Era rimasta alla
  1.1.20261016-123657: le mancavano la correzione dei FRITZ!Box aggiuntivi a 0, i limiti in totale per l'account e lo
  speedtest più preciso. *Strumenti, add-on Home Assistant.*
- **Un solo «Salva» per le Impostazioni**: il pulsante *Salva* in fondo alla pagina salva tutto quello che è cambiato
  (configurazione e avvisi della sonda, canali di notifica, SpeedTest periodici, conservazione dei dati) e compare
  anche in *Account e backup*. Tolti i pulsanti *Salva SpeedTest*, *Salva notifiche* e *Salva conservazione*: prima
  le scelte dello SpeedTest si perdevano premendo il *Salva* generale. Se una parte non si salva, il messaggio dice
  quale e perché; per cambiare la conservazione resta richiesta la password. *Pagina utente.*
- **Uso della linea: download e upload in un solo grafico** sovrapposti sulla stessa scala (download ad area, upload
  a linea arancione, con legenda); il grafico occupa tutta l'altezza del riquadro. *Pagina utente.*
- **Sonde e VM più vecchie del gateway**: ogni sonda si aggiorna alla versione di netmon della sua VM, quindi le sonde
  di una VM non ancora aggiornata restavano indietro senza spiegazione. Ora *Sonde › Programma un aggiornamento*
  indica quali VM sono più vecchie del gateway, e la conferma di *Aggiorna netmon* lo ripete: prima si aggiorna la
  VM, poi le sue sonde. *Pannello.*
- **Esito dell'aggiornamento sulle VM sempre visibile**: installando un pacchetto dal gateway, l'esito per ogni VM
  (avviata, già aggiornata, o il motivo del rifiuto) compariva in fondo alla pagina solo per un attimo, perché poi il
  gateway si riavvia e la pagina si ricarica. Ora resta in *Server › Aggiornamento Netmon* anche dopo il
  ricaricamento, in rosso se una VM non è partita. *Pannello.*
- **Nessuna notifica dagli SpeedTest periodici**: neanche gli avvisi di velocità bassa o tornata normale, che restano
  negli *Ultimi eventi* e sulla Dashboard. Le notifiche arrivano solo per gli speedtest avviati a mano. *Server.*
- **Avviso Wi-Fi anche sulla Dashboard**: il riquadro SpeedTest segnala le sonde mostrate collegate in Wi-Fi.
  *Pagina utente.*
- **SpeedTest più preciso**: la velocità si calcola escludendo i primi 2 secondi, quando le connessioni stanno
  ancora accelerando, e il limite di dati cresce con la velocità della linea (circa 150 MB fino a 100 Mbit/s,
  fino a circa 1 GB a 1 Gbit/s). Prima le linee veloci risultavano più lente del vero, perché i 120 MB finivano
  durante l'accelerazione. In upload contano solo i dati già arrivati al server: prima si contavano anche quelli
  fermi nel buffer della sonda e l'upload poteva risultare più alto del vero. *Sonda.*
- **Avviso Wi-Fi negli SpeedTest periodici**: se la sonda è collegata in Wi-Fi, *Impostazioni › Controlli* avvisa che
  la velocità dipende anche dalla qualità del Wi-Fi e da quanti dispositivi lo usano, non solo dalla linea, e consiglia i test periodici solo con la sonda collegata via cavo. *Pagina utente.*
- **Email sulla scadenza dell'account più chiare**: spostando una scadenza già attiva l'email (*Scadenza dell'account
  spostata*) dice da quale data a quale; tutte le email sulla scadenza hanno la data anche nell'oggetto. Prima avevano
  lo stesso oggetto e il programma di posta le raggruppava, mostrando per prima la data dell'email precedente (le date
  erano corrette). *Server.*
- **SpeedTest sulla Dashboard**: nuovo riquadro *SpeedTest* accanto a *Uso della linea*, della stessa altezza. Per
  ogni sonda l'ultimo risultato e lo scarto dalla media dei 7 giorni, e grafici separati di download e upload degli
  ultimi 7 giorni (un colore per sonda, soglie e test sotto soglia in rosso). Il menu a tendina mostra *Tutte le
  sonde* o *SpeedTest* di una sola sonda; **Storico** apre grafici e tabella a 24 ore, 7 o 30 giorni; **Avvia ora**
  chiede subito il test. Nascondibile da *Visualizza*. *Pagina utente, server.*
- **SpeedTest periodici** (*Impostazioni › Controlli*): per ogni sonda, a scelta, ogni ora, 3 ore, 6 ore, 2 volte al
  giorno, ogni giorno, ogni settimana o personalizzato (*ogni N minuti/ore/giorni a partire dalle HH:MM*). Il piano
  limita la frequenza (basso uno al giorno, medio ogni 6 ore, alto e senza piano ogni ora). Con due o più sonde
  attive si può sfalsare la partenza (5 minuti – 2 ore) perché i test sulla stessa linea non partano insieme. I test
  periodici non scrivono un evento ogni volta. Funziona con le sonde già installate. *Server, pagina utente.*
- **Avvisi sulla velocità**: download o upload sotto una soglia fissa, o download sotto una percentuale della media
  dei 7 giorni; l'avviso parte dopo 2 test di fila sotto soglia (canale *SpeedTest* delle notifiche), con l'avviso di
  ripristino quando la velocità torna normale. *Server, pagina utente.*
- **Uso della linea ridisegnato**: un solo riquadro (menu a tendina se più sonde hanno il FRITZ!Box) con i numeri
  *Adesso* e *Linea*, grafici di download e upload con scala e orari e il pulsante *Storico*. *Pagina utente.*

- **Limiti in totale per l'account**: FRITZ!Box e dispositivi si contano su tutte le sonde insieme, non più per
  ogni sonda. Basso = 1 sonda, 1 FRITZ!Box e 5 dispositivi in tutto; medio 2, 2 e 15; alto 4, 4 e 45; senza piano
  50 FRITZ!Box e 500 dispositivi. Le sonde si servono in ordine di creazione (la prima prende quello che le serve,
  le altre quello che resta); ogni sonda riceve da sola la sua parte quando cambiano le altre e il server non tiene
  FRITZ!Box e dispositivi oltre il limite anche se una sonda li manda. I limiti scelti a mano prima (per sonda)
  diventano totali moltiplicandoli per le sonde dell'account. *Server, pannello, pagina utente, sonda.*
- **Corretto**: sulla sonda un limite di 0 FRITZ!Box aggiuntivi valeva come 4 (lo 0 era preso per «non
  indicato»), quindi il piano basso non limitava i FRITZ!Box. *Sonda.*
- **Tabella Utenti**: VM, piano e scadenza hanno ciascuno la sua colonna (ordinabile) invece di stare nella colonna
  *Stato*; *Registrato* e *Ultima attività* mostrano la data (l'ora passando sopra), così la tabella sta nello
  schermo. *Pannello.*
- **Tabella Utenti ordinabile**: nel pannello, un clic sull'intestazione di una colonna (Utente, Stato,
  Registrato, Ultima attività, Sessioni, Sonde, FRITZ!Box, Dispositivi) ordina l'elenco, un secondo clic lo
  inverte; la freccia indica la colonna e il verso. L'ordine scelto resta in questo browser e funziona insieme
  al filtro. *Pannello.*
- **Procedura guidata per la prima sonda**: un account senza sonde trova sulla Dashboard *Collega la tua prima
  sonda*, in quattro passi (nome, preparazione con il programma da scaricare, installazione con dominio e token
  da copiare, attesa del primo invio). Riconosce da sola quando la sonda si collega; propone di continuare con
  una sonda creata e mai collegata; permette di collegare una sonda già installata con il suo token. Prima la
  Dashboard diceva solo *Nessuna sonda ha ancora inviato dati*. *Pagina utente.*
- **I piani limitano anche le sonde**: basso 1 sonda, medio 2, alto 4 (oltre a FRITZ!Box e dispositivi per
  sonda). **I nuovi account nascono con il piano basso** (`NEW_USER_PLAN` nel `.env`); quelli esistenti restano
  come sono. *Server, pannello.*

## 18 ottobre 2026 (1.1.20261018-221955 · 4 versioni)

- **Mappe sul telefono della giusta misura**: la mappa delle VM (pannello, *Server › Tutte le VM*) e la *Mappa* della
  pagina utente si disegnavano a volte nella versione orizzontale, minuscola, finché non si ingrandiva la pagina:
  succedeva quando la mappa veniva preparata con la sua sezione ancora nascosta (per esempio aprendo *Tutte le
  VM* dopo *Aggiornamento Netmon*). Ora si ridisegna da sola appena la sezione compare o cambia larghezza.
- **Pallini sotto la latenza**: nella *Mappa* della pagina utente i pallini in movimento passano sotto le
  etichette dei ms invece di coprirle. *Pagina utente, pannello.*
- **Priorità bassa come multiplo della normale**: in *Impostazioni → Notifiche → Priorità di notifica* la bassa si
  sceglie come «2 volte la priorità Normale», «3 volte…» e così via (multipli dei *Controlli falliti prima
  dell'alert*), invece di un numero fisso di controlli. Sotto la scelta la pagina scrive il numero esatto («con la soglia normale di 4
  controlli falliti, la priorità bassa avvisa dopo 8»); se cambi la soglia normale, la bassa la segue. Le soglie
  scelte prima diventano il multiplo più vicino per eccesso (almeno ×2). Nel `.env`, `LOW_FACTOR` (predefinito 2)
  prende il posto di `LOW_THRESHOLD`. *Server, pagina utente.*
- **«Grafici» ora si chiama «Mappa»** (*Stato rete › Mappa*); i link e le scelte salvate con il nome vecchio
  portano alla Mappa. *Pagina utente.*
- **Conferma del salvataggio nelle Impostazioni**: premendo *Salva* compare accanto al pulsante, in verde con la
  spunta, *Salvataggio effettuato* (o l'errore in rosso). Prima la conferma finiva nel piede della pagina, fuori
  dallo schermo. Le altre conferme (ordine salvato, eventi eliminati, richieste alla sonda…) compaiono anche in
  un riquadro in basso al centro per qualche secondo. *Pagina utente.*

## 17 ottobre 2026 (1.1.20261017-165856 · 1 versione)

- **Invio email dal pannello**: in *Server › Invio email* del gateway si sceglie l'account da cui partono tutte
  le email (server, porta, utente, password, mittente). Passa da solo a tutte le VM, anche a quelle collegate
  dopo, senza toccare il `.env`; *Usa il .env* torna alle righe `SMTP_…` di ogni macchina. *Invia email di prova*
  la fa partire dal gateway e da ogni VM e per ognuna dice se è partita o perché no. *Server, pannello.*
- **Errore vero quando la password è sbagliata**: prima, se Gmail rifiutava la password, si vedeva solo
  *Connection unexpectedly closed* (dopo il rifiuto si provava un secondo metodo di accesso e Gmail chiudeva);
  ora l'accesso è un tentativo solo e l'errore è *535 Username and Password not accepted*. *Server.*
- **Il pannello parte dal gateway**: la macchina scelta nella barra (gateway o VM) resta solo nella scheda del
  browser in cui l'hai scelta. Prima veniva ricordata per sempre e, senza scelta, il pannello apriva la prima
  VM: aprendo per esempio *Aggiornamento Netmon* si finiva su vm1 o vm2 invece che sul gateway. *Pannello.*

## 16 ottobre 2026 (1.1.20261016-123657 · 1 versione)

- **Conservazione dei dati scelta da ogni utente**: in *Impostazioni → Account e backup → Conservazione dei
  dati* l'utente sceglie per quanto tenere lo storico delle sue sonde (giorni, settimane, mesi, tutto, oppure
  come il server) e può cambiarla quando vuole; accorciando, i dati esclusi si eliminano subito. *Elimina lo
  storico adesso* cancella misure ed eventi delle sue sonde lasciando sonde e account. La conservazione del
  pannello diventa quella predefinita (account che non scelgono, sonde senza account). La pulizia oraria e le
  misure in arrivo dal buffer seguono la durata di chi possiede la sonda. *Server.*
- **Piani dell'account**: nei *Limiti* di un utente il campo *Piano* sceglie FRITZ!Box e dispositivi per sonda:
  basso (1 FRITZ!Box, 5 dispositivi), medio (2 e 15), alto (4 e 45) o personalizzato (numeri a mano). Il piano
  compare nella colonna *Stato*. *Server, pannello.*
- **Scadenza dell'account**: dal menu *Azioni* di un utente, *Scadenza…* attiva, sposta o toglie la data di
  scadenza. L'utente riceve un'email all'attivazione e un promemoria 7 giorni prima; alla data l'account si
  blocca da solo (email all'utente, avviso agli amministratori, messaggio dedicato all'accesso). Spostando o
  togliendo la scadenza l'account si sblocca. L'utente vede la data nelle sue impostazioni. *Server, pannello.*

## 15 ottobre 2026 (1.1.20261015-152918 · 5 versioni)

- **Cambio di dominio senza toccare le sonde**: rilanciando l'installazione con un dominio nuovo (gateway con
  *Riconfigurare*, VM con `--dietro-gateway` e un token nuovo) i nomi precedenti della macchina finiscono in
  `OLD_HOSTS` nel `.env` e restano nel Caddyfile. Chi arriva a un vecchio nome è rimandato al nuovo indirizzo:
  i browser con un reindirizzamento permanente, le sonde con la risposta degli utenti spostati, così scrivono
  da sole il nuovo indirizzo in `config.yaml`. Su una VM l'installatore propone già il nome sul nuovo dominio
  (`vm1.<nuovo dominio>`). Procedura in `GUIDA.md`, capitolo 11. *Server, gateway, installazione.*
- **Firmare da più computer**: in *Firma NetMon* il comando *Usa la chiave di un altro computer* importa la copia
  di riserva di un altro computer al posto della chiave di questo (che resta da parte, `…sostituita-<data>`).
  Così Mac e Windows firmano con la stessa chiave, l'unica che la VM accetta. *Strumenti.*
- **«Firma NetMon» per Windows e nuova app per il Mac**: `tools/windows/FirmaNetMon.exe`, un solo file senza
  installazione, e l'app per il Mac (`tools/mac`) aprono la stessa pagina nel browser, servita solo al computer
  (127.0.0.1, codice segreto nell'indirizzo, niente richieste da altri siti). Il programma si chiude con *Chiudi*
  o da solo una ventina di minuti dopo la chiusura della pagina; firma, zip con la chiave, chiave pubblica e
  copia di riserva si scaricano dalla pagina stessa, quindi i pulsanti *Scarica…* funzionano anche a programma
  chiuso (prima, con la scheda in secondo piano, il programma poteva chiudersi e i download non partivano). Creano o importano la chiave di rilascio, firmano un pacchetto (aggiungendo la chiave se manca,
  con conferma se ce n'è un'altra), verificano una firma e salvano la copia di riserva. Stessa crittografia e
  stesso formato di chiave dell'app di prima e di `openssl`: le copie di riserva passano da Mac a Windows e
  viceversa. Sorgente unico in `tools/firma/src` (Go, solo libreria standard), compilato da
  `tools/firma/build.sh`. Gli eseguibili restano nel repository e non entrano nello zip del pacchetto: l'app per
  il Mac nello zip, senza di loro, usa le finestre di sistema come prima. *Strumenti.*
- **Rilascio con la numerazione corretta**: stessa versione del 14 ottobre sera, con il numero di versione
  allineato all'ora italiana reale (le versioni della sera del 14 erano qualche ora avanti). Nessuna modifica al
  codice: da qui `python3 tools/nuova-versione.py` senza argomenti produce di nuovo versioni sempre crescenti.

## 14 ottobre 2026 (1.1.20261014-235930 · 20 versioni)

- **Latenza tra sonda e VM nei Grafici**: la sonda cronometra ogni invio del report (arrivo al server e
  conferma) e manda la durata con il report successivo; l'albero la mostra a metà del collegamento server-sonda
  (sul telefono nella riga della sonda). Serve una sonda aggiornata. Inoltre l'albero non si ridisegna più a ogni
  aggiornamento della pagina: cambiano solo i testi. *Sonda, server (pagina di stato).*
- **Nuova pagina «Grafici»** sotto *Stato rete*, con un albero unico **Server, sonde e dispositivi**: la tua VM, le
  sonde (IP, dispositivi che rispondono, ultimo report) e i loro dispositivi (indirizzo e tempo di risposta), con lo
  stato a colori. Toccando una sonda se ne chiudono o aprono i dispositivi. Tre colonne su schermo largo, albero
  rientrato sul telefono; si muovono solo pallini lenti tra server e sonde. La mappa delle sonde non è più in
  *Sonde e monitoraggio*. *Server (pagina di stato).*
- **Mappe: nomi lunghi e chiusura**: le schede si allargano per il nome più lungo; oltre il limite il testo si
  rimpicciolisce e, se serve, si accorcia con «…» (nome intero nel suggerimento). Il riquadro dei *Grafici* si
  chiude come le altre sezioni; nel pannello la riga *Mappa dei collegamenti* chiude solo la mappa. Le scelte
  restano nel browser. *Server.*
- **Mappe con meno movimento** (Grafici e VM): si muovono solo dei pallini lenti sui collegamenti; schede,
  linee, led e gateway sono fermi. *Server.*
- **Su quale macchina stai lavorando** nel pannello: nelle sezioni che valgono per una sola macchina, una barra
  sotto l'intestazione con gateway e VM e il loro stato. La macchina attiva è blu (gateway) o verde acqua (VM);
  sotto, una frase dice su quale macchina agiscono i pulsanti della pagina. Lo stesso colore compare sul nome
  nel titolo e in cima ai riquadri. La barra sostituisce il menu a tendina «VM». *Server (pannello).*
- **«Firma NetMon» aggiunge la chiave al pacchetto**: se lo zip non contiene ancora una chiave pubblica di
  rilascio, l'app ci mette la tua (`server/release-key.pub`) e poi lo firma. Così la prima chiave arriva
  sulla VM dal pannello senza dover cambiare il repository. La password si controlla prima di toccare lo
  zip. Il messaggio del pannello *La VM non ha ancora la chiave di rilascio…* ora dice come risolvere.
  *Strumenti, server (pannello).*
- **Mappa dei collegamenti delle VM**: in *Server › Tutte le VM* il gateway al centro e le VM intorno, con nome,
  IP privato, dominio pubblico, versione e sonde. Collegamenti animati (pacchetti nei due versi, latenza a metà
  linea), in verde, giallo (lenta o da riavviare) o rosso tratteggiato (non risponde); toccando una VM la si
  apre. Sul telefono le VM stanno una sotto l'altra su una linea comune; con *Riduci movimento* le animazioni si
  fermano. Il disegno è un componente riutilizzabile, pronto anche per le sonde. *Server (pannello).*
- **Icona per l'app «Firma NetMon»**: il logo di netmon con un pennino, in tutte le misure di macOS
  (`AppIcon.icns`), generata da `tools/genera-icone.py --mac`. *Strumenti.*
- **Zip rifatti dal Finder accettati**: il verificatore dei pacchetti (VM e sonda) ignora i file nascosti che il
  Mac aggiunge comprimendo una cartella (`__MACOSX/`, `._*`, `.DS_Store`) e non li estrae mai; prima il
  pacchetto veniva rifiutato con *Percorsi non ammessi: __MACOSX/…*. Tra i controlli compare quanti ne ha
  ignorati. *Server, sonda.*
- **1.1 · Pacchetti firmati dall'autore**: dal pannello `/admin` la VM installa solo pacchetti `netmon.zip`
  firmati con la **chiave di rilascio** dell'autore (ECDSA P-256). La privata sta solo sul Mac dell'autore,
  cifrata con una password; la VM ha la pubblica (`/usr/local/share/netmon/release-key.pub`, dal file
  `server/release-key.pub` del pacchetto). `netmon-vm-selfupdate` (root) verifica la firma sulla sua copia
  privata prima di ogni altro controllo; senza firma valida non installa nulla. Prima chi entrava nel pannello
  poteva far girare codice come root sulla VM e, con la firma della VM, sulle sonde di tutti gli utenti. Lo zip si
  carica insieme al suo `.sig`; il pannello mostra l'impronta della chiave installata e l'esito della firma tra i
  controlli; dal gateway la firma va con lo zip a ogni VM. La prima chiave arriva con il primo pacchetto che la
  contiene ed è firmato con lei; per cambiarla si firma con la vecchia il pacchetto con la nuova. *Server, gateway.*
- **Nuova app «Firma NetMon» per il Mac** (`tools/mac`): con un doppio clic crea la chiave di rilascio, firma i
  pacchetti (crea `netmon-<versione>.zip.sig` accanto allo zip), verifica una firma, mostra la chiave pubblica e
  ne salva una copia di riserva. Usa solo ciò che c'è già in macOS. Istruzioni in `tools/mac/LEGGIMI.md`. *Strumenti.*
- **Spostamenti tra VM solo verso `https://`**: una sonda spostata su un'altra VM segue il nuovo indirizzo solo
  se è `https://` (o `http://` nella rete di casa, come nella pagina locale): prima un indirizzo `http://`
  pubblico avrebbe fatto viaggiare il token in chiaro. Il pannello sposta un utente solo verso una VM con
  indirizzo `https://`, controllato prima di copiare l'utente, e una VM si collega al gateway solo con un
  indirizzo pubblico `https://`. *Server, sonda.*
- **Informativa sulla privacy aggiornata** (quattro lingue): titolare indicato come gestore del servizio, senza
  nome; descrive server di accesso e server degli utenti (i dati delle sonde stanno solo sul server
  dell'account) e i controlli di sicurezza. *Server.*
- **robots.txt e sitemap.xml**: pubblici su gateway e VM, con le sole pagine pubbliche (accesso, stato,
  informativa); la sitemap del gateway elenca anche le pagine di tutte le VM collegate, per Search
  Console. *Server, gateway.*
- **Meno pacchetti Google sulle VM**: su Google Cloud l'installazione (anche `--aggiorna`) toglie
  `google-cloud-cli` (con i suoi componenti) e `google-osconfig-agent`, che netmon non usa e che rendevano
  lenti gli aggiornamenti del sistema. Restano gli agenti per SSH, rete e metadati. Si tengono con
  `NETMON_KEEP_GOOGLE=1`. *Server.*
- **Aggiornamento del sistema a priorità bassa**: apt gira con priorità minima di CPU e disco, così su
  una VM piccola (una CPU condivisa) pagina e sonde restano più reattive durante l'aggiornamento.
  *Server (VM).*
- **`/admin` di una VM porta al gateway**: `https://vmN.…/admin` rimanda a `https://dominio/admin`,
  l'unico pannello con gli amministratori; prima mostrava un accesso che non accettava nessuna
  password. *Server (VM).*
- **Barra in alto sempre in vista e tasto «Torna su»**: nella pagina di stato e nel pannello la barra blu
  resta in cima mentre si scorre; su telefono, scendendo lungo la pagina, compare in basso a destra un
  tasto tondo che riporta all'inizio. *Server.*
- **Pausa e avvio uguali su telefono e PC**: i tasti ⏸ e ▶ sono disegnati come lo scudo, invece delle
  emoji che su iPhone diventavano un riquadro blu. Pausa, scudo e grafico hanno la stessa misura e su
  telefono restano in colonna da un dispositivo all'altro. *Server.*
- **Pagina giusta sul telefono**: la barra blu in alto allargava la pagina oltre lo schermo e il telefono
  la rimpiccioliva, lasciando il contenuto in un terzo della larghezza. Ora la pagina occupa tutto lo
  schermo, come prima su PC. *Server.*
- **Scudi del controllo di sicurezza più chiari**: lo scudo è disegnato e colorato secondo lo stato (mai
  controllato, in corso o in coda, nessun rischio, rischio medio, rischio alto, non riuscito), e passandoci
  sopra lo dice a parole. Prima era un'emoji quasi uguale in tutti i casi. *Server.*
- **Accesso dalla VM sbagliata**: chi accede all'indirizzo di una VM che non ha il suo account viene
  portato alla VM dove l'account c'è, con l'email già scritta (la VM lo chiede all'orchestratore). *Server.*
- **Freccia del menu VM**: nella barra in alto del pannello il menu per scegliere la VM ha di nuovo la
  sua freccia (la perdeva per lo stile della barra scura). *Server.*
- **Pagina d'accesso del gateway e amministratori**: l'email di un amministratore che non è anche un
  utente porta al pannello di amministrazione, con l'email già inserita, invece che alla prima VM. Se
  è anche un utente, si va alla sua VM come prima. *Gateway e server.*

## 13 ottobre 2026 (1.0.20261013-235139 · 31 versioni)

- **Controllo di sicurezza: tipo e coda**: prima di partire si sceglie *Veloce* (circa 30 porte a
  rischio), *Standard* (circa 50) o *Approfondito* (oltre 1100 porte, anche i servizi non riconosciuti).
  Se sulla sonda è già in corso un controllo, il nuovo va in coda e parte da solo dopo; si può togliere
  dalla coda. *Server e sonda* (sonde da aggiornare per scegliere il tipo).
- **Avviso del controllo di sicurezza**: un controllo chiesto con *Controlla ora* manda sempre l'esito sui
  canali scelti, anche senza rischi o se non riesce; prima arrivava solo per un rischio nuovo, quindi
  ricontrollare un dispositivo già segnalato non mandava niente. Il controllo giornaliero avvisa ancora
  solo per i rischi nuovi. Il registro dice anche quando l'avviso è saltato per il tetto orario. *Server.*
- **Aggiornamento dal gateway, scelta delle VM**: nell'elenco *VM collegate* ogni VM da aggiornare (e
  il gateway) ha una casella; togliendo la spunta resta esclusa. Cambiando la VM in alto il pannello
  resta nella sezione aperta, invece di tornare a *Tutte le VM* dove la scelta non c'è. *Server.*
- **Conteggi della Dashboard cliccabili**: *Totale dispositivi*, *Rispondono*, *In verifica*, *Non
  rispondono* e *In pausa* aprono *Sonde e monitoraggio* con i soli dispositivi in quello stato. Lo
  stesso filtro si sceglie anche lì, dalla barra *Mostra:* con un pulsante per stato e il conteggio. *Server.*
- **Accesso dal gateway dopo un ripristino da backup**: un utente spostato con *Sposta* e poi
  eliminato e reimportato su un'altra VM veniva mandato ancora alla VM dello spostamento. Ora conta la
  VM dove l'account c'è davvero; lo spostamento ricordato serve solo se nessuna VM ha l'account, e il
  pannello toglie da solo gli spostamenti superati. *Gateway e server.*
- **Sonda: chiave degli aggiornamenti di nuovo installata**: `installa-sonda.sh` scartava ogni indirizzo
  del server («Indirizzo del server non valido: https://vm1…») per un errore nell'espressione che lo
  controlla, quindi non scaricava (né rinnovava) la chiave con cui la sonda verifica gli aggiornamenti
  completi dal server. *Solo sonda: rilancia `installa-sonda.sh --aggiorna`.*
- **Aggiornamento di una sonda già aggiornata non è più un errore**: se la sonda ha già la versione
  del server, l'esito è «completato» invece di «[ALERT] … non riuscito» (anche per le sonde con i
  programmi di prima, riconosciute dal server). *Server e sonda.*
- **Registro delle operazioni nel pannello**: in *Sonde › Elenco sonde*, colonna *Operazione*,
  **Registro** mostra il registro dell'ultima operazione della sonda (aggiornamento, Wi-Fi…), come
  promette l'avviso. *Solo server.*
- **Sonde di tutte le VM nel pannello del gateway**: *Sonde › Elenco sonde* sul gateway mostra le
  sonde di ogni VM con la colonna **VM**, e *Programma un aggiornamento* le aggiorna su tutte le VM
  (tutte o quelle selezionate). Anche *Aggiornamento Netmon* sul gateway propone le sonde di tutte le VM
  da aggiornare dopo le VM, comprese quelle delle VM che hanno già la versione nuova. Prima sul
  gateway l'elenco era vuoto. *Solo server.*
- **Utenti eliminati: email e «Utenti non attivi»**: chi viene eliminato (dall'amministratore o da sé)
  riceve un'email. Con «elimina tutto» l'utente sparisce con i dati; con «solo l'account» compare nella
  nuova sezione **Utenti non attivi** del pannello, sotto Utenti, con le sonde e lo storico ancora sul
  server: **Elimina i dati** li cancella subito, altrimenti si cancellano da soli dopo **30 giorni**.
  Corretto anche un difetto: su una VM rimasta senza utenti, il primo che si registrava riceveva le
  sonde (con i dati) degli account eliminati. *Solo server.*
- **Pagina d'accesso del gateway con logo e nome** *NetMon Home tool*, come le altre pagine.
  *Solo gateway.*
- **Icona nel browser su tutte le pagine**: sul gateway icone, caratteri e informativa venivano
  rimandati a una VM (e se il browser non segue il rimando, o la VM non risponde, la scheda restava
  senza icona); ora li serve l'orchestratore. La pagina locale della sonda ha anche l'icona PNG, per
  Safari e per la schermata Home. *Gateway e sonda.*
- **Utente spostato tra VM**: la pagina d'accesso del gateway lo mandava ancora alla VM di prima
  (ricordata fino a 24 ore, o fino al prossimo controllo dell'elenco). Ora a ogni accesso il gateway
  chiede alle VM dove vive l'account. *Solo gateway.*
- **Registro delle notifiche più chiaro**: se nel `.env` della macchina che invia mancano `SMTP_HOST`
  o `TELEGRAM_BOT_TOKEN`, il registro lo dice («non inviato: manca la configurazione…») invece di
  segnarlo come inviato. *Solo server.*
- **Registro degli avvisi inviati**: ogni avviso ora lascia una riga nel registro del server anche quando parte bene (*Avviso «…» inviato via telegram*), oppure dice perché non è partito (nessun canale scelto per quel tipo, sonda senza proprietario). Prima si vedevano solo gli invii falliti, quindi un registro vuoto non distingueva «inviato» da «mai tentato». *Solo server.*
- **Controllo di sicurezza dei dispositivi**: lo scudo 🛡 nella riga di ogni dispositivo fa provare alla
  sonda circa 55 porte TCP comuni e segnala i servizi a rischio (Telnet, MQTT/Redis/VNC senza password,
  telecamere RTSP aperte, ADB, RDP, pannelli web con login senza HTTPS, certificati scaduti…), su
  richiesta o una volta al giorno. Solo indirizzi della rete di casa (la sonda rifiuta gli IP pubblici),
  poche connessioni alla volta e solo domande innocue ai servizi. Avviso del nuovo tipo *Controllo di
  sicurezza* quando compare un rischio alto o medio nuovo. *Server e sonda.*
- **Stessa larghezza per tutte le pagine**: pagina utente, pannello di amministrazione e pagina locale
  della sonda ora sono larghe al massimo 1230 px (prima 1100 per utente e sonda, 1360 per il pannello).
  *Server e sonda.*
- **Telegram: la prova riuscita salva il chat ID**: prima il messaggio di prova partiva verso il chat ID
  scritto nella pagina anche se non era ancora salvato, quindi la prova riusciva ma gli avvisi veri non
  arrivavano finché non si premeva *Salva*. Ora, se il messaggio arriva, il chat ID si salva subito (per
  gli utenti e per gli amministratori). Nel registro del server un invio Telegram fallito riporta il
  motivo scritto da Telegram (es. «chat not found»). *Solo server.*
- **Nuovo aspetto «Oceano» e nuovo logo**: blu oceano al posto del lampone, sfondo azzurro tenue con i
  riquadri bianchi e la barra in alto piena in blu notte, anche nel pannello di amministrazione, nella
  pagina locale della sonda, nella pagina del gateway e nelle email. Tema scuro allineato. Il logo è ora
  una «maglia con la casa al centro»: sei dispositivi su un esagono collegati alla sonda di casa, a linee
  sottili (favicon e icona del telefono rigenerate con `tools/genera-icone.py`). La schermata di accesso
  mostra il logo più grande e il nome per esteso, *NetMon Home tool*, e resta centrata anche quando il
  menu laterale era aperto. *Server e sonda.*
- **Pannello di amministrazione in inglese, tedesco e francese**: in *Il tuo account › Lingua e fuso
  orario* ogni amministratore sceglie la lingua del pannello e degli avvisi che riceve (email e
  Telegram). Le traduzioni del pannello stanno in `server/i18n_admin.py`; completati anche i testi della
  pagina utente che mancavano. *Solo server.*
- **Fuso orario per utente e per amministratore**: in *Impostazioni › Account e backup › Lingua e fuso
  orario* ogni utente sceglie il fuso degli orari della pagina e delle notifiche; gli amministratori lo
  scelgono in *Il tuo account* per gli orari del pannello. Predefinito: quello del server (`TIMEZONE`).
  *Solo server.*
- **Sposta un utente su un'altra VM**: nel pannello del gateway, *Utenti › Azioni ▾ › Sposta su un'altra
  VM* porta account, sonde e tutto lo storico sulla VM scelta. Prima controlla lo spazio (sulla VM di
  arrivo circa tre volte lo storico più una riserva, e lo spazio per lo zip sulla VM di partenza e sul
  gateway) e non parte se non basta; lo ricontrolla con la misura vera dello zip. Durante lo spostamento
  le sonde tengono da parte le misure e le mandano dopo. La VM di partenza ricorda dove è andato
  l'utente: le sonde ricevono il nuovo indirizzo e lo scrivono da sole in `config.yaml` (token
  invariato), chi accede viene portato alla VM nuova, il gateway instrada lì anche le sonde puntate a
  lui. *Server, gateway e sonde* (le sonde più vecchie vanno aggiornate o ripuntate a mano).
- **Pulsante Azioni ▾ sugli utenti**: in *Utenti* e *Codici di accesso* le azioni di ogni riga (limiti,
  reinvia codice, blocca, esporta, sposta, elimina; per i codici reinvia, cambia mail, dettagli, elimina)
  stanno in un menu che si apre da un pulsante con lo stesso stile degli altri. Nei codici già usati il
  menu ha anche le azioni sull'account. *Solo server.*
- **Reinvia codice anche agli utenti registrati**: manda all'email un nuovo codice di accesso (7 giorni)
  con cui l'utente rientra nel suo account scegliendo una nuova password; sonde e storico restano.
  *Solo server.*
- **Niente doppioni con un nuovo codice**: un codice d'invito per l'email di un account esistente (per
  esempio *Reinvia codice* dopo la registrazione) non crea un secondo account: chi lo usa rientra nel
  suo con la nuova password, con sonde e storico. Nella tabella *Utenti* il codice compare come *nuovo
  codice per l'account*. *Solo server.*
- **Codici di verifica incollabili**: nei campi del codice a 6 cifre (accesso al pannello, nuovi
  amministratori) si incolla anche un testo con spazi o parole intorno: restano solo le cifre. *Solo server.*
- **Link d'invito con email e codice già inseriti** anche sulla prima registrazione di una VM nuova (prima
  la VM senza utenti mostrava la pagina del primo accesso e ignorava il link). *Solo server.*
- **Impostazioni già compilate**: nella pagina utente i campi di *Controlli* e *Notifiche* mostrano sempre
  i valori predefiniti (controllo ogni 60 s, 2 pacchetti, 3 controlli falliti, priorità bassa dopo 5, ecc.)
  anche prima che la sonda mandi il primo report; finché non c'è una sonda sono in sola lettura.
  Le colonne *Indirizzo IP* e *Ultimo RTT* sono attive di base per chi non le ha mai scelte. *Solo server.*
- **Pannello › Server**: la tabella di tutte le VM e «Collega una VM» compaiono solo nella sezione
  *Tutte le VM* (prima si vedevano anche in *Stato VM* e nelle altre). Tolto il tasto *Apri*: la VM da
  guardare si sceglie dal menu «VM» in alto, che ora ha lo stesso aspetto degli altri pulsanti e non compare
  in *Tutte le VM*, dove non serve. La casella «Installa lo stesso pacchetto su tutte le VM» è
  allineata alla sua scritta. *Solo server.*
- **Pagine centrate anche con il menu aperto**: su schermo largo il contenuto resta centrato nello spazio
  a destra del menu (prima si spostava verso destra). Il pannello di amministrazione è più largo
  (fino a 1360 px), così le tabelle degli utenti e delle VM entrano senza scorrere. *Solo server.*
- **Documentazione allineata**: `INSTALLAZIONE.md` ha il Caso 4 (più VM dietro un gateway), `GUIDA.md` la
  sezione 11 (gateway, *Tutte le VM*, menu VM, esporta e importa un utente) e le impostazioni predefinite,
  `README.md` descrive il progetto; i comandi usano lo zip della versione e la cartella `~/netmon`.
- **Comando per collegare una VM** (*Server › Tutte le VM*) con lo zip della versione invece di git. *Solo server.*
- **Zip della sonda scaricabile**: `/scarica-sonda` (link in *Impostazioni › Sonde* e nell'email d'invito)
  scarica `netmon-sonda-<versione>.zip` con la sola cartella `probe`, sempre della versione installata sulla
  VM (che si aggiorna insieme al gateway). Solo per utenti registrati: senza accesso porta alla pagina di
  accesso e dopo l'accesso scarica lo zip. L'email d'invito spiega anche come installarlo. *Solo server.*
- **Importa un utente già presente: unisci o sovrascrivi lo storico**: se l'account esiste già sulla VM,
  l'importazione non si rifiuta più ma porta solo lo storico (misure, eventi, traffico, speedtest, FRITZ!Box)
  sulle sonde che scegli (proposta: stessa sonda o stesso nome). *Unisci* aggiunge ciò che manca senza
  doppioni; *Sovrascrivi* tiene i dati del backup nel periodo che copre. Account, sonde, token e impostazioni
  della VM non cambiano. *Solo server.*
- **Indirizzo del server accanto al token della sonda**: in *Impostazioni › Sonde*, creando una sonda o
  generando un nuovo token, il riquadro mostra anche l'indirizzo a cui la sonda deve puntare (quello della VM
  dell'utente, es. `https://vm1.netmon-public.com/api/report`), con il suo tasto *Copia*. *Solo server.*
- **Aggiornamento dal gateway propagato alle VM**: caricando lo zip con il gateway scelto in alto, il
  pacchetto va da solo a tutte le VM con una versione più vecchia (prima loro, per ultimo il gateway), come
  per le sonde: l'elenco dopo il controllo segnala le VM **da aggiornare**, quelle che hanno **già** quella
  versione (non vengono toccate) e quelle che non rispondono. Se il gateway è già aggiornato si aggiornano
  solo le VM rimaste indietro. Tolta la casella «Installa lo stesso pacchetto su tutte le VM». *Solo server.*
- **Conferma della nuova versione propagata alle VM**: con il gateway scelto in alto, il riquadro del rollback
  elenca anche le VM con la versione nuova ancora da confermare e *Conferma la nuova versione* le conferma
  tutte insieme al gateway (prima la conferma valeva solo per il gateway e le VM, alla scadenza delle 4 ore,
  tornavano da sole alla versione precedente). *Rollback subito* resta per la sola macchina scelta. *Solo server.*
- **Revisione di sicurezza (server, gateway, sonda)**:
  - le azioni del pannello che chiedono la password, inoltrate dall'orchestratore a una VM, valgono solo se
    la password è stata davvero verificata sull'orchestratore; e la VM accetta le intestazioni del gateway
    solo dagli indirizzi in `TRUSTED_PROXIES`;
  - richieste grandi (oltre 256 KB) accettate solo da sonde con un token valido, su report e recupero dati;
  - blocco dei tentativi di accesso: per coppia IP-account (nessuno può bloccare l'account di un altro
    sbagliando la password apposta), indirizzi IPv6 raggruppati per rete /64, gli errori dell'IP non
    si azzerano più con un accesso riuscito; corretto un controllo invertito sul blocco dei codici
    MFA degli amministratori;
  - caratteri di controllo tolti da email e nomi della rete;
  - il gateway, in collegamento diretto, non serve le pagine delle VM con il suo indirizzo: le
    reindirizza a `https://vmN.…` (passano solo sonde e controlli di stato);
  - `installa-server.sh --dietro-gateway`: gateway solo in `https://`; la risposta del gateway è
    controllata (nome, chiave, indirizzi, solo le impostazioni email/Telegram previste) prima di finire
    nel `.env`, e nessun valore con un a capo entra nel `.env`;
  - sonda: pagina locale con un limite globale ai tentativi sbagliati, nuova password di almeno 12
    caratteri; l'indirizzo per la chiave degli aggiornamenti è controllato; le richieste al server non
    seguono reindirizzamenti (il token non va mai a un altro indirizzo); i file in `/var/lib/netprobe`
    sono leggibili solo dalla sonda.
- **Pulizia del codice**: tolte funzioni, campi e stili che nessuno usava più (icona 192 px, vecchi elenchi
  di amministratori, registro Wi-Fi, opzioni del pannello della sonda, variabili degli installatori);
  alcune letture del database spostate fuori dal ciclo principale del server. `tools/nuova-versione.py`
  controlla anche `gateway.py`, `netprobe-wifi` e che la pagina della sonda abbia lo stesso traduttore
  del server; `tools/i18n-estrai.py probe --mancanti` non conta più le traduzioni come testi da tradurre.

## 12 ottobre 2026 (1.0.20261012-232942 · 5 versioni)

- **Numerazione da 1.0**: la versione riparte da `1.0.` con il repository NetMon.
  Server e sonde già sulla 2.x non accettano un pacchetto 1.0 dal pannello (lo vedono come più vecchio):
  la prima volta si aggiornano a mano (`installa-server.sh --aggiorna`, `installa-sonda.sh --aggiorna`).
- **Più VM dietro un indirizzo unico (gateway)**: nuovo servizio `gateway/`. Ogni VM probe scrive il proprio
  nome (`VM_ID`) in testa a token delle sonde, sessioni e codici di accesso, e il gateway inoltra ogni
  richiesta alla VM giusta. *Server e gateway.*
- **Il gateway fa da orchestratore**: sulla macchina del gateway gira netmon con `ROLE=orchestratore`, che ha
  il pannello di amministrazione e gli amministratori (uguali per tutte le VM) ma nessun utente. Le VM probe
  sono tutte uguali: tengono utenti, sonde e dati, non hanno un pannello e accettano comandi solo
  dall'orchestratore, con una chiave per ogni VM. *Server e gateway.*
- **Un solo pannello per tutte le VM**: utenti e codici di accesso di tutte le VM in un elenco, ognuno con la
  sua VM; creando un utente si sceglie la VM (proposta quella con meno sonde). *Sonde* e *Server* mostrano una
  macchina alla volta, scelta in alto. La conservazione dei dati vale per tutte le VM; un pacchetto netmon si
  può installare su tutte in un colpo. Gli avvisi delle VM arrivano agli amministratori del gateway.
  *Solo server.*
- **VM collegate con un token**: *Server › Tutte le VM › Collega una VM* genera un token (uno per VM, vale
  24 ore, una volta sola) e il comando da lanciare sulla VM. Collegandosi la VM riceve nome, chiave e
  impostazioni comuni (email, Telegram). Una VM si toglie solo se non ha utenti né sonde. Il gateway rilegge
  l'elenco delle VM ogni 30 secondi e subito quando ne vede una nuova. *Server e gateway.*
- **Tutte le VM** nella pagina *Server* del pannello: per ogni macchina se risponde, versione, utenti, sonde,
  CPU, memoria, disco. *Solo server.*
- **Collegamento diretto alle VM**: ogni VM probe ha il suo indirizzo pubblico (es. `vm1.netmon-public.com`)
  con il suo certificato HTTPS, e sonde e utenti parlano direttamente con lei. Il gateway mostra la pagina
  d'accesso: dall'email (o dal codice di accesso) capisce la VM e ci manda il browser, con l'email già
  inserita. Le sonde ancora puntate al gateway continuano a funzionare. `--dietro-gateway` chiede
  l'indirizzo pubblico della VM, configura Caddy e apre le porte 80 e 443. *Server e gateway.*
- **Trasferimento di utenti**: nella pagina *Utenti*, *Esporta* scarica uno zip con account, sonde e tutto
  lo storico (anche dalla 2.1, aggiornata alla 2.1.20261012-231218), e *Importa un utente* lo carica su
  una VM a scelta. L'utente entra con la stessa password e le sonde continuano con il loro token, in
  pausa per un'ora: il gateway trova da solo la VM anche dei token senza nome della VM. *Server e gateway.*
- **`installa-server.sh --orchestratore`** installa il gateway con l'orchestratore e Caddy;
  **`--dietro-gateway`** chiede indirizzo del gateway e token e collega la VM (niente Caddy, porta 8000
  aperta solo al gateway). Su una VM già installata la ricollega senza toccare account e dati. *Solo server.*

## 10 ottobre 2026 (2.1.20261010-212741 · 14 versioni)

- **Aggiornamenti e riavvii immediati senza notifiche**: con *Adesso* nella programmazione (sistema
  della VM, netmon da pacchetto, sonde) e con i pulsanti *Aggiorna sistema* e *Riavvia la VM* non parte
  nessun avviso, né agli utenti né agli amministratori; resta il registro eventi. Gli errori restano
  allarmi per gli amministratori; le programmazioni a data e ora avvisano come prima. *Solo server.*
- **Repeater collegato alla mesh via cavo: grafico 📊** del suo traffico (download e upload, medie,
  picchi, dati scambiati), un campione al minuto dai contatori della porta LAN, nello storico del
  traffico con l'id del repeater; la sonda invia anche la durata di ogni campione. *Server e sonde.*
- **CHANGELOG riassunto per giorno**, per tutte le versioni.
- **Lingue: italiano, inglese, tedesco, francese.**
  - *Pagina utente*: la lingua dell'account si sceglie alla registrazione (prima dell'accesso la pagina
    segue il browser, con un selettore in alto) e si cambia in *Impostazioni → Account e backup → Lingua*.
    Nuova colonna `lang` negli utenti; nuove rotte `/api/account/lang` e `/api/lang`; una pagina per lingua.
  - *Notifiche* (email, Telegram, ntfy, email di conferma, messaggio di prova) nella lingua del destinatario.
  - *Pagina locale della sonda*: lingua chiesta da `installa-sonda.sh` e cambiabile in alto a destra
    (`language` in `config.yaml`, nuova rotta `/api/language`).
  - Come funziona: i testi restano in italiano nel codice; un traduttore nel browser e uno sul server li
    sostituiscono con quelli di `server/i18n.py` (nuovo file, circa 860 voci; per la sonda un dizionario
    dentro `config_web.py`), compresi testi con parti variabili, messaggi d'errore ed eventi già salvati. I
    nomi scelti dagli utenti non si traducono. Il pannello di amministrazione resta in italiano.
  - Nuovo `tools/i18n-estrai.py`: elenca i testi da tradurre (`--mancanti` per quelli nuovi). *Server e sonde.*
- **Impostazioni → Notifiche**: «Salva i canali» diventa **Salva notifiche**, in evidenza; anche **Salva** in
  fondo alla pagina salva le notifiche se sono cambiate (e si attiva anche senza una sonda scelta).
- **Selettori della lingua** (Impostazioni, schermata di accesso, pagina locale della sonda) con lo stesso
  aspetto dei pulsanti come *Scarica backup*: pillola, stesso carattere e altezza, freccina.
- **Traduzioni mancanti nella scheda della sonda** (Salute e Rete): *regolare*, *ottimo/buono/discreto*,
  *trasmissione*, «154 MB su 448 MB», «media … su 1 core» (singolare), più altre parole singole
  (eventi delle reti Wi-Fi e dei comandi della sonda, *accesso richiesto*). In inglese i numeri usano il
  punto decimale (38.5 °C, 2.4 GHz), nella pagina e nelle notifiche. L'estrattore ora riconosce queste
  parole. *Server e sonde.*
- **Versione 2.1**: da qui la numerazione è `2.1.AAAAMMGG-hhmmss`.
- **Privacy e GDPR.**
  - *Niente più Google Fonts*: Roboto e Roboto Mono (licenza SIL OFL 1.1) li servono il server (nuovo
    `server/fonts.py`, rotta `/fonts/…`) e la pagina locale della sonda; la CSP non ammette più altri siti.
  - *Scarica i miei dati* in *Impostazioni → Account e backup*: zip con `account.json`, `sonde.json` e lo
    storico di ogni sonda in CSV (eventi, ping, traffico, FRITZ!Box, SpeedTest, sistema). Nuova rotta
    `/api/account/export`.
  - *Eliminazione dell'account* (dall'utente o dal pannello): l'email esce dal registro amministrativo e
    dagli inviti; gli inviti ancora validi per quell'indirizzo si revocano. `secure_delete` nei database.
  - *Durate*: il registro amministrativo scade dopo un anno (`ADMIN_EVENTS_DAYS`, nuova voce nel `.env`);
    `installa-server.sh` limita il registro di sistema a 30 giorni e 200 MB.
  - *Informativa* `server/privacy.html` (titolare, Google Cloud nell'UE, email con Brevo, nessuna copia di sicurezza,
    riquadro *Fase di prova*: fino a nuova comunicazione, dati cancellati entro 30 giorni dalla fine),
    installata con il server e servita su `/privacy` con la durata dello storico scritta dal server; una versione
    in `data/privacy.html` ha la precedenza. Link **Informativa sulla privacy** sempre visibile, in piccolo, in
    fondo a ogni pagina (pagina di stato, `/admin` e le loro schermate di accesso, pagina locale della sonda,
    che apre quella del suo server). Informativa in italiano, inglese, tedesco e francese con selettore della
    lingua; si apre nella lingua dell'account, del browser o della sonda (`?lang=`). Con il logo netmon in
    alto (link alla pagina di stato) e le stesse icone delle altre pagine.
  - `env.example`: esempio di configurazione con Brevo.
  - GUIDA: nuova sezione *Privacy e GDPR*. *Server e sonde* (la sonda solo per i caratteri).

## 9 ottobre 2026 (2.0.20261009-225502 · 21 versioni)

- **FRITZ!Box: rete mesh.** La sonda legge ogni 5 minuti la mappa mesh del FRITZ!Box principale
  (`Hosts1` → `X_AVM-DE_GetMeshListPath`) e la invia solo quando la rilegge; il server tiene l'ultima
  per 15 minuti. Nel riquadro: casella **Mesh** e sezione **Rete mesh** (chiusa di default) con il
  collegamento di ogni repeater (cavo o Wi-Fi, velocità attuale su possibile, segnale) e i dispositivi
  di ogni nodo, quelli a segnale debole in giallo. Storico nel 📈 (*Collegamento mesh · nome*). **Avvisi
  della mesh** (spenti di default): repeater uscito e rientrato, collegamento Wi-Fi lento e tornato
  normale; nuovo tipo di avviso *Rete mesh*.
- **Repeater («Solo Wi-Fi» nella mesh)**: *Collegamento alla mesh*, dispositivi **Via cavo** (dalla
  mappa) e **banda in uso** dai contatori della porta LAN (`LANEthernetInterfaceConfig1`): *Download/
  Upload ora* con il collegamento via cavo, *Via cavo · download/upload* con quello Wi-Fi.
- **Stato della fibra** (`X_AVM-DE_WANFiber1`): sezione **Fibra** con i valori letti ogni 5 minuti, con
  nomi italiani per quelli del 5590 Fiber; nascosta se la linea in fibra non è in uso.
- **Clienti Wi-Fi di casa**: con più FRITZ!Box sulla stessa sonda, il pulsante 📶 apre il grafico
  cumulativo (uno strato per FRITZ!Box più gli ospiti); nuova rotta `/api/wifi-history`. Nuove voci
  *Rete mesh* e *Stato della fibra* in *Visualizzazione*. Corretti: stessa rete su due bande contata
  una volta sola; metrica *Ospiti Wi-Fi* vuota.
- **Correzioni dallo stress test** (solo server): le letture dello storico (Dashboard e grafici) girano in
  un thread con un tetto per server (4) e per account (2, fino a 8 in coda), così non fermano più i
  report; i tentativi di accesso in corso contano come errori (200 tentativi contemporanei: ne passano
  5); con un codice d'invito inventato la registrazione non rivela più se un'email ha un account.
- **Pagina locale della sonda** con il menu a sinistra (una sezione alla volta, indirizzo per sezione)
  e la sezione **Disinstalla sonda** (scrivere `DISINSTALLA` e la password); nuovo script di root
  `netprobe-uninstall`, usato anche da `installa-sonda.sh --disinstalla`.
- **`installa-sonda.sh` non richiede più `sudo`**: senza, completa l'installazione e spiega cosa non è
  disponibile e come attivarlo; *Stato sonda* dice *Aggiornamenti dal server: non disponibili*.
- **Limiti per utente**: dispositivi monitorati per sonda (predefinito 30; oltre, gli ultimi della lista
  non vengono controllati); a limite raggiunto spariscono *Aggiungi una sonda* e *Collega una sonda*;
  nota dei limiti nella pagina locale della sonda; colonne **FRITZ!Box** e **Dispositivi** nella tabella
  *Utenti*.
- **Ultimi eventi: filtro** per testo e tag (lavora su tutti gli eventi), con *Elimina tutti i filtrati*.
- **Telegram per gli utenti**: nome del bot letto dal token (`getMe`), *Invia un messaggio di prova*,
  istruzioni in una finestra (**Istruzioni configurazione Telegram**).
- **Dashboard**: ⇅ Ordine dei riquadri, salvato nell'account. Pagine di partenza: `/` apre la
  Dashboard, `/admin` *Amministrazione › Utenti*. Tasto **Esci** in alto nella pagina di stato.
- **Pannello**: separatori tra le parti di Impostazioni e Amministrazione, pulsanti larghi quanto il
  testo; tolti il tasto «i» e i commenti a scomparsa (resta, visibile, quello di *Conservazione dei
  dati*). *Dopo, aggiorna le sonde* parte sempre da *Nessuna*. Priorità di notifica in ordine Alta,
  Normale, Bassa, Mai.
- **GUIDA e INSTALLAZIONE riviste per intero** sul funzionamento attuale (tolte istruzioni superate e in
  parte dannose, nuove tabelle *Cosa installa lo script*).

## 8 ottobre 2026 (2.0.20261008-173139 · 19 versioni)

- **Nuova numerazione** `2.0.AAAAMMGG-hhmmss`; ogni modifica alza la versione e crea la zip
  `../netmon-<versione>.zip`, controllata da `pkgcheck.py` (tolto `nuova-versione.py --zip`).
- **Rollback degli aggiornamenti da pacchetto**: copia della versione precedente per 4 ore, con
  *Conferma la nuova versione* e *Rollback subito*; allo scadere torna da solo alla precedente. Reso
  sicuro in giornata: se la vecchia non riparte torna la nuova; il timer sopravvive ai riavvii
  (`netmon-vm-rollback-boot.service`); gli script in esecuzione non vengono sovrascritti sul posto; un
  lucchetto per tutte le operazioni; un aggiornamento a mano chiude la finestra. Riquadro sempre
  visibile, con testi brevi.
- **Pagina Dashboard**, prima voce del menu: riepilogo, un riquadro per dispositivo con il ping delle
  24 ore, **uso della linea** del FRITZ!Box in scala sul traffico reale (toccandolo si apre il traffico
  Internet). **Visualizza** nella barra in alto, scelte salvate nell'account (`dash_prefs`); grafici
  corretti (veri SVG, caricati anche aprendo la Dashboard direttamente).
- **Storico delle metriche FRITZ!Box** (📈: velocità, linea, cavo, ospiti, clienti per rete Wi-Fi;
  tabella `fritz_hist`) accanto al **📊** del traffico Internet; grafici a linea anche con punti più fitti
  dei campioni, asse in Mbit/s.
- **Limiti per utente** (tasto *Limiti* nella tabella *Utenti*): sonde per account (predefinito 50) e
  FRITZ!Box oltre al primo per sonda (predefinito 4).
- **Pagina locale della sonda**: rinomina della sonda e cambio della password della pagina (anche
  `installa-sonda.sh` accetta password con caratteri speciali).
- **Pannello**: scheda *Stato VM* → **Server** (titolo interno *Stato VM*), *Aggiorna netmon da
  pacchetto* → **Aggiornamento Netmon**, *Conservazione dei dati* spostata in *Sonde*; dettagli dei
  codici di accesso in un popup; testi più brevi.
- **Stato rete**: sezione *Sonde* → **Sonde e monitoraggio**; dispositivi nuovi o ripresi dalla pausa
  visibili subito come *modifiche in attesa*; nota FRITZ!Box più corta e a tutta larghezza.

## 7 ottobre 2026 (1.2.20261007-150232 · 1 versione)

- **Amministrazione › Utenti**: torna **＋ Aggiungi utente** (invito per email legato all'indirizzo,
  oppure codice da consegnare a mano). Gli inviti in attesa compaiono tra gli utenti come *invitato* /
  *invito scaduto*, con **Reinvia codice**, **Cambia mail** (nuovo codice per il nuovo indirizzo, il
  vecchio si elimina) ed **Elimina**; gli stessi tasti anche in *Codici di accesso*. Invitare
  un'email già registrata è rifiutato. Nuovo `POST /api/admin/invites/email`.

## 6 ottobre 2026 (1.2.20261006-140259 · 8 versioni)

- **Più FRITZ!Box per sonda** (fino a 4 oltre al primo, dalla pagina locale della sonda), con ruolo
  *Solo Wi-Fi* (repeater o secondo FRITZ in casa: solo client Wi-Fi) o *Principale* (altro posto,
  riepilogo e traffico completi). Letti in parallelo; il primo resta nei campi di sempre del report
  (compatibile con server e sonde vecchi), gli altri in `fritz_boxes` / `traffic_more`. Un riquadro
  per FRITZ in *Stato rete › FRITZ!Box*, traffico per FRITZ (`/api/traffic?box=`, colonna `box` nella
  tabella `traffic`). I FRITZ si aggiungono solo dalla pagina locale: la password non passa dal server.
- **FRITZ!Box più leggero e robusto**: traffico ogni 30 s di default (prima 10); il riepilogo si ferma
  al primo errore di rete e oltre 15 s usa gli ultimi valori; dopo un timeout si chiudono solo le
  connessioni HTTP (connessione ricreata dopo 3 errori di fila); elenco ospiti riletto solo quando cambia
  il numero di client o ogni 5 minuti.
- **Togliere un dispositivo con «－»** nell'intestazione della sonda; **＋** apre la finestra con una riga
  già pronta.
- **Tema «Lampone e foglia»** (Roboto, pulsanti a pillola, lampone `#CD2355`, verde foglia, errori
  arancio), striscia colorata per stato, nuovo logo (stella di nodi) su tutte le pagine e nelle email.
  **Impostazioni diventa una pagina** (`#impostazioni`), con *Salva* sempre in vista.
- **Dettaglio memoria della VM** (programmi, cache, libera, chi usa più RAM) e **Libera la memoria del
  server** (`gc` + `malloc_trim`, anche da solo ogni ora).
- Grafici: trascinare non seleziona più il testo. Correzioni: pagina di stato vuota per un errore
  JavaScript introdotto il giorno prima; casella degli ospiti allineata.

## 5 ottobre 2026 (1.2.20261005-172932 · 27 versioni, da 1.1 a 1.2)

- **Nuova navigazione ad albero** nel pannello di amministrazione e nella pagina di stato: una sezione
  alla volta, percorso in alto, indirizzo per sezione (`#vm/registro-amministrativo`, `#rete/fritzbox`…).
  **⇅ Ordine** per sonde e riquadri FRITZ!Box. *Registro aggiornamenti sonde* in *Sonde › Elenco sonde*.
- **Reti Wi-Fi della sonda dalla pagina di stato** (elenco, *Aggiungi* o *Collegati subito* con ritorno
  automatico alla rete precedente, *Rimuovi*), con la password dell'account; la password della rete resta
  solo in memoria sul server. Nuovo script di root `netprobe-wifi` (NetworkManager). La sonda dice
  **perché** non può gestire le reti (`wifi_why`), ricontrollato ogni 10 minuti.
- **SpeedTest dalla sonda** (Cloudflare, solo libreria standard, limiti di durata e volume), risultato
  sotto il nome della sonda, negli eventi e, a scelta, come **notifica**. Tabella `speedtests`.
- **Canali per tipo di avviso** per utenti (Dispositivi, Sonde, Rete ospiti, Manutenzione, SpeedTest) e
  amministratori (Allarmi, Manutenzione, Account), su email/Telegram/ntfy; colonna `notify_routes`.
- **Aggiornamenti completi o solo programmi**: la sonda dice se sa installare il pacchetto completo
  (`full_update`), mostrato in *Stato sonda* e nell'elenco sonde. Un'opzione «senza notifiche» per gli
  aggiornamenti è stata aggiunta e tolta in giornata (resta la colonna `quiet`, inutilizzata).
- **Visualizzazione salvata nell'account** (colonne dei dispositivi e riquadro FRITZ!Box), uguale su
  ogni dispositivo; colonna `view_prefs`, `POST /api/account/view`.
- **Log a pagine** con la stessa barra ovunque (25/50/100/200 righe); storico completo di programmazioni
  e registro amministrativo, che **non scade più** con la conservazione dei dati.
- **Testi più asciutti** in tutte le pagine (note e avvisi ridotti all'essenziale, etichette più corte).

## 4 ottobre 2026 (1.1.20261004-204545 · 8 versioni)

- **Le sonde si collegano solo con il loro token personale**: la chiave del server non vale più per
  report, buffer, configurazione e aggiornamenti (resta solo per creare il primo account). Una sonda che
  usa ancora la chiave viene rifiutata e gli amministratori ricevono un avviso (al massimo ogni 6 ore).
  Corretta la finestra in cui una sonda appena collegata accettava ancora la chiave. Tolto il codice
  delle sonde «ereditate» e `MAX_UNOWNED_PROBES`.
- **Pausa di una sonda** (niente avvisi né eventi, i dati continuano ad arrivare; a fine pausa lo stato
  riparte da zero) e **pausa del ping verso un singolo dispositivo** (la sonda smette davvero di
  pingarlo; per un tempo scelto o fino a ripresa, con nota).
- **Conservazione dei dati dal pannello** (giorni, settimane, mesi o tutto; accorciando si elimina
  subito, con password e conferma). **Pulizia 25 volte più veloce** e a pezzi; meno connessioni al
  database per aggiornamento della pagina; letture tolte dal ciclo principale; `auth.db` in WAL; codice
  inutilizzato rimosso.
- «Mostra altri» negli *Ultimi eventi*; su telefono il nome del dispositivo su una riga sua;
  *Il tuo account* separato da *Amministratori*.

## 3 ottobre 2026 (1.1.20261003-225948 · 6 versioni)

- **Amministratori dal pannello**: creazione (password provvisoria mostrata una volta, serve anche il
  codice dell'app), **Password dimenticata** (nuova password provvisoria, sessioni chiuse) ed
  **Elimina** (nessuno elimina se stesso). **Telegram personale** per ogni amministratore, con messaggio
  di prova; chat ID coperti finché non si preme *Mostra*.
- **Dispositivo riconosciuto per la 2FA** («non chiedermi il codice per 15 giorni»), legato a account e
  browser e annullato da cambio password o app. **Rimanda** per i codici di accesso legati a un'email.
- **Registrazione solo con codice di accesso**; via la sezione *Chiave del server* (la chiave si cambia
  solo nel `.env` della VM).
- Spiegazioni delle sezioni del pannello dietro un tasto «i»; intestazioni delle sezioni su una riga
  (titolo intero da aperta, accorciato da chiusa; stato mai incolonnato).

## 1 ottobre 2026 (1.1.20261001-081721 · 2 versioni)

- **Menu delle sezioni a sinistra** (☰) nella pagina di stato e nel pannello; su schermo stretto si
  apre sopra la pagina. L'indirizzo senza sezione porta sempre a *Stato rete*. Tendine anche in *Sonde*.
  Corretto un messaggio che citava un pulsante *Annulla* inesistente.

## 30 settembre 2026 (1.1.20260930-221341 · 4 versioni)

- **Rilascio di sicurezza**: una password admin sbagliata non apre più nessuna sessione; password
  sbagliate limitate per IP e account senza bloccare l'account (il blocco resta sui codici di verifica);
  utenti limitati per IP con tetto per account; email da confermare prima di ricevere avvisi;
  registrazione con la chiave del server disattivata; limiti a report, buffer, notifiche (60 l'ora),
  eventi per sonda e spazio su disco; NaN e infinito scartati; `/opt/netmon` di root (primo aggiornamento a
  mano). La firma dell'autore sui pacchetti, introdotta qui, è stata **tolta** in giornata: chi carica
  un pacchetto dal pannello è di fatto root sulla VM; resta la firma VM → sonde.
- **Aggiornamenti solo dal pannello**: dalla pagina locale della sonda restano solo riavvio e lettura
  dello stato. **Riavvio della VM programmabile**.
- **Le sonde vanno aggiornate oppure no**: confronto dei file della sonda senza il numero di versione,
  mostrato nel pannello, nelle email e da `installa-server.sh`.
- **Priorità di notifica per dispositivo** (Alta, Normale, Bassa con soglia propria, Mai), solo server.

## 28 settembre 2026 (1.1.20260928-151213 · 1 versione)

- **Sicurezza**: blocco admin che scade da solo (da 15 minuti fino a 24 ore, con email); scrypt limitato
  a 3 calcoli alla volta (`SCRYPT_SLOTS`, `MemoryMax=384M`, `TasksMax=256`); richieste al massimo di 10 MB
  anche in Caddy; `Cache-Control: no-store` sulle API; HSTS e niente intestazione `Server`; dipendenze
  dirette a versione fissa.

## 27 settembre 2026 (1.0.20260927-214225 · 10 versioni)

- **Revisione di sicurezza**: aggiornamenti delle sonde **firmati dalla VM** (chiave leggibile solo da
  root); niente scritture di root nella cartella della sonda; pagina locale della sonda con password
  obbligatoria, controllo dell'Host (DNS rebinding), rifiuto delle richieste da altri siti e segreti
  nascosti fino a *Mostra*; chiave del server meno potente; ntfy solo verso server pubblici; intestazioni
  di sicurezza, cookie `Secure`, limiti contro il sovraccarico (200 dispositivi, 10 MB, 50 sonde per utente).
- **Aggiornamenti programmati** della VM e delle sonde (adesso o a data e ora, annullabili, con avvisi) e
  nuova scheda **Sonde** nel pannello, con filtri.
- **Aggiornamento da pacchetto** `netmon.zip` solo dal pannello `/admin`, con verifica di idoneità
  (`pkgcheck.py`), scelta di quando installarlo e, dopo, quali sonde aggiornare; aggiornamento delle
  sonde dal server completo (pacchetto firmato dalla VM).
- **Utenti tutti uguali** (niente utente principale); avvisi di manutenzione della VM a tutti gli utenti;
  avvisi amministrativi solo agli amministratori e nel nuovo **Registro amministrativo**.
- Nuovo **logo** (anche icone e email), `account.py sonde`, sonde senza account eliminate dopo
  `ORPHAN_DAYS`, conteggio delle sonde corretto, ritocchi alla pagina locale della sonda.
- 1.0.20260927-001638: versione di partenza della revisione di sicurezza.

---

### Come si fa un nuovo rilascio

```bash
python3 tools/nuova-versione.py   # versione 1.1.AAAAMMGG-hhmmss (ora italiana) in tutti i file,
                                 # controlli e crea ../netmon-<versione>.zip
```

**Ogni zip porta la sua versione**: a ogni modifica, anche di un solo carattere, si alza la
versione (la stessa versione non si può reinstallare). Prima scrivi le novità qui sopra, nella voce
del giorno: se non c'è ancora, creala in cima con la data. Nell'intestazione metti la versione che
stai per rilasciare e aggiorna il numero delle versioni del giorno. Poi lancia lo script: il
pacchetto e il CHANGELOG restano allineati.

Il programma sostituisce solo il numero di versione come testo, senza toccare il codice, e
controlla che server e sonda si compilino. Poi firma lo zip sul Mac con *Firma NetMon* (`tools/mac`) e
carica nel pannello lo zip insieme al suo `.sig`.
