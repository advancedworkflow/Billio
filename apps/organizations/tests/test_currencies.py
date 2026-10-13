from decimal import Decimal

from django.test import SimpleTestCase

from apps.organizations import currencies
from apps.templates_app.templatetags.billio_format import money


class _Org:
    def __init__(self, customs):
        self.billing_preferences = {'custom_currencies': customs}


class CurrencyFormatTests(SimpleTestCase):
    def test_usd_default(self):
        self.assertEqual(currencies.format_money(Decimal('1234.5')), '$1,234.50')

    def test_euro(self):
        self.assertEqual(currencies.format_money(1234.5, 'EUR'), '1 234,50 €')

    def test_fcfa_no_decimals(self):
        self.assertEqual(currencies.format_money(1250000, 'XOF'), '1 250 000 FCFA')

    def test_negative(self):
        self.assertEqual(currencies.format_money(-10, 'USD'), '-$10.00')

    def test_custom_currency(self):
        org = _Org([{'code': 'abc', 'name': 'Test', 'symbol': 'T', 'position': 'after', 'decimals': 0, 'style': 'fr'}])
        self.assertEqual(currencies.format_money(1500, 'ABC', org), '1 500 T')
        self.assertIn('ABC', dict(currencies.choices(org)))

    def test_money_filter_uses_activated_org(self):
        currencies.activate(_Org([{'code': 'ZZZ', 'symbol': 'Z', 'decimals': 0}]))
        try:
            self.assertEqual(money(42, 'ZZZ'), '42 Z')
        finally:
            currencies.activate(None)

    def test_editor_context_sets_org_currency_on_new(self):
        org = _Org([])
        org.default_currency = 'XOF'
        boot = {'invoice_data': {'currency': 'EUR'}}
        ctx = currencies.editor_context(org, boot, new=True)
        self.assertEqual(boot['invoice_data']['currency'], 'XOF')
        self.assertIn('XOF', ctx['currency_formats'])
