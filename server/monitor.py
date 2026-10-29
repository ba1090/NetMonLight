"""Logica di monitoraggio: tiene lo stato di sonde e dispositivi e decide quando generare alert.

Priorità di notifica, per singolo dispositivo (campo "prio" nello stato del dispositivo):

    alta      notifica dopo 1 solo ciclo fallito — per quello che non può aspettare
    normale   soglia della sonda (predefinita)
    bassa     N volte la soglia normale (×2, ×3…), configurabile per sonda in alerts["low_factor"]
    mai       nessuna notifica, né di caduta né di ripristino

"mai" non spegne il monitoraggio: il dispositivo continua a essere misurato e sulla pagina si vede
giù come gli altri. A tacere è solo la notifica — utile per quello che si vuole tenere d'occhio
senza esserne avvisati.

Nessuna dipendenza esterna: si può testare da sola.
"""
__version__ = "1.1.20261029-200000"
import time
from dataclasses import dataclass

# Priorità ammesse. L'assenza del campo vale "normale": lo stato salvato da una versione
# precedente resta valido senza conversioni.
PRIORITIES = ("alta", "normale", "bassa", "mai")
NORMAL_PRIORITY = "normale"
LOW_FACTOR_DEFAULT = 2          # priorità bassa: il doppio dei controlli della normale
LOW_FACTOR_MAX = 10
# Dopo un aggiornamento, un riavvio o comunque una ripartenza del programma della sonda: per
# questi secondi non si dice «in ritardo» né «non comunica». I primi cicli dopo l'avvio sono i più
# lenti (primo collegamento al FRITZ!Box, mappa mesh, elenco dei dispositivi), soprattutto su un
# Raspberry Pi Zero. Il silenzio si conta dall'ultimo report, quindi la finestra non nasconde mai
# più di questi 5 minuti.
RESTART_GRACE = 300


@dataclass
class Alert:
    title: str
    body: str
    critical: bool = False
    recovery: bool = False
    subject: str = ""  # nome del dispositivo o della sonda, evidenziato su Telegram
    key: str = ""      # chiave interna della sonda (proprietario/nome), per sapere a chi notificare
    kind: str = "dispositivi"   # categoria per i canali scelti dall'utente: dispositivi | sonde | ospiti


def label_of(key: str, p: dict) -> str:
    """Nome della sonda da mostrare: senza il proprietario che compare nella chiave interna."""
    return p.get("name") or key.split("/", 1)[-1]


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}min"
    if m:
        return f"{m}min"
    return f"{s}s"


class Monitor:
    def __init__(self, fail_threshold=3, heartbeat_factor=3.0, stale_factor=1.5,
                 default_interval=60, remind_minutes=60, state=None,
                 low_factor=LOW_FACTOR_DEFAULT):
        self.fail_threshold = fail_threshold
        self.heartbeat_factor = heartbeat_factor   # cicli persi prima dell'alert critico
        self.stale_factor = stale_factor           # cicli persi prima del giallo
        self.default_interval = default_interval   # usato se la sonda non comunica il suo intervallo
        self.remind_seconds = remind_minutes * 60
        self.low_factor = low_factor               # priorità bassa: quante volte la soglia normale
        self.state = state or {}

    def interval(self, p) -> float:
        """Intervallo di controllo dichiarato dalla sonda."""
        return p.get("interval") or self.default_interval

    def stale_after(self, p, now=None) -> float:
        """Secondi di silenzio prima del giallo: valore della sonda, altrimenti proporzionale."""
        return (p.get("stale_after") or self.interval(p) * self.stale_factor) + self.update_grace(p, now)

    def offline_after(self, p, now=None) -> float:
        return (p.get("offline_after") or self.interval(p) * self.heartbeat_factor) + self.update_grace(p, now)

    @staticmethod
    def slow_hardware(p) -> bool:
        """Sonda poco potente (Raspberry Pi Zero, un solo processore): riparte più lentamente."""
        s = p.get("system") or {}
        return "zero" in str(s.get("model") or "").lower() or (isinstance(s.get("cpus"), int) and s["cpus"] <= 1)

    @staticmethod
    def restart_reason(p, now=None):
        """"update" nei 5 minuti dopo un aggiornamento (o riavvio) chiesto alla sonda e completato,
        "restart" nei 5 minuti dopo una ripartenza qualsiasi del programma della sonda, altrimenti None."""
        now = now or time.time()
        c = p.get("command") or {}
        if (c.get("cmd") in ("update", "upgrade", "reboot") and c.get("state") == "done"
                and 0 <= now - float(c.get("done_at") or 0) < RESTART_GRACE):
            return "update"
        if 0 <= now - float(p.get("restart_at") or 0) < RESTART_GRACE:
            return "restart"
        return None

    def update_grace(self, p, now=None) -> float:
        """Durante un aggiornamento (o un riavvio) chiesto alla sonda: un ciclo in più prima di dirla in
        ritardo o irraggiungibile, due sull'hardware lento. La sonda si ferma per installare e ripartire,
        e su un Raspberry Pi Zero la ripartenza da sola può durare più di un ciclo. Dopo, per
        RESTART_GRACE secondi (vedi restart_reason), lo sconto copre i primi cicli lenti."""
        if self.restart_reason(p, now):
            return RESTART_GRACE
        c = p.get("command") or {}
        if c.get("cmd") not in ("update", "upgrade", "reboot") or c.get("state") not in ("pending", "running"):
            return 0
        now = now or time.time()
        if now - float(c.get("requested") or 0) > 3 * 3600:     # comando rimasto appeso: niente sconto
            return 0
        return self.interval(p) * (2 if self.slow_hardware(p) else 1)

    @staticmethod
    def priority_of(d) -> str:
        """Priorità di un dispositivo; senza il campo vale "normale"."""
        prio = (d or {}).get("prio")
        return prio if prio in PRIORITIES else NORMAL_PRIORITY

    def low_factor_of(self, p) -> int:
        """Quante volte la soglia normale aspetta un dispositivo a priorità bassa, per questa sonda.

        Le versioni precedenti salvavano un numero fisso di controlli (low_threshold): finché
        l'utente non sceglie di nuovo vale il multiplo più vicino per eccesso, almeno ×2."""
        alerts = p.get("alerts") or {}
        try:
            return min(LOW_FACTOR_MAX, max(2, int(alerts["low_factor"])))
        except (KeyError, TypeError, ValueError):
            pass
        try:
            base = int(p.get("fail_threshold") or self.fail_threshold)
            vecchio = int(alerts["low_threshold"])
            return min(LOW_FACTOR_MAX, max(2, -(-vecchio // max(1, base))))
        except (KeyError, TypeError, ValueError):
            return self.low_factor

    def low_threshold_of(self, p) -> int:
        """Controlli falliti prima di notificare un dispositivo a priorità bassa, per questa sonda."""
        return int(p.get("fail_threshold") or self.fail_threshold) * self.low_factor_of(p)

    def fails_needed(self, p, d=None) -> int:
        """Cicli falliti prima di considerare giù un dispositivo.

        Senza dispositivo è la soglia della sonda (quella di sempre). Con un dispositivo si tiene
        conto della sua priorità. La soglia "bassa" è un multiplo (almeno doppio) di quella normale:
        un dispositivo di poco conto non viene mai segnalato prima di uno importante.
        """
        base = int(p.get("fail_threshold") or self.fail_threshold)
        if d is None:
            return base
        prio = self.priority_of(d)
        if prio == "alta":
            return 1
        if prio == "bassa":
            return base * self.low_factor_of(p)
        return base                                 # "normale" e "mai" seguono la soglia della sonda

    def notifies(self, d) -> bool:
        """Se un dispositivo genera notifiche. "mai" resta monitorato, ma in silenzio."""
        return self.priority_of(d) != "mai"

    @staticmethod
    def _new_probe(now):
        return {"last_seen": now, "offline": False, "offline_since": None, "interval": None,
                "fail_threshold": None, "stale_after": None, "offline_after": None,
                "all_down": False, "all_down_since": None, "last_remind": now, "devices": {}}

    def process_report(self, probe: str, devices: dict, now: float,
                       interval=None, thresholds=None) -> list:
        """Elabora un report della sonda. devices = {nome: True/False}.

        thresholds: soglie decise dalla sonda {fail_threshold, stale, offline}.
        """
        alerts = []
        p = self.state.setdefault(probe, self._new_probe(now))
        key, probe = probe, label_of(probe, p)          # nei messaggi solo il nome della sonda
        if interval:
            p["interval"] = interval
        if thresholds:
            # chiavi distinte da "offline" (che indica se la sonda è muta)
            p["fail_threshold"] = thresholds["fail_threshold"]
            p["stale_after"] = thresholds["stale"]
            p["offline_after"] = thresholds["offline"]

        # La sonda era considerata offline: ora è tornata
        if p["offline"]:
            alerts.append(Alert(
                f"[OK] Sonda '{probe}' di nuovo online",
                f"La sonda '{probe}' ha ripreso a inviare dati dopo "
                f"{fmt_duration(now - p['offline_since'])} di silenzio.",
                critical=True, recovery=True, subject=probe, key=key, kind="sonde"))
            p["offline"] = False
            p["offline_since"] = None
        p["last_seen"] = now

        # Aggiorna i singoli dispositivi
        newly_down, newly_up = [], []
        for name, ok in devices.items():
            if name not in p["devices"]:
                d = p["devices"][name] = {"fails": 0, "down": False, "since": now}
                # priorità scelta prima che la sonda lo misurasse (appena aggiunto, o in pausa)
                kept = (p.get("prio_keep") or {}).pop(name, None)
                if kept in PRIORITIES and kept != NORMAL_PRIORITY:
                    d["prio"] = kept
            d = p["devices"][name]
            if ok:
                if d["down"] and self.notifies(d):
                    newly_up.append((name, now - d["since"]))
                if d["down"]:
                    d["down"] = False
                    d["since"] = now
                d["fails"] = 0
            else:
                d["fails"] += 1
                if not d["down"] and d["fails"] >= self.fails_needed(p, d):
                    d["down"] = True
                    d["since"] = now
                    newly_down.append(name)

        # Dispositivi rimossi dalla configurazione della sonda
        for name in list(p["devices"]):
            if name not in devices:
                del p["devices"][name]

        all_down = bool(p["devices"]) and all(d["down"] for d in p["devices"].values())

        if all_down and not p["all_down"]:
            p["all_down"] = True
            p["all_down_since"] = now
            p["last_remind"] = now
            alerts.append(Alert(
                f"[CRITICO] Nessun dispositivo risponde ({probe})",
                f"La sonda '{probe}' è attiva ma non risponde al ping "
                + ("l'unico dispositivo controllato." if len(p["devices"]) == 1
                   else f"nessuno dei {len(p['devices'])} dispositivi controllati.")
                + " Possibile guasto di switch, router o rete locale.",
                critical=True, subject=probe, key=key))
            return alerts  # evita di mandare anche gli alert singoli

        if not all_down and p["all_down"]:
            still_down = [n for n, d in p["devices"].items() if d["down"]]
            body = (f"Almeno un dispositivo risponde di nuovo dopo "
                    f"{fmt_duration(now - p['all_down_since'])}.")
            if still_down:
                body += " Ancora non raggiungibili: " + ", ".join(still_down) + "."
            alerts.append(Alert(f"[OK] La rete di '{probe}' risponde di nuovo", body,
                                critical=True, recovery=True, subject=probe, key=key))
            p["all_down"] = False
            p["all_down_since"] = None
            newly_up = []  # il ripristino generale riassume già la situazione

        for name in newly_down:
            d = p["devices"][name]
            if not self.notifies(d):
                continue                            # priorità "mai": giù sulla pagina, ma in silenzio
            prio = self.priority_of(d)
            cicli = self.fails_needed(p, d)
            nota = {"alta": " Dispositivo a priorità alta.",
                    "bassa": " Dispositivo a priorità bassa: segnalato con ritardo."}.get(prio, "")
            quanti = ("al primo controllo" if cicli == 1
                      else f"da {cicli} controlli consecutivi")
            alerts.append(Alert(
                f"[ALERT] {name} non risponde ({probe})",
                f"Il dispositivo '{name}' non risponde al ping {quanti}." + nota,
                subject=name, key=key))
        for name, dur in newly_up:
            alerts.append(Alert(
                f"[OK] {name} di nuovo raggiungibile ({probe})",
                f"Il dispositivo '{name}' risponde di nuovo dopo {fmt_duration(dur)}.",
                recovery=True, subject=name, key=key))
        return alerts

    def check(self, now: float) -> list:
        """Controllo periodico: sonde silenziose e promemoria per i problemi critici."""
        alerts = []
        for key, p in self.state.items():
            probe = label_of(key, p)
            if not p["offline"] and now - p["last_seen"] > self.offline_after(p, now):
                p["offline"] = True
                p["offline_since"] = p["last_seen"]
                p["last_remind"] = now
                alerts.append(Alert(
                    f"[CRITICO] La sonda '{probe}' non comunica",
                    f"Nessun dato dalla sonda '{probe}' da {fmt_duration(now - p['last_seen'])}. "
                    f"Possibile blackout, router spento o connessione internet assente.",
                    critical=True, subject=probe, key=key, kind="sonde"))
                continue

            if self.remind_seconds > 0 and (p["offline"] or p["all_down"]) \
                    and now - p["last_remind"] > self.remind_seconds:
                p["last_remind"] = now
                if p["offline"]:
                    what, since = "la sonda non comunica", p.get("offline_since")
                else:
                    what, since = "nessun dispositivo risponde", p.get("all_down_since")
                since = since or p["last_seen"]     # dato mancante (stato vecchio): non blocca le altre sonde
                alerts.append(Alert(
                    f"[CRITICO] Promemoria: problema ancora in corso ({probe})",
                    f"Per '{probe}' {what} da {fmt_duration(now - since)}.",
                    critical=True, subject=probe, key=key, kind="sonde" if p["offline"] else "dispositivi"))
        return alerts
