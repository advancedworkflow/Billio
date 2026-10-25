"""Paiement en ligne avec Stripe Connect : inscription, encaissement sur le compte connecté, commission, webhook."""
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import Client as HttpClient, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.dashboard.models import Notification
from apps.integrations.models import ConnectionInstance, Connector
from apps.invoices.models import Invoice
from apps.organizations.models import Organization, OrganizationMember
from apps.payments import stripe_connect
from apps.payments.models import Payment, StripeConnectAccount
from apps.payments.stripe_checkout import stripe_access
from apps.subscriptions.models import Plan
from apps.subscriptions.testing import give_plan

PLATFORM = 'sk_test_platform'
WEBHOOK = {'STRIPE_CONNECT_WEBHOOK_SECRET': 'whsec_connect'}


class FakeStripe:
    """Répond aux appels de l'API Stripe et garde chaque appel (méthode, chemin, formulaire, en-têtes)."""

    def __init__(self, account=None):
        self.account = {'id': 'acct_123', 'country': 'FR', 'default_currency': 'eur', 'details_submitted': False,
                        'charges_enabled': False, 'payouts_enabled': False,
                        'requirements': {'currently_due': ['external_account']}, **(account or {})}
        self.calls = []

    def __call__(self, method, url, form=None, headers=None, **kwargs):
        path = urllib.parse.urlparse(url).path.removeprefix('/v1')
        self.calls.append((method, path, form or {}, headers or {}))
        if path == '/accounts' or path.startswith('/accounts/'):
            return self.account
        if path == '/account_links':
            return {'url': 'https://connect.stripe.com/setup/s/abc'}
        if path == '/checkout/sessions':
            return {'url': 'https://checkout.stripe.com/c/pay/cs_test_1'}
        return {}

    def call(self, path):
        return next(c for c in self.calls if c[1] == path)


def signed_post(http, event, secret='whsec_connect'):
    payload = json.dumps(event).encode()
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f'{ts}.'.encode() + payload, hashlib.sha256).hexdigest()
    return http.post(reverse('payments:stripe-connect-webhook'), payload, content_type='application/json',
                     HTTP_STRIPE_SIGNATURE=f't={ts},v1={sig}')


def make_org(country=None):
    user = User.objects.create_user(username='owner', email='owner@studio.test', password='x-Test-1234')
    org = Organization.objects.create(name='Studio Lumen', owner=user, email='owner@studio.test')
    if country:
        org.billing_preferences = {'compliance': {'country': country}}
        org.save()
    return user, org


def make_invoice(org):
    client = Client.objects.create(organization=org, name='Rive', email='rive@client.test')
    today = timezone.localdate()
    invoice = Invoice.objects.create(organization=org, client=client, issue_date=today, due_date=today + timedelta(days=30),
                                     subtotal=Decimal('100'), tax_amount=Decimal('20'), total_amount=Decimal('120'))
    invoice.status = 'sent'
    invoice.save()
    return invoice


@override_settings(STRIPE_SECRET_KEY=PLATFORM)
class OnboardingTests(TestCase):
    def setUp(self):
        self.user, self.org = make_org()
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def test_start_creates_account_and_opens_stripe_onboarding(self):
        fake = FakeStripe()
        with mock.patch('apps.payments.stripe_connect.http', fake):
            response = self.http.post(reverse('payments:connect-start'))
        self.assertEqual(response['Location'], 'https://connect.stripe.com/setup/s/abc')
        _, _, form, headers = fake.call('/accounts')
        self.assertEqual(headers['Authorization'], f'Bearer {PLATFORM}')
        self.assertEqual((form['country'], form['controller[stripe_dashboard][type]'], form['controller[fees][payer]']),
                         ('FR', 'full', 'account'))
        self.assertEqual(form['metadata[organization_id]'], self.org.id)
        link = fake.call('/account_links')[2]
        self.assertTrue(link['return_url'].endswith(reverse('payments:connect-return')))
        account = StripeConnectAccount.objects.get(organization=self.org)
        self.assertEqual((account.account_id, account.status, account.requirements), ('acct_123', 'incomplete', ['external_account']))

    def test_restart_reuses_the_same_account(self):
        StripeConnectAccount.objects.create(organization=self.org, account_id='acct_old')
        fake = FakeStripe()
        with mock.patch('apps.payments.stripe_connect.http', fake):
            self.http.post(reverse('payments:connect-start'))
        self.assertEqual([c[1] for c in fake.calls], ['/account_links'])
        self.assertEqual(fake.call('/account_links')[2]['account'], 'acct_old')

    def test_unsupported_country_is_refused(self):
        self.org.billing_preferences = {'compliance': {'country': 'BR'}}
        self.org.save()
        with mock.patch('apps.payments.stripe_connect.http') as http:
            self.http.post(reverse('payments:connect-start'))
        http.assert_not_called()
        self.assertFalse(StripeConnectAccount.objects.exists())

    def test_simple_member_cannot_activate(self):
        member = User.objects.create_user(username='m', email='m@studio.test', password='x-Test-1234')
        OrganizationMember.objects.create(organization=self.org, user=member, role='member')
        self.http.force_login(member)
        with mock.patch('apps.payments.stripe_connect.http') as http:
            self.http.post(reverse('payments:connect-start'))
        http.assert_not_called()

    def test_return_syncs_status_and_notifies_activation(self):
        StripeConnectAccount.objects.create(organization=self.org, account_id='acct_123')
        fake = FakeStripe({'details_submitted': True, 'charges_enabled': True, 'payouts_enabled': True,
                           'requirements': {'currently_due': []}, 'settings': {'dashboard': {'display_name': 'Studio Lumen'}}})
        with mock.patch('apps.payments.stripe_connect.http', fake):
            self.http.get(reverse('payments:connect-return'))
        account = StripeConnectAccount.objects.get(organization=self.org)
        self.assertEqual((account.status, account.payouts_enabled, account.display_name), ('active', True, 'Studio Lumen'))
        self.assertEqual(Notification.objects.filter(user=self.user, title='Paiement en ligne activé').count(), 1)

    def test_settings_page_offers_activation(self):
        html = self.http.get(reverse('accounts:user-settings')).content.decode()
        self.assertIn(reverse('payments:connect-start'), html)
        self.assertIn('Activer les paiements', html)

    @override_settings(STRIPE_SECRET_KEY='')
    def test_without_platform_key_settings_keep_own_keys_mode(self):
        html = self.http.get(reverse('accounts:user-settings')).content.decode()
        self.assertNotIn(reverse('payments:connect-start'), html)


@override_settings(STRIPE_SECRET_KEY=PLATFORM)
class ConnectCheckoutTests(TestCase):
    def setUp(self):
        self.user, self.org = make_org()
        self.account = StripeConnectAccount.objects.create(organization=self.org, account_id='acct_123', charges_enabled=True)
        self.invoice = make_invoice(self.org)
        self.http = HttpClient(HTTP_HOST='127.0.0.1')

    def pay(self):
        fake = FakeStripe()
        with mock.patch('apps.payments.stripe_checkout.http', fake):
            response = self.http.post(reverse('invoices:public-invoice-pay', args=[self.invoice.id]))
        self.assertEqual(response['Location'], 'https://checkout.stripe.com/c/pay/cs_test_1')
        return fake.call('/checkout/sessions')

    def test_session_is_created_on_the_connected_account_with_billio_fee(self):
        _, _, form, headers = self.pay()
        self.assertEqual(headers['Stripe-Account'], 'acct_123')
        self.assertEqual(headers['Authorization'], f'Bearer {PLATFORM}')
        self.assertEqual(form['payment_intent_data[application_fee_amount]'], 60)  # 0,5 % de 120 €

    def test_business_plan_pays_no_fee(self):
        give_plan(self.user, 'business')
        form = self.pay()[2]
        self.assertNotIn('payment_intent_data[application_fee_amount]', form)

    def test_plan_fees(self):
        fees = {p.code: p.limit('payment_fee_percent') for p in Plan.objects.all()}
        self.assertEqual(fees, {'free': 0.5, 'starter': 0.5, 'pro': 0.5, 'business': 0, 'agency': 0})
        self.assertEqual(stripe_connect.application_fee(self.org, 12345), 62)

    def test_connect_takes_over_own_keys_until_it_can_charge(self):
        connector, _ = Connector.objects.get_or_create(key='stripe', defaults={'name': 'Stripe', 'category': 'payment'})
        ConnectionInstance.objects.create(organization=self.org, connector=connector, status='connected',
                                          config={'secret_key': 'sk_test_own', 'webhook_secret': 'whsec_own'})
        self.assertEqual(tuple(stripe_access(self.org)), (PLATFORM, 'acct_123'))
        self.account.charges_enabled = False
        self.account.save()
        self.assertEqual(tuple(stripe_access(self.org)), ('sk_test_own', ''))

    def test_restricted_account_cannot_charge(self):
        self.account.charges_enabled = False
        self.account.save()
        self.assertIsNone(stripe_access(self.org))
        with mock.patch('apps.payments.stripe_checkout.http') as http:
            self.http.post(reverse('invoices:public-invoice-pay', args=[self.invoice.id]))
        http.assert_not_called()


@override_settings(STRIPE_SECRET_KEY=PLATFORM)
@mock.patch.dict(os.environ, WEBHOOK)
class ConnectWebhookTests(TestCase):
    def setUp(self):
        self.user, self.org = make_org()
        self.account = StripeConnectAccount.objects.create(organization=self.org, account_id='acct_123', charges_enabled=True)
        self.invoice = make_invoice(self.org)
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        patcher = mock.patch('apps.payments.stripe_checkout.used_method', return_value='card')
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, event, secret='whsec_connect'):
        return signed_post(self.http, event, secret)

    def paid_event(self, account='acct_123'):
        return {'type': 'checkout.session.completed', 'account': account, 'data': {'object': {
            'id': 'cs_test_1', 'payment_status': 'paid', 'amount_total': 12000, 'payment_intent': 'pi_1',
            'metadata': {'organization_id': str(self.org.id), 'invoice_id': str(self.invoice.id)}}}}

    def test_bad_signature_is_rejected(self):
        self.assertEqual(self.post(self.paid_event(), secret='whsec_other').status_code, 400)
        self.invoice.refresh_from_db()
        self.assertNotEqual(self.invoice.status, 'paid')

    def test_paid_session_on_connected_account_pays_invoice_once(self):
        self.assertEqual(self.post(self.paid_event()).status_code, 200)
        self.post(self.paid_event())
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'paid')
        self.assertEqual(Payment.objects.filter(invoice=self.invoice, provider='stripe').count(), 1)

    def test_event_from_unknown_account_is_ignored(self):
        self.assertEqual(self.post(self.paid_event(account='acct_other')).status_code, 200)
        self.invoice.refresh_from_db()
        self.assertNotEqual(self.invoice.status, 'paid')

    def test_account_updated_refreshes_status(self):
        self.post({'type': 'account.updated', 'account': 'acct_123', 'data': {'object': {
            'id': 'acct_123', 'details_submitted': True, 'charges_enabled': False, 'payouts_enabled': False,
            'requirements': {'currently_due': ['individual.verification.document'], 'disabled_reason': 'requirements.past_due'}}}})
        self.account.refresh_from_db()
        self.assertEqual((self.account.status, self.account.disabled_reason), ('restricted', 'requirements.past_due'))
        self.assertIsNone(stripe_access(self.org))
