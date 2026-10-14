"""
Devises : symbole, position, décimales et format des nombres, pour afficher les montants
partout de la même façon (documents, tableau de bord, éditeur de facture).

- Devises courantes intégrées (USD par défaut : marché américain d'abord).
- Devises personnalisées par organisation (Paramètres › Facturation), rangées dans
  `Organization.billing_preferences['custom_currencies']` : code, nom, symbole, position, décimales.

Le format des nombres suit l'usage de la devise : « en » = 1,234.56 ; « fr » = 1 234,56.
"""
from contextvars import ContextVar
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

DEFAULT_CURRENCY = 'USD'
NARROW_NBSP = ' '

# code : (nom, symbole, position, décimales, style des nombres)
BUILTIN = {
    'USD': ('Dollar américain', '$', 'before', 2, 'en'),
    'EUR': ('Euro', '€', 'after', 2, 'fr'),
    'GBP': ('Livre sterling', '£', 'before', 2, 'en'),
    'CAD': ('Dollar canadien', 'CA$', 'before', 2, 'en'),
    'AUD': ('Dollar australien', 'A$', 'before', 2, 'en'),
    'CHF': ('Franc suisse', 'CHF', 'after', 2, 'fr'),
    'XOF': ('Franc CFA (UEMOA)', 'FCFA', 'after', 0, 'fr'),
    'XAF': ('Franc CFA (CEMAC)', 'FCFA', 'after', 0, 'fr'),
    'MAD': ('Dirham marocain', 'DH', 'after', 2, 'fr'),
    'TND': ('Dinar tunisien', 'DT', 'after', 3, 'fr'),
    'DZD': ('Dinar algérien', 'DA', 'after', 2, 'fr'),
    'NGN': ('Naira', '₦', 'before', 2, 'en'),
    'GHS': ('Cedi', 'GH₵', 'before', 2, 'en'),
    'KES': ('Shilling kényan', 'KSh', 'before', 2, 'en'),
    'ZAR': ('Rand', 'R', 'before', 2, 'en'),
    'CDF': ('Franc congolais', 'FC', 'after', 2, 'fr'),
    'GNF': ('Franc guinéen', 'FG', 'after', 0, 'fr'),
    'HTG': ('Gourde', 'G', 'after', 2, 'fr'),
    'MXN': ('Peso mexicain', 'MX$', 'before', 2, 'en'),
    'BRL': ('Real brésilien', 'R$', 'before', 2, 'fr'),
    'INR': ('Roupie indienne', '₹', 'before', 2, 'en'),
    'JPY': ('Yen', '¥', 'before', 0, 'en'),
    'CNY': ('Yuan', '¥', 'before', 2, 'en'),
    'AED': ('Dirham des Émirats', 'AED', 'before', 2, 'en'),
}

# Devises personnalisées de l'organisation dont on rend les documents (posées par `activate`).
_custom = ContextVar('billio_custom_currencies', default=None)


def custom_currencies(organization):
    prefs = (getattr(organization, 'billing_preferences', None) or {}) if organization else {}
    result = {}
    for raw in prefs.get('custom_currencies') or []:
        try:
            code = str(raw['code']).strip().upper()[:3]  # les documents stockent un code à 3 lettres
            if not code:
                continue
            result[code] = (str(raw.get('name') or code)[:40], str(raw.get('symbol') or code)[:6],
                            'before' if raw.get('position') == 'before' else 'after',
                            max(0, min(3, int(raw.get('decimals', 2)))), 'en' if raw.get('style') == 'en' else 'fr')
        except (KeyError, TypeError, ValueError):
            continue
    return result


def activate(organization):
    """Rend les devises personnalisées de l'organisation disponibles au filtre `money` (contexte courant)."""
    _custom.set(custom_currencies(organization))


def info(code, organization=None):
    code = str(code or DEFAULT_CURRENCY).strip().upper()
    customs = custom_currencies(organization) if organization is not None else (_custom.get() or {})
    if code in customs:
        spec = customs[code]
    elif code in BUILTIN:
        spec = BUILTIN[code]
    else:
        spec = (code, code, 'after', 2, 'fr')
    name, symbol, position, decimals, style = spec
    return {'code': code, 'name': name, 'symbol': symbol, 'position': position, 'decimals': decimals, 'style': style}


def format_number(amount, decimals=2, style='fr'):
    try:
        value = Decimal(str(amount if amount not in (None, '') else 0))
    except (InvalidOperation, ValueError):
        return str(amount)
    quantum = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
    value = value.quantize(quantum, rounding=ROUND_HALF_UP)
    sign = '-' if value < 0 else ''
    integer, _, fraction = f'{abs(value):.{decimals}f}'.partition('.')
    groups = []
    while integer:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    thousands, point = (',', '.') if style == 'en' else (NARROW_NBSP, ',')
    text = thousands.join(groups or ['0'])
    return sign + (f'{text}{point}{fraction}' if decimals else text)


def format_money(amount, code=DEFAULT_CURRENCY, organization=None):
    """« $1,234.56 », « 1 234,56 € », « 1 250 000 FCFA »."""
    spec = info(code, organization)
    number = format_number(amount, spec['decimals'], spec['style'])
    negative = number.startswith('-')
    number = number.lstrip('-')
    if spec['position'] == 'before':
        text = f"{spec['symbol']}{number}" if len(spec['symbol']) <= 1 or spec['symbol'].endswith('$') else f"{spec['symbol']} {number}"
    else:
        text = f"{number}{NARROW_NBSP}{spec['symbol']}"
    return f'-{text}' if negative else text


def choices(organization=None):
    """[(code, libellé)] : devises personnalisées d'abord, puis les devises intégrées."""
    items = [(code, f'{spec[0]} ({spec[1]}) · personnalisée') for code, spec in custom_currencies(organization).items()]
    items += [(code, f'{spec[0]} ({spec[1]})') for code, spec in BUILTIN.items()]
    return items


def js_formats(organization=None):
    """Formats pour le navigateur (éditeur de facture) : {code: {symbol, position, decimals, style}}."""
    codes = set(BUILTIN) | set(custom_currencies(organization))
    return {code: {k: v for k, v in info(code, organization).items() if k != 'code'} for code in codes}


def editor_context(organization, bootstrap, *, new):
    """Devises proposées dans l'éditeur ; un nouveau document prend la devise par défaut de l'organisation."""
    if new and organization is not None and isinstance(bootstrap, dict):
        data = bootstrap.get('invoice_data') or bootstrap.get('quote_data')
        if isinstance(data, dict):
            data['currency'] = organization.default_currency or DEFAULT_CURRENCY
    from apps.templates_app.canvas_assets import assets_for
    return {'currency_choices': choices(organization), 'currency_formats': js_formats(organization),
            'logo_assets': assets_for(organization)}
