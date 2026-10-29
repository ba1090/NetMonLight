"""Invio notifiche. Ogni canale si attiva solo se configurato nel file .env.

- Email: tutti gli alert (quelli critici con priorità alta), all'email dell'utente. Il file .env
  contiene solo l'account che spedisce (SMTP_*), non i destinatari.
- Telegram: tutti gli alert; quelli normali arrivano silenziosi, quelli critici con suono. Il .env
  contiene solo il token del bot; il chat ID lo indica ogni utente.
- ntfy: priorità 5 (massima, suona anche in "non disturbare" se configurato) per i critici; il
  topic lo indica ogni utente.
"""
__version__ = "1.1.20261029-180000"
import html
import http.client
import ipaddress
import json
import logging
import os
import re
import smtplib
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import brand
import i18n

log = logging.getLogger("notifier")


# Invio email scelto dal pannello di amministrazione (Server › Invio email): se c'è, vale al posto
# delle righe SMTP_* del .env. app.py lo riempie all'avvio e quando l'amministratore lo cambia.
SMTP_PANEL = {}


def smtp_value(name, default=""):
    """Valore SMTP_* in uso: quello del pannello se configurato, altrimenti quello del .env."""
    if SMTP_PANEL.get("SMTP_HOST"):
        return str(SMTP_PANEL.get(name) or default).strip()
    return os.getenv(name, default).strip()


def _env(name, default=""):
    if name.startswith("SMTP_"):
        return smtp_value(name, default)
    return os.getenv(name, default).strip()


_URL_RE = re.compile(r"(https?://[^\s<>\"]*[^\s<>\".,;:!?)])")    # senza la punteggiatura finale


LOGO_CID = "netmon-logo@netmon"


def _html_body(title, body, action=None, lang="it"):
    """Versione HTML del messaggio, ricavata dal testo: paragrafi, righe rientrate come blocchi
    evidenziati, link cliccabili ed eventuale pulsante (action = (testo, url))."""
    parts, placed = [], False
    for block in body.strip().split("\n\n"):
        lines = block.split("\n")
        if action and not placed and block.strip() == action[1]:          # il link del pulsante: pulsante al suo posto
            parts.append('<p style="margin:4px 0 8px"><a href="' + html.escape(action[1], quote=True) + '" style="display:inline-block;'
                         'background:#174A72;color:#ffffff;text-decoration:none;padding:11px 22px;border-radius:9999px;'
                         'font-weight:600">' + html.escape(action[0]) + "</a></p>"
                         '<p style="margin:0 0 16px;color:#5A6878;font-size:12px;word-break:break-all">'
                         + html.escape(action[1]) + "</p>")
            placed = True
            continue
        if all(line.startswith("    ") for line in lines):             # codice, link o dati: riquadro
            inner = "<br>".join(html.escape(line.strip()) for line in lines)
            inner = _URL_RE.sub(r'<a href="\1" style="color:#174A72">\1</a>', inner)
            parts.append('<p style="margin:0 0 16px;padding:10px 14px;background:#E2ECF5;border-radius:6px;'
                         'font-family:Menlo,Consolas,monospace;font-size:14px;word-break:break-all">' + inner + "</p>")
        else:
            inner = "<br>".join(html.escape(line) for line in lines)
            inner = _URL_RE.sub(r'<a href="\1" style="color:#174A72">\1</a>', inner)
            parts.append('<p style="margin:0 0 16px">' + inner + "</p>")
    button = ""
    if action and not placed:                                              # link non presente nel testo: pulsante in cima
        label, url = action
        button = ('<p style="margin:4px 0 22px"><a href="' + html.escape(url, quote=True) + '" style="display:inline-block;'
                  'background:#174A72;color:#ffffff;text-decoration:none;padding:11px 22px;border-radius:9999px;'
                  'font-weight:600">' + html.escape(label) + "</a></p>")
    return ('<!doctype html><html lang="' + lang + '"><head><meta charset="utf-8"><title>' + html.escape(title) + "</title></head>"
            '<body style="margin:0;padding:24px;background:#F0F4F8;color:#222222;font:15px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif">'
            '<div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #D5DFE9;border-radius:10px;padding:24px 26px">'
            # logo: immagine allegata al messaggio (cid), l'unico modo mostrato da Gmail e Outlook
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 18px;border-collapse:collapse"><tr>'
            '<td style="padding:0 10px 0 0;vertical-align:middle"><img src="cid:' + LOGO_CID + '" width="40" height="40" alt="netmon" '
            'style="display:block;border:0;width:40px;height:40px;border-radius:9px"></td>'
            '<td style="vertical-align:middle;font-weight:600;font-size:18px;color:#222222;letter-spacing:-.2px">netmon</td>'
            '</tr></table>'
            '<p style="margin:0 0 14px;font-weight:600;font-size:17px">' + html.escape(title) + "</p>"
            + button + "".join(parts) +
            '<p style="margin:18px 0 0;color:#5A6878;font-size:12px">'
            + html.escape(i18n.tr(lang, "Messaggio automatico di netmon, il monitoraggio della rete.")) + '</p>'
            "</div></body></html>")


def send_email(title, body, critical, to=None, action=None, lang="it"):
    """Email in testo e HTML, con mittente con nome, data, identificativo e lingua: le intestazioni
    complete aiutano i filtri antispam. action = (testo del pulsante, link) facoltativo."""
    host = _env("SMTP_HOST")
    if not host or not to:
        return False                              # niente server di posta nel .env: non inviata
    sender = _env("SMTP_FROM") or _env("SMTP_USER")
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = formataddr((_env("SMTP_FROM_NAME", "netmon"), sender))
    msg["To"] = to
    msg["Reply-To"] = sender
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    msg["Auto-Submitted"] = "auto-generated"              # messaggio automatico (niente risposte automatiche)
    if critical:
        msg["X-Priority"] = "1"
        msg["Importance"] = "high"
    msg.set_content(body)
    msg.add_alternative(_html_body(title, body, action, lang), subtype="html")
    # il logo viaggia dentro il messaggio, accanto alla parte HTML (multipart/related)
    msg.get_payload()[1].add_related(brand.LOGO_EMAIL_PNG, maintype="image", subtype="png",
                                     cid=f"<{LOGO_CID}>", filename="netmon.png", disposition="inline")
    msg["Content-Language"] = lang                        # dopo il contenuto (set_content lo azzererebbe)

    port = int(_env("SMTP_PORT", "587"))
    ctx = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, context=ctx, timeout=20)
    else:
        server = smtplib.SMTP(host, port, timeout=20)
        server.starttls(context=ctx)
    with server:
        if _env("SMTP_USER"):
            _login(server, _env("SMTP_USER"), _env("SMTP_PASSWORD"))
        server.send_message(msg)


def _login(server, user, password):
    """Accesso al server di posta con UN solo tentativo. smtplib.login, se il primo metodo viene
    rifiutato, ne prova un altro: Gmail a quel punto chiude la connessione e l'errore vero (535,
    password non accettata) si perde dietro un «Connection unexpectedly closed»."""
    server.ehlo_or_helo_if_needed()
    if "PLAIN" in server.esmtp_features.get("auth", "").upper().split():
        server.user, server.password = user, password
        server.auth("PLAIN", server.auth_plain)
    else:
        server.login(user, password)


def _telegram_html(title, body, subject):
    """Titolo e nome del dispositivo in grassetto (formato HTML di Telegram)."""
    t, b = html.escape(title, quote=False), html.escape(body, quote=False)
    if subject:
        s = html.escape(subject, quote=False)
        b = b.replace(f"'{s}'", f"<b>{s}</b>")
        t = t.replace(f"'{s}'", s)
    return f"<b>{t}</b>\n\n{b}"


def send_telegram(title, body, critical, subject="", chat_id=None):
    token = _env("TELEGRAM_BOT_TOKEN")           # il bot da cui partono i messaggi; il chat ID è dell'utente
    if not (token and chat_id):
        return False                              # niente bot nel .env di questa macchina: non inviato
    data = json.dumps({
        "chat_id": chat_id,
        "text": _telegram_html(title, body, subject),
        "parse_mode": "HTML",
        "disable_notification": not critical,
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except urllib.error.HTTPError as exc:
        # nel registro il motivo scritto da Telegram (es. «chat not found», «bot was blocked by the
        # user»), non solo «HTTP Error 400»: è quello che serve per capire perché non arriva
        try:
            why = json.loads(exc.read(2000) or b"{}").get("description") or ""
        except (ValueError, OSError):
            why = ""
        raise OSError(f"Telegram ha risposto {exc.code}{': ' + why if why else ''}") from None


# Nome del bot (@username), letto da Telegram con il token del .env: così la pagina può dire agli
# utenti a quale bot scrivere senza che l'amministratore lo debba scrivere da qualche parte.
# In memoria: un'ora se la risposta è buona, 5 minuti se Telegram non risponde.
_bot_name = {"token": None, "name": "", "until": 0.0}


def telegram_bot_name():
    import time
    token = _env("TELEGRAM_BOT_TOKEN")
    if not token:
        return ""
    now = time.monotonic()
    if _bot_name["token"] == token and now < _bot_name["until"]:
        return _bot_name["name"]
    name = ""
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=8) as r:
            res = json.loads(r.read().decode("utf-8"))
        cand = str(((res or {}).get("result") or {}).get("username") or "")
        if re.fullmatch(r"[A-Za-z0-9_]{5,64}", cand):
            name = cand
    except Exception as exc:  # noqa: BLE001
        log.warning("Nome del bot Telegram non letto: %s", exc)
    _bot_name.update(token=token, name=name, until=now + (3600 if name else 300))
    return name


class UnsafeUrl(ValueError):
    """Indirizzo non accettato per le notifiche (non https o verso la rete interna)."""


def check_public_https(url):
    """Controlla che l'indirizzo sia https e che il nome porti solo a indirizzi pubblici di
    Internet. Restituisce (parti dell'URL, IP da usare). Così un utente non può far contattare
    al server servizi interni della VM o del provider (per esempio 127.0.0.1 o 169.254.169.254)."""
    u = urlsplit((url or "").strip())
    try:
        port = u.port or 443
    except ValueError:
        raise UnsafeUrl("porta non valida") from None
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        raise UnsafeUrl("serve un indirizzo https:// senza credenziali")
    try:
        infos = socket.getaddrinfo(u.hostname, port, proto=socket.IPPROTO_TCP)
    except OSError:
        raise UnsafeUrl(f"il nome {u.hostname} non esiste o il DNS non risponde") from None
    ips = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise UnsafeUrl("l'indirizzo porta alla rete interna")
        ips.append(str(ip))
    if not ips:
        raise UnsafeUrl(f"il nome {u.hostname} non ha indirizzi")
    return u, port, ips[0]


class _PinnedHTTPS(http.client.HTTPSConnection):
    """Connessione HTTPS verso l'IP già controllato (il nome non viene risolto una seconda
    volta), con verifica del certificato sul nome originale."""

    def __init__(self, host, port, ip, **kw):
        super().__init__(host, port, **kw)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def send_ntfy(title, body, critical, recovery, url=None):
    # url: il topic dell'utente, es. https://ntfy.sh/il-tuo-topic-segreto
    if not url:
        return
    u, port, ip = check_public_https(url)
    headers = {
        "Title": title.encode("latin-1", "ignore").decode("latin-1"),
        "Priority": "5" if critical and not recovery else "3",
        "Tags": "white_check_mark" if recovery else ("rotating_light" if critical else "warning"),
        "Content-Type": "text/plain; charset=utf-8",
    }
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    conn = _PinnedHTTPS(u.hostname, port, ip, timeout=15, context=ssl.create_default_context())
    try:
        conn.request("POST", path, body=body.encode(), headers=headers)
        resp = conn.getresponse()
        resp.read(10_000)                       # i redirect NON vengono seguiti
        if resp.status >= 300:
            raise OSError(f"ntfy ha risposto {resp.status} {resp.reason}")
    finally:
        conn.close()


def allowed(routes, kind, channel):
    """Il canale è scelto per questo tipo di avviso? Tipo non impostato = tutti i canali."""
    chosen = (routes or {}).get(kind)
    return chosen is None or channel in chosen


def notify(title, body, critical=False, recovery=False, subject="", to=None, kind="dispositivi"):
    """Invia l'alert sui canali dell'utente: {"email", "telegram_chat", "ntfy_url", "routes"} (vuoti =
    saltati; routes = canali scelti per tipo di avviso). Un canale che fallisce non blocca gli altri."""
    to = dict(to or {})
    lang = to.get("lang") or "it"
    if lang != "it":                    # nella lingua del destinatario (i nomi dei dispositivi restano)
        title, body = i18n.tr(lang, title), i18n.tr_text(lang, body)
    for ch, field in (("email", "email"), ("telegram", "telegram_chat"), ("ntfy", "ntfy_url")):
        if not allowed(to.get("routes"), kind, ch):
            to[field] = ""
    channels = []
    if to.get("email"):
        channels.append(("email", send_email, (title, body, critical, to["email"], None, lang)))
    if to.get("telegram_chat"):
        channels.append(("telegram", send_telegram, (title, body, critical, subject, to["telegram_chat"])))
    if to.get("ntfy_url"):
        channels.append(("ntfy", send_ntfy, (title, body, critical, recovery, to["ntfy_url"])))
    if not channels:
        log.info("Avviso «%s» non inviato: nessun canale attivo per questo tipo (%s)", title[:80], kind)
    for name, fn, args in channels:
        try:
            if fn(*args) is False:
                log.warning("Avviso «%s» non inviato via %s: manca la configurazione su questa macchina "
                            "(%s)", title[:80], name, "Invio email nel pannello o SMTP_HOST nel .env"
                            if name == "email" else "TELEGRAM_BOT_TOKEN")
            else:
                log.info("Avviso «%s» inviato via %s", title[:80], name)
        except Exception as exc:  # noqa: BLE001
            log.error("Invio %s fallito: %s", name, exc)
