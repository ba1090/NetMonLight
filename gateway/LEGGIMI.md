# netmon gateway e orchestratore

Un indirizzo d'ingresso (es. `netmonhome.net`) davanti a più VM netmon. Ogni utente, con le sue sonde e i suoi dati, vive su una VM sola, e sonde e utenti parlano **direttamente con la loro VM** (`vm1.netmonhome.net`, `vm2.…`): il gateway fa solo da pannello di controllo e da pagina d'accesso.

## Le macchine

- **Gateway (orchestratore)**: ci girano Caddy (HTTPS), il gateway (`gateway.py`: pagina d'accesso e smistamento) e netmon con `ROLE=orchestratore`, il **pannello di amministrazione di tutte le VM**, con gli amministratori. Non ha utenti né sonde.
- **VM probe**: tutte uguali, ognuna con il suo indirizzo pubblico e il suo certificato HTTPS. Tengono utenti, sonde e dati, e non hanno un pannello né amministratori propri: accettano comandi solo dall'orchestratore, sulla rete privata, ognuna con la sua chiave personale.

## Chi parla con chi

| Chi | Dove | Come |
|---|---|---|
| Utente che entra | `https://netmonhome.net` | scrive l'email; il gateway chiede alle VM chi ce l'ha (a ogni accesso, e prima rilegge gli utenti spostati) e lo manda a `https://vmN.…/` con l'email già inserita: la password la scrive lì. L'email di un amministratore che non è anche utente porta al pannello (`/admin`). Chi accede da una VM che non ha il suo account viene mandato alla VM giusta. `https://vmN.…/admin` porta a `https://netmonhome.net/admin`: il pannello c'è solo sul gateway |
| Nuovo utente con codice | `https://netmonhome.net` › *Ho un codice di accesso* | il codice (`accesso_vm2.…`) dice la VM: si registra lì. Le email d'invito portano già all'indirizzo della VM |
| Utente collegato | `https://vmN.…` | direttamente con la sua VM |
| Sonda | `https://vmN.…` (l'indirizzo che vede in *Impostazioni › Sonde* sulla sua VM) | direttamente con la sua VM |
| Amministratore | `https://netmonhome.net/admin` | orchestratore, che comanda le VM sulla rete privata |

Le sonde ancora puntate al gateway (per esempio quelle trasferite da un vecchio server con il suo dominio portato sul gateway) continuano a funzionare: il gateway legge la VM nel token (`sonda_vm2.…`), o la chiede alle VM per i token senza nome, e inoltra. Il resto (pagine e API degli utenti) il gateway non lo fa passare quando la VM ha il suo indirizzo pubblico: una pagina viene reindirizzata a `https://vmN.…`, le altre richieste ricevono un errore che indica di usare l'indirizzo della VM.

Icone (`/favicon.ico`, `/favicon.svg`…), caratteri e informativa delle pagine del gateway vengono sempre dall'orchestratore, senza rimandi a una VM.

L'elenco delle VM, con chiavi e indirizzi, lo tiene l'orchestratore (`vms.json` nei suoi dati); il gateway lo rilegge ogni 30 secondi, e subito quando vede il nome di una VM che non conosce.

## Il pannello

- *Utenti* e *Codici di accesso* mostrano gli utenti di tutte le VM, ognuno con la sua; creando un utente si sceglie la VM (è proposta quella con meno sonde). Le azioni su un utente stanno nel menu **Azioni ▾** della sua riga: nuovo codice di accesso, blocco, limiti, esportazione ed eliminazione vanno alla VM dell'utente; **Sposta su un'altra VM** controlla lo spazio sulla VM di arrivo, porta account, sonde e storico, e lascia sulla VM di partenza il rimando: le sonde ricevono il nuovo indirizzo (il token non cambia), chi accede viene mandato alla VM nuova e il gateway instrada lì le sonde puntate a lui.
- *Sonde* e *Server* mostrano una macchina alla volta (il gateway o una VM probe): si sceglie nel menu **VM** in alto, che non compare in *Amministrazione* né in *Tutte le VM* (valgono per tutte).
- La conservazione dei dati vale per tutte le VM; un pacchetto netmon si può installare su tutte insieme.
- *Server › Tutte le VM*: stato di ogni macchina; **Collega una VM** genera il token di una VM; **Togli** la toglie (solo se non ha utenti né sonde).
- Gli avvisi per gli amministratori delle VM arrivano agli amministratori del gateway.

L'orchestratore controlla accesso e password dell'amministratore, poi inoltra l'azione alla VM sulla rete privata con la chiave di quella VM.

## Installazione

Su ogni macchina si carica nella home lo zip della versione (`netmon-VERSIONE.zip`) e lo si estrae in `~/netmon`.

Gateway:

```bash
cd ~ && rm -rf ~/netmon && unzip -q netmon-VERSIONE.zip   # lo zip caricato nella home
sudo bash ~/netmon/server/installa-server.sh --orchestratore
```

Chiede dominio, email e Telegram (valgono per tutte le VM) e crea l'amministratore. Installa netmon come orchestratore, il gateway e Caddy.

Ogni VM probe:

1. Nel DNS crea un record A `vm1.netmonhome.net` (`vm2`, …) verso l'IP pubblico della VM e apri le porte 80 e 443 (Google Cloud: *Consenti traffico HTTP e HTTPS*).
2. Nel pannello, *Server › Tutte le VM › Collega una VM*, genera il token (vale 24 ore, una volta sola).
3. Sulla VM:

```bash
cd ~ && rm -rf ~/netmon && unzip -q netmon-VERSIONE.zip   # lo zip caricato nella home
sudo bash ~/netmon/server/installa-server.sh --dietro-gateway
```

Chiede l'indirizzo del gateway (solo `https://`: la risposta contiene la chiave della VM), il token e l'indirizzo pubblico della VM (proposto `vmN.<dominio del gateway>`). L'installatore accetta dal gateway solo nome, chiave, indirizzi e impostazioni email/Telegram, ciascuno controllato. La VM si collega, riceve nome, chiave e impostazioni (email, Telegram), prende il suo certificato HTTPS e apre la porta 8000 solo al gateway. Su una VM già installata lo stesso comando la ricollega: account, sonde e dati restano. Il token deve avere il nome che la VM ha già.

Nel pannello, *Server › Tutte le VM* mostra in alto la mappa dei collegamenti: il gateway al centro, le VM intorno con nome, IP, dominio e latenza, in verde, giallo o rosso secondo lo stato.

Nelle sezioni che valgono per una sola macchina, la barra sotto l'intestazione mostra gateway (blu) e VM (verde acqua) e dice su quale stai lavorando.

Aggiornamenti dal browser: nel pannello, pagina *Server*, scegli il gateway nella barra delle macchine, carica lo zip insieme alla sua firma `.sig` (fatta sul Mac con *Firma NetMon*, `tools/mac`) e premi *Installa*. Ogni VM verifica la firma con la sua chiave di rilascio: tieni la stessa chiave su tutte. Una VM si collega al gateway solo con un indirizzo pubblico `https://`. Il pacchetto va prima sulle VM probe con una versione più vecchia e per ultimo sul gateway, dove aggiorna anche `gateway.py`. Le VM che hanno già quella versione sono segnalate nell'elenco e non vengono toccate; se il gateway è già aggiornato, si aggiornano solo le VM rimaste indietro. Dopo l'installazione, *Conferma la nuova versione* (finestra di rollback) premuto con il gateway scelto conferma anche le VM. In alternativa, `installa-server.sh --aggiorna` su ogni macchina.

Cambiare dominio (es. da `netmon-public.com` a `netmonhome.net`): crea i nuovi record DNS lasciando i vecchi,
rilancia `installa-server.sh --orchestratore` sul gateway (**2) Riconfigurare**) e `--dietro-gateway` su ogni VM
con un token nuovo. I nomi precedenti finiscono in `OLD_HOSTS` (nel `.env` e in `/opt/netmon-gateway/.env`),
restano nel Caddyfile e rimandano al nuovo indirizzo: i browser con un 301, le sonde con la risposta «spostata»
(410 con il nuovo indirizzo), che scrivono da sole in `config.yaml`. Procedura completa in `GUIDA.md`, capitolo 11.
