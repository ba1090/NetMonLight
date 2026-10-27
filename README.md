# netmon

Monitoraggio della rete di casa e dei dispositivi IoT: una **sonda** (per esempio un Raspberry Pi) fa
ping ai dispositivi, legge il FRITZ!Box e su richiesta controlla le porte aperte dei dispositivi
(controllo di sicurezza), un **server** online raccoglie i dati, mostra la pagina di
stato e manda gli avvisi (email, Telegram, ntfy). Con molti utenti il server si divide su più VM dietro
un **gateway**, che fa da pannello di amministrazione e da pagina d'accesso; dal pannello un utente si
sposta da una VM all'altra con sonde e storico, dopo un controllo dello spazio libero.

| Documento | Cosa c'è |
|---|---|
| [`INSTALLAZIONE.md`](INSTALLAZIONE.md) | installazione e aggiornamento in breve: server, sonde, più VM con il gateway |
| [`GUIDA.md`](GUIDA.md) | guida completa: installazione, notifiche, uso quotidiano, pannello, problemi |
| [`gateway/LEGGIMI.md`](gateway/LEGGIMI.md) | gateway e VM probe: come sono collegati e come si installano |
| [`tools/mac/LEGGIMI.md`](tools/mac/LEGGIMI.md) | *Firma NetMon*, l'app per il Mac che firma i pacchetti (dalla 1.1 obbligatoria per aggiornare dal pannello) |
| [`tools/windows/LEGGIMI.md`](tools/windows/LEGGIMI.md) | *Firma NetMon* per Windows: `FirmaNetMon.exe`, un solo file senza installazione |
| [`CHANGELOG.md`](CHANGELOG.md) | novità di ogni versione |

Si installa dallo zip del rilascio (`netmon-<versione>.zip`), estratto nella cartella `~/netmon`.
Versione attuale: vedi il file [`VERSION`](VERSION).
