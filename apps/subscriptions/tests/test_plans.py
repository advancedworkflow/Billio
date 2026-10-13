"""
Forfaits Billio : grille, quotas, options, délai de grâce, Stripe (Checkout, webhook signé), API.

    python manage.py test apps.subscriptions
"""
import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import Client as HttpClient, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.dashboard.models import Project
from apps.invoices.models import Invoice, Quote
from apps.organizations.models import Organization
from apps.subscriptions import billing
from apps.subscriptions.entitlements import has_feature, plan_for, usage
from apps.subscriptions.models import Plan, Subscription
from apps.subscriptions.testing import give_plan

WEBHOOK_SECRET = 'whsec_billio_test'


def make_account(email='camille@test.fr'):
    user = User.objects.create_user(username=email.split('@')[0], email=email, password='x-Test-1234')
    org = Organization.objects.create(name='Studio', owner=user, email=email)
    return user, org


def signed(payload):
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    sig = hmac.new(WEBHOOK_SECRET.encode(), f'{ts}.'.encode() + body, hashlib.sha256).hexdigest()
    return body, f't={ts},v1={sig}'


class PlanGridTests(TestCase):
    def test_launch_grid(self):
        grid = {p.code: (p.price_monthly, p.limit('clients'), p.feature('api')) for p in Plan.objects.all()}
        self.assertEqual(grid, {
            'free': (Decimal('0.00'), 15, False), 'starter': (Decimal('9.00'), 100, False),
            'pro': (Decimal('19.00'), 300, False), 'business': (Decimal('39.00'), 1000, True),
            'agency': (Decimal('79.00'), None, True),
        })

    def test_new_account_is_free(self):
        user, org = make_account()
        self.assertEqual(plan_for(org).code, 'free')
        self.assertFalse(has_feature(org, 'reminders'))
        self.assertTrue(has_feature(org, 'portal', 'basic'))
        self.assertFalse(has_feature(org, 'portal', 'full'))


class QuotaTests(TestCase):
    def setUp(self):
        self.user, self.org = make_account()
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def test_client_limit_blocks_only_new_creations(self):
        for i in range(15):  # hors requête : jamais bloqué (imports, tâches planifiées)
            Client.objects.create(organization=self.org, name=f'Client {i}', email=f'c{i}@test.fr')
        response = self.http.post(reverse('clients:client-quick-create'), {'name': 'Seizième', 'email': 'c16@test.fr'},
                                  HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertIn('15 clients actifs', data['message'])
        self.assertIn('Starter', data['message'])
        self.assertTrue(data['upgrade_url'].startswith(reverse('subscriptions:billing')))
        self.assertEqual(Client.objects.filter(organization=self.org).count(), 15)
        give_plan(self.user, 'starter')
        response = self.http.post(reverse('clients:client-quick-create'), {'name': 'Seizième', 'email': 'c16@test.fr'},
                                  HTTP_ACCEPT='application/json')
        self.assertLess(response.status_code, 300)

    def test_monthly_documents_counts_invoices_and_quotes(self):
        client = Client.objects.create(organization=self.org, name='ACME', email='a@test.fr')
        today = timezone.localdate()
        for _ in range(6):
            Invoice.objects.create(organization=self.org, client=client, issue_date=today, due_date=today, total_amount=10)
        for _ in range(4):
            Quote.objects.create(organization=self.org, client=client, issue_date=today, expiry_date=today, total_amount=10)
        self.assertEqual(usage(self.org, 'documents_per_month'), 10)
        invoice = Invoice.objects.filter(organization=self.org).first()
        response = self.http.post(reverse('invoices:duplicate-invoice', args=[invoice.id]), HTTP_ACCEPT='application/json')
        self.assertGreaterEqual(response.status_code, 400)
        self.assertIn('10 factures et devis par mois', response.json()['message'])
        self.assertEqual(Invoice.objects.filter(organization=self.org).count(), 6)

    def test_feature_locked_message(self):
        project = Project.objects.create(organization=self.org, client=Client.objects.create(organization=self.org, name='B', email='b@test.fr'), name='Film')
        response = self.http.post(reverse('dashboard:time-timer-start', args=[project.id]), HTTP_SEC_FETCH_MODE='cors')
        self.assertEqual(response.status_code, 403)
        self.assertIn('Le suivi du temps est disponible à partir du forfait Starter', response.json()['message'])
        give_plan(self.user, 'starter')
        self.assertEqual(self.http.post(reverse('dashboard:time-timer-start', args=[project.id])).status_code, 200)
        self.assertEqual(self.http.post(reverse('dashboard:time-invoice', args=[project.id]), HTTP_SEC_FETCH_MODE='cors').status_code, 403)  # facturation : Pro

    def test_second_organization_needs_agency(self):
        response = self.http.post(reverse('organizations:organization-create'), {'name': 'Deuxième'},
                                  HTTP_REFERER='http://127.0.0.1/organizations/list/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Organization.objects.filter(owner=self.user).count(), 1)
        give_plan(self.user, 'agency')
        self.http.post(reverse('organizations:organization-create'), {'name': 'Deuxième'})
        self.assertEqual(Organization.objects.filter(owner=self.user).count(), 2)


class GraceTests(TestCase):
    def test_past_due_keeps_plan_for_seven_days(self):
        user, org = make_account()
        sub = give_plan(user, 'pro')
        sub.comped = False
        sub.status, sub.past_due_since = 'past_due', timezone.now() - timedelta(days=3)
        sub.save()
        self.assertEqual(plan_for(org).code, 'pro')
        Subscription.objects.filter(pk=sub.pk).update(past_due_since=timezone.now() - timedelta(days=8))
        self.assertEqual(plan_for(org).code, 'free')
        Subscription.objects.filter(pk=sub.pk).update(status='canceled', past_due_since=None)
        self.assertEqual(plan_for(org).code, 'free')


@override_settings(STRIPE_SECRET_KEY='sk_test_billio', STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET)
class StripeTests(TestCase):
    def setUp(self):
        self.user, self.org = make_account()
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def remote(self, status='active', code='pro', cents=1900, **extra):
        return {
            'id': 'sub_123', 'customer': 'cus_123', 'status': status, 'cancel_at_period_end': False,
            'current_period_end': int(time.time()) + 30 * 86400, 'metadata': {'user_id': str(self.user.pk)},
            'items': {'data': [{'id': 'si_1', 'price': {'id': f'price_{code}', 'lookup_key': f'billio_{code}_{cents}_eur_month'}}]},
            **extra,
        }

    def test_checkout_redirects_to_stripe(self):
        calls = []

        def fake(method, path, form=None):
            calls.append((method, path, form))
            if path.startswith('/prices?'):
                return {'data': [{'id': 'price_pro'}]}
            if path == '/customers':
                return {'id': 'cus_123'}
            if path == '/checkout/sessions':
                return {'url': 'https://checkout.stripe.com/c/pay/cs_test_1'}
            raise AssertionError(path)

        with mock.patch.object(billing, '_call', side_effect=fake):
            response = self.http.post(reverse('subscriptions:choose', args=['pro']))
        self.assertRedirects(response, 'https://checkout.stripe.com/c/pay/cs_test_1', fetch_redirect_response=False)
        session = next(form for method, path, form in calls if path == '/checkout/sessions')
        self.assertEqual((session['mode'], session['line_items[0][price]'], session['client_reference_id']),
                         ('subscription', 'price_pro', self.user.pk))
        self.assertEqual(Subscription.objects.get(user=self.user).stripe_customer_id, 'cus_123')
        self.assertEqual(plan_for(self.org).code, 'free')  # rien n'est accordé avant la confirmation de Stripe

    def test_signed_webhook_activates_plan(self):
        body, header = signed({'id': 'evt_1', 'type': 'customer.subscription.updated', 'data': {'object': {'id': 'sub_123'}}})
        with mock.patch.object(billing, '_call', return_value=self.remote()):
            response = self.http.post(reverse('subscriptions:stripe-webhook'), body, content_type='application/json',
                                      HTTP_STRIPE_SIGNATURE=header)
        self.assertEqual(response.status_code, 200)
        sub = Subscription.objects.get(user=self.user)
        self.assertEqual((sub.plan.code, sub.status, sub.stripe_subscription_id), ('pro', 'active', 'sub_123'))
        self.assertEqual(plan_for(self.org).code, 'pro')

    def test_webhook_rejects_bad_signature(self):
        body, _ = signed({'type': 'customer.subscription.updated', 'data': {'object': {'id': 'sub_123'}}})
        response = self.http.post(reverse('subscriptions:stripe-webhook'), body, content_type='application/json',
                                  HTTP_STRIPE_SIGNATURE='t=1,v1=faux')
        self.assertEqual(response.status_code, 400)

    def test_payment_failed_then_canceled(self):
        with mock.patch.object(billing, '_call', return_value=self.remote(status='past_due')):
            billing.handle_event({'type': 'invoice.payment_failed', 'data': {'object': {'subscription': 'sub_123'}}})
        sub = Subscription.objects.get(user=self.user)
        self.assertIsNotNone(sub.past_due_since)
        self.assertTrue(sub.in_grace_period)
        self.assertTrue(self.user.notifications.filter(title__icontains='refusé').exists())
        with mock.patch.object(billing, '_call', return_value=self.remote(status='canceled')):
            billing.handle_event({'type': 'customer.subscription.deleted', 'data': {'object': {'id': 'sub_123'}}})
        self.assertEqual(plan_for(self.org).code, 'free')

    def test_billing_page(self):
        html = self.http.get(reverse('subscriptions:billing')).content.decode()
        for name in ('Free', 'Starter', 'Pro', 'Business', 'Agency', 'Clients actifs'):
            self.assertIn(name, html)
        self.assertIn(reverse('subscriptions:choose', args=['business']), html)


class ApiAccessTests(TestCase):
    def test_token_needs_business(self):
        from rest_framework.authtoken.models import Token
        user, _org = make_account()
        token = Token.objects.create(user=user)
        api = HttpClient(HTTP_HOST='127.0.0.1')
        url = reverse('subscriptions:plan-list')
        self.assertEqual(api.get(url, HTTP_AUTHORIZATION=f'Token {token.key}').status_code, 403)
        give_plan(user, 'business')
        self.assertEqual(api.get(url, HTTP_AUTHORIZATION=f'Token {token.key}').status_code, 200)


class IntegrationsPageTests(TestCase):
    def test_stripe_is_internal(self):
        from apps.integrations.models import ConnectionInstance, Connector
        user, org = make_account()
        stripe, _ = Connector.objects.get_or_create(key='stripe', defaults={'name': 'Stripe', 'category': 'payment'})
        ConnectionInstance.objects.create(organization=org, connector=stripe, status='connected', config={'secret_key': 'sk_test_x'})
        self.assertEqual(usage(org, 'integrations'), 0)  # brique interne : hors quota du forfait
        http = HttpClient(HTTP_HOST='127.0.0.1')
        http.force_login(user)
        html = http.get(reverse('integrations:integrations-page')).content.decode()
        self.assertIn('data-key="mailchimp"', html)
        self.assertIn('class="ig-tile" hidden', html)  # Stripe : panneau seulement, ouvert depuis Paramètres
        self.assertIn('?plugin=stripe', http.get(reverse('accounts:user-settings')).content.decode())
