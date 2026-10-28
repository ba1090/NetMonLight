# NetMon Light

Versione "light" di [NetMon](https://github.com/ba1090/NetMon): **una sola VM** fa tutto.

- **Pagina di stato** (`https://dominio/status`): ogni utente vede le sue sonde, i dispositivi, gli
  eventi e riceve i suoi avvisi (email, Telegram, ntfy).
- **Pannello di amministrazione** (`https://dominio/admin`): amministratori, utenti, codici di accesso,
  limiti e piani, elenco e aggiornamento delle sonde, stato e manutenzione della VM, aggiornamento di
  netmon con firma dell'autore e rollback.
- **Sonde** (per esempio un Raspberry Pi a casa di ogni utente): fanno ping ai dispositivi, leggono il
  FRITZ!Box e mandano i dati alla VM.

```
 CASA DEGLI UTENTI                          INTERNET
┌───────────────────────┐   HTTPS   ┌──────────────────────────────────────┐
│ Sonda utente A        │ ────────> │ VM unica (NetMon Light)              │
├───────────────────────┤           │  Caddy (HTTPS) → app.py              │
│ Sonda utente B        │ ────────> │  /status  pagina di stato utenti     │
└───────────────────────┘           │  /admin   pannello di amministrazione│
                                    │  avvisi: email / Telegram / ntfy     │
                                    └──────────────────────────────────────┘
```

## Cosa cambia rispetto a NetMon

| NetMon | NetMon Light |
|---|---|
| Gateway con pagina d'accesso e orchestratore, più VM probe dietro | Una sola VM: niente gateway, niente orchestratore, niente VM probe |
| `installa-server.sh --orchestratore` / `--dietro-gateway` | Solo `installa-server.sh` (e `--aggiorna`) |
| *Server › Tutte le VM*, barra delle macchine, colonna *VM* negli utenti | Tutto riferito all'unico server |
| *Sposta su un'altra VM* | Resta *Esporta (file cifrato)* / *Importa un utente*, per passare da un server all'altro |
| Aggiornamento del pacchetto a cascata su tutte le VM | Il pacchetto si installa sulla VM, poi (se scegli) sulle sonde |

Il formato dei dati, delle sonde e dei pacchetti è lo stesso di NetMon 1.1: le sonde esistenti funzionano
con NetMon Light, e un utente si porta da NetMon a NetMon Light con *Esporta* / *Importa un utente*
(vedi `INSTALLAZIONE.md`, Caso 4).

## Documenti

| Documento | Cosa c'è |
|---|---|
| [`INSTALLAZIONE.md`](INSTALLAZIONE.md) | installazione e aggiornamento in breve: VM e sonde |
| [`GUIDA.md`](GUIDA.md) | guida completa: installazione, notifiche, uso quotidiano, pannello, problemi |
| [`tools/mac/LEGGIMI.md`](tools/mac/LEGGIMI.md) | *Firma NetMon*, l'app per il Mac che firma i pacchetti (obbligatoria per aggiornare dal pannello) |
| [`tools/windows/LEGGIMI.md`](tools/windows/LEGGIMI.md) | *Firma NetMon* per Windows: `FirmaNetMon.exe`, un solo file senza installazione |
| [`tests/LEGGIMI.md`](tests/LEGGIMI.md) | le prove automatiche (`pytest`) |
| [`CHANGELOG.md`](CHANGELOG.md) | novità di ogni versione |

## Installazione in breve

Sulla VM (Ubuntu 24.04 o Debian 12/13, porte 80 e 443 aperte, un dominio che punta alla VM), con lo zip
del rilascio (`netmon-light-<versione>.zip`, creato con `python3 tools/nuova-versione.py`) nella home:

```bash
cd ~ && sudo apt install -y unzip && rm -rf ~/netmon && unzip -q netmon-light-<versione>.zip
sudo bash ~/netmon/server/installa-server.sh
```

Poi, sulla sonda, `sudo bash ~/netmon/probe/installa-sonda.sh` (dettagli in `INSTALLAZIONE.md`).

Lo zip contiene solo `VERSION`, `server/` e `probe/`: documenti, test e strumenti (*Firma NetMon*) stanno
in questo repository.

Versione attuale: vedi il file [`VERSION`](VERSION).
