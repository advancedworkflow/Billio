"""
Tableau des lignes personnalisable des modèles en mise en page libre.

Les colonnes sont des **variables** de ligne (désignation, quantité, unité, prix, remise, TVA,
totaux…) ou des colonnes personnalisées dont le texte mélange du texte libre et des variables
écrites entre accolades, par ex. « {quantite} × {prix_unitaire} ». Le style (en-tête, couleurs,
séparateurs, rayures, arrondis, marges, police…) devient des classes et des variables CSS :
rien de ce que tape l'utilisateur ne devient une balise de gabarit.

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

# Couleurs-variables (partagées avec canvas) : jetons du modèle ou couleur #rrggbb.
COLOR_TOKENS = ('', 'accent', 'secondary', 'ink', 'white', 'black', 'muted')
_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


def valid_color(value, default=''):
    value = str(value or '')
    return value if value in COLOR_TOKENS or _HEX.match(value) else default


def font_keys():
    from .preview import FONT_CHOICES
    return tuple(FONT_CHOICES)

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
    # Réglages avancés (vides = style de l'en-tête choisi ci-dessus)
    'th_bg': '', 'th_fg': '', 'border_color': '', 'border_width': 1, 'stripe_color': '',
    'radius': 0, 'inset': 52, 'font': '',
}

_TOKEN = re.compile(r'\{(\w+)\}')


def _escape(text):
    """Texte saisi : HTML échappé, accolades et % neutralisés (aucune balise de gabarit possible)."""
    return html.escape(str(text)).replace('{', '&#123;').replace('}', '&#125;').replace('%', '&#37;')


def render_tokens(text, variables):
    """« {quantite} × {prix_unitaire} » → texte échappé + expressions des variables connues."""
    parts, last = [], 0
    for match in _TOKEN.finditer(text):
        parts.append(_escape(text[last:match.start()]))
        key = match.group(1)
        spec = variables.get(key)
        parts.append(spec[1] if spec else _escape(match.group(0)))
        last = match.end()
    parts.append(_escape(text[last:]))
    return ''.join(parts)


def _pick(value, allowed, default):
    return value if value in allowed else default


def _int(value, default, low, high):
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def clean_table(raw):
    """Valide la configuration reçue du navigateur (clés connues, couleurs, bornes, textes tronqués)."""
    color = valid_color
    raw = raw if isinstance(raw, dict) else {}
    columns = []
    for col in (raw.get('columns') if isinstance(raw.get('columns'), list) else DEFAULT_TABLE['columns'])[:MAX_COLUMNS]:
        if not isinstance(col, dict) or (col.get('key') not in VARIABLES and col.get('key') != CUSTOM):
            continue
        key = col['key']
        default_label = VARIABLES[key][0] if key in VARIABLES else 'Colonne'
        clean = {
            'key': key,
            'label': str(col.get('label') if col.get('label') is not None else default_label)[:40],
            'align': _pick(col.get('align'), ALIGNS, 'auto'),
            'width': _int(col.get('width'), 0, 0, 70),
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
        'th_bg': color(raw.get('th_bg')),
        'th_fg': color(raw.get('th_fg')),
        'border_color': color(raw.get('border_color')),
        'border_width': _int(raw.get('border_width'), d['border_width'], 0, 4),
        'stripe_color': color(raw.get('stripe_color')),
        'radius': _int(raw.get('radius'), 0, 0, 24),
        'inset': _int(raw.get('inset'), d['inset'], 0, 160),
        'font': raw.get('font') if raw.get('font') in font_keys() else '',
    }


def _cell_attrs(col, numeric, p):
    classes = [f'{p}c-num' if numeric else f'{p}c-desc']
    if col['align'] != 'auto':
        classes.append(f'ta-{col["align"]}')
    style = f' style="width:{col["width"]}%"' if col['width'] else ''
    return classes, style


def build_items(table, p, css_color=None, font_stack=None):
    """
    HTML du tableau des lignes (préfixe CSS `p`), objet du document compris.
    `css_color(jeton)` et `font_stack(clé)` sont fournis par canvas (couleurs-variables, polices).
    """
    table = clean_table(table)  # toujours revalidé : la configuration peut venir du navigateur (aperçus)
    css_color = css_color or (lambda token: token)
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
            content = render_tokens(col.get('text') or '', VARIABLES)
        else:
            content = VARIABLES[key][1]
        if col['strong']:
            classes = classes + [f'{p}c-strong']
        cells.append(f'<td class="{" ".join(classes)}">{content}</td>')
    flags = [f'{p}items', f'tb-h-{table["header"]}', f'tb-b-{table["borders"]}', f'tb-d-{table["density"]}', f'tb-s-{table["size"]}']
    style = []
    if table['stripes']:
        flags.append('tb-zebra')
    if not table['uppercase']:
        flags.append('tb-plain')
    for key, var, flag in (('th_bg', '--th-bg', 'tb-thbg'), ('th_fg', '--th-fg', 'tb-thfg'),
                           ('border_color', '--bd', 'tb-bd'), ('stripe_color', '--zebra', '')):
        value = css_color(table[key]) if table[key] else ''
        if value:
            style.append(f'{var}:{value}')
            if flag:
                flags.append(flag)
    if table['border_width'] != 1:
        style.append(f'--bw:{table["border_width"]}px')
        flags.append('tb-bw')
    if table['radius']:
        style.append(f'--r:{table["radius"]}px')
        flags.append('tb-round')
    if table['font'] and font_stack:
        style.append(f'font-family:{font_stack(table["font"])}')
    style_attr = f' style="{";".join(style)}"' if style else ''
    return (
        f'{{% if subject %}}<p class="{p}subject"><span class="{p}muted">Objet :</span> {{{{ subject }}}}</p>{{% endif %}}'
        f'<table class="{" ".join(flags)}"{style_attr}><thead><tr>{"".join(heads)}</tr></thead><tbody>'
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
.{p}items.tb-zebra tbody tr:nth-child(even) td { background: var(--zebra, #f9fafb); }
.{p}items.tb-thbg th { background: var(--th-bg) !important; border-bottom-color: var(--th-bg); }
.{p}items.tb-thfg th { color: var(--th-fg) !important; }
.{p}items.tb-bd td, .{p}items.tb-bd th { border-color: var(--bd) !important; }
.{p}items.tb-bw td { border-bottom-width: var(--bw) !important; }
.{p}items.tb-bw.tb-b-grid td, .{p}items.tb-bw.tb-b-grid th { border-width: var(--bw) !important; }
.{p}items.tb-round { border-collapse: separate; border-spacing: 0; }
.{p}items.tb-round th:first-child { border-top-left-radius: var(--r); border-bottom-left-radius: var(--r); }
.{p}items.tb-round th:last-child { border-top-right-radius: var(--r); border-bottom-right-radius: var(--r); }
.{p}items.tb-round.tb-b-grid th, .{p}items.tb-round.tb-b-grid td { border-radius: 0; }
.{p}items.tb-d-compact th { padding-top: 6px; padding-bottom: 6px; }
.{p}items.tb-d-compact td { padding-top: 6px; padding-bottom: 6px; }
.{p}items.tb-d-airy td { padding-top: 16px; padding-bottom: 16px; }
.{p}items.tb-s-s td { font-size: 11px; }
.{p}items.tb-s-l td { font-size: 14px; }
"""

# Styles prêts à l'emploi proposés dans l'éditeur (appliqués côté navigateur, puis réglables).
PRESETS = [
    {'key': 'classique', 'label': 'Classique', 'set': {'header': 'line', 'borders': 'rows', 'stripes': False, 'uppercase': True,
                                                       'th_bg': '', 'th_fg': '', 'border_color': '', 'stripe_color': '', 'radius': 0}},
    {'key': 'sombre', 'label': 'En-tête foncé', 'set': {'header': 'line', 'borders': 'rows', 'stripes': False, 'uppercase': True,
                                                         'th_bg': 'black', 'th_fg': 'white', 'border_color': '', 'stripe_color': '', 'radius': 0}},
    {'key': 'couleur', 'label': 'Couleur d’accent', 'set': {'header': 'accent', 'borders': 'rows', 'stripes': False, 'uppercase': True,
                                                             'th_bg': '', 'th_fg': '', 'border_color': '', 'stripe_color': '', 'radius': 0}},
    {'key': 'pastille', 'label': 'Pastille', 'set': {'header': 'accent', 'borders': 'none', 'stripes': True, 'uppercase': False,
                                                      'th_bg': '', 'th_fg': '', 'border_color': '', 'stripe_color': 'secondary', 'radius': 10}},
    {'key': 'doux', 'label': 'Doux rayé', 'set': {'header': 'soft', 'borders': 'none', 'stripes': True, 'uppercase': True,
                                                   'th_bg': '', 'th_fg': '', 'border_color': '', 'stripe_color': '', 'radius': 0}},
    {'key': 'grille', 'label': 'Grille', 'set': {'header': 'soft', 'borders': 'grid', 'stripes': False, 'uppercase': True,
                                                  'th_bg': '', 'th_fg': '', 'border_color': '', 'stripe_color': '', 'radius': 0}},
    {'key': 'administratif', 'label': 'Administratif', 'set': {'header': 'soft', 'borders': 'grid', 'stripes': False, 'uppercase': False,
                                                                'th_bg': '', 'th_fg': '', 'border_color': 'black', 'stripe_color': '', 'radius': 0}},
    {'key': 'epure', 'label': 'Épuré', 'set': {'header': 'none', 'borders': 'none', 'stripes': False, 'uppercase': False,
                                               'th_bg': '', 'th_fg': 'muted', 'border_color': '', 'stripe_color': '', 'radius': 0}},
]


def variables_for_editor():
    """[(clé, libellé)] proposés dans l'éditeur (colonnes et variables des colonnes personnalisées)."""
    return [{'key': key, 'label': spec[0]} for key, spec in VARIABLES.items()]
