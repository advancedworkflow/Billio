"""
Filtres de mise en forme pour les modèles de facture / devis (rendus avec
`django.template.Template` dans l'aperçu de l'éditeur comme dans le PDF) :

    {% load billio_format %}
    {{ total_amount|money:currency }}   ->  3 240,00 €
    {{ item.quantity|qty }}             ->  2   /  1,5
    {{ item.tax_rate|percent }}         ->  20 %

Les valeurs arrivent sous forme de chaînes ("1800.00"), de Decimal ou de nombres
selon qu'on est dans l'aperçu ou dans le PDF : les filtres acceptent les trois et
renvoient la valeur telle quelle si elle n'est pas numérique.
"""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

THIN_SPACE = ' '
CURRENCY_SYMBOLS = {'EUR': '€', 'USD': '$', 'GBP': '£', 'CAD': '$ CA', 'CHF': 'CHF'}


def _to_decimal(value):
    if value is None or value == '':
        return None
    if isinstance(value, Decimal):
        return value
    try:
        text = str(value).replace(THIN_SPACE, '').replace(' ', '').replace(' ', '')
        if text.count(',') == 1 and '.' not in text:
            text = text.replace(',', '.')
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _group(number_text):
    """1234567.89 -> 1 234 567,89 (espaces fines, virgule décimale)."""
    integer, _, decimals = number_text.partition('.')
    negative = integer.startswith('-')
    integer = integer.lstrip('-')
    groups = []
    while len(integer) > 3:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    groups.insert(0, integer)
    result = THIN_SPACE.join(groups)
    if decimals:
        result = f'{result},{decimals}'
    return f'-{result}' if negative else result


@register.filter
def money(value, currency='USD'):
    """Montant dans sa devise (symbole, position, décimales et format : voir organizations.currencies)."""
    from apps.organizations.currencies import format_money
    amount = _to_decimal(value)
    if amount is None:
        return value
    return format_money(amount, currency or 'USD')


@register.filter
def amount(value):
    """Montant sans symbole : 1 800,00"""
    number = _to_decimal(value)
    return value if number is None else _group(f'{number:.2f}')


@register.filter
def qty(value):
    number = _to_decimal(value)
    if number is None:
        return value
    text = f'{number.normalize():f}'
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return _group(text)


@register.filter
def percent(value):
    number = _to_decimal(value)
    if number is None:
        return value
    return f'{qty(number)} %'


@register.filter
def get_item(mapping, key):
    """{{ dict|get_item:cle }} — accès à une clé variable dans un template."""
    if isinstance(mapping, dict):
        return mapping.get(key, '')
    return ''


@register.filter
def split_options(value):
    """« Option A, Option B » -> ['Option A', 'Option B'] (listes de choix des formulaires)."""
    return [part.strip() for part in str(value or '').split(',') if part.strip()]


def _line_field(item, name):
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


@register.filter
def line_tax(item):
    """Montant de TVA d'une ligne : total HT × taux."""
    total, rate = _to_decimal(_line_field(item, 'total')), _to_decimal(_line_field(item, 'tax_rate'))
    if total is None or rate is None:
        return ''
    return (total * rate / 100).quantize(Decimal('0.01'))


@register.filter
def line_ttc(item):
    """Total TTC d'une ligne."""
    tax = line_tax(item)
    total = _to_decimal(_line_field(item, 'total'))
    return '' if total is None or tax == '' else total + tax


@register.filter
def nonzero(value):
    number = _to_decimal(value)
    return bool(number)
