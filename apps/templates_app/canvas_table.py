"""
Tableau des lignes personnalisable des modèles en mise en page libre.

Les colonnes sont des **variables** de ligne (désignation, quantité, unité, prix, remise, TVA,
totaux…) ou des colonnes personnalisées dont le texte mélange du texte libre et des variables
écrites entre accolades, par ex. « {quantite} × {prix_unitaire} ». Le style (en-tête, séparateurs,
rayures, densité, taille, majuscules) est un jeu de classes CSS : rien de ce que tape
l'utilisateur ne devient une balise de gabarit.

La configuration vit dans `layout_config['canvas']['table']` ; `build_items()` en tire le HTML.
"""
import html
import re

# Variables d'une ligne : clé → (libellé, expression du gabarit, colonne numérique)
VARIABLES = {
    'numero': ('N°', '{{ forloop.counter }}', True),
    'designation': ('Désignation', '{{ item.name }}', False),
    'description': ('Description', '{{ item.description|default_if_none:"" }}', False),
    'quantite': ('Quantité', '{{ item.quantity|qty }}', True),
    'unite': ('Unité', "{% if item.unit and item.unit != 'unit' %}{{ item.unit }}{% endif %}", False),
    'prix_unitaire': ('Prix unitaire HT', '{{ item.unit_price|money:currency }}', True),
    'remise': ('Remise', '{% if item.discount_percent|nonzero %}{{ item.discount_percent|percent }}{% endif %}', True),
    'tva': ('TVA', '{{ item.tax_rate|percent }}', True),
    'montant_tva': ('Montant TVA', '{{ item|line_tax|money:currency }}', True),
    'total_ht': ('Total HT', '{{ item.total|money:currency }}', True),
    'total_ttc': ('Total TTC', '{{ item|line_ttc|money:currency }}', True),
}
CUSTOM = 'perso'
ALIGNS = ('auto', 'left', 'center', 'right')
HEADERS = ('line', 'soft', 'accent', 'none')
BORDERS = ('rows', 'grid', 'none')
DENSITIES = ('compact', 'normal', 'airy')
SIZES = ('s', 'm', 'l')
MAX_COLUMNS = 10

DEFAULT_TABLE = {
    'columns': [
        {'key': 'designation', 'label': 'Désignation'},
        {'key': 'quantite', 'label': 'Qté'},
        {'key': 'prix_unitaire', 'label': 'Prix unitaire HT'},
        {'key': 'tva', 'label': 'TVA'},
        {'key': 'total_ht', 'label': 'Total HT', 'strong': True},
    ],
    'header': 'line', 'borders': 'rows', 'stripes': False, 'density': 'normal', 'size': 'm',
    'uppercase': True, 'show_description': True, 'empty_text': 'Aucune ligne',
}

_TOKEN = re.compile(r'\{(\w+)\}')


def _escape(text):
    """Texte saisi : HTML échappé, accolades et % neutralisés (aucune balise de gabarit possible)."""
    return html.escape(str(text)).replace('{', '&#123;').replace('}', '&#125;').replace('%', '&#37;')


def _custom_cell(text):
    """« {quantite} × {prix_unitaire} » → texte échappé + expressions des variables connues."""
    parts, last = [], 0
    for match in _TOKEN.finditer(text):
        parts.append(_escape(text[last:match.start()]))
        key = match.group(1)
        parts.append(VARIABLES[key][1] if key in VARIABLES else _escape(match.group(0)))
        last = match.end()
    parts.append(_escape(text[last:]))
    return ''.join(parts)


def _pick(value, allowed, default):
    return value if value in allowed else default


def clean_table(raw):
    """Valide la configuration reçue du navigateur (clés connues, bornes, textes tronqués)."""
    raw = raw if isinstance(raw, dict) else {}
    columns = []
    for col in (raw.get('columns') if isinstance(raw.get('columns'), list) else DEFAULT_TABLE['columns'])[:MAX_COLUMNS]:
        if not isinstance(col, dict) or (col.get('key') not in VARIABLES and col.get('key') != CUSTOM):
            continue
        key = col['key']
        default_label = VARIABLES[key][0] if key in VARIABLES else 'Colonne'
        try:
            width = max(0, min(70, int(col.get('width') or 0)))
        except (TypeError, ValueError):
            width = 0
        clean = {
            'key': key,
            'label': str(col.get('label') if col.get('label') is not None else default_label)[:40],
            'align': _pick(col.get('align'), ALIGNS, 'auto'),
            'width': width,
            'strong': bool(col.get('strong')),
        }
        if key == CUSTOM:
            clean['text'] = str(col.get('text') or '')[:200]
        columns.append(clean)
    if not columns:
        columns = [dict(c, align='auto', width=0, strong=bool(c.get('strong'))) for c in DEFAULT_TABLE['columns']]
    d = DEFAULT_TABLE
    return {
        'columns': columns,
        'header': _pick(raw.get('header'), HEADERS, d['header']),
        'borders': _pick(raw.get('borders'), BORDERS, d['borders']),
        'stripes': bool(raw.get('stripes', d['stripes'])),
        'density': _pick(raw.get('density'), DENSITIES, d['density']),
        'size': _pick(raw.get('size'), SIZES, d['size']),
        'uppercase': bool(raw.get('uppercase', d['uppercase'])),
        'show_description': bool(raw.get('show_description', d['show_description'])),
        'empty_text': str(raw.get('empty_text') if raw.get('empty_text') is not None else d['empty_text'])[:80],
    }


def _cell_attrs(col, numeric, p):
    classes = [f'{p}c-num' if numeric else f'{p}c-desc']
    if col['align'] != 'auto':
        classes.append(f'ta-{col["align"]}')
    style = f' style="width:{col["width"]}%"' if col['width'] else ''
    return classes, style


def build_items(table, p):
    """HTML du tableau des lignes (préfixe CSS `p`), objet du document compris."""
    table = clean_table(table)
    heads, cells = [], []
    for col in table['columns']:
        key = col['key']
        numeric = VARIABLES[key][2] if key in VARIABLES else False
        classes, style = _cell_attrs(col, numeric, p)
        heads.append(f'<th class="{" ".join(classes)}"{style}>{_escape(col["label"])}</th>')
        if key == 'designation':
            content = f'<span class="{p}item-name">{{{{ item.name }}}}</span>'
            if table['show_description']:
                content += f'{{% if item.description %}}<span class="{p}item-desc">{{{{ item.description }}}}</span>{{% endif %}}'
        elif key == CUSTOM:
            content = _custom_cell(col.get('text') or '')
        else:
            content = VARIABLES[key][1]
        if col['strong']:
            classes = classes + [f'{p}c-strong']
        cells.append(f'<td class="{" ".join(classes)}">{content}</td>')
    flags = [f'{p}items', f'tb-h-{table["header"]}', f'tb-b-{table["borders"]}', f'tb-d-{table["density"]}', f'tb-s-{table["size"]}']
    if table['stripes']:
        flags.append('tb-zebra')
    if not table['uppercase']:
        flags.append('tb-plain')
    return (
        f'{{% if subject %}}<p class="{p}subject"><span class="{p}muted">Objet :</span> {{{{ subject }}}}</p>{{% endif %}}'
        f'<table class="{" ".join(flags)}"><thead><tr>{"".join(heads)}</tr></thead><tbody>'
        f'{{% for item in items %}}<tr>{"".join(cells)}</tr>'
        f'{{% empty %}}<tr><td colspan="{len(cells)}" class="{p}empty">{_escape(table["empty_text"])}</td></tr>{{% endfor %}}'
        '</tbody></table>'
    )


TABLE_CSS = """
.{p}items .ta-left { text-align: left !important; }
.{p}items .ta-center { text-align: center !important; }
.{p}items .ta-right { text-align: right !important; }
.{p}items.tb-plain th { text-transform: none; letter-spacing: 0; font-size: 11px; }
.{p}items.tb-h-soft th { background: #f3f4f6; border-bottom: none; color: #374151; }
.{p}items.tb-h-accent th { background: var(--accent); border-bottom: none; color: #fff; }
.{p}items.tb-h-none th { border-bottom: none; background: none; }
.{p}items.tb-b-none td { border-bottom: none; }
.{p}items.tb-b-grid th, .{p}items.tb-b-grid td { border: 1px solid #e5e7eb; }
.{p}items.tb-zebra tbody tr:nth-child(even) td { background: #f9fafb; }
.{p}items.tb-d-compact th { padding-top: 6px; padding-bottom: 6px; }
.{p}items.tb-d-compact td { padding-top: 6px; padding-bottom: 6px; }
.{p}items.tb-d-airy td { padding-top: 16px; padding-bottom: 16px; }
.{p}items.tb-s-s td { font-size: 11px; }
.{p}items.tb-s-l td { font-size: 14px; }
"""


def variables_for_editor():
    """[(clé, libellé)] proposés dans l'éditeur (colonnes et variables des colonnes personnalisées)."""
    return [{'key': key, 'label': spec[0]} for key, spec in VARIABLES.items()]
