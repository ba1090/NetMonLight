"""Account di accesso alla pagina di stato: email e password, sessioni del browser.

Il database (auth.db) non contiene nulla di riutilizzabile se venisse copiato:
- password: impronta scrypt con sale casuale per ogni utente;
- sessioni: solo l'impronta SHA-256 del codice di sessione, che esiste in chiaro
  soltanto nel cookie del browser.
Il file viene creato con permessi 600 (leggibile solo dall'utente del servizio).
"""
__version__ = "1.1.20261029-200000"
import ipaddress
import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

import mfa

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
MIN_PASSWORD = 10
SESSION_DAYS_REMEMBER = 30        # "Ricordami"
SESSION_HOURS = 12                # sessione senza "Ricordami"
ADMIN_MAX_FAILS = 5               # password o codici di amministratore sbagliati di fila prima del blocco
ADMIN_LOCK_MINUTES = 15           # durata del primo blocco dopo troppi errori
ADMIN_LOCK_MAX_MINUTES = 1440     # tetto del blocco: un giorno
ADMIN_LOCK_REPEAT = 24 * 3600     # entro questo tempo un nuovo blocco dura il doppio
ADMIN_PENDING_MINUTES = 15        # sessione a metà (password giusta, verifica in due passaggi da fare)
MAIL_CODE_GAP = 60                # secondi minimi tra due codici via email
MAIL_CODE_PER_HOUR = 5
ADMIN_SESSION_HOURS = 8           # pagina di amministrazione: sessione breve, senza "Ricordami"
# "Non chiedermi il codice su questo dispositivo": NON allunga la sessione (la password si rimette
# a ogni accesso), salta solo il secondo fattore su quel browser. Il segno sta in un cookie a parte,
# e in archivio ne resta la sola impronta, come per le sessioni.
ADMIN_TRUST_DAYS = 15

# Piano con cui nasce ogni nuovo account: basso, medio, alto, oppure vuoto (nessun piano = limiti predefiniti)
NEW_USER_PLAN = os.environ.get("NEW_USER_PLAN", "alto").strip().lower() or None
if NEW_USER_PLAN not in (None, "basso", "medio", "alto"):
    NEW_USER_PLAN = "alto"


def new_secret(nbytes: int) -> str:
    """Segreto casuale (token delle sonde, sessioni, codici di accesso)."""
    return secrets.token_urlsafe(nbytes)

VERIFY_HOURS = 48                 # validità del link di conferma dell'email di un utente
VERIFY_GAP = 600                  # secondi minimi tra due link di conferma allo stesso utente

# scrypt: ~32 MB di memoria e qualche decina di ms per verifica, lento per chi tenta a forza bruta
_N, _R, _P, _DKLEN = 2 ** 15, 8, 1, 32
_MAXMEM = 64 * 1024 * 1024

# Ogni verifica scrypt tiene ~32 MB in memoria. Senza un tetto, una raffica di richieste di
# accesso esaurirebbe la RAM del servizio e systemd lo ucciderebbe (MemoryMax), causando un
# ciclo di riavvii: DoS che non richiede credenziali. Le verifiche scrypt sono quindi in coda,
# al massimo SCRYPT_SLOTS per volta. I tentativi in eccesso aspettano invece di allocare.
SCRYPT_SLOTS = max(1, int(os.environ.get("SCRYPT_SLOTS", "3")))
_scrypt_slots = threading.BoundedSemaphore(SCRYPT_SLOTS)


# ------------------------------------------------------------------ password

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    with _scrypt_slots:
        dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=_DKLEN)
    b64 = lambda b: base64.b64encode(b).decode()
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(dk)}"


def _routes(raw) -> dict:
    """Canali scelti per tipo di avviso: {tipo: [canali]}. Un tipo assente = tutti i canali."""
    import json
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): [str(x) for x in v] for k, v in data.items() if isinstance(v, list)}


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(dk)
        with _scrypt_slots:
            got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r),
                                 p=int(p), maxmem=_MAXMEM, dklen=len(expected))
        return hmac.compare_digest(got, expected)
    except (ValueError, TypeError):
        return False


# Impronta fittizia: si verifica anche quando l'email non esiste, così i tempi di risposta
# non rivelano quali email sono registrate
_DUMMY = hash_password(secrets.token_hex(16))


def normalize_email(email: str) -> str:
    # niente caratteri di controllo: l'email finisce nei registri e nelle chiavi dei limiti
    return re.sub(r"[\x00-\x1f\x7f]", "", email or "").strip().lower()


def temporary_password() -> str:
    """Password provvisoria leggibile: 4 gruppi di 4 caratteri senza simboli ambigui.

    Sta qui, e non nella CLI, perche' un amministratore si crea sia da riga di comando sia dal
    pannello: due generatori diversi vorrebbe dire due robustezze diverse."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4))


def valid_email(email: str) -> bool:
    return len(email) <= 254 and bool(EMAIL_RE.match(email))


def password_problem(password: str, email: str = "") -> str | None:
    """Motivo per cui la password non va bene, oppure None."""
    if len(password) < MIN_PASSWORD:
        return f"La password deve avere almeno {MIN_PASSWORD} caratteri."
    if len(password) > 256:
        return "La password è troppo lunga (massimo 256 caratteri)."
    if email and password.strip().lower() == email.lower():
        return "La password non può essere uguale all'email."
    if len(set(password)) < 4:
        return "La password è troppo semplice: usa caratteri diversi."
    return None


def _session_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ------------------------------------------------------------------ database

class ClosingConnection(sqlite3.Connection):
    """Connessione che il «with» CHIUDE, oltre a confermare o annullare la transazione.

    Il «with» di sqlite3 non chiude la connessione: restava aperta finché passava il garbage
    collector (le connessioni stanno in un ciclo di riferimenti). Sotto carico — sonde che scrivono,
    pagine aperte — se ne accumulavano migliaia, ognuna con un file aperto e la sua cache: in pochi
    minuti «unable to open database file» e gigabyte di memoria, oltre MemoryMax del servizio.
    Va usata solo con un «with» per connessione (dopo il blocco la connessione non c'è più)."""

    def __exit__(self, *exc):
        try:
            return super().__exit__(*exc)
        finally:
            self.close()


class AuthDB:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            # WAL resta scritto nel file: letture e scritture non si bloccano a vicenda, come in
            # events.db. Una sola volta, all'avvio.
            c.execute("PRAGMA journal_mode = WAL")
            c.execute("CREATE TABLE IF NOT EXISTS users ("
                      " id INTEGER PRIMARY KEY,"
                      " email TEXT NOT NULL UNIQUE COLLATE NOCASE,"
                      " pw_hash TEXT NOT NULL,"
                      " created REAL NOT NULL,"
                      " pw_changed REAL NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS sessions ("
                      " id_hash TEXT PRIMARY KEY,"
                      " user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
                      " created REAL NOT NULL,"
                      " expires REAL NOT NULL,"
                      " remember INTEGER NOT NULL,"
                      " user_agent TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS probes ("
                      " key TEXT PRIMARY KEY,"
                      " owner INTEGER REFERENCES users(id) ON DELETE SET NULL,"
                      " token_hash TEXT UNIQUE,"
                      " created REAL NOT NULL)")
            pcols = {r[1] for r in c.execute("PRAGMA table_info(probes)")}
            if "name" not in pcols:
                c.execute("ALTER TABLE probes ADD COLUMN name TEXT")
            if "token_used" not in pcols:          # 1 = la sonda ha già usato il suo token personale
                c.execute("ALTER TABLE probes ADD COLUMN token_used INTEGER NOT NULL DEFAULT 0")
            # Dispositivo titolare del token (il primo che l'ha usato) e, se c'è, un secondo
            # dispositivo con lo stesso token, i cui dati vengono rifiutati. JSON.
            if "inst" not in pcols:
                c.execute("ALTER TABLE probes ADD COLUMN inst TEXT")
            if "dup" not in pcols:
                c.execute("ALTER TABLE probes ADD COLUMN dup TEXT")
            # Singolo dispositivo in pausa: la sonda smette proprio di mandargli i ping, quindi
            # non ci sono né misure né avvisi. La riga sparisce quando sparisce la sonda.
            c.execute("CREATE TABLE IF NOT EXISTS device_pauses ("
                      " probe TEXT NOT NULL REFERENCES probes(key) ON DELETE CASCADE,"
                      " device TEXT NOT NULL,"
                      " until REAL,"                      # NULL = finché non lo riprendi a mano
                      " note TEXT,"
                      " created REAL NOT NULL,"
                      " PRIMARY KEY (probe, device))")
            # Sonda in pausa: continua a ricevere e salvare i dati, ma non genera nessun avviso.
            # paused_until NULL = pausa senza scadenza; una data = fino a quel momento.
            if "paused" not in pcols:
                c.execute("ALTER TABLE probes ADD COLUMN paused INTEGER NOT NULL DEFAULT 0")
                c.execute("ALTER TABLE probes ADD COLUMN paused_until REAL")
                c.execute("ALTER TABLE probes ADD COLUMN paused_note TEXT")
            if "key_ok" not in pcols:
                # 1 = la sonda è nata dalla chiave del server e può ancora presentarsi con quella
                # (probe.py vecchio). Le sonde create o rigenerate dalla pagina restano a 0: per
                # loro la chiave del server non vale mai, nemmeno prima del primo uso del token.
                c.execute("ALTER TABLE probes ADD COLUMN key_ok INTEGER NOT NULL DEFAULT 0")
                # Sonde già presenti: quelle create dalla pagina hanno sempre una chiave p_<12 hex>
                for (k,) in c.execute("SELECT key FROM probes WHERE token_used = 0").fetchall():
                    if not re.fullmatch(r"p_[0-9a-f]{12}", k):
                        c.execute("UPDATE probes SET key_ok = 1 WHERE key = ?", (k,))
            if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
                c.execute("UPDATE probes SET key_ok = 0 WHERE key_ok = 1 AND owner IS NOT NULL "
                          "AND owner != (SELECT id FROM users ORDER BY id LIMIT 1)")
            cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
            for col, ddl in (("is_admin", "INTEGER NOT NULL DEFAULT 0"), ("telegram_chat", "TEXT"),
                             ("ntfy_url", "TEXT"), ("notify_email", "INTEGER NOT NULL DEFAULT 1"),
                             # interruttori dei canali: spento = nessun invio, chat ID e topic restano salvati
                             ("telegram_on", "INTEGER NOT NULL DEFAULT 1"), ("ntfy_on", "INTEGER NOT NULL DEFAULT 1"),
                             ("layout", "TEXT"), ("view_prefs", "TEXT"),
                             ("dash_prefs", "TEXT"),          # cosa mostra la Dashboard (JSON)
                             ("notify_routes", "TEXT"),        # canali per tipo di avviso (JSON)
                             ("must_change", "INTEGER NOT NULL DEFAULT 0"),
                             ("last_seen", "REAL"), ("blocked", "INTEGER NOT NULL DEFAULT 0"),
                             # email confermata dal suo proprietario: senza, nessun avviso via email.
                             # Gli account già esistenti restano confermati (DEFAULT 1).
                             ("email_verified", "INTEGER NOT NULL DEFAULT 1"),
                             ("verify_hash", "TEXT"), ("verify_expires", "REAL"), ("verify_sent", "REAL"),
                             # Limiti per account decisi dall'amministratore: NULL = default.
                             ("max_probes", "INTEGER"), ("max_fritz", "INTEGER"),
                             ("max_devices", "INTEGER"),
                             # piano scelto dall'amministratore (basso, medio, alto, personalizzato):
                             # NULL = limiti predefiniti, oppure numeri scelti prima che esistessero i piani
                             ("plan", "TEXT"),
                             # conservazione dei dati scelta dall'utente: NULL = quella del server
                             ("ret_value", "INTEGER"), ("ret_unit", "TEXT"),
                             # scadenza dell'account (abbonamento): NULL = nessuna. expiry_warned = 1
                             # quando è partita l'email dei 7 giorni; expired = 1 se l'ha bloccato la scadenza
                             ("expires", "REAL"), ("expiry_warned", "INTEGER NOT NULL DEFAULT 0"),
                             ("expired", "INTEGER NOT NULL DEFAULT 0"),
                             # speedtest periodici: sfalsamento tra le sonde e avvisi sulla velocità (JSON)
                             ("st_prefs", "TEXT"),
                             # aggiornamenti automatici delle sonde (1 = sì, il predefinito)
                             ("probe_auto", "INTEGER NOT NULL DEFAULT 1"),
                             ("tz", "TEXT"),                  # fuso orario scelto (NULL = quello del server)
                             # lingua della pagina e delle notifiche (NULL = italiano)
                             ("lang", "TEXT")):
                if col not in cols:
                    c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
            # Codici di accesso (inviti) generati dall'amministratore: solo l'impronta, come le sessioni
            c.execute("CREATE TABLE IF NOT EXISTS invites ("
                      " id INTEGER PRIMARY KEY,"
                      " code_hash TEXT NOT NULL UNIQUE,"
                      " hint TEXT,"
                      " note TEXT,"
                      " created REAL NOT NULL,"
                      " created_by TEXT,"
                      " expires REAL,"
                      " max_uses INTEGER NOT NULL DEFAULT 1,"
                      " uses INTEGER NOT NULL DEFAULT 0,"
                      " last_used REAL,"
                      " last_user TEXT)")
            # Versione precedente: "chi ha creato il codice" era un utente (vincolo verso users).
            # Ora i codici li crea un amministratore (account separato): tabella ricreata senza vincolo,
            # conservando i codici esistenti.
            if any(r[2] == "users" for r in c.execute("PRAGMA foreign_key_list(invites)")):
                c.execute("ALTER TABLE invites RENAME TO invites_old")
                c.execute("CREATE TABLE invites ("
                          " id INTEGER PRIMARY KEY, code_hash TEXT NOT NULL UNIQUE, hint TEXT, note TEXT,"
                          " created REAL NOT NULL, created_by TEXT, expires REAL,"
                          " max_uses INTEGER NOT NULL DEFAULT 1, uses INTEGER NOT NULL DEFAULT 0,"
                          " last_used REAL, last_user TEXT)")
                c.execute("INSERT INTO invites SELECT o.id, o.code_hash, o.hint, o.note, o.created, "
                          "(SELECT u.email FROM users u WHERE u.id = o.created_by), o.expires, o.max_uses, "
                          "o.uses, o.last_used, o.last_user FROM invites_old o")
                c.execute("DROP TABLE invites_old")
            if "email" not in {r[1] for r in c.execute("PRAGMA table_info(invites)")}:
                c.execute("ALTER TABLE invites ADD COLUMN email TEXT")   # codice valido solo per questa email
            c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            # Amministratori: account separati dagli utenti, validi solo per la pagina /admin
            c.execute("CREATE TABLE IF NOT EXISTS admins ("
                      " id INTEGER PRIMARY KEY,"
                      " login TEXT NOT NULL UNIQUE COLLATE NOCASE,"
                      " pw_hash TEXT NOT NULL,"
                      " created REAL NOT NULL,"
                      " pw_changed REAL NOT NULL,"
                      " must_change INTEGER NOT NULL DEFAULT 1,"
                      " last_seen REAL)")
            acols = {r[1] for r in c.execute("PRAGMA table_info(admins)")}
            for col, ddl in (("failed", "INTEGER NOT NULL DEFAULT 0"),   # tentativi sbagliati di fila
                             ("locked", "INTEGER NOT NULL DEFAULT 0"),   # account bloccato
                             ("locked_until", "REAL"),                    # fine del blocco (0/NULL = libero)
                             ("lock_count", "INTEGER NOT NULL DEFAULT 0"),
                             ("last_lock", "REAL"),
                             ("email", "TEXT"), ("name", "TEXT"),
                             # verifica in due passaggi: app (TOTP) e codice via email
                             ("totp_secret", "TEXT"), ("totp_pending", "TEXT"),
                             ("totp_last_step", "INTEGER NOT NULL DEFAULT -1"), ("totp_since", "REAL"),
                             ("mail_code", "TEXT"), ("mail_code_expires", "REAL"),
                             ("mail_sent", "TEXT"),                      # orari degli ultimi invii
                             # chat Telegram personale: gli avvisi amministrativi arrivano anche li'
                             ("telegram_chat", "TEXT"),
                             ("notify_routes", "TEXT"),          # canali per tipo di avviso (JSON)
                             ("tz", "TEXT"),                     # fuso orario scelto (NULL = quello del server)
                             ("lang", "TEXT")):                  # lingua del pannello e degli avvisi (NULL = italiano)
                if col not in acols:
                    c.execute(f"ALTER TABLE admins ADD COLUMN {col} {ddl}")
            # I blocchi delle versioni precedenti erano permanenti e senza scadenza: chi era
            # stato bloccato non poteva piu' rientrare senza passare dalla VM. Ora il blocco
            # scade da solo, quindi le righe con locked=1 e senza locked_until vengono liberate.
            c.execute("UPDATE admins SET locked = 0, failed = 0 WHERE locked = 1 AND locked_until IS NULL")
            c.execute("CREATE TABLE IF NOT EXISTS admin_sessions ("
                      " id_hash TEXT PRIMARY KEY,"
                      " admin_id INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,"
                      " created REAL NOT NULL,"
                      " expires REAL NOT NULL)")
            # Dispositivi su cui non richiedere il secondo fattore (vedi ADMIN_TRUST_DAYS)
            c.execute("CREATE TABLE IF NOT EXISTS admin_trusted ("
                      " id_hash TEXT PRIMARY KEY,"
                      " admin_id INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,"
                      " created REAL NOT NULL,"
                      " expires REAL NOT NULL)")
            if "mfa" not in {r[1] for r in c.execute("PRAGMA table_info(admin_sessions)")}:
                c.execute("ALTER TABLE admin_sessions ADD COLUMN mfa INTEGER NOT NULL DEFAULT 0")
            # Aggiornamenti programmati dal pannello di amministrazione (VM o sonde)
            c.execute("CREATE TABLE IF NOT EXISTS schedules ("
                      " id INTEGER PRIMARY KEY,"
                      " target TEXT NOT NULL,"            # vm | probes
                      " cmd TEXT NOT NULL,"               # upgrade (sistema) | update (netmon, solo sonde)
                                                          # | reboot (solo VM) | package (netmon da pacchetto)
                      " probes TEXT,"                     # elenco JSON delle chiavi; NULL = tutte
                      " at REAL NOT NULL,"
                      " created REAL NOT NULL,"
                      " created_by TEXT,"
                      " state TEXT NOT NULL DEFAULT 'pending',"   # pending | running | done | error | cancelled
                      " reminded INTEGER NOT NULL DEFAULT 0,"
                      " result TEXT,"
                      " finished REAL)")
            scols = {r[1] for r in c.execute("PRAGMA table_info(schedules)")}
            for col, ddl in (("package", "TEXT"),          # JSON {version, sha256, file}: pacchetto caricato
                             ("after_id", "INTEGER"),      # parte quando è finita questa programmazione (VM)
                             ("batch", "TEXT")):           # campagna del pannello: un solo riepilogo
                if col not in scols:
                    c.execute(f"ALTER TABLE schedules ADD COLUMN {col} {ddl}")
            # la colonna is_admin ("utente principale") non è più usata: tutti gli utenti sono uguali
        os.chmod(self.path, 0o600)

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None, factory=ClosingConnection)
        c.execute("PRAGMA foreign_keys = ON")
        # Con WAL (attivato una volta in __init__) NORMAL resta sicuro contro gli arresti del
        # programma e risparmia una sincronizzazione del disco a ogni scrittura (sessioni, token).
        c.execute("PRAGMA synchronous = NORMAL")
        c.execute("PRAGMA secure_delete = ON")       # dati cancellati sovrascritti, non solo marcati liberi
        return c

    # --- utenti
    def has_users(self) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def user_exists(self, email: str) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone() is not None

    def create_user(self, email: str, password: str, invite: str | None = None, lang: str | None = None):
        """Registra un utente.
        Con `invite` il codice di accesso viene verificato e consumato nella stessa transazione.
        Restituisce (id, primo, errore): errore è "exists" (email già registrata) o "invite"
        (codice non valido, scaduto o esaurito); "blocked" se l'account è bloccato. Con "renewed" l'id
        c'è: l'invito era per l'email di un account esistente, che riceve la nuova password.
        L'email risulta già confermata solo con un invito legato a quell'indirizzo (è arrivato
        lì); negli altri casi va confermata dal link inviato all'indirizzo (email_verify_new)."""
        c = self._conn()
        try:
            c.execute("BEGIN IMMEDIATE")
            # Prima il codice, poi l'email: con un codice inventato la risposta è sempre «codice non
            # valido», così nessuno può scoprire quali indirizzi hanno un account.
            exists = c.execute("SELECT 1 FROM users WHERE email = ?", (normalize_email(email),)).fetchone()
            verified = False
            if invite is not None:
                row = c.execute("SELECT id, expires, max_uses, uses, email FROM invites WHERE code_hash = ?",
                                (_session_hash(invite),)).fetchone()
                if (row is None or (row[1] and row[1] < time.time())
                        or (row[2] and row[3] >= row[2])
                        or (row[4] and normalize_email(row[4]) != normalize_email(email))):
                    c.execute("ROLLBACK")
                    return None, False, "invite"
            if exists and invite is not None and row[4]:
                # Invito legato a questa email per un account che esiste già (per esempio «Reinvia
                # codice» dopo la registrazione): niente secondo account. Chi lo usa ha dimostrato di
                # leggere quella casella, quindi entra nel SUO account con la nuova password; sonde e
                # storico restano dove sono. Le altre sessioni si chiudono, come a ogni cambio password.
                uid = c.execute("SELECT id, blocked FROM users WHERE email = ?", (normalize_email(email),)).fetchone()
                if uid[1]:
                    c.execute("ROLLBACK")
                    return None, False, "blocked"
                now = time.time()
                c.execute("UPDATE invites SET uses = uses + 1, last_used = ?, last_user = ? WHERE id = ?",
                          (now, normalize_email(email), row[0]))
                c.execute("UPDATE users SET pw_hash = ?, pw_changed = ?, email_verified = 1 WHERE id = ?",
                          (hash_password(password), now, uid[0]))
                c.execute("DELETE FROM sessions WHERE user_id = ?", (uid[0],))
                c.execute("COMMIT")
                return uid[0], False, "renewed"
            if exists:
                c.execute("ROLLBACK")              # il codice resta valido: non è stato usato
                return None, False, "exists"
            if invite is not None:
                c.execute("UPDATE invites SET uses = uses + 1, last_used = ?, last_user = ? WHERE id = ?",
                          (time.time(), normalize_email(email), row[0]))
                verified = bool(row[4])
            first = c.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None
            now = time.time()
            # piano dei nuovi account (NEW_USER_PLAN nel .env, predefinito «alto»); l'amministratore
            # lo cambia dal pannello (Limiti). Gli account già esistenti restano come sono.
            cur = c.execute("INSERT INTO users (email, pw_hash, created, pw_changed, is_admin, email_verified, lang, plan) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            (normalize_email(email), hash_password(password), now, now, int(first), int(verified),
                             lang, NEW_USER_PLAN))
            uid = cur.lastrowid
            # Le sonde senza proprietario NON passano al primo utente: sono di account eliminati o
            # spostati (in «Utenti non attivi»), e chi si registra dopo non deve vederne i dati.
            c.execute("COMMIT")
            return uid, first, None
        except Exception:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    # --- amministratori (pagina /admin, separati dagli utenti)
    # Accesso in fasi: password -> verifica in due passaggi (app o codice via email) -> eventuale
    # cambio della password provvisoria -> attivazione dell'app (obbligatoria) -> accesso completo.
    def create_admin(self, email: str, password: str, name: str = "", reset_mfa: bool = False):
        """Crea (o reimposta) un amministratore nominale, identificato dall'email, con password
        provvisoria da cambiare al primo accesso. Restituisce (id, creato). Se esiste già riceve una
        nuova password provvisoria, viene sbloccato e le sue sessioni si chiudono; con reset_mfa
        dovrà anche configurare di nuovo l'app di autenticazione."""
        email = normalize_email(email)
        now = time.time()
        with self._conn() as c:
            row = c.execute("SELECT id FROM admins WHERE login = ?", (email,)).fetchone()
            if row:
                # locked_until va azzerato insieme a locked: l'accesso controlla la scadenza del blocco
                c.execute("UPDATE admins SET pw_hash = ?, pw_changed = ?, must_change = 1, failed = 0, locked = 0, "
                          "locked_until = NULL, lock_count = 0, "
                          "email = COALESCE(email, ?), name = COALESCE(NULLIF(?, ''), name), "
                          "mail_code = NULL WHERE id = ?", (hash_password(password), now, email if "@" in email else None,
                                                             name, row[0]))
                if reset_mfa:
                    c.execute("UPDATE admins SET totp_secret = NULL, totp_pending = NULL, totp_last_step = -1, "
                              "totp_since = NULL WHERE id = ?", (row[0],))
                c.execute("DELETE FROM admin_sessions WHERE admin_id = ?", (row[0],))
                c.execute("DELETE FROM admin_trusted WHERE admin_id = ?", (row[0],))
                return row[0], False
            cur = c.execute("INSERT INTO admins (login, pw_hash, created, pw_changed, must_change, email, name) "
                            "VALUES (?,?,?,?,1,?,?)", (email, hash_password(password), now, now,
                                                       email if "@" in email else None, name or None))
            return cur.lastrowid, True

    def set_admin_name(self, admin_id: int, name: str):
        """Nome e cognome dell'amministratore (compare negli inviti e nel pannello)."""
        with self._conn() as c:
            c.execute("UPDATE admins SET name = ? WHERE id = ?", ((name or "").strip()[:80] or None, admin_id))

    def delete_admin(self, login: str) -> bool:
        with self._conn() as c:
            return c.execute("DELETE FROM admins WHERE login = ?", (normalize_email(login),)).rowcount > 0

    def is_admin_email(self, email: str) -> bool:
        """C'è un amministratore con questo accesso o questa email? """
        e = (email or "").strip().lower()
        if not e:
            return False
        with self._conn() as c:
            return c.execute("SELECT 1 FROM admins WHERE lower(login) = ? OR lower(email) = ? LIMIT 1",
                             (e, e)).fetchone() is not None

    def list_admins(self):
        now = time.time()
        with self._conn() as c:
            rows = c.execute("SELECT a.login, a.created, a.last_seen, a.must_change, "
                             "(SELECT COUNT(*) FROM admin_sessions s WHERE s.admin_id = a.id AND s.expires > ? "
                             " AND (s.mfa = 1 OR a.totp_secret IS NULL)), "
                             "a.locked, a.failed, a.email, a.name, a.totp_secret IS NOT NULL, a.totp_since, "
                             "a.locked_until, "
                             # solo SE la chat c'e', non qual e': la chat di un collega non e' affar tuo
                             "a.telegram_chat IS NOT NULL AND a.telegram_chat != '' "
                             "FROM admins a ORDER BY a.id", (now,)).fetchall()
        return [{"login": r[0], "created": r[1], "last_seen": r[2], "must_change": bool(r[3]),
                 "sessions": r[4], "locked": bool(r[5]) and self._lock_active(r[11], now),
                 "lock_left": max(0, int((r[11] - now) // 60) + 1) if (r[5] and self._lock_active(r[11], now)) else 0,
                 "failed": r[6], "email": r[7] or "",
                 "name": r[8] or "", "mfa": bool(r[9]), "mfa_since": r[10],
                 "telegram": bool(r[12])} for r in rows]

    @staticmethod
    def _lock_active(locked_until, now=None) -> bool:
        """Un blocco vale solo se locked_until e nel futuro: expired = accesso consentito."""
        return bool(locked_until) and locked_until > (now if now is not None else time.time())

    def _admin_lock_left(self, c, admin_id: int) -> int:
        """Minuti di blocco residui, 0 se l'account e libero. Libera i blocchi scaduti."""
        row = c.execute("SELECT locked, locked_until FROM admins WHERE id = ?", (admin_id,)).fetchone()
        if not row or not row[0]:
            return 0
        if not self._lock_active(row[1]):
            c.execute("UPDATE admins SET locked = 0, failed = 0 WHERE id = ?", (admin_id,))
            return 0
        return max(1, int((row[1] - time.time()) // 60) + 1)

    def _admin_fail(self, c, admin_id: int) -> bool:
        """Un codice di verifica sbagliato in piu'; True se l'account e ora bloccato.

        Il blocco non e' permanente: scade da solo e si allunga a ogni nuovo blocco ravvicinato,
        cosi' chi tentasse a forza bruta non puo' bloccare davvero l'amministratore per sempre.
        """
        now = time.time()
        c.execute("UPDATE admins SET failed = failed + 1 WHERE id = ?", (admin_id,))
        failed = c.execute("SELECT failed FROM admins WHERE id = ?", (admin_id,)).fetchone()[0]
        if failed < ADMIN_MAX_FAILS:
            return False
        # Riazzera il contatore e calcola la durata: raddoppia a ogni blocco ravvicinato
        row = c.execute("SELECT lock_count, last_lock FROM admins WHERE id = ?", (admin_id,)).fetchone()
        streak = (row[0] or 0) + 1 if (row[1] and now - row[1] < ADMIN_LOCK_REPEAT) else 1
        minutes = min(ADMIN_LOCK_MINUTES * (2 ** (streak - 1)), ADMIN_LOCK_MAX_MINUTES)
        c.execute("UPDATE admins SET failed = 0, locked = 1, locked_until = ?, lock_count = ?, last_lock = ?, "
                  "mail_code = NULL WHERE id = ?", (now + minutes * 60, streak, now, admin_id))
        c.execute("DELETE FROM admin_sessions WHERE admin_id = ?", (admin_id,))
        return True

    def admin_lock_left(self, admin_id: int) -> int:
        """Minuti di blocco residui per l'amministratore indicato (0 se libero)."""
        with self._conn() as c:
            return self._admin_lock_left(c, admin_id)

    def verify_admin(self, login: str, password: str):
        """(id, esito). Esiti: "ok", "bad" (utente o password errati), "locked" (account bloccato
        per qualche tempo, con la password giusta finche il blocco non scade).
        Una password sbagliata NON blocca l'account e non chiude le sessioni: altrimenti chiunque
        conosca l'email di un amministratore potrebbe tenerlo fuori dal pannello senza sapere
        nient'altro. I tentativi sulla password li limita il chiamante (per indirizzo IP e, con un
        tetto alto, per account). Il blocco scatta solo dopo ADMIN_MAX_FAILS codici di verifica
        sbagliati di fila (_admin_fail): per arrivarci serve gia' la password giusta, quindi e' il
        segnale che la password e' nota a qualcun altro.
        Su "locked" l'id e' comunque restituito: serve solo per sapere quanto manca, il chiamante
        risponde comunque 423 e non apre sessione."""
        with self._conn() as c:
            row = c.execute("SELECT id, pw_hash, locked, locked_until, totp_secret IS NOT NULL "
                            "FROM admins WHERE login = ?", (normalize_email(login),)).fetchone()
        if row is None:
            verify_password(password, _DUMMY)          # stesso tempo di una verifica vera
            return None, "bad"
        good = verify_password(password, row[1])
        with self._conn() as c:
            if self._lock_active(row[3]):
                # Il blocco si rivela solo a chi conosce la password: con una password sbagliata la
                # risposta e' la stessa di un account inesistente (niente indizi a chi tira a indovinare)
                return (row[0], "locked") if good else (None, "bad")
            if row[2]:
                # Blocco scaduto: si riparte puliti
                c.execute("UPDATE admins SET locked = 0, failed = 0 WHERE id = ?", (row[0],))
            if good:
                if not row[4]:
                    c.execute("UPDATE admins SET failed = 0 WHERE id = ?", (row[0],))
                return row[0], "ok"
            # mai l'id con una password sbagliata: il chiamante non deve poter aprire una sessione
            return None, "bad"

    def check_admin_password(self, admin_id: int, password: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT pw_hash FROM admins WHERE id = ?", (admin_id,)).fetchone()
        return bool(row) and verify_password(password, row[0])

    def set_admin_password(self, admin_id: int, password: str):
        """Nuova password, fine della password provvisoria e chiusura di tutte le sessioni."""
        with self._conn() as c:
            c.execute("UPDATE admins SET pw_hash = ?, pw_changed = ?, must_change = 0 WHERE id = ?",
                      (hash_password(password), time.time(), admin_id))
            c.execute("DELETE FROM admin_sessions WHERE admin_id = ?", (admin_id,))
            c.execute("DELETE FROM admin_trusted WHERE admin_id = ?", (admin_id,))

    # --- sessioni di amministrazione, con la fase dell'accesso
    @staticmethod
    def _stage(must_change, has_totp, mfa_done):
        if has_totp and not mfa_done:
            return "mfa"          # password giusta: manca il codice dell'app (o via email)
        if must_change:
            return "password"     # password provvisoria da cambiare
        if not has_totp:
            return "setup"        # app di autenticazione da attivare (obbligatoria)
        return "full"

    def _session_expiry(self, c, admin_id, mfa_done, now):
        r = c.execute("SELECT must_change, totp_secret IS NOT NULL FROM admins WHERE id = ?", (admin_id,)).fetchone()
        full = self._stage(r[0], r[1], mfa_done) == "full"
        return now + (ADMIN_SESSION_HOURS * 3600 if full else ADMIN_PENDING_MINUTES * 60)

    # --- dispositivi fidati: saltano il secondo fattore, non la password
    def trust_device(self, admin_id: int) -> str:
        """Segna questo dispositivo come fidato per ADMIN_TRUST_DAYS giorni."""
        raw = secrets.token_urlsafe(32)
        now = time.time()
        with self._conn() as c:
            c.execute("DELETE FROM admin_trusted WHERE expires < ?", (now,))
            c.execute("INSERT INTO admin_trusted (id_hash, admin_id, created, expires) VALUES (?,?,?,?)",
                      (_session_hash(raw), admin_id, now, now + ADMIN_TRUST_DAYS * 86400))
        return raw

    def device_is_trusted(self, raw: str | None, admin_id: int) -> bool:
        """Se questo dispositivo e' fidato PER QUESTO amministratore: il segno vale per un account
        solo, altrimenti basterebbe un cookie preso altrove per saltare il codice di chiunque."""
        if not raw or len(raw) > 100:
            return False
        with self._conn() as c:
            r = c.execute("SELECT admin_id, expires FROM admin_trusted WHERE id_hash = ?",
                          (_session_hash(raw),)).fetchone()
        return bool(r) and r[0] == admin_id and r[1] > time.time()

    def create_admin_session(self, admin_id: int, mfa: bool = False) -> str:
        raw = new_secret(32)
        now = time.time()
        with self._conn() as c:
            c.execute("DELETE FROM admin_sessions WHERE expires < ?", (now,))
            c.execute("INSERT INTO admin_sessions (id_hash, admin_id, created, expires, mfa) VALUES (?,?,?,?,?)",
                      (_session_hash(raw), admin_id, now, self._session_expiry(c, admin_id, mfa, now), int(mfa)))
        return raw

    def refresh_admin_session(self, raw: str, mfa: bool | None = None):
        """Aggiorna la sessione dopo un passo completato: diventa lunga solo ad accesso completo."""
        now = time.time()
        with self._conn() as c:
            row = c.execute("SELECT admin_id, mfa FROM admin_sessions WHERE id_hash = ?", (_session_hash(raw),)).fetchone()
            if not row:
                return
            done = bool(row[1]) if mfa is None else mfa
            c.execute("UPDATE admin_sessions SET mfa = ?, expires = ? WHERE id_hash = ?",
                      (int(done), self._session_expiry(c, row[0], done, now), _session_hash(raw)))

    def admin_session(self, raw: str | None):
        """Amministratore della sessione con la fase dell'accesso, oppure None."""
        if not raw or len(raw) > 100:
            return None
        now = time.time()
        with self._conn() as c:
            row = c.execute("SELECT s.expires, a.id, a.login, a.must_change, a.last_seen, s.mfa, "
                            "a.totp_secret IS NOT NULL, a.email, a.name, a.locked, a.locked_until, a.tz, a.lang "
                            "FROM admin_sessions s "
                            "JOIN admins a ON a.id = s.admin_id WHERE s.id_hash = ?",
                            (_session_hash(raw),)).fetchone()
            if row is None:
                return None
            if row[9] and self._lock_active(row[10], now):
                return None
            if row[9]:                       # blocco scaduto: si riparte puliti
                c.execute("UPDATE admins SET locked = 0, failed = 0 WHERE id = ?", (row[1],))
            if row[0] < now:
                c.execute("DELETE FROM admin_sessions WHERE id_hash = ?", (_session_hash(raw),))
                return None
            stage = self._stage(row[3], row[6], row[5])
            if stage == "full" and (not row[4] or now - row[4] > 300):
                c.execute("UPDATE admins SET last_seen = ? WHERE id = ?", (now, row[1]))
        return {"id": row[1], "login": row[2], "must_change": bool(row[3]), "stage": stage,
                "mfa": bool(row[6]), "email": row[7] or "", "name": row[8] or "", "tz": row[11] or "",
                "lang": row[12] or "it"}

    def delete_admin_session(self, raw: str | None):
        if raw:
            with self._conn() as c:
                c.execute("DELETE FROM admin_sessions WHERE id_hash = ?", (_session_hash(raw),))

    # --- app di autenticazione (TOTP)
    def totp_begin(self, admin_id: int) -> str:
        """Nuova chiave in attesa di conferma: quella attuale resta valida finché la nuova non è confermata."""
        secret = mfa.new_secret()
        with self._conn() as c:
            c.execute("UPDATE admins SET totp_pending = ? WHERE id = ?", (secret, admin_id))
        return secret

    def totp_confirm(self, admin_id: int, code: str) -> str:
        """Conferma la nuova chiave con un codice dell'app: "ok", "bad", "locked", "none"."""
        with self._conn() as c:
            row = c.execute("SELECT totp_pending FROM admins WHERE id = ?", (admin_id,)).fetchone()
            if not row or not row[0]:
                return "none"
            step = mfa.verify_totp(row[0], code)
            if step is None:
                return "locked" if self._admin_fail(c, admin_id) else "bad"
            c.execute("UPDATE admins SET totp_secret = totp_pending, totp_pending = NULL, totp_last_step = ?, "
                      "totp_since = ?, failed = 0 WHERE id = ?", (step, time.time(), admin_id))
            # Cambiato il secondo fattore, i «non chiedermelo piu'» dati prima non valgono piu':
            # erano legati alla vecchia app, e chi l'avesse ancora salterebbe il codice nuovo.
            c.execute("DELETE FROM admin_trusted WHERE admin_id = ?", (admin_id,))
            return "ok"

    def totp_check(self, admin_id: int, code: str) -> str:
        """Secondo passaggio con il codice dell'app: "ok", "bad", "locked"."""
        with self._conn() as c:
            row = c.execute("SELECT totp_secret, totp_last_step, locked, locked_until FROM admins "
                            "WHERE id = ?", (admin_id,)).fetchone()
            if not row or (row[2] and self._admin_lock_left(c, admin_id)):   # blocco ancora attivo
                return "locked"
            step = mfa.verify_totp(row[0], code, row[1])
            if step is None:
                return "locked" if self._admin_fail(c, admin_id) else "bad"
            c.execute("UPDATE admins SET totp_last_step = ?, failed = 0, mail_code = NULL WHERE id = ?", (step, admin_id))
            return "ok"

    # --- codice di riserva via email
    def mail_code_new(self, admin_id: int):
        """(codice, attesa in secondi). Il codice è None se bisogna aspettare prima di chiederne un altro."""
        import json as _json
        now = time.time()
        with self._conn() as c:
            row = c.execute("SELECT mail_sent FROM admins WHERE id = ?", (admin_id,)).fetchone()
            try:
                sent = [t for t in _json.loads(row[0] or "[]") if now - t < 3600]
            except (ValueError, TypeError):
                sent = []
            if sent and now - sent[-1] < MAIL_CODE_GAP:
                return None, int(MAIL_CODE_GAP - (now - sent[-1])) + 1
            if len(sent) >= MAIL_CODE_PER_HOUR:
                return None, int(3600 - (now - sent[0])) + 1
            code = mfa.new_mail_code()
            sent.append(now)
            c.execute("UPDATE admins SET mail_code = ?, mail_code_expires = ?, mail_sent = ? WHERE id = ?",
                      (mfa.hash_mail_code(admin_id, code), now + mfa.MAIL_CODE_MINUTES * 60, _json.dumps(sent), admin_id))
        return code, 0

    def mail_code_check(self, admin_id: int, code: str) -> str:
        """Secondo passaggio con il codice ricevuto via email: "ok", "bad", "expired", "locked"."""
        with self._conn() as c:
            row = c.execute("SELECT mail_code, mail_code_expires, locked, locked_until FROM admins "
                            "WHERE id = ?", (admin_id,)).fetchone()
            if not row or (row[2] and self._admin_lock_left(c, admin_id)):   # blocco ancora attivo
                return "locked"
            if not row[0] or (row[1] or 0) < time.time():
                return "expired"
            if not hmac.compare_digest(row[0], mfa.hash_mail_code(admin_id, code)):
                return "locked" if self._admin_fail(c, admin_id) else "bad"
            c.execute("UPDATE admins SET mail_code = NULL, failed = 0 WHERE id = ?", (admin_id,))
            return "ok"

    # --- impostazioni del server
    # --- aggiornamenti programmati
    _SCHED_COLS = ("id, target, cmd, probes, at, created, created_by, state, reminded, result, finished, package, after_id, "
                   "batch")

    def _sched(self, r):
        import json
        return None if r is None else {
            "id": r[0], "target": r[1], "cmd": r[2], "probes": json.loads(r[3]) if r[3] else None,
            "at": r[4], "created": r[5], "created_by": r[6] or "", "state": r[7], "reminded": bool(r[8]),
            "result": r[9] or "", "finished": r[10], "package": json.loads(r[11]) if r[11] else None,
            "after_id": r[12], "batch": r[13] or None}

    def add_schedule(self, target: str, cmd: str, probes, at: float, by: str, package=None, after_id=None,
                     batch=None) -> int:
        import json
        with self._conn() as c:
            return c.execute("INSERT INTO schedules (target, cmd, probes, at, created, created_by, package, after_id, batch) "
                             "VALUES (?,?,?,?,?,?,?,?,?)",
                             (target, cmd, json.dumps(probes) if probes is not None else None, at, time.time(), by,
                              json.dumps(package) if package else None, after_id, batch)).lastrowid

    def schedules_of_batch(self, batch: str):
        with self._conn() as c:
            return [self._sched(r) for r in c.execute(
                f"SELECT {self._SCHED_COLS} FROM schedules WHERE batch = ? ORDER BY id", (batch,)).fetchall()]

    def get_schedule(self, sid: int):
        with self._conn() as c:
            return self._sched(c.execute(f"SELECT {self._SCHED_COLS} FROM schedules WHERE id = ?", (sid,)).fetchone())

    def list_schedules(self, limit: int | None = None):
        """Prima quelle in attesa o in corso (dalla più vicina), poi le concluse (tutte, o le ultime `limit`)."""
        with self._conn() as c:
            rows = c.execute(f"SELECT {self._SCHED_COLS} FROM schedules WHERE state IN ('pending','running') "
                             "ORDER BY at").fetchall()
            rows += c.execute(f"SELECT {self._SCHED_COLS} FROM schedules WHERE state NOT IN ('pending','running') "
                              "ORDER BY COALESCE(finished, at) DESC LIMIT ?", (-1 if limit is None else limit,)).fetchall()
        return [self._sched(r) for r in rows]

    def schedules_in(self, *states):
        marks = ",".join("?" * len(states))
        with self._conn() as c:
            return [self._sched(r) for r in c.execute(
                f"SELECT {self._SCHED_COLS} FROM schedules WHERE state IN ({marks}) ORDER BY at", states)]

    def update_schedule(self, sid: int, **fields):
        allowed = {"state", "reminded", "result", "finished"}
        keys = [k for k in fields if k in allowed]
        if keys:
            with self._conn() as c:
                c.execute(f"UPDATE schedules SET {', '.join(k + ' = ?' for k in keys)} WHERE id = ?",
                          [fields[k] for k in keys] + [sid])

    def set_admin_telegram(self, admin_id: int, chat: str):
        """Chat Telegram personale dell'amministratore ("" = nessuna)."""
        with self._conn() as c:
            c.execute("UPDATE admins SET telegram_chat = ? WHERE id = ?", (chat or None, admin_id))

    def admin_telegram(self, admin_id: int) -> str:
        with self._conn() as c:
            r = c.execute("SELECT telegram_chat FROM admins WHERE id = ?", (admin_id,)).fetchone()
        return (r[0] if r else "") or ""

    def admin_contacts(self) -> list:
        """Email, chat Telegram e canali per tipo di avviso di ogni amministratore non bloccato."""
        now = time.time()
        with self._conn() as c:
            rows = c.execute("SELECT email, telegram_chat, notify_routes, locked, locked_until, lang FROM admins").fetchall()
        return [{"email": r[0] or "", "telegram": r[1] or "", "routes": _routes(r[2]), "lang": r[5] or "it"}
                for r in rows if not (r[3] and self._lock_active(r[4], now))]

    def admin_routes(self, admin_id: int) -> dict:
        with self._conn() as c:
            r = c.execute("SELECT notify_routes FROM admins WHERE id = ?", (admin_id,)).fetchone()
        return _routes(r[0] if r else None)

    def set_admin_routes(self, admin_id: int, routes: dict):
        import json
        with self._conn() as c:
            c.execute("UPDATE admins SET notify_routes = ? WHERE id = ?", (json.dumps(routes), admin_id))

    def admin_email_by_login(self, login: str) -> str:
        with self._conn() as c:
            row = c.execute("SELECT email FROM admins WHERE login = ?", (normalize_email(login),)).fetchone()
        return (row[0] if row else "") or ""

    def get_setting(self, key: str, default: str | None = None):
        with self._conn() as c:
            row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str):
        with self._conn() as c:
            c.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                      "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # --- codici di accesso (inviti)
    def create_invite(self, created_by: str, note: str = "", max_uses: int = 1, days: float | None = 7,
                      email: str | None = None):
        """Nuovo codice di accesso: restituito in chiaro una sola volta, salvato solo come impronta.
        Con `email` vale solo per quell'indirizzo, per una sola registrazione."""
        raw = "accesso_" + new_secret(18)
        now = time.time()
        email = normalize_email(email) if email else None
        with self._conn() as c:
            c.execute("INSERT INTO invites (code_hash, hint, note, created, created_by, expires, max_uses, email) "
                      "VALUES (?,?,?,?,?,?,?,?)",
                      (_session_hash(raw), raw[-4:], (note or "")[:80], now, created_by,
                       now + days * 86400 if days else None, 1 if email else max(0, int(max_uses)), email))
        return raw

    def get_invite(self, rid: int):
        """Un codice di accesso, per rimandarlo. Il codice in chiaro non c'e': in archivio sta solo
        la sua impronta, quindi di lui si possono riusare le impostazioni, non il valore."""
        with self._conn() as c:
            r = c.execute("SELECT id, note, expires, max_uses, uses, email FROM invites WHERE id = ?",
                          (rid,)).fetchone()
        if not r:
            return None
        return {"id": r[0], "note": r[1] or "", "expires": r[2], "max_uses": r[3],
                "uses": r[4], "email": r[5] or ""}

    def list_invites(self):
        with self._conn() as c:
            rows = c.execute("SELECT id, hint, note, created, created_by, expires, max_uses, uses, "
                             "last_used, last_user, email FROM invites ORDER BY created DESC").fetchall()
        now = time.time()
        out = []
        for rid, hint, note, created, by, expires, max_uses, uses, last_used, last_user, email in rows:
            state = ("scaduto" if expires and expires < now
                     else "esaurito" if max_uses and uses >= max_uses else "valido")
            out.append({"id": rid, "hint": hint, "note": note or "", "created": created, "created_by": by,
                        "expires": expires, "max_uses": max_uses, "uses": uses, "last_used": last_used,
                        "last_user": last_user, "state": state, "email": email or ""})
        return out

    def delete_invite(self, invite_id: int) -> bool:
        with self._conn() as c:
            return c.execute("DELETE FROM invites WHERE id = ?", (invite_id,)).rowcount > 0

    def email_registered(self, email: str) -> bool:
        """True se esiste già un account con questa email (per non invitare chi è già registrato)."""
        with self._conn() as c:
            return c.execute("SELECT 1 FROM users WHERE email = ?", (normalize_email(email),)).fetchone() is not None

    def users_overview(self):
        """Tutti gli account con attività, sessioni aperte e numero di sonde (pagina amministratore)."""
        now = time.time()
        with self._conn() as c:
            rows = c.execute(
                "SELECT u.id, u.email, u.is_admin, u.created, u.last_seen, u.blocked, "
                "(SELECT COUNT(*) FROM sessions s WHERE s.user_id = u.id AND s.expires > ?), "
                "(SELECT MAX(created) FROM sessions s WHERE s.user_id = u.id), "
                "(SELECT COUNT(*) FROM probes p WHERE p.owner = u.id), "
                "u.max_probes, u.max_fritz, u.max_devices, u.plan, u.expires, u.expired, u.tz "
                "FROM users u ORDER BY u.id", (now,)).fetchall()
        return [{"id": r[0], "email": r[1], "is_admin": bool(r[2]), "created": r[3],
                 "last_seen": r[4] or r[7], "blocked": bool(r[5]), "sessions": r[6], "probes": r[8],
                 "max_probes": r[9], "max_fritz": r[10], "max_devices": r[11], "plan": r[12],
                 "expires": r[13], "expired": bool(r[14]), "tz": r[15] or ""}
                for r in rows]

    # --- limiti per utente: quante sonde, quanti FRITZ!Box aggiuntivi e quanti dispositivi per
    # sonda può avere. Un valore NULL vuol dire «default» (50 sonde, 4 FRITZ, 30 dispositivi):
    # app.py è chi risolve.
    def limits_of(self, user_id):
        with self._conn() as c:
            r = c.execute("SELECT max_probes, max_fritz, max_devices, plan FROM users WHERE id = ?",
                          (user_id,)).fetchone()
        if not r:
            return {"max_probes": None, "max_fritz": None, "max_devices": None, "plan": None}
        return {"max_probes": r[0], "max_fritz": r[1], "max_devices": r[2], "plan": r[3]}

    def set_limits(self, user_id, max_probes=None, max_fritz=None, max_devices=None, plan=None) -> bool:
        """Scrive i limiti di un account (None = torna al default). Con un piano (basso, medio,
        alto) FRITZ!Box e dispositivi li decide il piano: app.py è chi risolve."""
        with self._conn() as c:
            return c.execute("UPDATE users SET max_probes = ?, max_fritz = ?, max_devices = ?, plan = ? "
                             "WHERE id = ?", (max_probes, max_fritz, max_devices, plan, user_id)).rowcount > 0

    # --- conservazione dei dati scelta dall'utente: (valore, unità), (None, "sempre") = tutto,
    # (None, None) = quella del server
    def retention_of(self, user_id):
        with self._conn() as c:
            r = c.execute("SELECT ret_value, ret_unit FROM users WHERE id = ?", (user_id,)).fetchone()
        return (r[0], r[1]) if r and r[1] else (None, None)

    def set_retention(self, user_id, value, unit):
        with self._conn() as c:
            c.execute("UPDATE users SET ret_value = ?, ret_unit = ? WHERE id = ?", (value, unit, user_id))

    def retentions(self):
        """Utenti che hanno scelto la loro conservazione: id -> (valore, unità)."""
        with self._conn() as c:
            return {r[0]: (r[1], r[2]) for r in
                    c.execute("SELECT id, ret_value, ret_unit FROM users WHERE ret_unit IS NOT NULL")}

    # --- scadenza dell'account: alla data scelta dall'amministratore l'account si blocca da solo
    def expiry_of(self, user_id):
        with self._conn() as c:
            r = c.execute("SELECT expires, expiry_warned, expired FROM users WHERE id = ?", (user_id,)).fetchone()
        return {"expires": r[0], "warned": bool(r[1]), "expired": bool(r[2])} if r else None

    def set_expiry(self, user_id, expires, warned=False):
        """Nuova scadenza (None = nessuna). Se era stata la scadenza a bloccare l'account, lo sblocca."""
        with self._conn() as c:
            c.execute("UPDATE users SET blocked = CASE WHEN expired = 1 THEN 0 ELSE blocked END, "
                      "expires = ?, expiry_warned = ?, expired = 0 WHERE id = ?", (expires, int(warned), user_id))

    def expiry_due(self, now, warn_before):
        """(da avvisare, da bloccare): account con scadenza entro warn_before secondi e senza
        avviso, e account con la scadenza passata non ancora bloccati da lei."""
        with self._conn() as c:
            warn = c.execute("SELECT id FROM users WHERE expires IS NOT NULL AND expiry_warned = 0 "
                             "AND expired = 0 AND expires > ? AND expires <= ?", (now, now + warn_before)).fetchall()
            due = c.execute("SELECT id FROM users WHERE expires IS NOT NULL AND expired = 0 AND expires <= ?",
                            (now,)).fetchall()
        return [r[0] for r in warn], [r[0] for r in due]

    def mark_expiry_warned(self, user_id):
        with self._conn() as c:
            c.execute("UPDATE users SET expiry_warned = 1 WHERE id = ?", (user_id,))

    def expire(self, user_id) -> bool:
        """Blocca l'account per scadenza (chiudendo le sessioni). False se nel frattempo è cambiata."""
        with self._conn() as c:
            n = c.execute("UPDATE users SET expired = 1, blocked = 1 WHERE id = ? AND expired = 0 "
                          "AND expires IS NOT NULL AND expires <= ?", (user_id, time.time())).rowcount
            if n:
                c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return n > 0

    def admin_id(self):
        """Primo account registrato: riceve solo le sonde e i canali delle versioni a utente singolo
        (migrazione una tantum). Non ha nessun privilegio."""
        with self._conn() as c:
            row = c.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        return row[0] if row else None

    def get_user(self, user_id):
        with self._conn() as c:
            row = c.execute("SELECT id, email, is_admin, telegram_chat, ntfy_url, notify_email, blocked, "
                            "email_verified, notify_routes, lang, tz, telegram_on, ntfy_on FROM users WHERE id = ?",
                            (user_id,)).fetchone()
        if not row:
            return None
        return {"id": row[0], "email": row[1], "is_admin": bool(row[2]), "telegram_chat": row[3] or "",
                "ntfy_url": row[4] or "", "notify_email": bool(row[5]), "blocked": bool(row[6]),
                "email_verified": bool(row[7]), "routes": _routes(row[8]), "lang": row[9] or "it", "tz": row[10] or "",
                "telegram_on": bool(row[11]), "ntfy_on": bool(row[12])}

    def set_lang(self, user_id: int, lang: str):
        with self._conn() as c:
            c.execute("UPDATE users SET lang = ? WHERE id = ?", (lang, user_id))

    def set_tz(self, user_id: int, tz: str):
        with self._conn() as c:
            c.execute("UPDATE users SET tz = ? WHERE id = ?", (tz or None, user_id))

    def set_admin_lang(self, admin_id: int, lang: str):
        with self._conn() as c:
            c.execute("UPDATE admins SET lang = ? WHERE id = ?", (lang, admin_id))

    def set_admin_tz(self, admin_id: int, tz: str):
        with self._conn() as c:
            c.execute("UPDATE admins SET tz = ? WHERE id = ?", (tz or None, admin_id))

    # --- conferma dell'email: gli avvisi via email partono solo verso indirizzi confermati
    def email_verify_new(self, user_id: int):
        """(codice, attesa in secondi) per il link di conferma: in chiaro una sola volta, salvato
        solo come impronta. Il codice è None se l'email è già confermata (attesa 0) o se bisogna
        aspettare prima di chiederne un altro: un indirizzo altrui non si può tempestare di link."""
        now = time.time()
        with self._conn() as c:
            row = c.execute("SELECT email_verified, verify_sent FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row or row[0]:
                return None, 0
            if row[1] and now - row[1] < VERIFY_GAP:
                return None, int(VERIFY_GAP - (now - row[1])) + 1
            raw = secrets.token_urlsafe(24)
            c.execute("UPDATE users SET verify_hash = ?, verify_expires = ?, verify_sent = ? WHERE id = ?",
                      (_session_hash(raw), now + VERIFY_HOURS * 3600, now, user_id))
        return raw, 0

    def email_verify_check(self, user_id: int, raw: str) -> bool:
        """Conferma l'email dell'utente con il codice ricevuto a quell'indirizzo (una sola volta)."""
        if not raw or len(raw) > 100:
            return False
        with self._conn() as c:
            row = c.execute("SELECT email_verified, verify_hash, verify_expires FROM users WHERE id = ?",
                            (user_id,)).fetchone()
            if not row:
                return False
            if row[0]:
                return True
            if not row[1] or (row[2] or 0) < time.time() or not hmac.compare_digest(row[1], _session_hash(raw)):
                return False
            c.execute("UPDATE users SET email_verified = 1, verify_hash = NULL, verify_expires = NULL WHERE id = ?",
                      (user_id,))
        return True

    def get_layout(self, user_id) -> list:
        """Ordine delle sezioni della pagina scelto dall'utente."""
        import json
        with self._conn() as c:
            row = c.execute("SELECT layout FROM users WHERE id = ?", (user_id,)).fetchone()
        try:
            data = json.loads(row[0]) if row and row[0] else []
            return [str(x) for x in data][:200] if isinstance(data, list) else []
        except ValueError:
            return []

    def set_layout(self, user_id, order: list):
        import json
        with self._conn() as c:
            c.execute("UPDATE users SET layout = ? WHERE id = ?", (json.dumps(order[:200]), user_id))

    def get_view(self, user_id) -> dict:
        """Preferenze di visualizzazione della pagina di stato (colonne, riquadro FRITZ!Box)."""
        import json
        with self._conn() as c:
            row = c.execute("SELECT view_prefs FROM users WHERE id = ?", (user_id,)).fetchone()
        try:
            data = json.loads(row[0]) if row and row[0] else {}
            return {str(k): bool(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except ValueError:
            return {}

    def set_view(self, user_id, prefs: dict):
        import json
        with self._conn() as c:
            c.execute("UPDATE users SET view_prefs = ? WHERE id = ?", (json.dumps(prefs), user_id))

    def get_dash(self, user_id):
        """Cosa mostra la Dashboard (riepilogo, uso della linea, sonde e dispositivi nascosti).
        None se l'account non ha ancora scelto nulla."""
        import json
        with self._conn() as c:
            row = c.execute("SELECT dash_prefs FROM users WHERE id = ?", (user_id,)).fetchone()
        try:
            data = json.loads(row[0]) if row and row[0] else None
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        hide, order = data.get("hide"), data.get("order")
        lst = lambda v: [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
        colors, sizes = data.get("colors"), data.get("sizes")
        return {"summary": data.get("summary") is not False, "line": data.get("line") is not False,
                "speed": data.get("speed") is not False,
                "hide": lst(hide), "order": lst(order), "groups": lst(data.get("groups")),
                "closed": lst(data.get("closed")),
                "colors": {k: v for k, v in colors.items() if isinstance(k, str) and isinstance(v, str)}
                if isinstance(colors, dict) else {},
                "blocks": lst(data.get("blocks")),
                "sizes": {k: v for k, v in sizes.items() if isinstance(k, str) and isinstance(v, str)}
                if isinstance(sizes, dict) else {},
                "avail": data.get("avail") is not False,
                "avail_devs": lst(data.get("avail_devs")) if isinstance(data.get("avail_devs"), list) else None,
                "avail_range": data.get("avail_range") if data.get("avail_range") in ("24h", "7d") else "24h"}

    def get_st_prefs(self, user_id) -> dict:
        """Speedtest dell'account: sfalsamento tra le sonde (minuti) e avvisi sulla velocità."""
        import json
        with self._conn() as c:
            row = c.execute("SELECT st_prefs FROM users WHERE id = ?", (user_id,)).fetchone()
        try:
            data = json.loads(row[0]) if row and row[0] else {}
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}

    def set_st_prefs(self, user_id, prefs: dict):
        import json
        with self._conn() as c:
            c.execute("UPDATE users SET st_prefs = ? WHERE id = ?", (json.dumps(prefs), user_id))

    def get_probe_auto(self, user_id) -> bool:
        """Le sonde dell'utente si aggiornano da sole quando il server ha una versione nuova?"""
        with self._conn() as c:
            row = c.execute("SELECT probe_auto FROM users WHERE id = ?", (user_id,)).fetchone()
        return bool(row[0]) if row else True

    def set_probe_auto(self, user_id, on: bool):
        with self._conn() as c:
            c.execute("UPDATE users SET probe_auto = ? WHERE id = ?", (1 if on else 0, user_id))

    def probe_auto_off(self) -> set:
        """Utenti che hanno disattivato gli aggiornamenti automatici delle sonde."""
        with self._conn() as c:
            return {r[0] for r in c.execute("SELECT id FROM users WHERE probe_auto = 0")}

    def set_dash(self, user_id, prefs: dict):
        import json
        with self._conn() as c:
            c.execute("UPDATE users SET dash_prefs = ? WHERE id = ?", (json.dumps(prefs), user_id))

    def set_routes(self, user_id, routes: dict):
        import json
        with self._conn() as c:
            c.execute("UPDATE users SET notify_routes = ? WHERE id = ?", (json.dumps(routes), user_id))

    def set_notify(self, user_id, telegram_chat: str, ntfy_url: str, notify_email: bool,
                   telegram_on: bool | None = None, ntfy_on: bool | None = None):
        """Canali dell'utente. telegram_on/ntfy_on None = interruttore lasciato com'è."""
        with self._conn() as c:
            c.execute("UPDATE users SET telegram_chat = ?, ntfy_url = ?, notify_email = ?, "
                      "telegram_on = COALESCE(?, telegram_on), ntfy_on = COALESCE(?, ntfy_on) WHERE id = ?",
                      (telegram_chat or None, ntfy_url or None, int(notify_email),
                       None if telegram_on is None else int(telegram_on),
                       None if ntfy_on is None else int(ntfy_on), user_id))

    def set_blocked(self, user_id: int, blocked: bool) -> bool:
        """Blocca (chiudendo le sessioni) o sblocca un utente della pagina di stato."""
        with self._conn() as c:
            n = c.execute("UPDATE users SET blocked = ? WHERE id = ?", (int(blocked), user_id)).rowcount
            if blocked:
                c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return n > 0

    def delete_user(self, user_id):
        """Elimina l'utente; le sue sonde restano senza proprietario (ricollegabili con il loro token)."""
        with self._conn() as c:
            c.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def export_user(self, user_id) -> dict:
        """Tutto ciò che il server tiene di un utente (art. 15 e 20 GDPR), tranne impronte di
        password, sessioni e codici, che non servono a nessuno e non vanno fuori."""
        import json
        secret = {"pw_hash", "verify_hash"}
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                return {}
            user = {k: row[k] for k in row.keys() if k not in secret}
            for k in ("layout", "view_prefs", "dash_prefs", "notify_routes"):
                try:
                    user[k] = json.loads(user[k]) if user.get(k) else None
                except ValueError:
                    pass
            user["sessions"] = [dict(r) for r in c.execute(
                "SELECT created, expires, remember, user_agent FROM sessions WHERE user_id = ? "
                "ORDER BY created", (user_id,))]
        return user

    def forget_email(self, email):
        """Toglie un'email dagli inviti (indirizzo dell'invito e ultimo utente che l'ha usato)."""
        with self._conn() as c:
            # un invito ancora usabile legato a quell'indirizzo si revoca: senza email varrebbe per chiunque
            c.execute("DELETE FROM invites WHERE email = ? COLLATE NOCASE AND uses < max_uses", (email,))
            c.execute("UPDATE invites SET email = NULL WHERE email = ? COLLATE NOCASE", (email,))
            c.execute("UPDATE invites SET last_user = '(account eliminato)' WHERE last_user = ? COLLATE NOCASE",
                      (email,))

    def verify_login(self, email: str, password: str):
        """Id dell'utente se email e password sono corrette, altrimenti None.
        Utente bloccato dall'amministratore (con password corretta): -1; dalla scadenza: -2."""
        with self._conn() as c:
            row = c.execute("SELECT id, pw_hash, blocked, expired FROM users WHERE email = ?",
                            (normalize_email(email),)).fetchone()
        if row is None:
            verify_password(password, _DUMMY)          # stesso tempo di una verifica vera
            return None
        if not verify_password(password, row[1]):
            return None
        return (-2 if row[3] else -1) if row[2] else row[0]

    @staticmethod
    def burn_password_check(password: str):
        """Una verifica a vuoto, per pareggiare i tempi: la schermata d'accesso unica controlla anche
        la password da amministratore per le email del pannello, e senza questa le altre email
        risponderebbero prima (si capirebbe quali indirizzi sono di un amministratore)."""
        verify_password(password, _DUMMY)

    def check_password(self, user_id: int, password: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT pw_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        return bool(row) and verify_password(password, row[0])

    def set_password(self, user_id: int, password: str):
        """Nuova password e chiusura di tutte le sessioni dell'utente."""
        with self._conn() as c:
            c.execute("UPDATE users SET pw_hash = ?, pw_changed = ?, must_change = 0 WHERE id = ?",
                      (hash_password(password), time.time(), user_id))
            c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def set_password_by_email(self, email: str, password: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT id FROM users WHERE email = ?", (normalize_email(email),)).fetchone()
        if not row:
            return False
        self.set_password(row[0], password)
        return True

    def delete_everything(self):
        """Cancella account, sessioni e codici di accesso: al prossimo accesso si ripete la
        configurazione con la chiave del server."""
        with self._conn() as c:
            c.execute("DELETE FROM sessions")
            c.execute("DELETE FROM invites")
            c.execute("DELETE FROM users")

    # --- sessioni
    def create_session(self, user_id: int, remember: bool, user_agent: str = "") -> tuple[str, float]:
        raw = new_secret(32)
        now = time.time()
        expires = now + (SESSION_DAYS_REMEMBER * 86400 if remember else SESSION_HOURS * 3600)
        with self._conn() as c:
            c.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)",
                      (_session_hash(raw), user_id, now, expires, int(remember), (user_agent or "")[:200]))
        return raw, expires

    def session_user(self, raw: str | None):
        """Utente della sessione ({id, email}) oppure None se assente, scaduta o revocata."""
        if not raw or len(raw) > 100:
            return None
        now = time.time()
        with self._conn() as c:
            row = c.execute("SELECT s.expires, u.id, u.email, u.is_admin, u.must_change, u.last_seen, u.lang, u.tz "
                            "FROM sessions s JOIN users u ON u.id = s.user_id "
                            "WHERE s.id_hash = ? AND u.blocked = 0", (_session_hash(raw),)).fetchone()
            if row is None:
                return None
            if row[0] < now:
                c.execute("DELETE FROM sessions WHERE id_hash = ?", (_session_hash(raw),))
                return None
            if not row[5] or now - row[5] > 300:
                c.execute("UPDATE users SET last_seen = ? WHERE id = ?", (now, row[1]))
        return {"id": row[1], "email": row[2], "is_admin": bool(row[3]), "must_change": bool(row[4]),
                "lang": row[6] or "it", "tz": row[7] or ""}

    def delete_session(self, raw: str | None):
        if raw:
            with self._conn() as c:
                c.execute("DELETE FROM sessions WHERE id_hash = ?", (_session_hash(raw),))

    def delete_user_sessions(self, user_id: int):
        with self._conn() as c:
            c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def purge_expired(self):
        with self._conn() as c:
            c.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            c.execute("DELETE FROM admin_sessions WHERE expires < ?", (time.time(),))


# ------------------------------------------------------------------ sonde e loro token

def _json_obj(v):
    import json
    try:
        o = json.loads(v) if v else {}
    except ValueError:
        return {}
    return o if isinstance(o, dict) else {}


def new_probe_token() -> str:
    return "sonda_" + new_secret(30)


class ProbeRegistry:
    """Chi possiede quale sonda. Ogni sonda si identifica con un token personale, salvato solo come impronta."""

    def __init__(self, db: AuthDB):
        self.db = db

    def by_token(self, raw):
        """(chiave, proprietario) della sonda con questo token, oppure None."""
        if not raw:
            return None
        with self.db._conn() as c:
            row = c.execute("SELECT key, owner, token_used FROM probes WHERE token_hash = ?",
                            (_session_hash(raw),)).fetchone()
            if row and not row[2]:
                c.execute("UPDATE probes SET token_used = 1, key_ok = 0 WHERE key = ?", (row[0],))
        return (row[0], row[1]) if row else None

    def exists(self, key) -> bool:
        with self.db._conn() as c:
            return c.execute("SELECT 1 FROM probes WHERE key = ?", (key,)).fetchone() is not None

    def issue(self, key, owner=None) -> str:
        """Crea (o sostituisce) il token della sonda `key`; restituisce il token in chiaro, una sola volta.
        Lo genera solo la pagina: le sonde non ricevono più token dal server."""
        raw = new_probe_token()
        with self.db._conn() as c:
            if c.execute("SELECT 1 FROM probes WHERE key = ?", (key,)).fetchone():
                # token nuovo: il primo dispositivo che lo usa ne diventa il titolare
                c.execute("UPDATE probes SET token_hash = ?, token_used = 0, key_ok = ?, inst = NULL, dup = NULL "
                          "WHERE key = ?", (_session_hash(raw), 0, key))
                if owner is not None:
                    c.execute("UPDATE probes SET owner = ? WHERE key = ?", (owner, key))
            else:
                c.execute("INSERT INTO probes (key, owner, token_hash, created, key_ok) VALUES (?,?,?,?,?)",
                          (key, owner, _session_hash(raw), time.time(), 0))
        return raw

    def create(self, owner) -> tuple[str, str]:
        key = "p_" + secrets.token_hex(6)
        return key, self.issue(key, owner)

    def claim(self, raw, owner):
        """Collega all'utente la sonda con questo token, se non ha proprietario (o è già sua)."""
        row = self.by_token(raw)
        if not row:
            return None, "Nessuna sonda con questo token."
        key, current = row
        if current not in (None, owner):
            return None, "Questa sonda appartiene a un altro utente."
        # Chi collega la sonda ha dimostrato di avere il suo token personale: da qui in poi vale
        # solo quello. Senza azzerare key_ok, la chiave del server (condivisa da chiunque abbia
        # installato una sonda con essa) continuerebbe a valere per questa sonda finche' non usa il
        # token, e potrebbe farsene dare uno nuovo o leggerne la configurazione.
        with self.db._conn() as c:
            c.execute("UPDATE probes SET owner = ?, key_ok = 0 WHERE key = ?", (owner, key))
        return key, None

    # --- un token, un dispositivo: il primo che lo usa ne è il titolare, gli altri vengono rifiutati
    DUP_SHOW = 1800            # un secondo dispositivo conta finché ha provato negli ultimi 30 minuti

    def instance_seen(self, key, inst, host="", ip=None, now=None):
        """Registra il dispositivo che scrive per la sonda. None se è il titolare (o il primo, che lo
        diventa); altrimenti {"inst": titolare, "dup": secondo dispositivo, "notify": True se è
        ora di avvisare l'utente} e i dati vanno rifiutati."""
        import json
        now = now or time.time()
        with self.db._conn() as c:
            row = c.execute("SELECT inst, dup FROM probes WHERE key = ?", (key,)).fetchone()
            if not row:
                return None
            cur = _json_obj(row[0])
            if not cur.get("id"):
                cur = {"id": inst, "host": host, "ip": ip or "", "since": now}
                c.execute("UPDATE probes SET inst = ? WHERE key = ?", (json.dumps(cur), key))
                return None
            if cur["id"] == inst:
                if (host and host != cur.get("host")) or (ip and ip != cur.get("ip")):
                    cur.update({"host": host or cur.get("host", ""), "ip": ip or cur.get("ip", "")})
                    c.execute("UPDATE probes SET inst = ? WHERE key = ?", (json.dumps(cur), key))
                return None
            dup = _json_obj(row[1])
            if dup.get("id") != inst:
                dup = {"id": inst, "host": host, "ip": ip or "", "first": now, "notified": 0}
            dup.update({"last": now, "host": host or dup.get("host", ""), "ip": ip or dup.get("ip", "")})
            ora = now - float(dup.get("notified") or 0) >= 12 * 3600      # all'utente ogni 12 ore
            if ora:
                dup["notified"] = now
            c.execute("UPDATE probes SET dup = ? WHERE key = ?", (json.dumps(dup), key))
        return {"inst": cur, "dup": dup, "notify": ora}

    def instance_info(self, keys, now=None):
        """{chiave: {"inst", "dup"}} per le sonde con un secondo dispositivo attivo (ultimi 30 minuti)."""
        now = now or time.time()
        out = {}
        if not keys:
            return out
        with self.db._conn() as c:
            for key, inst, dup in c.execute(
                    f"SELECT key, inst, dup FROM probes WHERE dup IS NOT NULL AND key IN ({','.join('?' * len(keys))})",
                    list(keys)):
                d = _json_obj(dup)
                if d.get("id") and now - float(d.get("last") or 0) < self.DUP_SHOW:
                    out[key] = {"inst": _json_obj(inst), "dup": d}
        return out

    def instance_switch(self, key):
        """Il secondo dispositivo diventa il titolare (sostituzione della sonda). False se non c'è."""
        import json
        with self.db._conn() as c:
            row = c.execute("SELECT dup FROM probes WHERE key = ?", (key,)).fetchone()
            d = _json_obj(row[0]) if row else {}
            if not d.get("id"):
                return False
            c.execute("UPDATE probes SET inst = ?, dup = NULL WHERE key = ?",
                      (json.dumps({"id": d["id"], "host": d.get("host", ""), "ip": d.get("ip", ""),
                                   "since": time.time()}), key))
        return True

    def set_name(self, key, name):
        with self.db._conn() as c:
            c.execute("UPDATE probes SET name = ? WHERE key = ?", (name, key))

    def name_of(self, key):
        with self.db._conn() as c:
            row = c.execute("SELECT name FROM probes WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def owner_of(self, key):
        with self.db._conn() as c:
            row = c.execute("SELECT owner FROM probes WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    # --- pausa: la sonda resta monitorata e i dati si salvano, ma tace -----------------
    def set_paused(self, key, until=None, note=""):
        """Mette in pausa la sonda. until = momento in cui riprende da sola (None = finché non
        la riprendi a mano)."""
        with self.db._conn() as c:
            c.execute("UPDATE probes SET paused = 1, paused_until = ?, paused_note = ? WHERE key = ?",
                      (until, (note or "").strip() or None, key))

    def resume(self, key):
        with self.db._conn() as c:
            c.execute("UPDATE probes SET paused = 0, paused_until = NULL, paused_note = NULL "
                      "WHERE key = ?", (key,))

    def paused_keys(self, now=None) -> set:
        """Le sonde in pausa adesso. Una riga con la scadenza passata non conta."""
        now = now or time.time()
        with self.db._conn() as c:
            rows = c.execute("SELECT key, paused_until FROM probes WHERE paused = 1").fetchall()
        return {k for k, until in rows if until is None or until > now}

    def clear_expired_pauses(self, now=None) -> list:
        """Toglie la pausa alle sonde la cui scadenza è passata. Restituisce le loro chiavi."""
        now = now or time.time()
        with self.db._conn() as c:
            finite = [r[0] for r in c.execute(
                "SELECT key FROM probes WHERE paused = 1 AND paused_until IS NOT NULL "
                "AND paused_until <= ?", (now,)).fetchall()]
            if finite:
                c.execute("UPDATE probes SET paused = 0, paused_until = NULL, paused_note = NULL "
                          "WHERE paused = 1 AND paused_until IS NOT NULL AND paused_until <= ?", (now,))
        return finite

    # --- pausa di un singolo dispositivo ----------------------------------------------
    def pause_device(self, probe, device, until=None, note=""):
        with self.db._conn() as c:
            c.execute("INSERT INTO device_pauses (probe, device, until, note, created) VALUES (?,?,?,?,?) "
                      "ON CONFLICT(probe, device) DO UPDATE SET until = excluded.until, note = excluded.note",
                      (probe, device, until, (note or "").strip() or None, time.time()))

    def resume_device(self, probe, device):
        with self.db._conn() as c:
            c.execute("DELETE FROM device_pauses WHERE probe = ? AND device = ?", (probe, device))

    def device_pauses(self, probe, now=None) -> dict:
        """{nome: {"until", "note"}} dei dispositivi in pausa adesso su questa sonda."""
        now = now or time.time()
        with self.db._conn() as c:
            rows = c.execute("SELECT device, until, note FROM device_pauses WHERE probe = ?",
                             (probe,)).fetchall()
        return {d: {"until": u, "note": nota or ""} for d, u, nota in rows if u is None or u > now}

    def pauses_for(self, keys, now=None):
        """Pause di piu' sonde in una sola lettura: (pause delle sonde, pause dei dispositivi).

        La pagina di stato chiede lo stato di tutte le sue sonde a ogni aggiornamento: due letture
        per sonda erano due connessioni al database per sonda, a ogni giro e per ogni pagina aperta.
        Qui sono due interrogazioni in tutto, qualunque sia il numero di sonde."""
        now = now or time.time()
        keys = list(keys)
        if not keys:
            return {}, {}
        segni = ",".join("?" * len(keys))
        with self.db._conn() as c:
            sonde = c.execute(f"SELECT key, paused_until, paused_note FROM probes "
                              f"WHERE paused = 1 AND key IN ({segni})", keys).fetchall()
            disp = c.execute(f"SELECT probe, device, until, note FROM device_pauses "
                             f"WHERE probe IN ({segni})", keys).fetchall()
        attive = lambda until: until is None or until > now
        pause_sonde = {k: {"until": u, "note": nota or ""} for k, u, nota in sonde if attive(u)}
        pause_disp = {}
        for k, d, u, nota in disp:
            if attive(u):
                pause_disp.setdefault(k, {})[d] = {"until": u, "note": nota or ""}
        return pause_sonde, pause_disp

    def clear_expired_device_pauses(self, now=None) -> list:
        """Toglie le pause dei dispositivi scadute. Restituisce le sonde interessate."""
        now = now or time.time()
        with self.db._conn() as c:
            sonde = [r[0] for r in c.execute(
                "SELECT DISTINCT probe FROM device_pauses WHERE until IS NOT NULL AND until <= ?",
                (now,)).fetchall()]
            if sonde:
                c.execute("DELETE FROM device_pauses WHERE until IS NOT NULL AND until <= ?", (now,))
        return sonde

    def owned_keys(self) -> set:
        """Sonde collegate a un account (qualsiasi)."""
        with self.db._conn() as c:
            return {r[0] for r in c.execute("SELECT key FROM probes WHERE owner IS NOT NULL")}

    def owners(self) -> dict:
        """Proprietario di ogni sonda collegata a un account: chiave -> id dell'utente."""
        with self.db._conn() as c:
            return dict(c.execute("SELECT key, owner FROM probes WHERE owner IS NOT NULL").fetchall())

    def keys_of(self, owner) -> list[str]:
        with self.db._conn() as c:
            return [r[0] for r in c.execute("SELECT key FROM probes WHERE owner = ? ORDER BY created", (owner,))]

    def delete(self, key):
        with self.db._conn() as c:
            c.execute("DELETE FROM probes WHERE key = ?", (key,))

    def export_of(self, owner) -> list[dict]:
        """Sonde dell'utente con le loro pause, per «Scarica i miei dati» (senza l'impronta del token)."""
        with self.db._conn() as c:
            c.row_factory = sqlite3.Row
            probes = [dict(r) for r in c.execute(
                "SELECT key, name, created, paused, paused_until, paused_note FROM probes "
                "WHERE owner = ? ORDER BY created", (owner,))]
            for p in probes:
                p["device_pauses"] = [dict(r) for r in c.execute(
                    "SELECT device, until, note, created FROM device_pauses WHERE probe = ?", (p["key"],))]
        return probes


# ------------------------------------------------------------------ limite dei tentativi

class Throttle:
    """Blocca per qualche minuto una chiave (IP o email) dopo troppi tentativi falliti."""

    MAX_KEYS = 10_000          # oltre, le voci scadute vengono eliminate (memoria limitata)

    def __init__(self, max_fails=5, window=15 * 60):
        self.max_fails, self.window = max_fails, window
        self._fails: dict[str, list[float]] = {}
        # Tentativi ancora in corso (la verifica scrypt dura decine di ms). Contano come errori
        # finché non finiscono: senza, 200 richieste partite insieme passavano tutte il controllo
        # prima che il primo errore fosse registrato, e il tetto di 5 diventava di 200.
        self._busy: dict[str, int] = {}

    @staticmethod
    def _key(k: str) -> str:
        """Un indirizzo IPv6 conta per la sua rete /64: chi ne ha una ha miliardi di indirizzi."""
        head, sep, rest = k.partition("ip:")
        if head or not sep:
            return k
        ip, bar, tail = rest.partition("|")
        if ":" in ip:
            try:
                ip = str(ipaddress.ip_network(ip + "/64", strict=False).network_address) + "/64"
            except ValueError:
                pass
        return "ip:" + ip + bar + tail

    def _purge(self, now):
        self._fails = {k: v for k, v in self._fails.items() if v and now - v[-1] < self.window}

    def wait_seconds(self, *keys) -> int:
        now = time.time()
        worst = 0
        for k in map(self._key, keys):
            recent = [t for t in self._fails.get(k, []) if now - t < self.window]
            if recent:
                self._fails[k] = recent
            else:
                self._fails.pop(k, None)          # niente voci vuote: il dizionario non cresce
            if len(recent) + self._busy.get(k, 0) >= self.max_fails:
                # solo tentativi in corso: si riprova appena finiscono
                worst = max(worst, int(self.window - (now - recent[0])) + 1 if recent else 5)
        return worst

    def reserve(self, *keys):
        """Un tentativo comincia: conta finché non viene chiamato release."""
        for k in map(self._key, keys):
            self._busy[k] = self._busy.get(k, 0) + 1

    def release(self, *keys):
        for k in map(self._key, keys):
            n = self._busy.get(k, 0) - 1
            if n > 0:
                self._busy[k] = n
            else:
                self._busy.pop(k, None)

    def fail(self, *keys):
        now = time.time()
        if len(self._fails) > self.MAX_KEYS:
            self._purge(now)
        for k in map(self._key, keys):
            self._fails.setdefault(k, []).append(now)

    def success(self, *keys):
        for k in map(self._key, keys):
            self._fails.pop(k, None)
