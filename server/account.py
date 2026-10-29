#!/usr/bin/env python3
"""Gestione degli account della pagina di stato, dalla VM.

Uso (come utente del servizio):
  sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py elenco
  sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py crea-admin nome@dominio.it [--nome "Mario Rossi"] [--azzera-mfa]
  sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py elimina-admin nome@dominio.it
  sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py password nome@dominio.it
  sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py reset
  sudo -u netmon /opt/netmon/venv/bin/python /opt/netmon/account.py sonde

- elenco:        mostra amministratori e utenti, l'ultimo accesso e le sessioni aperte
- crea-admin:    crea un amministratore nominale della pagina /admin, identificato dalla sua
                 email, con una password provvisoria generata a caso e mostrata una volta sola.
                 Al primo accesso la pagina obbliga a cambiarla e ad attivare l'app di
                 autenticazione (verifica in due passaggi). Se esiste già, riceve una nuova
                 password provvisoria (utile se l'hai dimenticata o se l'account si è bloccato
                 dopo 5 errori), viene sbloccato e le sue sessioni si chiudono; con --azzera-mfa
                 dovrà anche configurare di nuovo l'app (per esempio dopo aver perso il telefono).
                 Gli amministratori sono separati dagli utenti: entrano solo in /admin.
- elimina-admin: elimina un amministratore
- password:      imposta una nuova password a un utente della pagina di stato (chiude le sessioni)
- sonde:         elenca tutte le sonde note al server, con l'account a cui sono collegate e
                 l'ultimo report (anche quelle senza account, eliminate da sole dopo 30 giorni ferme)
- reset:         cancella utenti, sessioni e codici di accesso (gli amministratori restano); al
                 prossimo accesso la pagina di stato chiederà di nuovo chiave del server, email e password
"""
__version__ = "1.1.20261029-210000"
import getpass
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth import AuthDB, password_problem, temporary_password, valid_email  # noqa: E402

DB_PATH = Path(os.getenv("DATA_DIR", "/opt/netmon/data")) / "auth.db"


def when(ts):
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(ts)) if ts else "mai"


def main(argv):
    if len(argv) < 2 or argv[1] not in ("elenco", "crea-admin", "elimina-admin", "password", "reset", "sonde"):
        print(__doc__)
        return 1
    db = AuthDB(DB_PATH)
    cmd = argv[1]

    if cmd == "sonde":
        try:
            state = json.loads((DB_PATH.parent / "state.json").read_text())
        except (OSError, ValueError):
            state = {}
        with db._conn() as c:
            rows = {r[0]: (r[1], r[2], r[3]) for r in c.execute(
                "SELECT p.key, p.name, u.email, p.token_used FROM probes p LEFT JOIN users u ON u.id = p.owner")}
        keys = list(state) + [k for k in rows if k not in state]
        if not keys:
            print("Nessuna sonda.")
            return 0
        print(f"{'Sonda':<24} {'Chiave':<16} {'Account':<32} {'Ultimo report':<17} {'Token':<12} Stato")
        now = time.time()
        for k in keys:
            p = state.get(k) or {}
            name = p.get("name") or (rows.get(k) or (None,))[0] or k
            email = (rows.get(k) or (None, None, None))[1] or "— nessun account —"
            # "personale" = la sonda ha gia' usato il suo token. Le altre, se si presentano con la
            # chiave del server, vengono rifiutate: serve generare un token nella pagina.
            tok = ("personale" if (rows.get(k) or (None, None, 0))[2] else
                   "mai usato" if k in rows else "nessuno")
            last = p.get("last_seen")
            st = ("mai collegata" if not p else "offline" if p.get("offline") else
                  "in ritardo" if last and now - last > 300 else "online")
            print(f"{str(name)[:24]:<24} {k[:16]:<16} {email[:32]:<32} {when(last):<17} {tok:<12} {st}")
        print("\nLe sonde senza account ferme da più di 30 giorni vengono eliminate dal server da sole "
              "(ORPHAN_DAYS nel .env).")
        print("Token «mai usato» o «nessuno»: la sonda non comunica con un token personale. Generane uno "
              "nella pagina di stato (⚙ Impostazioni → Sonde) e inseriscilo nella sua pagina locale: "
              "la chiave del server non vale più per le sonde.")
        return 0

    if cmd == "elenco":
        admins = db.list_admins()
        print("Amministratori (pagina /admin):" if admins else "Amministratori: nessuno")
        for a in admins:
            extra = (f"  ·  BLOCCATO per altri {a['lock_left']} minuti (scade da solo)" if a["locked"]
                     else "  ·  password provvisoria da cambiare" if a["must_change"] else "")
            mfa_txt = "app di autenticazione attiva" if a["mfa"] else "app di autenticazione da attivare"
            print(f"  {a['login']}{'  (' + a['name'] + ')' if a['name'] else ''}  ·  creato il {when(a['created'])}"
                  f"  ·  ultimo accesso {when(a['last_seen'])}  ·  {mfa_txt}  ·  sessioni aperte: {a['sessions']}{extra}")
        users = db.users_overview()
        print("Utenti (pagina di stato):" if users else "Utenti: nessuno")
        for u in users:
            blocked = "  ·  BLOCCATO" if u["blocked"] else ""
            print(f"  {u['email']}{blocked}  ·  creato il {when(u['created'])}  ·  ultimo accesso "
                  f"{when(u['last_seen'])}  ·  sessioni aperte: {u['sessions']}  ·  sonde: {u['probes']}")
        return 0

    if cmd == "crea-admin":
        args, name, i = [], "", 2
        while i < len(argv):
            if argv[i] == "--nome" and i + 1 < len(argv):
                name, i = argv[i + 1].strip()[:80], i + 2
                continue
            if not argv[i].startswith("--"):
                args.append(argv[i])
            i += 1
        quiet = "--solo-password" in argv
        login = (args[0] if args else "").strip().lower()
        existing = {a["login"] for a in db.list_admins()}
        if not valid_email(login) and login not in existing:
            print("Indica l'email dell'amministratore, per esempio: account.py crea-admin mario.rossi@gmail.com")
            print("L'email serve per l'accesso e per ricevere il codice di riserva della verifica in due passaggi.")
            return 1
        pw = temporary_password()
        _, created = db.create_admin(login, pw, name, reset_mfa="--azzera-mfa" in argv)
        if quiet:
            print(pw)
            return 0
        print()
        print("  Amministratore " + ("creato" if created else "aggiornato") + ".")
        print(f"  Email (accesso) ...... {login}" + (f"  ({name})" if name else ""))
        print(f"  Password provvisoria . {pw}")
        print()
        print("  Accedi su https://IL-TUO-DOMINIO/admin. Salvala ora: non verrà mostrata di nuovo.")
        print("  Al primo accesso la pagina chiederà di sceglierne una nuova e di attivare l'app di")
        print("  autenticazione (Google Authenticator, Microsoft Authenticator o simili).")
        print()
        return 0

    if cmd == "elimina-admin":
        if len(argv) < 3:
            print("Indica l'amministratore, per esempio: account.py elimina-admin admin")
            return 1
        if not db.delete_admin(argv[2]):
            print(f"Nessun amministratore {argv[2]}.")
            return 1
        print(f"Amministratore {argv[2]} eliminato.")
        return 0

    if cmd == "password":
        if len(argv) < 3:
            print("Indica l'utente, per esempio: account.py password nome@dominio.it")
            return 1
        email = argv[2].strip().lower()
        pw = getpass.getpass("Nuova password: ")
        problem = password_problem(pw, email)
        if problem:
            print(problem)
            return 1
        if getpass.getpass("Ripeti la password: ") != pw:
            print("Le due password non coincidono.")
            return 1
        if not db.set_password_by_email(email, pw):
            print(f"Nessun account {email}.")
            return 1
        print("Password aggiornata. Tutte le sessioni sono state chiuse.")
        return 0

    if cmd == "reset":
        answer = input("Cancellare utenti, sessioni e codici di accesso? Scrivi SI per confermare: ")
        if answer.strip().upper() != "SI":
            print("Annullato.")
            return 1
        db.delete_everything()
        print("Fatto. Al prossimo accesso la pagina chiederà di nuovo chiave del server, email e password.")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
