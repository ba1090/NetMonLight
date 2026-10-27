# Firma NetMon (Windows)

`FirmaNetMon.exe` firma i pacchetti `netmon-<versione>.zip` su Windows. È lo stesso programma, con la stessa
pagina, che usa l'app *Firma NetMon* per il Mac (`tools/mac`). Dalla 1.1 la VM installa dal pannello `/admin` **solo pacchetti firmati con la tua
chiave di rilascio**.

Un solo file, **senza installazione**: lo copi dove vuoi (anche su una chiavetta) e lo apri con un doppio
clic. Funziona su Windows 10 e 11 a 64 bit.

## Come funziona

Al doppio clic si apre una pagina nel browser: è servita **solo a questo computer** (indirizzo
`127.0.0.1`, con un codice segreto nell'indirizzo), nessun altro dispositivo la raggiunge e nessun sito
esterno può usarla. Premi **Chiudi** per chiudere il programma; se chiudi solo la pagina, si chiude da solo
dopo una ventina di minuti. I file firmati si scaricano dalla pagina stessa: i pulsanti *Scarica…* funzionano
anche se nel frattempo il programma si è chiuso.

La chiave privata non lascia mai il computer. Sta in `%APPDATA%\NetMon Firma`, cifrata con la tua
password (AES-256), nello stesso formato dell'app per il Mac: una copia di riserva fatta su Windows si
importa sul Mac e viceversa.

## Aprirlo la prima volta

Il programma non è firmato da Microsoft, quindi al primo avvio Windows può avvisare:

- **SmartScreen** (*Windows ha protetto il PC*): premi **Ulteriori informazioni** → **Esegui comunque**;
- se l'hai scaricato da Internet: tasto destro sul file → **Proprietà** → in basso spunta **Annulla
  blocco** → **OK**.

Il browser può chiedere se consentire il download di più file alla volta (lo zip e la firma): rispondi sì.

## Prima volta: la chiave di rilascio

1. Apri il programma → **Crea la chiave**, con una password di almeno 10 caratteri scritta due volte.
   Senza password la chiave non si può usare: annotala in un posto sicuro.
2. Il programma mostra l'**impronta** della chiave (es. `63ce e2c8 817b 6f4b`).
3. **Salva una copia di riserva**: scarica `netmon-release-signing.key` e `netmon-release-key.pub`;
   spostali su una chiavetta tenuta lontana dal computer.

Hai già una chiave sul Mac? Allora non crearne una nuova: **importa** la copia di riserva fatta dall'app
per il Mac (`netmon-release-signing.key`, con la sua password). Così Mac e Windows firmano con la stessa
chiave, e la VM accetta i pacchetti di tutti e due. Vedi *Firmare da più computer*.

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

1. **Firma un pacchetto** → scegli `netmon-<versione>.zip` (lo zip del rilascio, non il «Download ZIP» di
   GitHub) → password → **Firma**.
2. Il browser scarica la firma `netmon-<versione>.zip.sig`. Se il pacchetto non conteneva ancora la tua
   chiave pubblica, il programma ce la aggiunge e scarica anche lo zip aggiornato: da quel momento usa
   **quello** (è nella cartella *Download*), non lo zip di prima.
3. Pannello `/admin` → *Server › Aggiornamento Netmon* → seleziona **insieme** lo zip e il `.sig`. Tra i
   controlli deve comparire *Firma dell'autore verificata* (la prima volta: *Prima chiave di rilascio di
   questa VM*, con la stessa impronta del programma).

Se il pacchetto contiene una chiave **diversa** dalla tua, il programma si ferma e chiede conferma: firma
solo se stai cambiando chiave di proposito (dopo l'installazione la VM accetterebbe solo l'altra chiave).

**Verifica la firma di un pacchetto** controlla uno zip con il suo `.sig` con la tua chiave.

## Ricompilarlo

I sorgenti sono in `tools/firma/src` (Go, solo libreria standard), gli stessi dell'app per il Mac. Da Linux o
macOS, con Go 1.22 o successivo:

```bash
bash tools/firma/build.sh      # FirmaNetMon.exe e i programmi per il Mac, con le loro impronte SHA-256
```

L'icona (`tools/firma/icon.png`) la genera `python3 tools/genera-icone.py --mac`, la stessa dell'app per il
Mac. Gli eseguibili non entrano nel pacchetto `netmon.zip` (sarebbero un peso inutile per VM e sonde): si
prendono dal repository.
