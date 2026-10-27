"""Verifica in due passaggi per gli amministratori.

- App di autenticazione (TOTP, RFC 6238): codici di 6 cifre che cambiano ogni 30 secondi,
  compatibili con Google Authenticator, Microsoft Authenticator, Aegis, 1Password e simili.
- Codice via email (riserva): 6 cifre, valido 10 minuti, salvato solo come impronta.

Nessuna dipendenza obbligatoria: il QR code usa la libreria `segno` se installata, altrimenti
la pagina mostra solo la chiave da inserire a mano nell'app.
"""
__version__ = "1.1.20261026-104239"
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30                 # secondi di validità di ogni codice dell'app
DIGITS = 6
DRIFT = 1                 # accetta anche il codice precedente e il successivo (orologi non allineati)
ISSUER = "netmon"
MAIL_CODE_MINUTES = 10


def new_secret() -> str:
    """Chiave casuale di 160 bit in base32 (formato richiesto dalle app)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def totp(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def current_step(now=None) -> int:
    return int((now if now is not None else time.time()) // STEP)


def verify_totp(secret: str, code: str, last_step: int = -1, now=None):
    """Numero del passo accettato, oppure None. Un codice già usato (passo <= last_step) viene
    rifiutato: chi lo vede sullo schermo non può riutilizzarlo."""
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if len(code) != DIGITS or not secret:
        return None
    base = current_step(now)
    for step in range(base - DRIFT, base + DRIFT + 1):
        if step > (last_step or -1) and hmac.compare_digest(totp(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, account: str) -> str:
    label = quote(f"{ISSUER}:{account}", safe="")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def qr_svg(text: str):
    """QR code in SVG (stringa), oppure None se la libreria segno non è installata."""
    try:
        import io
        import segno
    except ImportError:
        return None
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=5, border=2, dark="#14212B",
                                     light="#FFFFFF", xmldecl=False, svgns=True, omitsize=True)
    return buf.getvalue().decode()


def group(secret: str) -> str:
    """Chiave a gruppi di 4 caratteri, più facile da copiare a mano."""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


def new_mail_code() -> str:
    return str(secrets.randbelow(10 ** DIGITS)).zfill(DIGITS)


def hash_mail_code(admin_id: int, code: str) -> str:
    code = "".join(ch for ch in str(code) if ch.isdigit())
    return hashlib.sha256(f"netmon-mfa:{admin_id}:{code}".encode()).hexdigest()


def mask_email(email: str) -> str:
    """m•••o@gmail.com: quanto basta per riconoscere la propria casella."""
    if not email or "@" not in email:
        return ""
    user, domain = email.split("@", 1)
    shown = user[0] + "•••" + (user[-1] if len(user) > 2 else "")
    return f"{shown}@{domain}"
