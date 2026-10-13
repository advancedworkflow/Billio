"""
Extraction des textes d'interface (français) : gabarits Django, JavaScript, vues Python.

L'interface n'utilise pas {% translate %} : les textes sont écrits en dur. Ce module les
recense tels qu'ils apparaissent dans la page (un nœud texte = une entrée), en remplaçant
les parties variables ({{ … }}, ${…}, {expr} des f-strings) par « {} ». Le catalogue
(apps/translations/catalog/) associe ensuite chaque texte à sa traduction.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

PH = '\x00'  # partie variable pendant l'extraction, « {} » dans le catalogue
UI_ATTRS = {'placeholder', 'title', 'aria-label', 'alt', 'data-tip', 'label'}
ALPINE_PREFIXES = ('x-text', 'x-html', ':', 'x-bind:', '@', 'x-on:', 'x-init', 'x-data', 'x-show')

_WS = re.compile(r'\s+')
_CSS_TOKEN = re.compile(r'^[!a-z0-9:\-\[\]./%#()_]+$')
_CODE_HINTS = ('=>', '();', '://', '&&', '||', '===', '!==', 'function', 'return ', 'querySelector', '.join(', '.map(')
_KEYWORDS = {'POST', 'GET', 'PUT', 'DELETE', 'PATCH', 'GMT', 'UTF', 'JSON', 'HTML', 'CSS', 'SVG'}


def normalize(text):
    return _WS.sub(' ', text.replace(PH, '{}')).strip()


def looks_like_ui_text(text):
    """Heuristique : texte lisible par un humain (pas une classe CSS, une clé ou du code)."""
    t = text.strip()
    letters = sum(c.isalpha() for c in t.replace('{}', ''))
    if letters < 2 or len(t) > 600:
        return False
    if any(h in t for h in _CODE_HINTS) or t.startswith(('.', '#', '[', '/', '--', 'data:', 'http', 'mailto:', 'tel:')):
        return False
    if t in _KEYWORDS or re.fullmatch(r'[A-Z_]{2,}', t) and t not in {'TVA', 'HT', 'TTC', 'PDF', 'IBAN', 'BIC', 'SIRET', 'API'}:
        return False
    tokens = t.split()
    if all(_CSS_TOKEN.match(tok) for tok in tokens) and any(('-' in tok or ':' in tok or '_' in tok or '.' in tok) for tok in tokens):
        return False  # « w-4 h-4 », « client.name », « in_progress »
    if len(tokens) == 1:
        word = tokens[0]
        has_accent = bool(re.search(r'[À-ÿœŒ]', word))
        if not (word[:1].isupper() or has_accent or word.endswith(('…', '.', '!', '?', ':'))):
            return False  # identifiant en minuscules
        if re.fullmatch(r'[A-Za-z]+[A-Z][a-z]+\w*', word):
            return False  # camelCase
    if re.fullmatch(r'[\w\-]+\.(js|css|png|svg|pdf|html|json)', t):
        return False
    if re.fullmatch(r'[dDjlNmMnFYyHhisaAgG:/\-. ]+', t) and len(t) <= 12:
        return False  # format de date (« d M Y »)
    return True


# --------------------------------------------------------------------------- #
# HTML (gabarits et chaînes JS contenant du balisage)
# --------------------------------------------------------------------------- #

class _TextCollector(HTMLParser):
    def __init__(self, sink, js_sink):
        super().__init__(convert_charrefs=True)
        self.sink = sink
        self.js_sink = js_sink
        self.in_script = 0
        self.in_style = 0
        self.script_buf = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.in_script += 1
            self.script_buf = []
            return
        if tag == 'style':
            self.in_style += 1
            return
        for name, value in attrs:
            if not value:
                continue
            if name in UI_ATTRS:
                self.sink(value)
            elif name == 'value' and dict(attrs).get('type') in ('submit', 'button'):
                self.sink(value)
            elif name.startswith(ALPINE_PREFIXES):
                self.js_sink(value)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag == 'script':
            self.in_script -= 1

    def handle_endtag(self, tag):
        if tag == 'script' and self.in_script:
            self.in_script -= 1
            self.js_sink(''.join(self.script_buf))
        elif tag == 'style' and self.in_style:
            self.in_style -= 1

    def handle_data(self, data):
        if self.in_script:
            self.script_buf.append(data)
        elif not self.in_style:
            self.sink(data)


def extract_html(source, add):
    def sink(text):
        for part in text.split('\x01'):
            part = normalize(part)
            if looks_like_ui_text(part):
                add(part)

    parser = _TextCollector(sink, lambda js: extract_js(js, add))
    parser.feed(source)
    parser.close()


def prepare_template(source):
    """Gabarit Django → HTML : {{ var }} devient une partie variable, {% tag %} une coupure."""
    source = re.sub(r'\{#.*?#\}', '', source, flags=re.S)
    source = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', '', source, flags=re.S)
    source = re.sub(r'\{%\s*(?:templatetag)[^%]*%\}', '', source)
    source = re.sub(r'\{\{.*?\}\}', PH, source, flags=re.S)
    return re.sub(r'\{%.*?%\}', '\x01', source, flags=re.S)


# --------------------------------------------------------------------------- #
# JavaScript : littéraux de chaîne (y compris gabarits `…${}…` imbriqués)
# --------------------------------------------------------------------------- #

_REGEX_PREV = set('(,=:[!&|?{};+-*%<>~^')


def _scan_js(src, i, end_char, literals):
    """Parcourt du code JS à partir de i jusqu'à end_char (ou la fin) ; retourne l'index d'arrêt."""
    n = len(src)
    depth = 0
    prev = ''
    while i < n:
        c = src[i]
        if c == end_char and depth == 0:
            return i
        if c in '{([':
            depth += 1
        elif c in '})]':
            depth -= 1
        if c == '/' and i + 1 < n and src[i + 1] == '/':
            j = src.find('\n', i)
            i = n if j < 0 else j
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '*':
            j = src.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == '/' and (prev in _REGEX_PREV or prev == '' or re.search(r'(return|typeof|case)\s*$', src[max(0, i - 8):i])):
            j = i + 1
            in_class = False
            while j < n:
                if src[j] == '\\':
                    j += 2
                    continue
                if src[j] == '[':
                    in_class = True
                elif src[j] == ']':
                    in_class = False
                elif src[j] == '/' and not in_class:
                    break
                elif src[j] == '\n':
                    break
                j += 1
            i = j + 1
            prev = '/'
            continue
        if c in ('"', "'"):
            j = i + 1
            buf = []
            while j < n and src[j] != c:
                if src[j] == '\\' and j + 1 < n:
                    buf.append({'n': '\n', 't': ' '}.get(src[j + 1], src[j + 1]))
                    j += 2
                    continue
                if src[j] == '\n':
                    break
                buf.append(src[j])
                j += 1
            literals.append(''.join(buf))
            i = j + 1
            prev = 'x'
            continue
        if c == '`':
            j = i + 1
            buf = []
            while j < n and src[j] != '`':
                if src[j] == '\\' and j + 1 < n:
                    buf.append(src[j + 1])
                    j += 2
                    continue
                if src[j] == '$' and j + 1 < n and src[j + 1] == '{':
                    j = _scan_js(src, j + 2, '}', literals) + 1
                    buf.append(PH)
                    continue
                buf.append(src[j])
                j += 1
            literals.append(''.join(buf))
            i = j + 1
            prev = 'x'
            continue
        if not c.isspace():
            prev = c
        i += 1
    return i


def extract_js(source, add):
    literals = []
    _scan_js(source, 0, None, literals)
    for lit in literals:
        if '<' in lit and '>' in lit:
            extract_html(lit, add)
        else:
            text = normalize(lit)
            if looks_like_ui_text(text):
                add(text)


# --------------------------------------------------------------------------- #
# Python : chaînes affichées (vues, messages, libellés, f-strings)
# --------------------------------------------------------------------------- #

_FRENCH = re.compile(r"[À-ÿœ]|(le|la|les|des|du|de|un|une|et|à|pour|est|vos|votre|aucun|aucune|sur|dans|avec|ce|cette|pas)", re.I)


def _python_strings(source):
    """Chaînes d'un fichier Python via tokenize : [(texte, est_docstring, précédé_de_gettext)]."""
    import ast
    import io
    import tokenize
    out = []
    prev = []
    fstring = None
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return out
    for tok in tokens:
        kind = tokenize.tok_name.get(tok.type, '')
        if kind == 'FSTRING_START':
            fstring = {'parts': [], 'depth': 0, 'gettext': prev[-2:] == ['_', '(']}
        elif fstring is not None:
            if kind == 'FSTRING_MIDDLE':
                if fstring['depth'] == 0:
                    fstring['parts'].append(tok.string.replace('{{', '{').replace('}}', '}'))
            elif kind == 'FSTRING_END':
                if fstring['depth'] == 0:
                    out.append((''.join(fstring['parts']), False, fstring['gettext']))
                    fstring = None
            elif tok.string == '{':
                if fstring['depth'] == 0:
                    fstring['parts'].append(PH)
                fstring['depth'] += 1
            elif tok.string == '}':
                fstring['depth'] -= 1
        elif kind == 'STRING':
            raw = tok.string
            prefix = re.match(r'^[a-zA-Z]*', raw).group(0).lower()
            if 'b' in prefix:
                continue
            is_doc = raw.lstrip('rRuUfF').startswith(('"""', "'''")) and (not prev or prev[-1] in (':', '', 'NEWLINE', 'INDENT'))
            try:
                if 'f' in prefix:
                    body = re.sub(r'\{[^{}]*\}', PH, raw[len(prefix):].strip('"\''))
                else:
                    body = ast.literal_eval(raw)
            except Exception:
                continue
            out.append((body, is_doc, prev[-2:] == ['_', '(']))
        if kind not in ('NL', 'COMMENT'):
            prev.append(tok.string if kind not in ('NEWLINE', 'INDENT', 'DEDENT') else kind)
            prev = prev[-3:]
    return out


def extract_python(source, add):
    for body, is_doc, is_gettext in _python_strings(source):
        if is_doc or not isinstance(body, str):
            continue
        if '<' in body and '>' in body:
            extract_html(prepare_template(body), add)
            continue
        if '{%' in body or '{{' in body:
            body = prepare_template(body)
            for part in body.split(''):
                text = normalize(part)
                if looks_like_ui_text(text) and (is_gettext or _FRENCH.search(text)):
                    add(text)
            continue
        text = normalize(body)
        if looks_like_ui_text(text) and (is_gettext or _FRENCH.search(text) or (' ' in text and text[:1].isupper())):
            add(text)


# --------------------------------------------------------------------------- #

SKIP_DIRS = {'migrations', '__pycache__', 'tests', 'management'}
# Contenu des documents / modèles de facture (langue du document, pas de l'interface) et pages de démo.
SKIP_FILES = {
    'canvas_templates.py', 'pro_templates.py', 'system_marketplace_seeds.py', 'seed_templates.py',
    'dev-tools.html', 'demo.html', 'demo_base.html',
}


def collect(base_dir):
    base = Path(base_dir)
    found = {}

    def adder(origin):
        def add(text):
            found.setdefault(text, set()).add(origin)
        return add

    for path in sorted((base / 'templates').rglob('*.html')):
        if path.name in SKIP_FILES:
            continue
        extract_html(prepare_template(path.read_text(encoding='utf-8')), adder(str(path.relative_to(base))))
    for path in sorted((base / 'static' / 'js').rglob('*.js')):
        if path.name.startswith('tailwind'):
            continue
        extract_js(path.read_text(encoding='utf-8'), adder(str(path.relative_to(base))))
    for path in sorted((base / 'apps').rglob('*.py')):
        if SKIP_DIRS & set(path.parts) or 'translations' in path.parts or path.name in SKIP_FILES:
            continue
        extract_python(path.read_text(encoding='utf-8'), adder(str(path.relative_to(base))))
    return found
