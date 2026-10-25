"""
Modèles en « mise en page libre » : des blocs positionnés à la souris sur une page A4.

La page a deux zones libres, l'**en-tête** et le **pied**, séparées par le tableau des lignes
(pleine largeur, qui s'allonge avec le nombre de lignes : indispensable pour les factures longues
et le PDF). Chaque bloc a une position (x, y) en pixels dans sa zone, une largeur, un alignement,
une taille, une police, des couleurs (variables du modèle ou couleurs fixes), un fond, une bordure…

Un troisième plan, la **page**, reçoit les décors accrochés en haut ou en bas de la feuille
(bandeaux, vagues, cadre, bande latérale) : formes SVG et images, dessinées derrière le contenu.

La mise en page est stockée dans `layout_config['canvas']` ; `build()` en tire le HTML et le CSS
du modèle (mêmes variables et mêmes filtres que les modèles pro), si bien que le rendu des
factures, des aperçus et des PDF ne change pas. Rien de ce que tape l'utilisateur ne devient une
balise de gabarit : textes échappés, variables `{nom}` traduites par liste blanche.
"""
import re
import uuid

from . import canvas_shapes
from .canvas_table import (
    TABLE_CSS, _escape, build_items, clean_table, font_keys, render_tokens, valid_color,
)
from .pro_templates import (
    CLIENT, COMMON_DEFAULTS, COMMON_SCHEMA, FOOTER, ISSUER, LOGO, META_ROWS, PAYMENT, TOTALS,
    _css, _fill, _root,
)

PREFIX = 'cv-'
PAGE_WIDTH = 794          # A4 à 96 ppp
PAGE_HEIGHT = 1122        # hauteur d'une page A4 à 96 ppp (1122,5 px) : le document en fait au moins une
PAGE_PADDING = 52         # marges latérales du tableau des lignes
BANDS = ('header', 'footer')
LAYERS = BANDS + ('page',)
MAX_BLOCKS = 60
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
    # Décors : forme vectorielle ou image importée.
    'shape': ('Forme', 200, 'header', None),
    'image': ('Image', 200, 'header', None),
}
DECOR = ('shape', 'image')

# Variables utilisables dans un texte libre : {client}, {numero}, {total}…
DOC_VARIABLES = {
    'type': ('Facture / Devis', '{{ document_kind }}'),
    'numero': ('N° du document', '{{ invoice_number }}'),
    'date': ('Date', '{{ issue_date }}'),
    'echeance': ('Échéance', '{{ due_date }}'),
    'client': ('Client', '{{ client_name }}'),
    'entreprise': ('Votre entreprise', '{{ organization_name }}'),
    'adresse': ('Adresse', '{{ organization_address }}'),
    'ville': ('Code postal et ville', '{{ organization_postal_code }} {{ organization_city }}'),
    'email': ('E-mail', '{{ organization_email }}'),
    'telephone': ('Téléphone', '{{ organization_phone }}'),
    'siret': ('SIRET', '{{ organization_registration_number }}'),
    'tva_intra': ('N° de TVA', '{{ organization_tax_id }}'),
    'iban': ('IBAN', '{{ organization_iban }}'),
    'lien_paiement': ('Lien de paiement en ligne', '{{ payment_url }}'),
    'total_ht': ('Total HT', '{{ subtotal|money:currency }}'),
    'total': ('Total TTC', '{{ total_amount|money:currency }}'),
}

_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
DEFAULT_COLORS = {'secondary': '#f3f4f6', 'ink': '#1f2937', 'page': '#ffffff'}

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
SIZES = {'s': 11, 'm': 12.5, 'l': 15, 'xl': 19, 'xxl': 26}
FITS = ('contain', 'cover')

CANVAS_CSS = """
.{p}doc { width: 794px; margin: 0 auto; position: relative; min-height: 1122px; color: var(--ink, #1f2937); background: var(--page, #fff); }
.{p}band { box-sizing: border-box; width: 794px; position: relative; overflow: hidden; }
.{p}deco { position: absolute; z-index: 0; }
.{p}deco img, .{p}b img.{p}img { display: block; width: 100%; }
.{p}row { position: relative; z-index: 1; }
.{p}body { position: relative; z-index: 1; }
.{p}box { box-sizing: border-box; }
.{p}box.has-color * { color: inherit !important; }
.{p}box.has-color .{p}hr { border-top-color: currentColor; }
.{p}box.upper { text-transform: uppercase; }
.{p}box.hl .{p}grand td { background: var(--hl); color: #fff !important; border-top: 0; padding: 10px 12px; }
.{p}row { font-size: 0; line-height: 0; white-space: nowrap; }
.{p}b { display: inline-block; vertical-align: top; box-sizing: border-box; white-space: normal; font-size: 12.5px; line-height: 1.5; }
.{p}b.al-center { text-align: center; }
.{p}b.al-right { text-align: right; }
.{p}b.al-right .{p}totals, .{p}b.al-right table.{p}meta { margin-left: auto; }
.{p}b.al-center .{p}totals, .{p}b.al-center table.{p}meta { margin-left: auto; margin-right: auto; }
.{p}b.al-center img.{p}img { margin: 0 auto; }
.{p}b.al-right img.{p}img { margin-left: auto; }
.{p}b.sz-s { font-size: 11px; }
.{p}b.sz-l { font-size: 15px; }
.{p}b.sz-xl { font-size: 19px; }
.{p}b.sz-xxl { font-size: 26px; }
.{p}b.is-accent, .{p}b.is-accent .{p}strong, .{p}b.is-accent .{p}big, .{p}b.is-accent .{p}title { color: var(--accent); }
.{p}b.is-accent .{p}hr { border-top-color: var(--accent); }
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


_color = valid_color


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


def font_stack(key):
    from .preview import FONT_CHOICES
    return FONT_CHOICES[key][0] if key in FONT_CHOICES else ''


def clean_block(raw, heights):
    """Bloc validé, ou None si son type est inconnu."""
    if not isinstance(raw, dict) or raw.get('type') not in BLOCKS:
        return None
    kind = raw['type']
    layer = raw.get('band') if raw.get('band') in LAYERS else BLOCKS[kind][2]
    if layer == 'page' and kind not in DECOR:
        layer = BLOCKS[kind][2]
    decor = kind in DECOR
    x = _int(raw.get('x'), 0 if decor else PAGE_PADDING, 0, PAGE_WIDTH - 2)
    y_max = PAGE_HEIGHT if layer == 'page' else heights[layer] - 10
    block = {
        'id': re.sub(r'[^a-z0-9]', '', str(raw.get('id') or ''))[:12] or _new_id(),
        'type': kind,
        'band': layer,
        'x': x,
        'y': _int(raw.get('y'), 40, 0, y_max),
        'w': min(_int(raw.get('w'), BLOCKS[kind][1], 2 if decor else 40, PAGE_WIDTH), PAGE_WIDTH - x),
        'align': raw.get('align') if raw.get('align') in ALIGNS else 'left',
        'size': raw.get('size') if raw.get('size') in SIZES else 'm',
        'accent': bool(raw.get('accent')),
        # Style libre : couleur du texte, fond, bordure, marge intérieure, arrondi, police, casse, interlettrage.
        'color': _color(raw.get('color')),
        'bg': _color(raw.get('bg')),
        'border': _color(raw.get('border')),
        'bw': _int(raw.get('bw'), 1, 1, 6),
        'pad': _int(raw.get('pad'), 0, 0, 60),
        'radius': _int(raw.get('radius'), 0, 0, 80),
        'font': raw.get('font') if raw.get('font') in font_keys() else '',
        'upper': bool(raw.get('upper')),
        'tracking': _int(raw.get('tracking'), 0, 0, 40),
    }
    if layer == 'page':
        block['anchor'] = 'bottom' if raw.get('anchor') == 'bottom' else 'top'
    if kind == 'text':
        block['text'] = str(raw.get('text') or '')[:1500]
    if kind == 'totals':
        block['hl'] = _color(raw.get('hl'))
    if decor:
        block['h'] = _int(raw.get('h'), 120, 2, PAGE_HEIGHT)
        block['opacity'] = _int(raw.get('opacity'), 100, 5, 100)
    if kind == 'shape':
        block['shape'] = raw.get('shape') if raw.get('shape') in canvas_shapes.SHAPES else canvas_shapes.DEFAULT_SHAPE
        block['fill'] = _color(raw.get('fill'), 'accent') or 'accent'
        block['fill2'] = _color(raw.get('fill2'), 'secondary') or 'secondary'
        block['gradient'] = bool(raw.get('gradient'))
        block['flip_x'] = bool(raw.get('flip_x'))
        block['flip_y'] = bool(raw.get('flip_y'))
        block['thickness'] = _int(raw.get('thickness'), 6, 1, 60)
    if kind == 'image':
        block['asset'] = _int(raw.get('asset'), 0, 0, 2 ** 31)
        block['fit'] = raw.get('fit') if raw.get('fit') in FITS else 'contain'
        # Image de contenu (dans le flux, comme un logo) ou décor (derrière le texte, position libre).
        block['behind'] = bool(raw.get('behind')) or layer == 'page'
    return block


def clean(canvas):
    """Valide et normalise une mise en page reçue du navigateur (types connus, bornes)."""
    canvas = canvas if isinstance(canvas, dict) else {}
    heights = {band: _int((canvas.get('heights') or {}).get(band), 300 if band == 'header' else 260, 60, MAX_BAND_HEIGHT)
               for band in BANDS}
    blocks = [b for b in (clean_block(raw, heights) for raw in (canvas.get('blocks') or [])[:MAX_BLOCKS]) if b]
    # Tableau des lignes : présent sauf retrait explicite (nouveau modèle vide).
    return {'version': 2, 'heights': heights, 'blocks': blocks, 'items': canvas.get('items') is not False,
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
    return _escape(text)


def _image_tag(block, assets, height=None):
    src = (assets or {}).get(block.get('asset'))
    if not src:
        return ''
    style = [f'height:{height or block["h"]}px', f'object-fit:{block["fit"]}']
    if block.get('radius'):
        style.append(f'border-radius:{block["radius"]}px')
    if block.get('opacity', 100) < 100:
        style.append(f'opacity:{block["opacity"] / 100:.2f}')
    return f'<img class="{PREFIX}img" src="{src}" alt="" style="{";".join(style)}">'


def block_inner(block, assets=None):
    kind = block['type']
    if kind == 'text':
        inner = f'<p class="{PREFIX}text">{render_tokens(block.get("text") or "", DOC_VARIABLES)}</p>'
    elif kind == 'image':
        return _image_tag(block, assets)
    else:
        inner = _fill(BLOCKS[kind][3], PREFIX)
    style, classes = [], [f'{PREFIX}box']
    if block.get('color'):
        style.append(f'color:{css_color(block["color"])}')
        classes.append('has-color')
    if block.get('bg'):
        style.append(f'background:{css_color(block["bg"])}')
    if block.get('border'):
        style.append(f'border:{block.get("bw", 1)}px solid {css_color(block["border"])}')
    if block.get('pad'):
        style.append(f'padding:{block["pad"]}px')
    if block.get('radius'):
        style.append(f'border-radius:{block["radius"]}px')
    if block.get('font'):
        style.append(f'font-family:{font_stack(block["font"])}')
    if block.get('tracking'):
        style.append(f'letter-spacing:{block["tracking"] / 100:.2f}em')
    if block.get('upper'):
        classes.append('upper')
    if kind == 'totals' and block.get('hl'):
        style.append(f'--hl:{css_color(block["hl"])}')
        classes.append('hl')
    if len(classes) == 1 and not style:
        return inner
    return f'<div class="{" ".join(classes)}" style="{";".join(style)}">{inner}</div>'


def shape_svg(block, colors):
    """Forme vectorielle (même dessin dans l'éditeur, l'aperçu et le PDF)."""
    fill2 = svg_color(block.get('fill2') or 'secondary', colors) if block.get('gradient') else None
    return canvas_shapes.svg(block, svg_color(block.get('fill') or 'accent', colors), fill2)


def _decor_html(block, colors, assets, anchor='top'):
    content = shape_svg(block, colors) if block['type'] == 'shape' else _image_tag(block, assets)
    if not content:
        return ''
    # Accroché en bas : position calculée depuis le haut de la première page (le moteur PDF place
    # mal `bottom` dans un bloc dont la hauteur vient de min-height).
    top = PAGE_HEIGHT - block['y'] - block['h'] if anchor == 'bottom' else block['y']
    return (f'<div class="{PREFIX}deco" style="left:{block["x"]}px;top:{top}px;'
            f'width:{block["w"]}px;height:{block["h"]}px">{content}</div>')


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


def _is_decor(block):
    return block['type'] == 'shape' or (block['type'] == 'image' and block.get('behind'))


def _band_html(blocks, height, band, colors=None, assets=None):
    """
    Zone rendue en rangées : chaque rangée garde les positions horizontales et l'écart vertical
    choisis dans l'éditeur (hauteur minimale), mais s'agrandit si son contenu est plus haut que
    prévu (devis avec délais, longue adresse…) au lieu de chevaucher la suivante.
    Les décors (formes, images en arrière-plan) sont posés en absolu derrière les rangées.
    """
    colors = colors or DEFAULT_COLORS
    parts = [_decor_html(b, colors, assets) for b in blocks if _is_decor(b)]
    rows = _rows([b for b in blocks if not _is_decor(b)])
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
                         f'padding-top:{block["y"] - row["y"]}px">{block_inner(block, assets)}</div>')
        parts.append(f'<div class="{PREFIX}row" style="min-height:{max(0, next_y - row["y"])}px">' + ''.join(cells) + '</div>')
    top = rows[0]['y'] if rows else 0  # les décors (absolus) partent du haut de la zone, marge comprise
    return (f'<div class="{PREFIX}band {PREFIX}band-{band}" style="min-height:{height}px;padding-top:{top}px">'
            + ''.join(parts) + '</div>')


def _font_imports(layout):
    from .preview import FONT_CHOICES
    used = {b.get('font') for b in layout['blocks'] if b.get('font')} | {(layout.get('table') or {}).get('font')}
    return ''.join(f"@import url('https://fonts.googleapis.com/css2?family={FONT_CHOICES[key][1]}&display=swap');\n"
                   for key in sorted(k for k in used if k in FONT_CHOICES and FONT_CHOICES[k][1]))


def build(canvas, assets=None):
    """
    (html, css) du modèle à partir d'une mise en page déjà nettoyée par `clean`.
    `assets` : {id: data URI} des images importées (voir canvas_assets.resolve).
    """
    colors = canvas.get('colors') or DEFAULT_COLORS
    colors = dict(DEFAULT_COLORS, **colors)
    page = ''.join(_decor_html(b, colors, assets, b.get('anchor', 'top')) for b in canvas['blocks'] if b['band'] == 'page')
    bands = {band: _band_html([b for b in canvas['blocks'] if b['band'] == band], canvas['heights'][band], band, colors, assets)
             for band in BANDS}
    body = ''
    if canvas.get('items', True):
        table = canvas.get('table') or {}
        inset = table.get('inset', PAGE_PADDING)
        body = (f'<div class="{PREFIX}body" style="padding:0 {inset}px">'
                f'{build_items(table, PREFIX, css_color=css_color, font_stack=font_stack)}</div>')
    inner = page + bands['header'] + body + bands['footer']
    style = f' --c2: {colors["secondary"]}; --ink: {colors["ink"]}; --page: {colors["page"]};'
    page_bg = f'@page {{ background: {colors["page"]}; }}\n' if colors['page'].lower() != '#ffffff' else ''
    return _root(PREFIX, inner, style), _font_imports(canvas) + _css(PREFIX, CANVAS_CSS + TABLE_CSS) + page_bg


def schema_and_defaults(accent):
    return {'fields': COMMON_SCHEMA}, dict(COMMON_DEFAULTS, accent_color=accent)


def palette():
    """Blocs proposés dans l'éditeur (type, libellé, largeur, zone conseillée)."""
    return [{'type': key, 'label': spec[0], 'w': spec[1], 'band': spec[2]} for key, spec in BLOCKS.items() if key not in DECOR]


def doc_variables_for_editor():
    return [{'key': key, 'label': spec[0]} for key, spec in DOC_VARIABLES.items()]


def _b(type_, band, x, y, w=None, **extra):
    block = {'id': _new_id(), 'type': type_, 'band': band, 'x': x, 'y': y, 'w': w or BLOCKS[type_][1],
             'align': extra.pop('align', 'left'), 'size': extra.pop('size', 'm'), 'accent': extra.pop('accent', False)}
    block.update(extra)
    return block


def _shape(shape, band, x, y, w, h, **extra):
    return _b('shape', band, x, y, w, shape=shape, h=h, **extra)


# --------------------------------------------------------------------------- #
# Modèles de la galerie construits en mise en page libre (modifiables à la souris)
# --------------------------------------------------------------------------- #

def _layout(heights, blocks, table=None, colors=None):
    return clean({'heights': {'header': heights[0], 'footer': heights[1]}, 'blocks': blocks,
                  'table': table or {}, 'colors': colors or {}})


def _cols(*keys, strong='total_ht', labels=None):
    labels = labels or {}
    return [{'key': key, 'label': labels.get(key, {'designation': 'Désignation', 'quantite': 'Qté', 'prix_unitaire': 'Prix unitaire HT',
                                                     'tva': 'TVA', 'total_ht': 'Total HT', 'numero': 'N°', 'unite': 'Unité',
                                                     'total_ttc': 'Total TTC', 'montant_tva': 'Montant TVA', 'remise': 'Remise'}.get(key, key)),
             'strong': key == strong} for key in keys]


_STANDARD_FOOTER = [
    _b('totals', 'footer', 442, 20, 300),
    _b('payment', 'footer', 52, 150, 690),
    _b('legal', 'footer', 52, 260, 690, size='s'),
]

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
    # ----- Inspirés des exemples fournis (bandeaux, formes, pages colorées) -----
    {
        'slug': 'libre-orange', 'title': 'Bandeaux orange', 'accent': '#ea7c3c',
        'description': 'Deux filets de couleur en haut et en bas de page, tableau à en-tête coloré.',
        'tags': ['libre', 'bandeau', 'coloré', 'facture', 'devis'],
        'canvas': _layout((330, 300), [
            _shape('rect', 'page', 0, 0, 794, 14),
            _shape('rect', 'page', 0, 0, 794, 14, anchor='bottom'),
            _b('issuer', 'header', 52, 50, 300, size='s'),
            _b('title', 'header', 482, 44, 260, align='right', size='l', upper=True, tracking=4),
            _b('client', 'header', 52, 180, 300),
            _b('meta', 'header', 482, 180, 260, align='right', bg='secondary', pad=12, radius=6),
            _b('totals', 'footer', 442, 20, 300, accent=True),
            _b('payment', 'footer', 52, 150, 690, size='s'),
            _b('legal', 'footer', 52, 260, 690, size='s'),
        ], table={'columns': _cols('designation', 'quantite', 'unite', 'prix_unitaire', 'tva', 'montant_tva', 'total_ttc', strong='total_ttc'),
                  'header': 'accent', 'borders': 'rows', 'stripes': True, 'stripe_color': 'secondary'},
           colors={'secondary': '#fdf1e8'}),
    },
    {
        'slug': 'libre-contraste', 'title': 'Contraste noir', 'accent': '#111111',
        'description': 'Grand titre condensé, tableau noir et pied de page inversé, pour une identité forte.',
        'tags': ['libre', 'noir', 'moderne', 'facture', 'devis'],
        'canvas': _layout((360, 320), [
            _b('logo', 'header', 52, 40),
            _b('meta', 'header', 482, 40, 260, align='right', size='s'),
            _b('title', 'header', 52, 128, 420, size='xxl', font='Oswald', upper=True),
            _b('client', 'header', 52, 236, 300, size='s'),
            _b('issuer', 'header', 442, 236, 300, size='s', align='right'),
            _b('totals', 'footer', 442, 20, 300, hl='black'),
            _b('payment', 'footer', 52, 150, 690, size='s'),
            _b('legal', 'footer', 0, 240, 794, size='s', align='center', bg='black', color='white', pad=22),
        ], table={'columns': _cols('quantite', 'designation', 'prix_unitaire', 'total_ht'),
                  'header': 'line', 'borders': 'grid', 'th_bg': 'black', 'th_fg': 'white', 'border_color': 'black'}),
    },
    {
        'slug': 'libre-geometrique', 'title': 'Géométrique bleu', 'accent': '#0284c7',
        'description': 'Facettes en coin, tableau rayé bleu et total mis en avant : esprit agence.',
        'tags': ['libre', 'géométrique', 'créatif', 'facture', 'devis'],
        'canvas': _layout((340, 320), [
            _shape('facets', 'page', 494, 0, 300, 250),
            _shape('facets', 'page', 0, 0, 260, 200, anchor='bottom', flip_x=True, flip_y=True, fill='secondary'),
            _b('logo', 'header', 52, 44),
            _b('title', 'header', 52, 120, 300, size='l', upper=True, tracking=8, accent=True),
            _b('client', 'header', 52, 206, 300, size='s'),
            _b('meta', 'header', 352, 206, 180, size='s', bg='accent', color='white', pad=12, radius=4),
            _b('issuer', 'header', 552, 206, 190, size='s'),
            _b('totals', 'footer', 442, 20, 300, hl='accent'),
            _b('payment', 'footer', 52, 150, 440, size='s'),
            _b('legal', 'footer', 52, 260, 440, size='s'),
        ], table={'columns': _cols('numero', 'designation', 'prix_unitaire', 'quantite', 'total_ht'),
                  'header': 'accent', 'borders': 'none', 'stripes': True, 'stripe_color': 'secondary', 'uppercase': True},
           colors={'secondary': '#bae6fd'}),
    },
    {
        'slug': 'libre-vague', 'title': 'Vague', 'accent': '#1f1f1f',
        'description': 'Une vague sombre en haut, une vague douce en bas et un grand titre épuré.',
        'tags': ['libre', 'vague', 'bien-être', 'facture', 'devis'],
        'canvas': _layout((380, 320), [
            _shape('wave', 'page', 0, 0, 794, 120, fill='ink'),
            _shape('wave_soft', 'page', 0, 0, 794, 110, anchor='bottom', flip_y=True, fill='secondary'),
            _b('logo', 'header', 52, 130),
            _b('title', 'header', 52, 196, 380, size='xxl', font='Oswald', upper=True),
            _b('meta', 'header', 482, 196, 260, align='right', size='s'),
            _b('issuer', 'header', 52, 296, 300, size='s'),
            _b('client', 'header', 442, 296, 300, size='s', align='right'),
            _b('totals', 'footer', 442, 20, 300),
            _b('payment', 'footer', 52, 150, 690, size='s'),
            _b('legal', 'footer', 52, 250, 690, size='s'),
        ], table={'columns': _cols('designation', 'prix_unitaire', 'quantite', 'total_ht', labels={'designation': 'Description', 'prix_unitaire': 'Prix unitaire', 'quantite': 'Quantité', 'total_ht': 'Total'}),
                  'header': 'none', 'borders': 'rows', 'uppercase': False, 'density': 'airy'},
           colors={'ink': '#1f1f1f', 'secondary': '#dcefe9'}),
    },
    {
        'slug': 'libre-pop', 'title': 'Pop coloré', 'accent': '#7c5cbf',
        'description': 'Page turquoise, carte blanche arrondie, titre en pastille jaune et encarts violets.',
        'tags': ['libre', 'coloré', 'créatif', 'facture', 'devis'],
        'canvas': _layout((330, 330), [
            _shape('rect', 'page', 24, 24, 746, 1075, fill='white', radius=26),
            _b('title', 'header', 60, 54, 300, size='l', bg='secondary', pad=14, radius=40, font='Poppins', upper=True),
            _b('logo', 'header', 542, 60, 200, align='right'),
            _b('meta', 'header', 60, 170, 330, size='s', bg='accent', color='white', pad=16, radius=12),
            _b('client', 'header', 404, 170, 330, size='s', bg='accent', color='white', pad=16, radius=12),
            _b('totals', 'footer', 434, 20, 300),
            _b('issuer', 'footer', 60, 20, 330, size='s'),
            _b('payment', 'footer', 60, 160, 674, size='s', bg='accent', color='white', pad=16, radius=12),
            _b('legal', 'footer', 60, 280, 674, size='s'),
        ], table={'columns': _cols('designation', 'quantite', 'prix_unitaire', 'total_ht', labels={'designation': 'Description', 'prix_unitaire': 'Prix', 'total_ht': 'Montant'}),
                  'header': 'none', 'borders': 'rows', 'uppercase': False, 'inset': 60, 'font': 'Poppins'},
           colors={'secondary': '#facc15', 'page': '#5fb3ad'}),
    },
    {
        'slug': 'libre-nature', 'title': 'Élégant nature', 'accent': '#4a6b57',
        'description': 'Fond crème, typographie à empattements et bandeau vert : idéal photographes et artisans d’art.',
        'tags': ['libre', 'élégant', 'nature', 'facture', 'devis'],
        'canvas': _layout((400, 330), [
            _shape('blob', 'page', 600, -40, 260, 230, fill='accent', opacity=18),
            _shape('blob', 'page', 690, 60, 140, 130, fill='accent', opacity=30, flip_x=True),
            _b('text', 'header', 52, 56, 480, text='{entreprise}', size='xl', font='Cormorant Garamond', upper=True, tracking=12),
            _b('issuer', 'header', 52, 112, 300, size='s'),
            _b('title', 'header', 52, 250, 300, size='m', font='Cormorant Garamond', upper=True, tracking=14),
            _b('meta', 'header', 442, 250, 300, size='s', align='right'),
            _b('client', 'header', 442, 112, 300, size='s', align='right'),
            _b('totals', 'footer', 442, 20, 300),
            _b('payment', 'footer', 0, 140, 794, size='s', align='center', bg='accent', color='white', pad=26),
            _b('legal', 'footer', 0, 250, 794, size='s', align='center', bg='accent', color='white', pad=18),
        ], table={'columns': _cols('designation', 'prix_unitaire', 'quantite', 'total_ht', labels={'designation': 'Description', 'prix_unitaire': 'Prix unitaire', 'quantite': 'Quantité', 'total_ht': 'Total'}),
                  'header': 'line', 'borders': 'rows', 'uppercase': False, 'font': 'Cormorant Garamond', 'border_color': 'accent'},
           colors={'page': '#f6f2ea', 'ink': '#3b3b36'}),
    },
    {
        'slug': 'libre-creme', 'title': 'Studio crème', 'accent': '#3f4553',
        'description': 'Fond crème, bandes ardoise en haut et en bas, titres à empattements et « Merci ! » final.',
        'tags': ['libre', 'élégant', 'créatif', 'facture', 'devis'],
        'canvas': _layout((360, 320), [
            _shape('rect', 'page', 0, 0, 794, 26, fill='accent'),
            _shape('rect', 'page', 0, 0, 794, 26, fill='accent', anchor='bottom'),
            _b('text', 'header', 52, 60, 380, text='{entreprise}', size='xl', font='Playfair Display', upper=True, tracking=4),
            _b('title', 'header', 482, 60, 260, align='right', size='m', font='Playfair Display', upper=True),
            _b('meta', 'header', 482, 150, 260, align='right', size='s'),
            _b('client', 'header', 52, 200, 300),
            _b('issuer', 'header', 442, 200, 300, size='s', align='right'),
            _b('totals', 'footer', 442, 20, 300),
            _b('payment', 'footer', 52, 150, 440, size='s'),
            _b('text', 'footer', 532, 160, 210, text='Merci !', size='xl', font='Playfair Display', align='right'),
            _b('legal', 'footer', 52, 250, 690, size='s', align='center'),
        ], table={'columns': _cols('designation', 'quantite', 'prix_unitaire', 'total_ht', labels={'designation': 'Prestation', 'prix_unitaire': 'Prix', 'total_ht': 'Total'}),
                  'header': 'line', 'borders': 'none', 'th_bg': 'accent', 'th_fg': 'white', 'stripes': True, 'stripe_color': 'secondary'},
           colors={'page': '#fbf1dc', 'secondary': '#efe2c4'}),
    },
    {
        'slug': 'libre-turquoise', 'title': 'Turquoise', 'accent': '#0891b2',
        'description': 'Grand titre coloré, pastille ronde pour le logo, encart des dates et filet en pied de page.',
        'tags': ['libre', 'coloré', 'proforma', 'facture', 'devis'],
        'canvas': _layout((380, 320), [
            _shape('rect', 'page', 0, 0, 794, 18, anchor='bottom'),
            _shape('ellipse', 'header', 614, 30, 120, 120, fill='#fbbf24'),
            _b('title', 'header', 52, 46, 480, size='xl', accent=True),
            _b('logo', 'header', 624, 66, 100, align='center'),
            _b('divider', 'header', 52, 162, 690, accent=True),
            _b('issuer', 'header', 52, 190, 300, size='s'),
            _b('client', 'header', 442, 190, 300, size='s'),
            _b('meta', 'header', 52, 300, 300, size='s', bg='secondary', pad=14, radius=4),
            _b('totals', 'footer', 442, 20, 300, accent=True),
            _b('payment', 'footer', 52, 150, 690, size='s'),
            _b('legal', 'footer', 52, 250, 690, size='s'),
        ], table={'columns': _cols('designation', 'quantite', 'unite', 'prix_unitaire', 'tva', 'montant_tva', 'total_ttc', strong='total_ttc',
                                   labels={'designation': 'Description', 'quantite': 'Quantité', 'tva': '% TVA', 'montant_tva': 'Total TVA'}),
                  'header': 'line', 'borders': 'rows', 'uppercase': False, 'border_color': 'accent'}),
    },
    {
        'slug': 'libre-chantier', 'title': 'Chantier', 'accent': '#5b4fd6',
        'description': 'Tableau numéroté à en-tête violet, avec unités : pensé pour le BTP et les situations.',
        'tags': ['libre', 'btp', 'artisan', 'facture', 'devis'],
        'canvas': _layout((340, 320), [
            _b('logo', 'header', 52, 40),
            _b('issuer', 'header', 52, 110, 300, size='s'),
            _b('title', 'header', 482, 40, 260, align='right', size='l', accent=True, upper=True),
            _b('meta', 'header', 482, 110, 260, align='right', size='s'),
            _b('client', 'header', 442, 200, 300, size='s', border='accent', pad=12, radius=4),
            _b('subject', 'header', 52, 200, 360),
            _b('totals', 'footer', 442, 20, 300, hl='accent'),
            _b('payment', 'footer', 52, 150, 690, size='s'),
            _b('legal', 'footer', 52, 250, 690, size='s'),
        ], table={'columns': _cols('numero', 'designation', 'quantite', 'unite', 'prix_unitaire', 'tva', 'total_ht',
                                   labels={'prix_unitaire': 'P.U. HT'}),
                  'header': 'accent', 'borders': 'grid', 'border_color': 'secondary', 'stripes': True, 'stripe_color': 'secondary', 'density': 'compact'},
           colors={'secondary': '#eeecfd'}),
    },
    {
        'slug': 'libre-cadre', 'title': 'Cadre', 'accent': '#f28c28',
        'description': 'Toute la page entourée d’un cadre de couleur : simple, lisible et reconnaissable.',
        'tags': ['libre', 'cadre', 'coloré', 'facture', 'devis'],
        'canvas': _layout((340, 330), [
            _shape('frame', 'page', 12, 12, 770, 1099, thickness=6),
            _b('logo', 'header', 52, 48),
            _b('issuer', 'header', 52, 120, 300, size='s'),
            _b('title', 'header', 482, 48, 260, align='right'),
            _b('meta', 'header', 482, 110, 260, align='right', size='s'),
            _b('client', 'header', 442, 200, 300, size='s'),
            _b('totals', 'footer', 442, 20, 300),
            _b('payment', 'footer', 52, 160, 690, size='s'),
            _b('legal', 'footer', 52, 260, 690, size='s', align='center'),
        ], table={'columns': _cols('designation', 'quantite', 'prix_unitaire', 'tva', 'total_ht', labels={'quantite': 'Qté', 'prix_unitaire': 'PU HT'}),
                  'header': 'line', 'borders': 'rows', 'uppercase': False}),
    },
    {
        'slug': 'libre-bande-laterale', 'title': 'Bande latérale', 'accent': '#b8962e',
        'description': 'Une bande dorée sur toute la hauteur et un total en bandeau : chic et sobre.',
        'tags': ['libre', 'élégant', 'or', 'facture', 'devis'],
        'canvas': _layout((340, 320), [
            _shape('rect', 'page', 0, 0, 48, 1123),
            _b('meta', 'header', 92, 54, 300, size='s'),
            _b('title', 'header', 452, 46, 290, align='right', size='l', upper=True, tracking=6, accent=True),
            _b('issuer', 'header', 92, 140, 300, size='s'),
            _b('client', 'header', 452, 140, 290, size='s', align='right'),
            _b('totals', 'footer', 442, 20, 300, hl='accent'),
            _b('payment', 'footer', 92, 150, 650, size='s'),
            _b('legal', 'footer', 92, 250, 650, size='s'),
        ], table={'columns': _cols('quantite', 'designation', 'prix_unitaire', 'total_ht', labels={'quantite': 'Heures', 'designation': 'Description', 'prix_unitaire': '€ / h', 'total_ht': 'Montant'}),
                  'header': 'soft', 'borders': 'rows', 'th_bg': 'muted', 'th_fg': 'white', 'inset': 92}),
    },
    {
        'slug': 'libre-administratif', 'title': 'Administratif', 'accent': '#111111',
        'description': 'Encadrés et grille complète, police classique : rassurant pour les marchés et collectivités.',
        'tags': ['libre', 'administratif', 'grille', 'facture', 'devis'],
        'canvas': _layout((340, 320), [
            _b('logo', 'header', 52, 40),
            _b('issuer', 'header', 52, 112, 320, size='s'),
            _b('title', 'header', 452, 40, 290, align='center', size='s', border='black', pad=10, font='Arial'),
            _b('meta', 'header', 452, 112, 290, size='s'),
            _b('client', 'header', 452, 200, 290, size='s', border='black', pad=10),
            _b('totals', 'footer', 442, 20, 300, border='black', pad=6),
            _b('payment', 'footer', 52, 160, 690, size='s', border='black', pad=10),
            _b('legal', 'footer', 52, 270, 690, size='s'),
        ], table={'columns': _cols('numero', 'designation', 'quantite', 'prix_unitaire', 'remise', 'total_ht', 'tva',
                                   labels={'numero': 'Réf.', 'prix_unitaire': 'P.U. HT'}),
                  'header': 'soft', 'borders': 'grid', 'border_color': 'black', 'uppercase': False, 'density': 'compact', 'font': 'Arial'}),
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
