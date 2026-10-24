"""QuickBooks Online : connexion OAuth (realmId, jeton renouvelé) et envoi des factures / paiements."""
import os
import urllib.parse
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client as HttpClient, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client
from apps.integrations import app_actions, oauth
from apps.integrations.models import ConnectionInstance, Connector
from apps.invoices.models import Invoice, InvoiceItem
from apps.organizations.models import Organization
from apps.payments.recording import record_manual_payment
from apps.subscriptions.testing import give_plan

ENV = {'QUICKBOOKS_CLIENT_ID': 'cid', 'QUICKBOOKS_CLIENT_SECRET': 'sec'}
CONFIG = {'access_token': 'at', 'realm_id': '9130', 'environment': 'sandbox'}


class FakeQuickBooks:
    """Répond aux appels de l'API QuickBooks et garde les créations envoyées."""

    def __init__(self, country='FR', invoices=()):
        self.country, self.invoices, self.posts = country, list(invoices), []

    def __call__(self, method, url, json_body=None, **kwargs):
        if method == 'POST':
            entity = urllib.parse.urlparse(url).path.rsplit('/', 1)[-1]
            self.posts.append((entity, json_body))
            name = {'creditmemo': 'CreditMemo'}.get(entity, entity.capitalize())
            return {name: {'Id': str(len(self.posts) + 100)}}
        if '/companyinfo/' in url:
            return {'CompanyInfo': {'CompanyName': 'Studio Lumen SAS', 'Country': self.country}}
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)['query'][0]
        if 'from TaxRate' in query:
            return {'QueryResponse': {'TaxRate': [{'Id': '1', 'RateValue': 20}, {'Id': '2', 'RateValue': 5.5}]}}
        if 'from TaxCode' in query:
            return {'QueryResponse': {'TaxCode': [
                {'Id': '7', 'SalesTaxRateList': {'TaxRateDetail': [{'TaxRateRef': {'value': '1'}}]}},
                {'Id': '8', 'SalesTaxRateList': {'TaxRateDetail': [{'TaxRateRef': {'value': '2'}}]}}]}}
        if 'from Invoice' in query:
            return {'QueryResponse': {'Invoice': self.invoices}}
        if 'from Account' in query:
            return {'QueryResponse': {'Account': [{'Id': '79'}]}}
        if 'from Preferences' in query:
            return {'QueryResponse': {'Preferences': [{'CurrencyPrefs': {'HomeCurrency': {'value': 'EUR'}}}]}}
        return {'QueryResponse': {}}  # client ou service absent : créé

    def posted(self, entity):
        return [body for name, body in self.posts if name == entity]


@mock.patch.dict(os.environ, ENV)
class QuickBooksConnectionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='q', email='q@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio', owner=self.user)
        give_plan(self.user, 'business')
        Connector.objects.get_or_create(key='quickbooks', defaults={'name': 'QuickBooks', 'category': 'accounting'})
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def _state(self):
        response = self.http.get(reverse('integrations:oauth-connect', args=['quickbooks']))
        url = urllib.parse.urlparse(response['Location'])
        self.assertEqual(url.hostname, 'appcenter.intuit.com')
        self.assertEqual(urllib.parse.parse_qs(url.query)['scope'], ['com.intuit.quickbooks.accounting'])
        return urllib.parse.parse_qs(url.query)['state'][0]

    def test_round_trip_keeps_company_and_tokens(self):
        state = self._state()
        tokens = {'access_token': 'at', 'refresh_token': 'rt', 'expires_in': 3600}
        with mock.patch('apps.integrations.oauth.http', return_value=tokens), \
                mock.patch('apps.integrations.providers.http', FakeQuickBooks()):
            self.http.get(reverse('integrations:oauth-callback', args=['quickbooks']),
                          {'code': 'abc', 'state': state, 'realmId': '9130'})
        instance = ConnectionInstance.objects.get(organization=self.org, connector__key='quickbooks')
        self.assertEqual(instance.status, 'connected')
        self.assertEqual((instance.config['realm_id'], instance.config['refresh_token']), ('9130', 'rt'))
        self.assertEqual(instance.config['account'], 'Studio Lumen SAS')
        self.assertEqual(instance.config['environment'], 'production')

    def test_missing_company_is_refused(self):
        state = self._state()
        with mock.patch('apps.integrations.oauth.http') as http:
            self.http.get(reverse('integrations:oauth-callback', args=['quickbooks']), {'code': 'abc', 'state': state})
        http.assert_not_called()
        self.assertFalse(ConnectionInstance.objects.filter(connector__key='quickbooks', status='connected').exists())

    def test_expired_token_is_renewed_and_new_refresh_token_saved(self):
        instance = ConnectionInstance.objects.create(
            organization=self.org, connector=Connector.objects.get(key='quickbooks'), status='connected',
            config=dict(CONFIG, refresh_token='old', token_expiry=0))
        with mock.patch('apps.integrations.oauth.http', return_value={'access_token': 'new', 'refresh_token': 'rt2'}) as http:
            config = oauth.fresh_config(instance)
        self.assertEqual(http.call_args.kwargs['form'], {'grant_type': 'refresh_token', 'refresh_token': 'old'})
        instance.refresh_from_db()
        self.assertEqual((config['access_token'], instance.config['refresh_token']), ('new', 'rt2'))
        self.assertGreater(instance.config['token_expiry'], timezone.now().timestamp())


class QuickBooksActionsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='q', email='q@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio', owner=self.user)
        self.client_obj = Client.objects.create(organization=self.org, name="L'Atelier Rive", email='r@rive.fr')
        self.invoice = Invoice.objects.create(organization=self.org, client=self.client_obj, issue_date=date(2026, 3, 1),
                                              due_date=date(2026, 3, 31), subtotal=Decimal('300'), tax_amount=Decimal('45.50'),
                                              total_amount=Decimal('345.50'), currency='EUR')
        InvoiceItem.objects.create(invoice=self.invoice, name='Design', quantity=2, unit_price=Decimal('100'), tax_rate=Decimal('20'))
        InvoiceItem.objects.create(invoice=self.invoice, name='Livre', quantity=1, unit_price=Decimal('100'), tax_rate=Decimal('5.5'))
        self.invoice.status = 'sent'
        self.invoice.save()

    def event(self, target_type, target_id):
        ctx = {'trigger_key': 'invoice_sent', 'target_type': target_type, 'target_id': target_id, 'organization': self.org}
        return app_actions.event_payload(ctx, self.client_obj)

    def test_invoice_is_created_with_lines_and_vat_codes(self):
        fake = FakeQuickBooks()
        with mock.patch('apps.integrations.providers.http', fake):
            detail = app_actions._qbo_invoice(CONFIG, {'item': 'Prestations'}, self.event('invoice', self.invoice.id))
        self.assertIn(self.invoice.invoice_number, detail)
        self.assertEqual(fake.posted('customer')[0]['DisplayName'], "L'Atelier Rive")
        self.assertEqual(fake.posted('item')[0]['IncomeAccountRef'], {'value': '79'})
        body = fake.posted('invoice')[0]
        self.assertEqual(body['DocNumber'], self.invoice.invoice_number)
        self.assertEqual(body['GlobalTaxCalculation'], 'TaxExcluded')
        self.assertEqual([line['Amount'] for line in body['Line']], [200.0, 100.0])
        self.assertEqual([line['SalesItemLineDetail']['TaxCodeRef']['value'] for line in body['Line']], ['7', '8'])
        self.assertNotIn('CurrencyRef', body)

    def test_invoice_already_in_quickbooks_is_not_duplicated(self):
        fake = FakeQuickBooks(invoices=[{'Id': '55'}])
        with mock.patch('apps.integrations.providers.http', fake):
            detail = app_actions._qbo_invoice(CONFIG, {}, self.event('invoice', self.invoice.id))
        self.assertIn('Déjà dans QuickBooks', detail)
        self.assertEqual(fake.posts, [])

    def test_us_company_uses_tax_flags(self):
        fake = FakeQuickBooks(country='US')
        with mock.patch('apps.integrations.providers.http', fake):
            app_actions._qbo_invoice(CONFIG, {}, self.event('invoice', self.invoice.id))
        body = fake.posted('invoice')[0]
        self.assertEqual({line['SalesItemLineDetail']['TaxCodeRef']['value'] for line in body['Line']}, {'TAX'})
        self.assertNotIn('GlobalTaxCalculation', body)

    def test_payment_is_linked_to_the_quickbooks_invoice(self):
        with mock.patch('apps.dashboard.automation_engine.run_automations'):
            payment, _, _ = record_manual_payment(self.invoice, Decimal('100'), date(2026, 3, 10), method_type='bank_transfer')
        fake = FakeQuickBooks(invoices=[{'Id': '55', 'CustomerRef': {'value': '12'}}])
        with mock.patch('apps.integrations.providers.http', fake):
            app_actions._qbo_payment(CONFIG, {}, self.event('payment', payment.id))
        body = fake.posted('payment')[0]
        self.assertEqual((body['TotalAmt'], body['CustomerRef']), (100.0, {'value': '12'}))
        self.assertEqual(body['Line'][0]['LinkedTxn'], [{'TxnId': '55', 'TxnType': 'Invoice'}])

    def test_invoice_of_another_client_is_refused(self):
        other = Client.objects.create(organization=self.org, name='Autre', email='a@a.fr')
        event = self.event('invoice', self.invoice.id)
        event['client']['id'] = str(other.id)
        from apps.integrations.providers import ProviderError
        with self.assertRaises(ProviderError):
            app_actions._qbo_invoice(CONFIG, {}, event)
