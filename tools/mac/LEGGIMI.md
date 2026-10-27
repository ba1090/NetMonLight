# Firma NetMon (Mac)

App per il tuo Mac che firma i pacchetti `netmon-light-<versione>.zip`. Dalla 1.1 la VM installa dal pannello
`/admin` **solo pacchetti firmati con la tua chiave di rilascio**: chi entrasse nel pannello non potrebbe
far girare codice suo come root sulla VM, né sulle sonde degli utenti.

Non serve installare nulla. Al doppio clic l'app apre una **pagina nel browser**, la stessa di
`FirmaNetMon.exe` per Windows (`tools/windows`): è servita **solo a questo Mac** (indirizzo `127.0.0.1`, con un
codice segreto nell'indirizzo), nessun altro dispositivo né sito la raggiunge. Premi **Chiudi** per chiudere il
programma; se chiudi solo la pagina, si chiude da solo dopo una ventina di minuti. I file firmati si scaricano
dalla pagina stessa, quindi i pulsanti *Scarica…* funzionano anche se il programma si è già chiuso. L'app non
compare nel Dock.

Due versioni dentro la stessa app, scelte da sole:

- **con la pagina nel browser** (macOS 11 o successivo, Apple Silicon o Intel): i programmi
  `firma-netmon-arm64` e `firma-netmon-amd64` in `Contents/MacOS`, compilati da `tools/firma/build.sh`. Ci
  sono nell'app del repository GitHub, non in quella dentro lo zip del pacchetto (sarebbero un peso
  inutile per VM e sonde);
- **con le finestre di sistema** (`firma-netmon-classic`): se quei programmi mancano o il Mac è più vecchio.
  Usa solo ciò che c'è già in macOS (`openssl`, `unzip`, le finestre di sistema).

Stessa chiave, stessa cartella e stesso formato in tutte e due, e anche su Windows: una copia di riserva fatta
su un computer si importa sull'altro.

L'icona è il logo di netmon con un pennino: la rigenera `python3 tools/genera-icone.py --mac`. Se il Finder
mostra ancora l'icona generica dopo un aggiornamento, sposta l'app in un'altra cartella e rimettila dov'era.

## Aprirla la prima volta

L'app non è firmata da Apple, quindi macOS la blocca al primo avvio:

1. copia `Firma NetMon.app` dove vuoi (per esempio in *Applicazioni*);
2. doppio clic: macOS dice che non può verificare lo sviluppatore. Premi *Fine*;
3. *Impostazioni di Sistema → Privacy e sicurezza*, in fondo: *«Firma NetMon» è stata bloccata…* →
   **Apri comunque**, poi conferma con la password del Mac (su macOS 14 e precedenti basta anche
   clic destro sull'app → *Apri* → *Apri*).

Da Terminale fa lo stesso: `xattr -dr com.apple.quarantine "/Applications/Firma NetMon.app"`.

Se l'app non parte affatto (lo zip è stato estratto senza i permessi):
`chmod +x "/Applications/Firma NetMon.app/Contents/MacOS/"*`.

## Prima volta: la chiave di rilascio

1. Apri l'app → **Crea la chiave**, con una password di almeno 10 caratteri scritta due volte. Senza
   password la chiave non si può usare: annotala in un posto sicuro.
2. L'app mostra l'**impronta** della chiave (es. `63ce e2c8 817b 6f4b`). La chiave pubblica si scarica
   o si copia dalla stessa pagina.
3. Non serve altro: quando firmi un pacchetto che non contiene ancora una chiave pubblica, l'app ci
   aggiunge la tua (`server/release-key.pub`) e poi lo firma. Se vuoi, metti comunque la chiave pubblica
   nel repository come `server/release-key.pub`, così ogni zip la contiene già. È pubblica: si può
   condividere.
4. **Salva una copia di riserva** e spostala su una chiavetta tenuta lontana dal Mac. Se perdi la chiave o
   la password, dal pannello non potrai più installare pacchetti: dovrai crearne una nuova e installare a
   mano via SSH.

Hai già una chiave (su un altro Mac o su Windows)? Non crearne una nuova: **importa** la copia di riserva
(`netmon-release-signing.key`, con la sua password). Vedi *Firmare da più computer*.

Il primo pacchetto con la tua chiave (aggiunta dall'app o già nel repository), firmato con l'app,
installa la chiave sulla VM.
Tra i controlli del pannello compare *Prima chiave di rilascio di questa VM: …*: controlla che l'impronta
sia quella dell'app. Da lì in poi la VM accetta solo pacchetti firmati da te.

## Firmare da più computer (Mac e Windows)

La VM accetta **una sola chiave**: per firmare da più computer, tutti devono usare la **stessa** chiave, quella che
la VM conosce già (la sua impronta è nel pannello, *Server › Aggiornamento Netmon*, e nel messaggio *Firma
dell'autore NON valida per la chiave …*).

1. Sul computer che ha quella chiave: **Salva una copia di riserva** (`netmon-release-signing.key` e
   `netmon-release-key.pub`), poi portala sull'altro computer (chiavetta, cartella condivisa).
2. Sull'altro computer:
   - se non ha ancora una chiave: **Oppure importa una copia di riserva**;
   - se ne ha già creata una sua: **Usa la chiave di un altro computer** (in fondo al riquadro *Chiave di
     rilascio*). Sostituisce la chiave di questo computer, che resta comunque da parte nella stessa cartella
     (`release-signing.key.sostituita-<data>`).
3. Controlla che l'impronta mostrata sia quella della VM, poi rifirma lo zip e caricalo con il **nuovo** `.sig`.

## A ogni rilascio

1. **Firma un pacchetto** → scegli `netmon-light-<versione>.zip` → password → **Firma**.
2. Il browser scarica in *Download* la firma `netmon-light-<versione>.zip.sig` e, se l'app ha aggiunto la tua
   chiave, anche lo zip aggiornato: da quel momento usa **quello**, non lo zip di prima. (Con le finestre
   di sistema, invece, il `.sig` compare accanto allo zip e la chiave entra nello zip stesso.)
3. Pannello `/admin` → *Server › Aggiornamento Netmon* → seleziona **insieme** lo zip e il `.sig`
   (⌘-clic sul secondo file). Tra i controlli deve comparire *Firma dell'autore verificata*.

Se modifichi lo zip dopo la firma, anche di un byte, la firma non vale più: rifirmalo.
Se il pacchetto contiene una chiave **diversa** dalla tua, l'app si ferma e chiede conferma.

**Verifica la firma di un pacchetto** controlla uno zip con il suo `.sig` con la tua chiave.

## Dove sta la chiave

`~/Library/Application Support/NetMon Firma/`:

- `release-signing.key`: chiave privata ECDSA P-256, cifrata AES-256 con la tua password (permessi 600);
- `release-key.pub`: chiave pubblica.

## Cambiare chiave

Crea la nuova chiave in una copia di riserva separata, metti la nuova chiave pubblica in
`server/release-key.pub` e firma **quel** pacchetto con la chiave **vecchia**: installandolo, la VM passa
alla nuova. L'app avvisa quando il pacchetto contiene una chiave diversa dalla tua.

## Ricompilare i programmi

Sorgenti in `tools/firma/src` (Go, solo libreria standard), uguali per Mac e Windows:

```bash
bash tools/firma/build.sh     # FirmaNetMon.exe e i due programmi per il Mac, con le loro impronte SHA-256
```

## Da Terminale (stesse operazioni)

```bash
openssl dgst -sha256 -sign release-signing.key -out sig.der netmon-light-<versione>.zip
openssl base64 -A -in sig.der > netmon-light-<versione>.zip.sig
openssl dgst -sha256 -verify release-key.pub -signature sig.der netmon-light-<versione>.zip
```
