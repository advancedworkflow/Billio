"""
Modèles en « mise en page libre » : des blocs positionnés à la souris sur une page A4.

La page a deux zones libres, l'**en-tête** et le **pied**, séparées par le tableau des lignes
(pleine largeur, qui s'allonge avec le nombre de lignes : indispensable pour les factures longues
et le PDF). Chaque bloc a une position (x, y) en pixels dans sa zone, une largeur, un alignement,
une taille de texte et une couleur (normale ou accent).

La mise en page est stockée dans `layout_config['canvas']` ; `build()` en tire le HTML et le CSS
du modèle (mêmes variables et mêmes filtres que les modèles pro), si bien que le rendu des
factures, des aperçus et des PDF ne change pas.
"""
import html
import re
import uuid

from .pro_templates import (
    CLIENT, COMMON_DEFAULTS, COMMON_SCHEMA, FOOTER, ISSUER, LOGO, META_ROWS, PAYMENT, TOTALS,
    _css, _fill, _root,
)

from .canvas_table import TABLE_CSS, build_items, clean_table

PREFIX = 'cv-'
PAGE_WIDTH = 794          # A4 à 96 ppp
PAGE_PADDING = 52         # marges latérales du tableau des lignes
BANDS = ('header', 'footer')
MAX_BLOCKS = 40
MAX_BAND_HEIGHT = 900

# type : (libellé, largeur par défaut, zone conseillée, source HTML)
BLOCKS = {
    'logo': ('Logo', 200, 'header', LOGO),
    'title': ('Titre et numéro', 260, 'header',
              '<p class="{p}title">{{ document_kind }}</p><p class="{p}number">N° {{ invoice_number }}</p>'),
    'issuer': ('Votre entreprise', 300, 'header', ISSUER),
    'client': ('Client', 300, 'header', CLIENT),
    # Dates seules : le numéro figure déjà sous le titre.
    'meta': ('Dates', 260, 'header', '<table class="{p}meta">' + META_ROWS.split('\n', 1)[1] + '</table>'),
    'total_due': ('Montant à régler', 240, 'header',
                  '<p class="{p}label">{% if document_type == \'quote\' %}Total TTC{% else %}Net à payer{% endif %}</p>'
                  '<p class="{p}big">{{ total_amount|money:currency }}</p>'),
    'subject': ('Objet', 690, 'header',
                '{% if subject %}<p class="{p}label">Objet</p><p class="{p}strong">{{ subject }}</p>{% endif %}'),
    'totals': ('Totaux', 300, 'footer', TOTALS),
    'payment': ('Règlement et banque', 690, 'footer', PAYMENT),
    'legal': ('Mentions légales', 690, 'footer', FOOTER),
    'text': ('Texte libre', 300, 'header', None),
    'divider': ('Trait', 690, 'header', '<hr class="{p}hr">'),
    # Forme décorative (bandeau, cercle, diagonale…) : dessinée derrière les blocs, peut toucher les bords.
    'shape': ('Forme', 200, 'header', None),
}
SHAPES = ('rect', 'ellipse', 'triangle', 'diagonal', 'line')

# Couleurs-variables du modèle : accent (variable accent_color), secondaire et texte (dans la mise en page).
COLOR_TOKENS = ('', 'accent', 'secondary', 'ink', 'white', 'black', 'muted')
_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
DEFAULT_COLORS = {'secondary': '#f3f4f6', 'ink': '#1f2937'}

# Éléments indispensables d'une facture (en France : art. 242 nonies A du CGI, L441-9 du Code de commerce).
MANDATORY = {
    'title': 'Titre et numéro',
    'issuer': 'Votre entreprise',
    'client': 'Client',
    'meta': 'Dates',
    'totals': 'Totaux',
    'payment': 'Règlement et banque',
    'legal': 'Mentions légales',
}
ALIGNS = ('left', 'center', 'right')
SIZES = {'s': 11, 'm': 12.5, 'l': 15}

CANVAS_CSS = """
.{p}doc { width: 794px; margin: 0 auto; }
.{p}doc { color: var(--ink, #1f2937); }
.{p}band { box-sizing: border-box; width: 794px; position: relative; overflow: hidden; }
.{p}shape { position: absolute; z-index: 0; }
.{p}row { position: relative; z-index: 1; }
.{p}box { box-sizing: border-box; }
.{p}box.has-color * { color: inherit !important; }
.{p}row { font-size: 0; line-height: 0; white-space: nowrap; }
.{p}b { display: inline-block; vertical-align: top; box-sizing: border-box; white-space: normal; font-size: 12.5px; line-height: 1.5; }
.{p}b.al-center { text-align: center; }
.{p}b.al-right { text-align: right; }
.{p}b.al-right .{p}totals, .{p}b.al-right table.{p}meta { margin-left: auto; }
.{p}b.al-center .{p}totals, .{p}b.al-center table.{p}meta { margin-left: auto; margin-right: auto; }
.{p}b.sz-s { font-size: 11px; }
.{p}b.sz-l { font-size: 15px; }
.{p}b.is-accent, .{p}b.is-accent .{p}strong, .{p}b.is-accent .{p}big, .{p}b.is-accent .{p}title { color: var(--accent); }
.{p}b.is-accent .{p}hr { border-top-color: var(--accent); }
.{p}box.has-color .{p}hr { border-top-color: currentColor; }
.{p}title { font-size: 2.3em; font-weight: 800; letter-spacing: -0.02em; color: #111827; line-height: 1.05; }
.{p}number { margin-top: 6px !important; color: #6b7280; font-weight: 500; }
.{p}big { font-size: 2em; font-weight: 800; color: #111827; letter-spacing: -0.01em; line-height: 1.2; }
.{p}hr { border: 0; border-top: 2px solid #111827; margin: 0; }
.{p}text { white-space: pre-line; }
.{p}meta { border-collapse: collapse; }
.{p}meta td { padding: 2px 0; }
.{p}meta td:first-child { color: #6b7280; padding-right: 16px; }
.{p}meta td:last-child { font-weight: 600; color: #111827; text-align: right; }
.{p}body { padding: 0 52px; }
.{p}body .{p}items { margin-top: 0; }
.{p}b .{p}totals { margin-top: 0; }
.{p}b .{p}notes, .{p}b .{p}payment, .{p}b .{p}footer { margin-top: 0; }
.{p}b .{p}footer { border-top: 0; padding-top: 0; }
.{p}b .{p}sign { margin-top: 16px; width: 46%; }
"""


def _new_id():
    return 'b' + uuid.uuid4().hex[:8]


def _int(value, default, low, high):
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _color(value, default=''):
    value = str(value or '')
    return value if value in COLOR_TOKENS or _HEX.match(value) else default


def clean_colors(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {key: raw.get(key) if _HEX.match(str(raw.get(key) or '')) else default for key, default in DEFAULT_COLORS.items()}


def css_color(token, colors=None):
    """Jeton de couleur → valeur CSS (variables du modèle ou couleur fixe)."""
    return {'accent': 'var(--accent)', 'secondary': 'var(--c2)', 'ink': 'var(--ink)', 'white': '#ffffff',
            'black': '#111827', 'muted': '#6b7280'}.get(token, token if _HEX.match(token or '') else '')


def svg_color(token, colors):
    """Comme css_color, mais résolu (les SVG des PDF ne lisent pas les variables CSS)."""
    if token == 'accent' or not token:
        return '{{ accent_color }}'
    if token in ('secondary', 'ink'):
        return colors[token]
    return css_color(token, colors)


def clean(canvas):
    """Valide et normalise une mise en page reçue du navigateur (types connus, bornes)."""
    canvas = canvas if isinstance(canvas, dict) else {}
    heights = {band: _int((canvas.get('heights') or {}).get(band), 300 if band == 'header' else 260, 60, MAX_BAND_HEIGHT)
               for band in BANDS}
    blocks = []
    for raw in (canvas.get('blocks') or [])[:MAX_BLOCKS]:
        if not isinstance(raw, dict) or raw.get('type') not in BLOCKS:
            continue
        band = raw.get('band') if raw.get('band') in BANDS else BLOCKS[raw['type']][2]
        width = _int(raw.get('w'), BLOCKS[raw['type']][1], 40, PAGE_WIDTH)
        block = {
            'id': re.sub(r'[^a-z0-9]', '', str(raw.get('id') or ''))[:12] or _new_id(),
            'type': raw['type'],
            'band': band,
            'x': _int(raw.get('x'), PAGE_PADDING, 0, PAGE_WIDTH - 40),
            'y': _int(raw.get('y'), 40, 0, heights[band] - 10),
            'w': min(width, PAGE_WIDTH - _int(raw.get('x'), PAGE_PADDING, 0, PAGE_WIDTH - 40)),
            'align': raw.get('align') if raw.get('align') in ALIGNS else 'left',
            'size': raw.get('size') if raw.get('size') in SIZES else 'm',
            'accent': bool(raw.get('accent')),
        }
        if block['type'] == 'text':
            block['text'] = str(raw.get('text') or '')[:1500]
        # Style libre du bloc : couleur du texte, fond, marge intérieure, arrondi.
        block['color'] = _color(raw.get('color'))
        block['bg'] = _color(raw.get('bg'))
        block['pad'] = _int(raw.get('pad'), 0, 0, 40)
        block['radius'] = _int(raw.get('radius'), 0, 0, 60)
        if block['type'] == 'shape':
            block['shape'] = raw.get('shape') if raw.get('shape') in SHAPES else 'rect'
            block['h'] = _int(raw.get('h'), 120, 2, MAX_BAND_HEIGHT)
            block['fill'] = _color(raw.get('fill'), 'accent') or 'accent'
            block['opacity'] = _int(raw.get('opacity'), 100, 5, 100)
            block['x'] = _int(raw.get('x'), 0, 0, PAGE_WIDTH - 2)
            block['w'] = min(_int(raw.get('w'), 200, 2, PAGE_WIDTH), PAGE_WIDTH - block['x'])
        blocks.append(block)
    # Tableau des lignes : présent sauf retrait explicite (nouveau modèle vide).
    return {'version': 1, 'heights': heights, 'blocks': blocks, 'items': canvas.get('items') is not False,
            'table': clean_table(canvas.get('table')), 'colors': clean_colors(canvas.get('colors'))}


def missing_mandatory(layout):
    """Libellés des éléments obligatoires d'une facture absents de la mise en page."""
    present = {b['type'] for b in layout.get('blocks', [])}
    missing = [label for key, label in MANDATORY.items() if key not in present]
    if layout.get('items') is False:
        missing.insert(0, 'Tableau des lignes')
    return missing


def _escape_text(text):
    """Texte libre : HTML échappé et accolades neutralisées (pas de balise de gabarit possible)."""
    return html.escape(text).replace('{', '&#123;').replace('}', '&#125;').replace('%', '&#37;')


def block_inner(block):
    if block['type'] == 'text':
        inner = f'<p class="{PREFIX}text">{_escape_text(block.get("text") or "")}</p>'
    else:
        inner = _fill(BLOCKS[block['type']][3], PREFIX)
    style = []
    if block.get('color'):
        style.append(f'color:{css_color(block["color"])}')
    if block.get('bg'):
        style.append(f'background:{css_color(block["bg"])}')
    if block.get('pad'):
        style.append(f'padding:{block["pad"]}px')
    if block.get('radius'):
        style.append(f'border-radius:{block["radius"]}px')
    if not style:
        return inner
    classes = f'{PREFIX}box' + (' has-color' if block.get('color') else '')
    return f'<div class="{classes}" style="{";".join(style)}">{inner}</div>'


def shape_svg(block, colors):
    """Forme vectorielle (même dessin dans l'éditeur, l'aperçu et le PDF)."""
    w, h = block['w'], block['h']
    fill = svg_color(block['fill'], colors)
    paint = f'fill="{fill}" fill-opacity="{block["opacity"] / 100:.2f}"'
    kind = block['shape']
    if kind == 'ellipse':
        body = f'<ellipse cx="{w / 2}" cy="{h / 2}" rx="{w / 2}" ry="{h / 2}" {paint}/>'
    elif kind == 'triangle':
        body = f'<polygon points="0,0 {w},0 0,{h}" {paint}/>'
    elif kind == 'diagonal':
        body = f'<polygon points="0,0 {w},0 {w},{round(h * 0.55)} 0,{h}" {paint}/>'
    else:  # rect, line
        radius = min(block.get('radius') or 0, h / 2, w / 2)
        body = f'<rect width="{w}" height="{h}" rx="{radius}" {paint}/>'
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
            f'xmlns="http://www.w3.org/2000/svg" style="display:block">{body}</svg>')


ROW_SNAP = 24  # blocs dont le haut est à moins de 24 px l'un de l'autre : même rangée


def _rows(blocks):
    """Regroupe les blocs d'une zone en rangées (même hauteur de départ, à ROW_SNAP près)."""
    rows = []
    for block in sorted(blocks, key=lambda b: (b['y'], b['x'])):
        if rows and block['y'] - rows[-1]['y'] < ROW_SNAP:
            rows[-1]['blocks'].append(block)
        else:
            rows.append({'y': block['y'], 'blocks': [block]})
    return rows


def _band_html(blocks, height, band, colors=None):
    """
    Zone rendue en rangées : chaque rangée garde les positions horizontales et l'écart vertical
    choisis dans l'éditeur (hauteur minimale), mais s'agrandit si son contenu est plus haut que
    prévu (devis avec délais, longue adresse…) au lieu de chevaucher la suivante.
    """
    colors = colors or DEFAULT_COLORS
    shapes = [b for b in blocks if b['type'] == 'shape']
    rows = _rows([b for b in blocks if b['type'] != 'shape'])
    parts = [f'<div class="{PREFIX}shape" style="left:{b["x"]}px;top:{b["y"]}px;width:{b["w"]}px;height:{b["h"]}px">'
             f'{shape_svg(b, colors)}</div>' for b in shapes]
    for index, row in enumerate(rows):
        next_y = rows[index + 1]['y'] if index + 1 < len(rows) else height
        cells, cursor = [], 0
        for block in sorted(row['blocks'], key=lambda b: b['x']):
            margin = max(0, block['x'] - cursor)
            cursor += margin + block['w']
            classes = f"{PREFIX}b {PREFIX}b-{block['type']} al-{block['align']} sz-{block['size']}"
            if block['accent']:
                classes += ' is-accent'
            cells.append(f'<div class="{classes}" style="margin-left:{margin}px;width:{block["w"]}px;'
                         f'padding-top:{block["y"] - row["y"]}px">{block_inner(block)}</div>')
        parts.append(f'<div class="{PREFIX}row" style="min-height:{max(0, next_y - row["y"])}px">' + ''.join(cells) + '</div>')
    top = rows[0]['y'] if rows else 0  # les formes (absolues) partent du haut de la zone, marge comprise
    return (f'<div class="{PREFIX}band {PREFIX}band-{band}" style="min-height:{height}px;padding-top:{top}px">'
            + ''.join(parts) + '</div>')


def build(canvas):
    """(html, css) du modèle à partir d'une mise en page déjà nettoyée par `clean`."""
    colors = canvas.get('colors') or DEFAULT_COLORS
    bands = {band: _band_html([b for b in canvas['blocks'] if b['band'] == band], canvas['heights'][band], band, colors)
             for band in BANDS}
    body = f'<div class="{PREFIX}body">{build_items(canvas.get("table"), PREFIX)}</div>' if canvas.get('items', True) else ''
    inner = bands['header'] + body + bands['footer']
    return _root(PREFIX, inner, f' --c2: {colors["secondary"]}; --ink: {colors["ink"]};'), _css(PREFIX, CANVAS_CSS + TABLE_CSS)


def schema_and_defaults(accent):
    return {'fields': COMMON_SCHEMA}, dict(COMMON_DEFAULTS, accent_color=accent)


def palette():
    """Blocs proposés dans l'éditeur (type, libellé, largeur, zone conseillée)."""
    return [{'type': key, 'label': spec[0], 'w': spec[1], 'band': spec[2]} for key, spec in BLOCKS.items() if key != 'shape']


def _b(type_, band, x, y, w=None, **extra):
    block = {'id': _new_id(), 'type': type_, 'band': band, 'x': x, 'y': y, 'w': w or BLOCKS[type_][1],
             'align': extra.pop('align', 'left'), 'size': extra.pop('size', 'm'), 'accent': extra.pop('accent', False)}
    block.update(extra)
    return block


# --------------------------------------------------------------------------- #
# Modèles de la galerie construits en mise en page libre (modifiables à la souris)
# --------------------------------------------------------------------------- #

def _layout(heights, blocks):
    return clean({'heights': {'header': heights[0], 'footer': heights[1]}, 'blocks': blocks})


CANVAS_TEMPLATES = [
    {
        'slug': 'libre-classique', 'title': 'Classique', 'accent': '#111827',
        'description': 'La disposition la plus courante : logo et titre en haut, parties côte à côte.',
        'tags': ['libre', 'classique', 'facture', 'devis'],
        'canvas': _layout((330, 300), [
            _b('logo', 'header', 52, 44),
            _b('title', 'header', 482, 44, 260, align='right'),
            _b('issuer', 'header', 52, 150, 300),
            _b('client', 'header', 442, 150, 300),
            _b('meta', 'header', 482, 98, 260, align='right', size='s'),
            _b('totals', 'footer', 442, 20, 300),
            _b('payment', 'footer', 52, 150, 690),
            _b('legal', 'footer', 52, 250, 690, size='s'),
        ]),
    },
    {
        'slug': 'libre-studio', 'title': 'Studio', 'accent': '#7c3aed',
        'description': 'Logo centré, titre en couleur et montant à régler mis en avant.',
        'tags': ['libre', 'créatif', 'centré', 'facture', 'devis'],
        'canvas': _layout((380, 300), [
            _b('logo', 'header', 297, 36, 200, align='center'),
            _b('title', 'header', 197, 112, 400, align='center', accent=True),
            _b('divider', 'header', 347, 196, 100, accent=True),
            _b('client', 'header', 52, 226, 260),
            _b('meta', 'header', 312, 226, 200, size='s'),
            _b('total_due', 'header', 532, 226, 210, align='right', accent=True),
            _b('issuer', 'footer', 52, 20, 300, size='s'),  # adresse du vendeur : mention obligatoire
            _b('totals', 'footer', 442, 20, 300),
            _b('payment', 'footer', 52, 150, 690),
            _b('legal', 'footer', 52, 250, 690, size='s', align='center'),
        ]),
    },
    {
        'slug': 'libre-minimal', 'title': 'Minimal', 'accent': '#0f766e',
        'description': 'Beaucoup de blanc, petits caractères et un seul filet de couleur.',
        'tags': ['libre', 'minimal', 'facture', 'devis'],
        'canvas': _layout((300, 280), [
            _b('title', 'header', 52, 48, 300, size='s'),
            _b('logo', 'header', 542, 40, 200, align='right'),
            _b('divider', 'header', 52, 118, 690, accent=True),
            _b('issuer', 'header', 52, 142, 220, size='s'),
            _b('client', 'header', 292, 142, 220, size='s'),
            _b('meta', 'header', 532, 142, 210, size='s', align='right'),
            _b('totals', 'footer', 442, 20, 300, size='s'),
            _b('payment', 'footer', 52, 140, 690, size='s'),
            _b('legal', 'footer', 52, 236, 690, size='s'),
        ]),
    },
    {
        'slug': 'libre-artisan', 'title': 'Artisan', 'accent': '#b45309',
        'description': 'Pensé pour les chantiers : objet du devis en évidence, signature en bas.',
        'tags': ['libre', 'artisan', 'btp', 'facture', 'devis'],
        'canvas': _layout((400, 320), [
            _b('logo', 'header', 52, 40),
            _b('issuer', 'header', 52, 112, 300, size='s'),
            _b('title', 'header', 452, 40, 290, align='right', accent=True),
            _b('meta', 'header', 482, 124, 260, align='right'),
            _b('client', 'header', 442, 206, 300),
            _b('subject', 'header', 52, 320, 690),
            _b('totals', 'footer', 442, 20, 300),
            _b('payment', 'footer', 52, 150, 690),
            _b('legal', 'footer', 52, 270, 690, size='s'),
        ]),
    },
    {
        'slug': 'libre-conseil', 'title': 'Conseil', 'accent': '#1d4ed8',
        'description': 'Sobre et structuré, avec un mot d’introduction personnalisable.',
        'tags': ['libre', 'conseil', 'formation', 'facture', 'devis'],
        'canvas': _layout((420, 300), [
            _b('logo', 'header', 52, 44),
            _b('meta', 'header', 482, 44, 260, align='right', size='s'),
            _b('title', 'header', 52, 128, 400, accent=True),
            _b('client', 'header', 52, 214, 300),
            _b('issuer', 'header', 442, 214, 300, size='s', align='right'),
            _b('text', 'header', 52, 346, 690, text='Bonjour,\nveuillez trouver ci-dessous le détail de notre intervention.', size='s'),
            _b('totals', 'footer', 442, 20, 300),
            _b('payment', 'footer', 52, 150, 690),
            _b('legal', 'footer', 52, 250, 690, size='s'),
        ]),
    },
]


def template_fields(spec):
    """Champs MarketplaceTemplate pour un modèle en mise en page libre."""
    html_source, css = build(spec['canvas'])
    schema, defaults = schema_and_defaults(spec['accent'])
    return {
        'title': spec['title'],
        'description': spec['description'],
        'demo_html': html_source,
        'html_structure': html_source,
        'css_styles': css,
        'layout_config': {'variable_schema': schema, 'canvas': spec['canvas']},
        'style_config': {'variables_defaults': defaults},
        'tags': spec['tags'],
        'compatible_types': ['invoice', 'quote'],
        'template_type': 'system',
        'is_free': True,
        'is_active': True,
        'is_approved': True,
        'price': 0,
    }


def default_canvas():
    """Point de départ pour convertir un modèle existant en mise en page libre."""
    return CANVAS_TEMPLATES[0]['canvas']
