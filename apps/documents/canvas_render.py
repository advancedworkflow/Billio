"""
Mode « canvas » des documents : normalisation des données envoyées par l'éditeur
(static/js/document-canvas.js) et rendu HTML/WeasyPrint des pages à éléments
positionnés librement (textes, formes, images, tableaux).

Tout ce qui vient du navigateur est re-validé ici avant d'être stocké ou rendu :
nombres bornés, couleurs et énumérations sur liste blanche, HTML des zones de
texte filtré par balise/attribut, et images limitées aux fichiers de /media/ (ou
data:image) pour que le moteur PDF ne récupère jamais une URL arbitraire.
"""
import html
import re
import uuid
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings

from .models import clean_overrides, page_size_px

MAX_PAGES = 30
MAX_ELEMENTS_PER_PAGE = 200
MAX_TABLE_ROWS = 60
MAX_TABLE_COLS = 12

ELEMENT_TYPES = {'text', 'shape', 'image', 'table', 'field', 'button'}
# Champs de formulaire (documents de type sondage / demande) : remplis par le client dans son portail.
FIELD_TYPES = {'text', 'textarea', 'email', 'phone', 'number', 'date', 'select', 'radio', 'checkbox'}
SHAPE_KINDS = {'rect', 'ellipse', 'triangle', 'line', 'arrow', 'star', 'diamond', 'path'}
# Tracés vectoriels (shape « path ») : courbes de Bézier, voir static/js/document-canvas-vector.js.
MAX_SUBPATHS = 120
MAX_PATH_NODES = 2500
FILL_RULES = {'nonzero', 'evenodd'}
FONT_FAMILIES = {
    'Inter, sans-serif',
    "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Helvetica, Arial, sans-serif",
    'Arial, sans-serif',
    'Helvetica, Arial, sans-serif',
    'Georgia, serif',
    "'Times New Roman', serif",
    "'Courier New', monospace",
    'Manrope, sans-serif',
    'Newsreader, serif',
    'Verdana, sans-serif',
}
DEFAULT_FONT = 'Inter, sans-serif'
ALIGNS = {'left', 'center', 'right', 'justify'}
VALIGNS = {'top', 'middle', 'bottom'}
BORDER_STYLES = {'solid', 'dashed', 'dotted', 'double'}
FITS = {'cover', 'contain', 'fill'}
SHADOWS = {
    'none': '',
    'sm': '0 1px 2px rgba(15,23,42,.12)',
    'md': '0 4px 12px rgba(15,23,42,.14)',
    'lg': '0 12px 32px rgba(15,23,42,.18)',
}
FONT_WEIGHTS = {300, 400, 500, 600, 700, 800}

# Tableaux avancés : type de chaque colonne, totaux, bordures, remplissage depuis un devis / une facture.
COLUMN_KINDS = {'text', 'number', 'money', 'percent', 'calc'}
SOURCE_FIELDS = {'name', 'description', 'quantity', 'unit', 'unit_price', 'tax_rate', 'total'}
TABLE_SOURCES = {'', 'quote', 'invoice'}
TOTALS_MODES = {'none', 'sum', 'vat'}
TABLE_BORDERS = {'all', 'rows', 'outer', 'none'}
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

_COLOR_RE = re.compile(r'^(#[0-9a-fA-F]{3,8}|transparent|rgba?\(\s*[\d.]+%?\s*,\s*[\d.]+%?\s*,\s*[\d.]+%?\s*(,\s*[\d.]+\s*)?\))$')
_ID_RE = re.compile(r'^[\w-]{1,40}$')


# --------------------------------------------------------------------------- #
# Primitives de validation
# --------------------------------------------------------------------------- #

def _num(value, default, lo, hi):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(lo, min(hi, round(number, 2)))


def _color(value, default):
    if isinstance(value, str) and _COLOR_RE.match(value.strip()):
        return value.strip()
    return default


def _enum(value, allowed, default):
    return value if value in allowed else default


def _bool(value):
    return bool(value) and value not in ('false', '0')


def _safe_src(src):
    """Images autorisées : fichiers servis depuis MEDIA_URL ou data:image base64."""
    if not isinstance(src, str):
        return ''
    src = src.strip()
    if src.startswith('data:image/') and ';base64,' in src[:40] and len(src) < 4_000_000:
        return src
    if src.startswith(settings.MEDIA_URL) and '..' not in src:
        return src
    return ''


class _HtmlSanitizer(HTMLParser):
    """Liste blanche de balises/attributs pour le contenu des zones de texte."""

    ALLOWED_TAGS = {
        'b', 'strong', 'i', 'em', 'u', 's', 'strike', 'sub', 'sup', 'br', 'p', 'div', 'span',
        'ul', 'ol', 'li', 'a', 'h1', 'h2', 'h3', 'h4', 'blockquote', 'font', 'small', 'mark',
        'table', 'thead', 'tbody', 'tr', 'td', 'th', 'hr',
    }
    VOID_TAGS = {'br', 'hr'}
    ALLOWED_ATTRS = {'style', 'class', 'href', 'data-var', 'color', 'face', 'size', 'contenteditable', 'colspan', 'rowspan'}
    STYLE_FORBIDDEN = re.compile(r'url\s*\(|expression\s*\(|@import|behavior\s*:|javascript:', re.I)

    DROP_CONTENT_TAGS = {'script', 'style', 'template', 'iframe', 'object', 'noscript'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []
        self.dropping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.DROP_CONTENT_TAGS:
            self.dropping += 1
            return
        if self.dropping or tag not in self.ALLOWED_TAGS:
            return
        parts = [tag]
        for name, value in attrs:
            if name not in self.ALLOWED_ATTRS or value is None:
                continue
            if name == 'href' and not re.match(r'^(https?:|mailto:|tel:|#)', value.strip(), re.I):
                continue
            if name == 'style' and self.STYLE_FORBIDDEN.search(value):
                continue
            if name == 'contenteditable':
                # Les jetons de variable sont non éditables dans l'éditeur ; on ne garde que "false".
                value = 'false'
            parts.append(f'{name}="{html.escape(value, quote=True)}"')
        self.out.append('<' + ' '.join(parts) + '>')
        if tag not in self.VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in self.VOID_TAGS:
            self.out.append(f'<{tag}>')

    def handle_endtag(self, tag):
        if tag in self.DROP_CONTENT_TAGS:
            self.dropping = max(0, self.dropping - 1)
            return
        if self.dropping:
            return
        if tag in self.ALLOWED_TAGS and tag in self.stack:
            while self.stack:
                open_tag = self.stack.pop()
                self.out.append(f'</{open_tag}>')
                if open_tag == tag:
                    break

    def handle_data(self, data):
        if self.dropping:
            return
        self.out.append(html.escape(data, quote=False))

    def result(self):
        while self.stack:
            self.out.append(f'</{self.stack.pop()}>')
        return ''.join(self.out)


def sanitize_html(value, max_length=50_000):
    if not isinstance(value, str) or not value:
        return ''
    parser = _HtmlSanitizer()
    parser.feed(value[:max_length])
    parser.close()
    return parser.result()


# --------------------------------------------------------------------------- #
# Normalisation des données de l'éditeur
# --------------------------------------------------------------------------- #

def _clean_style(raw, element_type):
    raw = raw if isinstance(raw, dict) else {}
    style = {
        'opacity': _num(raw.get('opacity'), 1, 0, 1),
        'background': _color(raw.get('background'), 'transparent'),
        'borderWidth': _num(raw.get('borderWidth'), 0, 0, 40),
        'borderColor': _color(raw.get('borderColor'), '#1f2937'),
        'borderStyle': _enum(raw.get('borderStyle'), BORDER_STYLES, 'solid'),
        'radius': _num(raw.get('radius'), 0, 0, 400),
        'shadow': _enum(raw.get('shadow'), SHADOWS.keys(), 'none'),
        'padding': _num(raw.get('padding'), 0, 0, 120),
    }
    if element_type in ('text', 'table', 'field', 'button'):
        style.update({
            'fontFamily': _enum(raw.get('fontFamily'), FONT_FAMILIES, DEFAULT_FONT),
            'fontSize': _num(raw.get('fontSize'), 14, 6, 200),
            'fontWeight': int(raw.get('fontWeight')) if str(raw.get('fontWeight')).isdigit() and int(raw.get('fontWeight')) in FONT_WEIGHTS else 400,
            'italic': _bool(raw.get('italic')),
            'underline': _bool(raw.get('underline')),
            'uppercase': _bool(raw.get('uppercase')),
            'color': _color(raw.get('color'), '#1f2937'),
            'align': _enum(raw.get('align'), ALIGNS, 'left'),
            'valign': _enum(raw.get('valign'), VALIGNS, 'top'),
            'lineHeight': _num(raw.get('lineHeight'), 1.4, 0.8, 4),
            'letterSpacing': _num(raw.get('letterSpacing'), 0, -5, 40),
        })
    if element_type == 'shape':
        style.update({
            'fill': _color(raw.get('fill'), '#e0e7ff'),
            'strokeColor': _color(raw.get('strokeColor'), '#4f46e5'),
            'strokeWidth': _num(raw.get('strokeWidth'), 0, 0, 40),
            'strokeStyle': _enum(raw.get('strokeStyle'), BORDER_STYLES - {'double'}, 'solid'),
            # Dégradé linéaire facultatif : fill → fill2, angle en degrés (0 = de gauche à droite).
            'fill2': _color(raw.get('fill2'), ''),
            'gradientAngle': _num(raw.get('gradientAngle'), 0, 0, 360),
            'fillRule': _enum(raw.get('fillRule'), FILL_RULES, 'nonzero'),
        })
    if element_type == 'image':
        style['fit'] = _enum(raw.get('fit'), FITS, 'cover')
    if element_type == 'field':
        style.update({
            'labelColor': _color(raw.get('labelColor'), '#374151'),
            'fieldBg': _color(raw.get('fieldBg'), '#ffffff'),
            'fieldBorder': _color(raw.get('fieldBorder'), '#d1d5db'),
            'fieldRadius': _num(raw.get('fieldRadius'), 8, 0, 40),
            'accent': _color(raw.get('accent'), '#6d28d9'),
        })
    if element_type == 'table':
        style.update({
            'headerBg': _color(raw.get('headerBg'), '#111827'),
            'headerColor': _color(raw.get('headerColor'), '#ffffff'),
            'cellBorderColor': _color(raw.get('cellBorderColor'), '#e5e7eb'),
            'stripe': _color(raw.get('stripe'), 'transparent'),
            'cellPadding': _num(raw.get('cellPadding'), 8, 0, 40),
            'totalBg': _color(raw.get('totalBg'), 'transparent'),
        })
    return style


def _coord(value):
    """Coordonnée d'un tracé, relative à la boîte de l'élément (débord autorisé)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number or number in (float('inf'), float('-inf')):
        return 0.0
    return max(-4.0, min(5.0, round(number, 4)))


def _clean_paths(raw):
    """Sous-tracés : nœuds [x, y, entréeX, entréeY, sortieX, sortieY, lisse] en coordonnées 0–1."""
    paths = []
    budget = MAX_PATH_NODES
    for item in (raw if isinstance(raw, list) else [])[:MAX_SUBPATHS]:
        if not isinstance(item, dict) or not isinstance(item.get('nodes'), list):
            continue
        nodes = []
        for n in item['nodes'][:budget]:
            if isinstance(n, (list, tuple)) and len(n) >= 6:
                nodes.append([_coord(v) for v in n[:6]] + [1 if len(n) > 6 and n[6] else 0])
        if len(nodes) < 2:
            continue
        budget -= len(nodes)
        paths.append({'closed': _bool(item.get('closed')), 'nodes': nodes})
        if budget <= 0:
            break
    return paths


def _path_d(paths, w, h):
    """Attribut d du tracé en px (miroir de DcVector.toD)."""
    def f(value):
        return f'{round(value, 2):g}'
    out = []
    for path in paths:
        n = path['nodes']
        d = f'M{f(n[0][0] * w)} {f(n[0][1] * h)}'
        segs = list(zip(n, n[1:])) + ([(n[-1], n[0])] if path['closed'] else [])
        for a, b in segs:
            d += f'C{f(a[4] * w)} {f(a[5] * h)} {f(b[2] * w)} {f(b[3] * h)} {f(b[0] * w)} {f(b[1] * h)}'
        out.append(d + ('Z' if path['closed'] else ''))
    return ''.join(out)


def _clean_element(raw):
    if not isinstance(raw, dict):
        return None
    element_type = raw.get('type')
    if element_type not in ELEMENT_TYPES:
        return None
    element_id = raw.get('id') if isinstance(raw.get('id'), str) and _ID_RE.match(raw.get('id')) else uuid.uuid4().hex[:10]
    element = {
        'id': element_id,
        'type': element_type,
        'name': str(raw.get('name') or '')[:60],
        'x': _num(raw.get('x'), 40, -2000, 4000),
        'y': _num(raw.get('y'), 40, -2000, 4000),
        'w': _num(raw.get('w'), 200, 4, 4000),
        'h': _num(raw.get('h'), 60, 1, 4000),
        'rotation': _num(raw.get('rotation'), 0, -360, 360),
        'locked': _bool(raw.get('locked')),
        'hidden': _bool(raw.get('hidden')),
        'style': _clean_style(raw.get('style'), element_type),
    }
    if element_type == 'text':
        element['html'] = sanitize_html(raw.get('html'))
    elif element_type == 'shape':
        element['shape'] = _enum(raw.get('shape'), SHAPE_KINDS, 'rect')
        if element['shape'] == 'path':
            element['paths'] = _clean_paths(raw.get('paths'))
            if not element['paths']:
                element['shape'] = 'rect'
    elif element_type == 'image':
        element['src'] = _safe_src(raw.get('src'))
    elif element_type == 'table':
        rows = raw.get('rows') if isinstance(raw.get('rows'), list) else []
        rows = [r for r in rows[:MAX_TABLE_ROWS] if isinstance(r, list)] or [['']]
        cols = max(1, min(MAX_TABLE_COLS, max(len(r) for r in rows)))
        element['rows'] = [
            [sanitize_html(cell if isinstance(cell, str) else '', 5_000) for cell in (r + [''] * cols)[:cols]]
            for r in rows
        ]
        widths = raw.get('colWidths') if isinstance(raw.get('colWidths'), list) else []
        widths = [_num(w, 0, 1, 100) for w in widths[:cols]]
        if len(widths) != cols or not all(widths):
            widths = [round(100 / cols, 2)] * cols
        element['colWidths'] = widths
        element['header'] = _bool(raw.get('header', True))
        element['columns'] = _clean_columns(raw.get('columns'), cols)
        totals = raw.get('totals') if isinstance(raw.get('totals'), dict) else {}
        element['totals'] = {
            'mode': _enum(totals.get('mode'), TOTALS_MODES, 'none'),
            'vatRate': _num(totals.get('vatRate'), 20, 0, 100),
            'label': str(totals.get('label') or '')[:40],
        }
        element['borders'] = _enum(raw.get('borders'), TABLE_BORDERS, 'all')
        element['source'] = _enum(raw.get('source'), TABLE_SOURCES, '')
        element['cellStyles'] = _clean_cell_styles(raw.get('cellStyles'), len(element['rows']), cols)
    elif element_type == 'field':
        element['fieldType'] = _enum(raw.get('fieldType'), FIELD_TYPES, 'text')
        element['label'] = str(raw.get('label') or '')[:160]
        element['placeholder'] = str(raw.get('placeholder') or '')[:160]
        element['required'] = _bool(raw.get('required'))
        element['showLabel'] = _bool(raw.get('showLabel', True))
        options = raw.get('options') if isinstance(raw.get('options'), list) else []
        element['options'] = [str(o).strip()[:80] for o in options[:20] if str(o).strip()]
    elif element_type == 'button':
        element['text'] = str(raw.get('text') or 'Envoyer')[:60]
    return element


def clean_canvas_data(raw):
    """Normalise le JSON envoyé par l'éditeur canvas (structure, bornes, liste blanche)."""
    raw = raw if isinstance(raw, dict) else {}
    pages = []
    for raw_page in (raw.get('pages') or [])[:MAX_PAGES]:
        if not isinstance(raw_page, dict):
            continue
        page_id = raw_page.get('id') if isinstance(raw_page.get('id'), str) and _ID_RE.match(raw_page.get('id')) else uuid.uuid4().hex[:10]
        elements = [_clean_element(e) for e in (raw_page.get('elements') or [])[:MAX_ELEMENTS_PER_PAGE]]
        pages.append({
            'id': page_id,
            'background': _color(raw_page.get('background'), '#ffffff'),
            'elements': [e for e in elements if e],
        })
    if not pages:
        pages = [{'id': uuid.uuid4().hex[:10], 'background': '#ffffff', 'elements': []}]
    sources = raw.get('sources') if isinstance(raw.get('sources'), dict) else {}
    return {
        'pages': pages,
        'fields': clean_custom_fields(raw.get('fields')),
        # Devis / facture choisis pour remplir les tableaux ('' = le plus récent du client).
        'sources': {k: (sources.get(k) if isinstance(sources.get(k), str) and _UUID_RE.match(sources.get(k)) else '') for k in ('quote', 'invoice')},
        # Variables automatiques remplacées à la création (automatisations).
        'overrides': clean_overrides(raw.get('overrides')),
    }


def _clean_columns(raw, cols):
    raw = raw if isinstance(raw, list) else []
    columns = []
    for index in range(cols):
        item = raw[index] if index < len(raw) and isinstance(raw[index], dict) else {}
        kind = _enum(item.get('kind'), COLUMN_KINDS, 'text')
        column = {
            'kind': kind,
            'align': _enum(item.get('align'), ALIGNS - {'justify'}, ''),
            'field': _enum(item.get('field'), SOURCE_FIELDS, ''),
        }
        if kind == 'calc':
            column['a'] = int(_num(item.get('a'), 0, 0, cols - 1))
            column['b'] = int(_num(item.get('b'), 0, 0, cols - 1))
        columns.append(column)
    return columns


def _clean_cell_styles(raw, rows, cols):
    """Mise en forme cellule par cellule : {"ligne:colonne": {bg, color, bold, italic, align}}."""
    styles = {}
    for key, value in (raw.items() if isinstance(raw, dict) else []):
        match = re.match(r'^(\d{1,3}):(\d{1,2})$', str(key))
        if not match or not isinstance(value, dict) or int(match.group(1)) >= rows or int(match.group(2)) >= cols:
            continue
        cell = {}
        if _color(value.get('bg'), ''):
            cell['bg'] = _color(value.get('bg'), '')
        if _color(value.get('color'), ''):
            cell['color'] = _color(value.get('color'), '')
        for flag in ('bold', 'italic'):
            if _bool(value.get(flag)):
                cell[flag] = True
        if value.get('align') in ALIGNS:
            cell['align'] = value['align']
        if cell:
            styles[key] = cell
        if len(styles) >= 400:
            break
    return styles


# --------------------------------------------------------------------------- #
# Nombres des tableaux (format français) et construction des lignes
# --------------------------------------------------------------------------- #

_STRIP_TAGS_RE = re.compile(r'<[^>]+>')
_NUMBER_NOISE_RE = re.compile(r'[\s\u00a0\u202f€%]')


def parse_number(fragment):
    """« 1 234,50 € » → 1234.5 ; None si la cellule ne contient pas un nombre."""
    text = _NUMBER_NOISE_RE.sub('', html.unescape(_STRIP_TAGS_RE.sub('', str(fragment or ''))))
    if not text or not re.match(r'^-?[\d.,]+$', text):
        return None
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    elif text.count('.') > 1:
        text = text.replace('.', '')
    try:
        return float(text)
    except ValueError:
        return None


def format_number(value, kind='number'):
    """Format français : 1 234,50 € / 12,5 % / 3."""
    if value is None:
        return ''
    value = round(float(value) + 0.0, 2)
    if kind == 'money':
        text = f'{abs(value):,.2f}'
    else:
        text = f'{abs(value):,.2f}'.rstrip('0').rstrip('.')
    text = ('-' if value < 0 else '') + text.replace(',', '\u00a0').replace('.', ',')
    if kind == 'money':
        return text + '\u00a0€'
    if kind == 'percent':
        return text + '\u00a0%'
    return text


def table_rows(element, resolve, sources=None):
    """
    Lignes à afficher pour un tableau : [{'kind': header|body|total, 'cells': [...]}].
    Chaque cellule : {'html', 'r', 'c' (cellule enregistrée), 'calc', 'colspan', 'align'}.
    Les lignes du corps viennent du devis / de la facture si le tableau y est relié,
    les colonnes « Calcul » valent A × B et les totaux sont recalculés à chaque rendu.
    Garder en phase avec tableModel() de static/js/document-canvas.js.
    """
    columns = element['columns']
    count = len(columns)
    rows = element['rows']
    out = []
    if element['header']:
        out.append({'kind': 'header', 'cells': [{'html': resolve(cell), 'r': 0, 'c': i} for i, cell in enumerate(rows[0])]})
    offset = 1 if element['header'] else 0
    data = (sources or {}).get(element['source']) if element['source'] else None
    body = []
    if data is not None:
        for item in data.get('rows') or []:
            body.append([{'html': html.escape(str(item.get(col['field'], '') if col['field'] else '')), 'gen': True} for col in columns])
    else:
        for ri, row in enumerate(rows[offset:]):
            body.append([{'html': resolve(cell), 'r': ri + offset, 'c': ci} for ci, cell in enumerate(row)])

    sums = [0.0] * count
    amount_col = next((i for i in range(count - 1, -1, -1) if columns[i]['kind'] in ('money', 'calc')), None)
    if amount_col is None:
        amount_col = next((i for i in range(count - 1, -1, -1) if columns[i]['kind'] == 'number'), None)
    vat_lines, rates = 0.0, set()
    for index, cells in enumerate(body):
        numbers = [parse_number(cell['html']) for cell in cells]
        for i, column in enumerate(columns):
            if column['kind'] == 'calc':
                a, b = numbers[column['a']], numbers[column['b']]
                numbers[i] = round(a * b, 2) if a is not None and b is not None else None
                cells[i]['calc'] = True
                cells[i]['html'] = format_number(numbers[i], 'money')
            elif column['kind'] != 'text' and numbers[i] is not None:
                cells[i]['html'] = html.escape(format_number(numbers[i], column['kind']))
            if column['kind'] in ('number', 'money', 'calc') and numbers[i] is not None:
                sums[i] += numbers[i]
        if data is not None and amount_col is not None and numbers[amount_col] is not None:
            rate = (data.get('rows') or [])[index].get('_rate')
            if rate is not None:
                rates.add(rate)
                vat_lines += numbers[amount_col] * rate / 100
        out.append({'kind': 'body', 'cells': cells})

    totals = element['totals']
    if totals['mode'] == 'sum' and any(c['kind'] in ('number', 'money', 'calc') for c in columns):
        cells = []
        for i, column in enumerate(columns):
            if column['kind'] in ('number', 'money', 'calc'):
                cells.append({'html': html.escape(format_number(sums[i], 'money' if column['kind'] in ('money', 'calc') else 'number'))})
            elif i == 0:
                cells.append({'html': html.escape(totals['label'] or 'Total')})
            else:
                cells.append({'html': ''})
        out.append({'kind': 'total', 'cells': cells})
    elif totals['mode'] == 'vat' and amount_col is not None:
        ht = round(sums[amount_col], 2)
        if data is not None and rates:
            vat = round(vat_lines, 2)
            rate_label = f"TVA {format_number(next(iter(rates)), 'percent')}" if len(rates) == 1 else 'TVA'
        else:
            vat = round(ht * totals['vatRate'] / 100, 2)
            rate_label = f"TVA {format_number(totals['vatRate'], 'percent')}"
        for label, amount, strong in ((totals['label'] or 'Total HT', ht, False), (rate_label, vat, False), ('Total TTC', ht + vat, True)):
            cells = []
            if amount_col > 0:
                cells.append({'html': html.escape(label), 'colspan': amount_col, 'align': 'right'})
                cells.append({'html': html.escape(format_number(amount, 'money')), 'strong': strong})
            else:
                cells.append({'html': html.escape(f'{label} : {format_number(amount, "money")}'), 'strong': strong})
            if count - amount_col - 1 > 0:
                cells.append({'html': '', 'colspan': count - amount_col - 1})
            out.append({'kind': 'total', 'cells': cells})
    return out


def _table_html(element, resolve, sources):
    style = element['style']
    pad = style['cellPadding']
    border = style['cellBorderColor']
    mode = element['borders']
    columns = element['columns']
    cols = ''.join(f'<col style="width:{w}%">' for w in element['colWidths'])
    rows_html = []
    body_index = 0
    first_total = True
    for row in table_rows(element, resolve, sources):
        position = 0
        cells_html = []
        for cell in row['cells']:
            column = columns[min(position, len(columns) - 1)]
            css = [f'padding:{pad}px']
            if mode == 'all':
                css.append(f'border:1px solid {border}')
            elif mode == 'rows':
                css.append(f'border-bottom:1px solid {border}')
            align = cell.get('align') or column['align'] or ('right' if column['kind'] != 'text' and row['kind'] != 'header' else style['align'])
            if row['kind'] == 'header':
                css += [f"background:{style['headerBg']}", f"color:{style['headerColor']}", 'font-weight:600']
            elif row['kind'] == 'body':
                if style['stripe'] != 'transparent' and body_index % 2 == 1:
                    css.append(f"background:{style['stripe']}")
            else:
                css.append('font-weight:700' if cell.get('strong') else 'font-weight:600')
                if style['totalBg'] != 'transparent':
                    css.append(f"background:{style['totalBg']}")
                if first_total:
                    css.append(f"border-top:1.5px solid {style['color']}")
            custom = element['cellStyles'].get(f"{cell['r']}:{cell['c']}") if 'r' in cell else None
            if custom:
                if custom.get('bg'):
                    css.append(f"background:{custom['bg']}")
                if custom.get('color'):
                    css.append(f"color:{custom['color']}")
                if custom.get('bold'):
                    css.append('font-weight:700')
                if custom.get('italic'):
                    css.append('font-style:italic')
                align = custom.get('align') or align
            css.append(f'text-align:{align}')
            tag = 'th' if row['kind'] == 'header' else 'td'
            span = f' colspan="{cell["colspan"]}"' if cell.get('colspan', 1) > 1 else ''
            cells_html.append(f'<{tag}{span} style="{";".join(css)}">{cell["html"]}</{tag}>')
            position += cell.get('colspan', 1)
        if row['kind'] == 'body':
            body_index += 1
        if row['kind'] == 'total':
            first_total = False
        rows_html.append(f'<tr>{"".join(cells_html)}</tr>')
    table_css = f' style="border:1px solid {border}"' if mode == 'outer' else ''
    return f'<table{table_css}><colgroup>{cols}</colgroup>{"".join(rows_html)}</table>'


CUSTOM_FIELD_TYPES = ('text', 'choice', 'date', 'number', 'money')


def clean_custom_fields(raw):
    """
    Champs personnalisés du document (« Formule », « Durée »…), insérables comme variables
    `champ.<id>` et remplis depuis l'onglet Variables : texte, liste de choix, date, nombre.
    """
    fields = []
    seen = set()
    for item in (raw if isinstance(raw, list) else [])[:30]:
        if not isinstance(item, dict):
            continue
        fid = str(item.get('id') or '')
        label = str(item.get('label') or '').strip()[:60]
        if not _ID_RE.match(fid) or fid in seen or not label:
            continue
        seen.add(fid)
        ftype = item.get('type') if item.get('type') in CUSTOM_FIELD_TYPES else 'text'
        options = []
        if ftype == 'choice':
            options = [str(o).strip()[:80] for o in (item.get('options') or [])[:20] if str(o).strip()]
        value = str(item.get('value') or '').strip()[:500]
        if ftype == 'choice' and value and value not in options:
            value = ''
        fields.append({
            'id': fid, 'label': label, 'type': ftype, 'options': options, 'value': value,
            'required': _bool(item.get('required')),
            'help': str(item.get('help') or '').strip()[:140],
        })
    return fields


# --------------------------------------------------------------------------- #
# Rendu HTML (PDF)
# --------------------------------------------------------------------------- #

def _shape_svg(shape, w, h, style, paths=None):
    import math
    fill = style['fill']
    defs = ''
    if style.get('fill2') and shape not in ('line', 'arrow'):
        # Dégradé linéaire en unités de la boîte : angle 0 = de gauche à droite.
        gid = f'g{uuid.uuid4().hex[:8]}'
        angle = math.radians(style.get('gradientAngle') or 0)
        dx, dy = math.cos(angle) / 2, math.sin(angle) / 2
        defs = (f'<defs><linearGradient id="{gid}" x1="{0.5 - dx:.4f}" y1="{0.5 - dy:.4f}" x2="{0.5 + dx:.4f}" y2="{0.5 + dy:.4f}">'
                f'<stop offset="0" stop-color="{fill}"/><stop offset="1" stop-color="{style["fill2"]}"/></linearGradient></defs>')
        fill = f'url(#{gid})'
    stroke = style['strokeColor'] if style['strokeWidth'] else 'none'
    sw = style['strokeWidth']
    dash = {'dashed': f'{sw * 3},{sw * 2}', 'dotted': f'{sw},{sw * 1.5}'}.get(style['strokeStyle'], '')
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ''
    common = f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{dash_attr}'
    half = sw / 2
    if shape == 'path':
        stroke_attrs = f'fill="{fill}" fill-rule="{style.get("fillRule", "nonzero")}" stroke="{stroke}" stroke-width="{sw}"{dash_attr} stroke-linejoin="round" stroke-linecap="round"'
        body = f'<path d="{_path_d(paths or [], w, h)}" {stroke_attrs}/>'
    elif shape == 'ellipse':
        body = f'<ellipse cx="{w / 2}" cy="{h / 2}" rx="{max(0, w / 2 - half)}" ry="{max(0, h / 2 - half)}" {common}/>'
    elif shape == 'triangle':
        body = f'<polygon points="{w / 2},{half} {w - half},{h - half} {half},{h - half}" {common}/>'
    elif shape == 'diamond':
        body = f'<polygon points="{w / 2},{half} {w - half},{h / 2} {w / 2},{h - half} {half},{h / 2}" {common}/>'
    elif shape == 'star':
        import math
        cx, cy, outer = w / 2, h / 2, min(w, h) / 2 - half
        inner = outer * 0.45
        points = []
        for i in range(10):
            radius = outer if i % 2 == 0 else inner
            angle = math.pi / 5 * i - math.pi / 2
            points.append(f'{cx + radius * math.cos(angle):.2f},{cy + radius * math.sin(angle):.2f}')
        body = f'<polygon points="{" ".join(points)}" {common}/>'
    elif shape in ('line', 'arrow'):
        line_w = max(sw, 1)
        line_color = style['strokeColor']
        end = w - (line_w * 3 if shape == 'arrow' else 0)
        body = f'<line x1="0" y1="{h / 2}" x2="{end}" y2="{h / 2}" stroke="{line_color}" stroke-width="{line_w}"{dash_attr}/>'
        if shape == 'arrow':
            head = line_w * 3.5
            body += f'<polygon points="{w},{h / 2} {w - head},{h / 2 - head / 1.4} {w - head},{h / 2 + head / 1.4}" fill="{line_color}"/>'
    else:
        radius = style['radius']
        body = (
            f'<rect x="{half}" y="{half}" width="{max(0, w - sw)}" height="{max(0, h - sw)}" '
            f'rx="{radius}" ry="{radius}" {common}/>'
        )
    if shape == 'path' and sw:
        # WeasyPrint rogne le SVG à sa boîte : marge de l'épaisseur du trait autour du tracé.
        m = sw
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w + 2 * m}" height="{h + 2 * m}" '
                f'viewBox="{-m} {-m} {w + 2 * m} {h + 2 * m}" style="margin:{-m}px 0 0 {-m}px" overflow="visible">{defs}{body}</svg>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" overflow="visible">{defs}{body}</svg>'


def _box_css(element):
    style = element['style']
    css = [
        f"left:{element['x']}px", f"top:{element['y']}px",
        f"width:{element['w']}px", f"height:{element['h']}px",
        f"opacity:{style['opacity']}",
    ]
    if element['rotation']:
        css.append(f"transform:rotate({element['rotation']}deg)")
    if element['type'] != 'shape':
        css.append(f"background:{style['background']}")
        if style['borderWidth']:
            css.append(f"border:{style['borderWidth']}px {style['borderStyle']} {style['borderColor']}")
        if style['radius']:
            css.append(f"border-radius:{style['radius']}px")
        if style['padding']:
            css.append(f"padding:{style['padding']}px")
    shadow = SHADOWS.get(style['shadow'])
    if shadow and element['type'] != 'shape':
        css.append(f'box-shadow:{shadow}')
    return css


def _text_css(style):
    css = [
        f"font-family:{style['fontFamily']}", f"font-size:{style['fontSize']}px",
        f"font-weight:{style['fontWeight']}", f"color:{style['color']}",
        f"text-align:{style['align']}", f"line-height:{style['lineHeight']}",
    ]
    if style['letterSpacing']:
        css.append(f"letter-spacing:{style['letterSpacing']}px")
    if style['italic']:
        css.append('font-style:italic')
    if style['underline']:
        css.append('text-decoration:underline')
    if style['uppercase']:
        css.append('text-transform:uppercase')
    return css


def _media_to_file_uri(src):
    """WeasyPrint lit les fichiers /media/ directement sur le disque (pas de requête HTTP)."""
    if src.startswith('data:'):
        return src
    relative = src[len(settings.MEDIA_URL):]
    path = (Path(settings.MEDIA_ROOT) / relative).resolve()
    if Path(settings.MEDIA_ROOT).resolve() not in path.parents:
        return ''
    return path.as_uri()


def _field_html(element, for_pdf, interactive, answers):
    """Champ de formulaire : vrai contrôle dans le portail, boîte à remplir dans le PDF."""
    style = element['style']
    esc = lambda v: html.escape(str(v or ''), quote=True)
    name = f"f_{element['id']}"
    value = (answers or {}).get(element['id'], '')
    ftype = element['fieldType']
    radius = style['fieldRadius']
    control_css = (f"background:{style['fieldBg']};border:1px solid {style['fieldBorder']};border-radius:{radius}px;"
                   f"color:inherit;font:inherit;padding:6px 10px;width:100%;box-sizing:border-box;")
    label = ''
    if element['showLabel'] and element['label']:
        star = f' <span style="color:{style["accent"]}">*</span>' if element['required'] else ''
        label = f'<div class="fld-label" style="color:{style["labelColor"]};font-weight:600;margin-bottom:5px">{esc(element["label"])}{star}</div>'
    required = ' required' if element['required'] and interactive else ''
    disabled = '' if interactive else ' disabled'
    if ftype in ('radio', 'checkbox'):
        chosen = value if isinstance(value, list) else ([value] if value else [])
        mark_shape = '50%' if ftype == 'radio' else '4px'
        items = []
        for index, option in enumerate(element['options'] or ['Option']):
            if interactive or not for_pdf:
                checked = ' checked' if option in chosen else ''
                req = required if ftype == 'radio' and index == 0 else ''
                items.append(f'<label class="fld-opt"><input type="{ftype}" name="{name}" value="{esc(option)}"{checked}{req}{disabled} '
                             f'style="accent-color:{style["accent"]}"> <span>{esc(option)}</span></label>')
            else:
                filled = f'background:{style["accent"]};' if option in chosen else ''
                items.append(f'<div class="fld-opt"><span style="display:inline-block;width:12px;height:12px;border:1.5px solid {style["fieldBorder"]};'
                             f'border-radius:{mark_shape};vertical-align:-1px;margin-right:6px;{filled}"></span>{esc(option)}</div>')
        return label + f'<div class="fld-opts">{"".join(items)}</div>'
    if ftype == 'select':
        if interactive or not for_pdf:
            opts = ''.join(f'<option{" selected" if o == value else ""}>{esc(o)}</option>' for o in element['options'])
            return label + (f'<select name="{name}" style="{control_css}"{required}{disabled}>'
                            f'<option value="">{esc(element["placeholder"] or "Choisir…")}</option>{opts}</select>')
        return label + f'<div style="{control_css}min-height:34px">{esc(value) or "&nbsp;"} <span style="float:right;color:#9ca3af">▾</span></div>'
    if ftype == 'textarea':
        if interactive or not for_pdf:
            return label + (f'<textarea name="{name}" placeholder="{esc(element["placeholder"])}" style="{control_css}flex:1;resize:none;min-height:60px"'
                            f'{required}{disabled}>{esc(value)}</textarea>')
        return label + f'<div style="{control_css}flex:1;min-height:60px;white-space:pre-wrap">{esc(value)}</div>'
    input_type = {'email': 'email', 'phone': 'tel', 'number': 'number', 'date': 'date'}.get(ftype, 'text')
    if interactive or not for_pdf:
        return label + (f'<input type="{input_type}" name="{name}" value="{esc(value)}" placeholder="{esc(element["placeholder"])}" '
                        f'style="{control_css}"{required}{disabled}>')
    return label + f'<div style="{control_css}min-height:34px">{esc(value) or "&nbsp;"}</div>'


def _render_element(element, resolve, for_pdf=True, interactive=False, answers=None, sources=None):
    style = element['style']
    css = _box_css(element)
    kind = element['type']
    if kind == 'field':
        field_css = [c for c in css if not c.startswith(('background', 'border', 'box-shadow'))] + _text_css(style)
        field_css += ['display:flex', 'flex-direction:column']
        outer = [c for c in css if c.startswith(('background', 'border', 'box-shadow'))]
        return f'<div class="el el-field" style="{";".join(field_css + outer)}">{_field_html(element, for_pdf, interactive, answers)}</div>'
    if kind == 'button':
        if for_pdf:
            return ''  # un bouton d'envoi n'a pas de sens sur papier
        css += _text_css(style) + ['display:flex', 'align-items:center', 'justify-content:center', 'cursor:pointer']
        tag = 'button type="submit"' if interactive else 'div'
        end = 'button' if interactive else 'div'
        return f'<{tag} class="el el-button" style="{";".join(css)}">{html.escape(element["text"])}</{end}>'
    if kind == 'text':
        css += _text_css(style)
        justify = {'top': 'flex-start', 'middle': 'center', 'bottom': 'flex-end'}[style['valign']]
        css += ['display:flex', 'flex-direction:column', f'justify-content:{justify}']
        return f'<div class="el el-text" style="{";".join(css)}"><div>{resolve(element["html"])}</div></div>'
    if kind == 'shape':
        svg = _shape_svg(element['shape'], element['w'], element['h'], style, element.get('paths'))
        return f'<div class="el el-shape" style="{";".join(css)}">{svg}</div>'
    if kind == 'image':
        # PDF : lecture directe du fichier ; navigateur (portail, aperçus) : URL /media/ telle quelle.
        src = (_media_to_file_uri(element['src']) if for_pdf else element['src']) if element['src'] else ''
        if not src:
            return ''
        radius = f"border-radius:{style['radius']}px;" if style['radius'] else ''
        return (
            f'<div class="el" style="{";".join(css)};overflow:hidden">'
            f'<img src="{html.escape(src, quote=True)}" style="width:100%;height:100%;object-fit:{style["fit"]};{radius}"></div>'
        )
    if kind == 'table':
        css += _text_css(style)
        return f'<div class="el el-table" style="{";".join(css)}">{_table_html(element, resolve, sources)}</div>'
    return ''


def render_canvas_html(canvas_data, *, page_format='A4', orientation='portrait', resolve=lambda value: value, answers=None,
                       sources=None):
    data = clean_canvas_data(canvas_data)
    width, height = page_size_px(page_format, orientation)
    pages_html = []
    for page in data['pages']:
        elements = ''.join(_render_element(e, resolve, answers=answers, sources=sources) for e in page['elements'] if not e['hidden'])
        pages_html.append(f'<section class="page" style="background:{page["background"]}">{elements}</section>')
    # Polices web de l'éditeur : sans elles WeasyPrint retombe sur une police système
    # plus large et les textes se mettent à la ligne différemment de l'aperçu.
    # URL fixe (jamais fournie par l'utilisateur) ; hors ligne, la police système prend le relais.
    fonts_link = (
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=Inter:ital,wght@0,300..800;1,300..800&family=Manrope:wght@300..800'
        '&family=Newsreader:ital,wght@0,400..700;1,400..700&display=swap">'
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">{fonts_link}<style>
@page {{ size: {width}px {height}px; margin: 0; }}
html, body {{ margin: 0; padding: 0; }}
.page {{ position: relative; width: {width}px; height: {height}px; overflow: hidden; page-break-after: always; }}
.page:last-child {{ page-break-after: auto; }}
.el {{ position: absolute; box-sizing: border-box; overflow: hidden; word-wrap: break-word; }}
/* Textes et tableaux ne sont jamais rognés : un léger écart de métriques de police
   entre navigateur et PDF ne doit pas faire disparaître une ligne. */
.el-text, .el-table {{ overflow: visible; }}
.el-text p, .el-text h1, .el-text h2, .el-text h3, .el-text ul, .el-text ol {{ margin: 0; }}
.el-text h1 {{ font-size: 1.6em; }} .el-text h2 {{ font-size: 1.3em; }} .el-text h3 {{ font-size: 1.1em; }}
.el table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
.el svg {{ display: block; overflow: visible; }}
.el-shape {{ overflow: visible; }}
.el-field {{ overflow: visible; }} .fld-opt {{ margin: 2px 0; }}
a {{ color: inherit; }}
</style></head><body>{''.join(pages_html)}</body></html>"""


# --------------------------------------------------------------------------- #
# Rendu navigateur (portail client, vignettes de la galerie)
# --------------------------------------------------------------------------- #

WEB_CANVAS_CSS = """
@media print { * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; } }
.cv-page { position: relative; overflow: hidden; background: #fff; }
.cv-page .el { position: absolute; box-sizing: border-box; overflow: hidden; word-wrap: break-word; }
.cv-page .el-text, .cv-page .el-table { overflow: visible; }
.cv-page .el-text p, .cv-page .el-text h1, .cv-page .el-text h2, .cv-page .el-text h3,
.cv-page .el-text ul, .cv-page .el-text ol { margin: 0; }
.cv-page .el-text ul { list-style: disc; padding-left: 1.3em; }
.cv-page .el-text h1 { font-size: 1.6em; font-weight: 700; } .cv-page .el-text h2 { font-size: 1.3em; font-weight: 700; }
.cv-page .el-text h3 { font-size: 1.1em; font-weight: 700; } .cv-page .el-text strong, .cv-page .el-text b { font-weight: 700; }
.cv-page .el-text ol { list-style: decimal; padding-left: 1.3em; }
.cv-page .el table { width: 100%; border-collapse: collapse; table-layout: fixed; }
.cv-page .el svg { display: block; overflow: visible; }
.cv-page .el-shape { overflow: visible; }
.cv-page .el-field { overflow: visible; }
.cv-page .fld-opts { display: flex; flex-direction: column; gap: 4px; }
.cv-page .fld-opt { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.cv-page .el-field input:focus, .cv-page .el-field select:focus, .cv-page .el-field textarea:focus { outline: 2px solid rgba(109,40,217,.25); outline-offset: 1px; }
.cv-page button.el-button { border-style: solid; }
.cv-page button.el-button:hover { filter: brightness(.95); }
"""


def form_fields(canvas_data):
    """Champs de formulaire d'un document, dans l'ordre des pages : [element, …]."""
    data = clean_canvas_data(canvas_data)
    return [e for page in data['pages'] for e in sorted(page['elements'], key=lambda el: (el['y'], el['x'])) if e['type'] == 'field' and not e['hidden']]


def read_form_answers(canvas_data, post):
    """Réponses postées depuis le portail : ({id: valeur}, {id: erreur})."""
    answers, errors = {}, {}
    for field in form_fields(canvas_data):
        key = f"f_{field['id']}"
        if field['fieldType'] == 'checkbox':
            value = [v for v in post.getlist(key) if v in field['options']][:20]
        else:
            value = (post.get(key) or '').strip()[:5000]
            if field['fieldType'] in ('select', 'radio') and value and value not in field['options']:
                errors[field['id']] = 'Choix invalide.'
            if field['fieldType'] == 'email' and value and ('@' not in value or ' ' in value):
                errors[field['id']] = 'Adresse email invalide.'
        if field['required'] and not value:
            errors[field['id']] = 'Champ obligatoire.'
        answers[field['id']] = value
    return answers, errors


def render_canvas_pages(canvas_data, *, page_format='A4', orientation='portrait', resolve=lambda value: value, limit=None,
                        interactive=False, answers=None, sources=None):
    """
    Pages du canvas en HTML pour le navigateur : [{'width', 'height', 'html'}].
    Chaque page est un bloc `.cv-page` positionné en px CSS ; l'appelant le met à
    l'échelle (vignette, portail responsive) avec un transform. Voir WEB_CANVAS_CSS.
    """
    data = clean_canvas_data(canvas_data)
    width, height = page_size_px(page_format, orientation)
    pages = []
    for page in data['pages'][:limit]:
        elements = ''.join(_render_element(e, resolve, for_pdf=False, interactive=interactive, answers=answers, sources=sources)
                           for e in page['elements'] if not e['hidden'])
        pages.append({
            'width': width, 'height': height,
            'html': f'<div class="cv-page" style="width:{width}px;height:{height}px;background:{page["background"]}">{elements}</div>',
        })
    return pages


# --------------------------------------------------------------------------- #
# Conversion des anciens documents « texte continu » en canvas
# --------------------------------------------------------------------------- #

_BLOCK_SPLIT_RE = re.compile(
    r'(?=<(?:p|h1|h2|h3|h4|ul|ol|table|blockquote|div|hr)\b)', re.IGNORECASE,
)
_TAG_RE = re.compile(r'<[^>]+>')


def _text_length(fragment):
    return len(html.unescape(_TAG_RE.sub(' ', fragment)).strip())


def flow_to_canvas(header_html, body_html, footer_html, style_config, *, page_format='A4', orientation='portrait'):
    """
    Transforme un document en sections (en-tête / corps / pied) en pages canvas :
    l'en-tête et le pied sont répétés sur chaque page, le corps est découpé par blocs
    (paragraphes, titres, listes, tableaux) pour tenir dans la hauteur de la page.
    """
    style_config = style_config or {}
    width, height = page_size_px(page_format, orientation)
    margin = 56
    font = style_config.get('font_family') if style_config.get('font_family') in FONT_FAMILIES else DEFAULT_FONT
    color = style_config.get('text_color') or '#1f2937'
    background = style_config.get('page_background_color') or '#ffffff'
    header_html, body_html, footer_html = (header_html or '').strip(), (body_html or '').strip(), (footer_html or '').strip()

    header_h = 80 if _text_length(header_html) else 0
    footer_h = 40 if _text_length(footer_html) else 0
    body_top = margin + (header_h + 24 if header_h else 0)
    body_h = height - body_top - margin - (footer_h + 16 if footer_h else 0)
    content_w = width - 2 * margin
    # Capacité approximative d'une page en caractères (texte 13 px, interligne 1.6).
    chars_per_line = max(20, int(content_w / (13 * 0.52)))
    lines_per_page = max(5, int(body_h / (13 * 1.6)))
    budget = chars_per_line * lines_per_page

    blocks = [b for b in _BLOCK_SPLIT_RE.split(body_html) if b.strip()] or ['']
    chunks, current, used = [], [], 0
    for block in blocks:
        cost = _text_length(block) + chars_per_line  # chaque bloc commence une ligne
        if '<table' in block.lower():
            cost += block.lower().count('<tr') * chars_per_line
        if current and used + cost > budget:
            chunks.append(''.join(current))
            current, used = [], 0
        current.append(block)
        used += cost
    chunks.append(''.join(current))

    pages = []
    for chunk in chunks:
        elements = []
        if header_h:
            elements.append({
                'type': 'text', 'name': 'En-tête', 'x': margin, 'y': margin, 'w': content_w, 'h': header_h,
                'html': sanitize_html(header_html), 'style': {'fontFamily': font, 'color': color, 'fontSize': 14},
            })
        elements.append({
            'type': 'text', 'name': 'Corps', 'x': margin, 'y': body_top, 'w': content_w, 'h': body_h,
            'html': sanitize_html(chunk), 'style': {'fontFamily': font, 'color': color, 'fontSize': 13, 'lineHeight': 1.6},
        })
        if footer_h:
            elements.append({
                'type': 'text', 'name': 'Pied de page', 'x': margin, 'y': height - margin - footer_h, 'w': content_w,
                'h': footer_h, 'html': sanitize_html(footer_html),
                'style': {'fontFamily': font, 'color': '#6b7280', 'fontSize': 10, 'align': 'center'},
            })
        pages.append({'background': background, 'elements': elements})
    return clean_canvas_data({'pages': pages})
