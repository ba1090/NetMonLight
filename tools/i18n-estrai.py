#!/usr/bin/env python3
"""Estrae i testi italiani da tradurre di pagina utente, notifiche e pagina locale della sonda.

Uso (dalla cartella netmon):
  python3 tools/i18n-estrai.py server            # testi della pagina utente e delle notifiche
  python3 tools/i18n-estrai.py probe             # testi della pagina locale della sonda
  python3 tools/i18n-estrai.py server --mancanti # solo quelli senza traduzione in server/i18n.py
  python3 tools/i18n-estrai.py admin             # pannello di amministrazione e avvisi agli amministratori

Un testo con parti variabili diventa un modello con segnaposto numerati: `${n} dispositivi`
diventa «{0} dispositivi», "Mappa letta " + quando + ", si aggiorna…" diventa «Mappa letta {0},
si aggiorna…». La pagina e il server traducono confrontando il testo mostrato con questi modelli,
quindi il codice non cambia: le chiavi sono il testo italiano così com'è.

Solo libreria standard. L'analisi del JavaScript è lessicale (stringhe, modelli `…`, concatenazioni
con +): basta per i testi, non è un parser completo.
"""
import ast
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORD = re.compile(r"[A-Za-zÀ-ÿ]{2,}")
ITALIAN_HINT = re.compile(r"[àèéìòù]|\b(il|lo|la|le|gli|di|da|in|con|per|non|una|uno|del|della|dei|delle|"
                          r"alla|alle|nel|nella|sono|è|che|si|ogni|tutti|tutte|ora|dopo|prima|ancora|"
                          r"sonda|sonde|dispositiv\w*|account|password|email|pagina|server|rete|avvis\w*)\b", re.I)
CODEISH = re.compile(r"^[#.\[]|^[a-z0-9_\-]+(\.[a-z0-9_\-]+)+$|^/api/|^https?://|^[a-z]+:[a-z]|=\"|^\w+\(|"
                     r"^[a-z][a-z0-9]*(-[a-z0-9]+)+$|^[a-z]+[A-Z]\w*$|^[A-Z_]{2,}$|^netmon\.|^\d")


# ------------------------------------------------------------------ JavaScript: analisi lessicale
class Tok:
    __slots__ = ("kind", "val", "parts")

    def __init__(self, kind, val, parts=None):
        self.kind, self.val, self.parts = kind, val, parts     # parts: modello `…` = [testo, expr-token, testo…]

    def __repr__(self):
        return f"{self.kind}:{self.val!r}"


PUNCT = sorted(["===", "!==", "**=", "...", "&&=", "||=", "??=", "=>", "==", "!=", "<=", ">=", "&&", "||", "??",
                "?.", "++", "--", "+=", "-=", "*=", "/=", "%=", "<<", ">>", ">>>"], key=len, reverse=True)
REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^") | {"return", "typeof", "case", "do", "else", "in", "of", "new",
                                           "delete", "void", "throw", "=>", "&&", "||", "??", "===", "!==",
                                           "==", "!=", "+=", "-="}


def js_tokens(src, i=0, stop_brace=False):
    """Token di `src` da `i`. Con stop_brace si ferma alla } che chiude un ${…} (per i modelli)."""
    out, depth = [], 0
    n = len(src)
    while i < n:
        c = src[i]
        if c in " \t\r\n":
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c in "\"'":
            j, buf = i + 1, []
            while j < n and src[j] != c:
                if src[j] == "\\":
                    buf.append(_unescape(src[j:j + 2], src, j))
                    j += 2 if src[j + 1] != "u" else 6
                    continue
                buf.append(src[j])
                j += 1
            out.append(Tok("str", "".join(buf)))
            i = j + 1
            continue
        if c == "`":
            parts, j, buf = [], i + 1, []
            while j < n and src[j] != "`":
                if src[j] == "\\":
                    buf.append(_unescape(src[j:j + 2], src, j))
                    j += 2
                    continue
                if src.startswith("${", j):
                    parts.append("".join(buf))
                    buf = []
                    sub, j = js_tokens(src, j + 2, stop_brace=True)
                    parts.append(sub)
                    continue
                buf.append(src[j])
                j += 1
            parts.append("".join(buf))
            out.append(Tok("tpl", None, parts))
            i = j + 1
            continue
        if c == "/" and _regex_allowed(out):
            j, cls = i + 1, False
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    cls = True
                elif src[j] == "]":
                    cls = False
                elif src[j] == "/" and not cls:
                    break
                elif src[j] == "\n":
                    break
                j += 1
            j += 1
            while j < n and src[j].isalpha():
                j += 1
            out.append(Tok("re", src[i:j]))
            i = j
            continue
        if c.isalpha() or c in "_$":
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            out.append(Tok("id", src[i:j]))
            i = j
            continue
        if c.isdigit():
            j = i
            while j < n and (src[j].isalnum() or src[j] in "._"):
                j += 1
            out.append(Tok("num", src[i:j]))
            i = j
            continue
        if stop_brace:
            if c == "{":
                depth += 1
            elif c == "}":
                if depth == 0:
                    return out, i + 1
                depth -= 1
        p = next((p for p in PUNCT if src.startswith(p, i)), c)
        out.append(Tok("p", p))
        i += len(p)
    return (out, i) if stop_brace else out


def _unescape(two, src, j):
    m = {"\\n": "\n", "\\t": "\t", "\\\\": "\\", "\\'": "'", '\\"': '"', "\\`": "`", "\\$": "$"}
    if two in m:
        return m[two]
    if two == "\\u":
        try:
            return chr(int(src[j + 2:j + 6], 16))
        except ValueError:
            return ""
    return two[1:]


def _regex_allowed(out):
    if not out:
        return True
    t = out[-1]
    if t.kind == "p":
        return t.val in REGEX_AFTER and t.val not in (")", "]", "}")
    return t.kind == "id" and t.val in REGEX_AFTER


def js_texts(tokens, found):
    """Modelli dei testi: stringhe e modelli `…`, unendo le concatenazioni con + in un solo modello."""
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.kind == "tpl":
            for part in t.parts[1::2]:                      # dentro ${…}: altri testi
                js_texts(part, found)
        if t.kind in ("str", "tpl"):
            # catena: operando (+ operando)* che contiene almeno una stringa
            start = _chain_start(tokens, i)
            pieces, j = _chain(tokens, start)
            if j > i:
                add_pattern(found, pieces)
        i += 1                                              # anche i testi dentro gli operandi della catena


def _chain_start(tokens, i):
    """Inizio della catena di + che contiene il token i (risale gli operandi precedenti)."""
    k = i
    while True:
        b = _operand_back(tokens, k - 1)
        if b is None or b < 1 or not (tokens[b - 1].kind == "p" and tokens[b - 1].val == "+"):
            return k
        k = b - 1
        b2 = _operand_back(tokens, k - 1)
        if b2 is None:
            return k + 1
        k = b2


def _operand_back(tokens, k):
    """Indice di inizio dell'operando che finisce in k (semplice: id/num/str con . () [])."""
    if k < 0:
        return None
    depth = 0
    j = k
    while j >= 0:
        t = tokens[j]
        if t.kind == "p" and t.val in (")", "]"):
            depth += 1
        elif t.kind == "p" and t.val in ("(", "["):
            if depth == 0:
                return j + 1
            depth -= 1
        elif depth == 0:
            if t.kind == "p" and t.val not in (".", "?."):
                return j + 1
        j -= 1
    return 0


def _operand(tokens, j):
    """Fine (esclusa) dell'operando che inizia in j."""
    depth, k = 0, j
    while k < len(tokens):
        t = tokens[k]
        if t.kind == "p" and t.val in ("(", "["):
            depth += 1
        elif t.kind == "p" and t.val in (")", "]"):
            if depth == 0:
                return k
            depth -= 1
        elif depth == 0 and t.kind == "p" and t.val not in (".", "?.", "!"):
            return k
        k += 1
    return k


def _chain(tokens, j):
    """[pezzi] di una catena di + da j: testo per le stringhe, None per gli operandi variabili."""
    pieces, k, first = [], j, True
    while k < len(tokens):
        if not first:
            if not (tokens[k].kind == "p" and tokens[k].val == "+"):
                break
            k += 1
        first = False
        end = _operand(tokens, k)
        if end == k:
            break
        if end - k == 1 and tokens[k].kind == "str":
            pieces.append(tokens[k].val)
        elif end - k == 1 and tokens[k].kind == "tpl":
            t = tokens[k]
            for idx, part in enumerate(t.parts):
                pieces.append(part if idx % 2 == 0 else None)
        else:
            pieces.append(None)
        k = end
    if not any(isinstance(p, str) and WORD.search(p) for p in pieces):
        return pieces, j
    return pieces, k


def add_pattern(found, pieces):
    """Da [testo, None, testo…] al modello «testo {0} testo»; scarta ciò che non è testo per l'utente."""
    out, n = [], 0
    for p in pieces:
        if p is None:
            if out and out[-1].endswith("}") and re.search(r"\{\d+\}$", out[-1]):
                continue                                    # due variabili attaccate: un solo segnaposto
            out.append("{%d}" % n)
            n += 1
        elif p:
            out.append(p.replace("{", "{{").replace("}", "}}"))
    text = "".join(out)
    for line in split_units(text):
        keep(found, line)


def split_units(text):
    """Un testo su più righe si traduce riga per riga (come lo mostrano email e notifiche)."""
    return [x for x in re.split(r"\n+", text) if x.strip()]


SQL = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|PRAGMA|ALTER|DROP|BEGIN|COMMIT|ROLLBACK|WITH)\b")
CODE_WORDS = set()          # classi, id e nomi di campo della pagina: parole che non sono testo


def code_words(src):
    """Parole usate come codice nella pagina: classi e id HTML, selettori CSS, chiavi degli oggetti."""
    words = set()
    for m in re.finditer(r'(?:class|id|for|name|data-[\w-]+)="([^"]*)"', src):
        words.update(re.split(r"[\s-]+", m.group(1)))
    for m in re.finditer(r"[.#]([a-z][\w-]*)", src):
        words.update(re.split(r"-", m.group(1)))
    for m in re.finditer(r"\b([a-z_][a-z0-9_]*)\s*:", src):
        words.add(m.group(1))
    return {w for w in words if w}


TAG = re.compile(r"^\[([A-ZÀ-Ù' ]{2,20})\]\s*(.*)$")


def keep(found, text, unit=False):
    t = " ".join(text.split())
    m = TAG.match(t)
    if m and not unit:                              # «[CRITICO] testo»: etichetta e testo a parte
        found.setdefault("[" + m.group(1) + "]", None)
        if m.group(2):
            keep(found, m.group(2))
        return
    if unit:                                        # blocco con formattazione: si tiene intero
        if WORD.search(re.sub(r"<[^>]+>", "", t)):
            found.setdefault(t, None)
        return
    literal = re.sub(r"\{\d+\}", "", t)
    if len(WORD.findall(literal)) == 0 or CODEISH.search(t.strip()) or SQL.search(t):
        return
    if "_" in t and " " not in t:                   # nome di campo o di variabile
        return
    if re.search(r"\[[^\]]*=|^[\w.#\[\]=\-]+\[|:\w+\(", t):  # selettori CSS
        return
    words = WORD.findall(literal)
    if not ITALIAN_HINT.search(literal) and not any(ch.isupper() for ch in literal) \
            and all(w in CODE_WORDS or w in ENGLISH_CODE for w in words) \
            and not any(w in ITALIAN_WORDS for w in words):
        return
    letters = sum(ch.isalpha() for ch in literal)
    if letters < 3:
        return
    if len(WORD.findall(literal)) == 1 and not (ITALIAN_HINT.search(literal) or literal[:1].isupper()
                                                 or literal.strip().lower() in ITALIAN_WORDS):
        return
    found.setdefault(t, None)


ENGLISH_CODE = set("""ok bad warn off on up down main wifi none all some auto get post put true false null
undefined button submit text number checkbox radio hidden open close click change input keydown load
error info sel line area band loss hline grid cursor rate count stack name host value probe device
range start end box kind key label type mode role id mesh fiber now at""".split())

# parole singole minuscole che compaiono come testo (stati, unità, etichette brevi)
ITALIAN_WORDS = set("""connesso disconnesso cavo principale ospiti adesso mai alta normale bassa sì no
nessuna nessuno tutte tutti sconosciuto attivo attiva spento spenta acceso accesa invitato bloccato
oggi ieri minuti minuto ore ora giorni giorno secondi secondo settimane mesi fa fino lento debole
regolare ottimo buono discreto trasmissione completi controllo controlli clienti errore nome sezione
aggiunta attivata tolta avviato completato""".split())


# ------------------------------------------------------------------ HTML: testi e attributi
class HtmlTexts(HTMLParser):
    def __init__(self, found):
        super().__init__(convert_charrefs=True)
        self.found, self.skip = found, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        for k, v in attrs:
            if k in ("title", "placeholder", "aria-label", "alt", "value") and v:
                keep(self.found, v)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            keep(self.found, data)


def html_units(html, found):
    """Elementi con solo formattazione dentro (<strong>, <em>…): si traducono interi, tag compresi."""
    for m in re.finditer(r"<(p|li|label|legend|summary|small|dd|td|span|h[1-4])(\s[^>]*)?>((?:(?!<\1[\s>]).)*?)</\1>", html, re.S):
        inner = m.group(3)
        if "<" not in inner or re.search(r"<(?!/?(strong|em|b|i|code|br|a|kbd)\b)", inner):
            continue
        if re.search(r"<(input|select|textarea|button|div|p|ul|ol)\b", inner) or re.search(r"\sid=", inner):
            continue                                # con elementi usati dal codice: si traduce a pezzi
        keep(found, inner, unit=True)


# ------------------------------------------------------------------ Python: stringhe e f-string
SKIP_CALLS = {"log", "logging", "print", "re", "json", "os", "Path", "sqlite3"}


def py_texts(path, found, skip_funcs=lambda name: False, only_funcs=None, skip_names=()):
    tree = ast.parse(Path(path).read_text())
    parents = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            parents[ch] = node

    def owner(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return None

    def in_log(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.Call):
                f = node.func
                base = f.value if isinstance(f, ast.Attribute) else f
                name = base.id if isinstance(base, ast.Name) else ""
                if name in SKIP_CALLS:
                    return True
        return False

    def in_skipped(node):
        # valori di tabelle che non sono testi da tradurre (es. le traduzioni stesse)
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in skip_names
                                                    for t in node.targets):
                return True
        return False

    def is_doc(node):
        p = parents.get(node)
        return isinstance(p, ast.Expr)

    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and isinstance(node.value, str)
                                               and not isinstance(parents.get(node), ast.JoinedStr)):
            if is_doc(node) or in_log(node) or in_skipped(node):
                continue
            fn = owner(node)
            if fn is not None and skip_funcs(fn.name):
                continue
            if only_funcs is not None and (fn is None or fn.name not in only_funcs):
                continue
            if isinstance(node, ast.Constant):
                if len(node.value) > 3000:              # le pagine HTML: a parte
                    continue
                pieces = [node.value]
            else:
                pieces = [v.value if isinstance(v, ast.Constant) else None for v in node.values]
            add_pattern(found, pieces)


def server_texts():
    app = ROOT / "server" / "app.py"
    src = app.read_text()
    found = {}
    a = src.index("STATUS_PAGE = r'''")
    b = src.index("'''", a + 20)
    page = src[a + len("STATUS_PAGE = r'''"):b]
    CODE_WORDS.update(code_words(page))
    html_part = page[:page.index("<script>")] if "<script>" in page else page
    html_part = re.sub(r"<style>.*?</style>", "", html_part, flags=re.S)
    HtmlTexts(found).feed(html_part)
    html_units(html_part, found)
    for script in re.findall(r"<script>(.*?)</script>", page, re.S):
        js_texts(js_tokens(script), found)
    # Python: tutto tranne il pannello di amministrazione
    admin = re.compile(r"^(admin_|api_admin|_admin|sched_|_start_|_poll_|_run_sched|check_admin|vm_|package_)")
    py_texts(app, found, skip_funcs=lambda n: bool(admin.match(n)))
    for name in ("notifier.py", "monitor.py"):
        py_texts(ROOT / "server" / name, found)
    # avvisi di manutenzione agli utenti (in funzioni dello scheduler)
    py_texts(app, found, only_funcs={"sched_user_text", "sched_text"})
    return found


def admin_texts():
    """Pannello di amministrazione (ADMIN_TEMPLATE) e messaggi del server che vede o riceve
    l'amministratore (errori delle API, avvisi amministrativi)."""
    app = ROOT / "server" / "app.py"
    src = app.read_text()
    found = {}
    a = src.index("ADMIN_TEMPLATE = r'''")
    b = src.index("'''", a + 24)
    page = src[a + len("ADMIN_TEMPLATE = r'''"):b]
    CODE_WORDS.update(code_words(page))
    html_part = re.sub(r"<script>.*?</script>|<style>.*?</style>", "", page, flags=re.S)
    HtmlTexts(found).feed(html_part)
    html_units(html_part, found)
    for script in re.findall(r"<script>(.*?)</script>", page, re.S):
        js_texts(js_tokens(script), found)
    py_texts(app, found)
    for name in ("auth.py", "vmops.py", "pkgcheck.py", "notifier.py", "monitor.py"):
        py_texts(ROOT / "server" / name, found)
    return found


def probe_texts():
    cw = ROOT / "probe" / "config_web.py"
    src = cw.read_text()
    found = {}
    CODE_WORDS.update(code_words(src))
    for m in re.finditer(r"PAGE\w*\s*=\s*r?(?:'''(.*?)'''|\"\"\"(.*?)\"\"\")", src, re.S):
        page = m.group(1) or m.group(2)
        html_part = re.sub(r"<script>.*?</script>|<style>.*?</style>", "", page, flags=re.S)
        HtmlTexts(found).feed(html_part)
        html_units(html_part, found)
        for script in re.findall(r"<script>(.*?)</script>", page, re.S):
            js_texts(js_tokens(script), found)
    py_texts(cw, found, skip_names={"TRANSLATIONS", "FONTS"})
    return found


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "server"
    texts = server_texts() if which == "server" else admin_texts() if which == "admin" else probe_texts()
    if "--mancanti" in sys.argv:
        sys.path.insert(0, str(ROOT / ("probe" if which == "probe" else "server")))
        mod = __import__("config_web" if which == "probe" else "i18n")
        have = ({l: mod.table(l, admin=True) for l in ("en", "de", "fr")} if which == "admin"
                else getattr(mod, "TRANSLATIONS", {}))
        texts = {k: v for k, v in texts.items() if any(k not in have.get(l, {}) for l in ("en", "de", "fr"))}
    json.dump(sorted(texts), sys.stdout, ensure_ascii=False, indent=0)
    print(f"\n{len(texts)} testi", file=sys.stderr)
