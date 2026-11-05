"""Rappel « Terminez votre profil de paiement » sur l'accueil tant que Stripe n'est pas entièrement configuré."""
from unittest import mock

from django.test import Client as HttpClient, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.organizations.models import Organization
from apps.payments import stripe_connect
from apps.payments.models import StripeConnectAccount

PLATFORM = 'sk_test_platform'


@override_settings(STRIPE_SECRET_KEY=PLATFORM)
class StripeSetupTodoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='todo', email='todo@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Atelier', owner=self.user, email='todo@test.fr', country='FR')
        prefs = dict(self.org.billing_preferences or {})
        prefs['onboarding'] = {'state': 'done'}
        self.org.billing_preferences = prefs
        self.org.save()

    def account(self, **flags):
        return StripeConnectAccount.objects.create(organization=self.org, account_id='acct_todo', **flags)

    def test_states(self):
        self.assertEqual(stripe_connect.setup_todo(self.org)['state'], 'none')
        account = self.account()
        self.assertEqual(stripe_connect.setup_todo(self.org)['state'], 'incomplete')
        account.details_submitted = True
        account.save()
        self.assertEqual(stripe_connect.setup_todo(self.org)['state'], 'restricted')
        account.charges_enabled = True
        account.save()
        self.assertEqual(stripe_connect.setup_todo(self.org)['state'], 'payouts')
        account.payouts_enabled = True
        account.save()
        self.assertIsNone(stripe_connect.setup_todo(self.org))

    @override_settings(STRIPE_SECRET_KEY='')
    def test_hidden_when_connect_is_not_offered(self):
        self.assertIsNone(stripe_connect.setup_todo(self.org))

    def test_dashboard_shows_the_reminder_until_stripe_is_ready(self):
        http = HttpClient(HTTP_HOST='127.0.0.1')
        http.force_login(self.user)
        self.account(details_submitted=False)
        html = http.get('/dashboard/').content.decode()
        self.assertIn('Terminez votre profil de paiement', html)
        self.assertIn(reverse('payments:connect-refresh'), html)
        StripeConnectAccount.objects.filter(organization=self.org).update(
            details_submitted=True, charges_enabled=True, payouts_enabled=True)
        html = http.get('/dashboard/').content.decode()
        self.assertNotIn('Terminez votre profil de paiement', html)


class CompliancePreviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='comp', email='comp@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Atelier', owner=self.user, email='comp@test.fr', country='FR')
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def test_heading_follows_the_chosen_country_without_saving(self):
        url = reverse('accounts:compliance-preview')
        data = self.http.get(url, {'country': 'BE', 'status': 'freelance', 'taxed': 'yes'}).json()
        self.assertEqual(data['heading'], "Ce qu'il faut sur vos factures en Belgique.")
        self.assertTrue(data['items'])
        data = self.http.get(url, {'country': 'US'}).json()
        self.assertIn('États-Unis', data['heading'])
        self.org.refresh_from_db()
        self.assertNotIn('compliance', self.org.billing_preferences or {})


@override_settings(STRIPE_SECRET_KEY=PLATFORM, STRIPE_PUBLISHABLE_KEY='pk_test_platform')
class EmbeddedOnboardingTests(TestCase):
    """Inscription Stripe Connect affichée dans Billio (composant Stripe), sans quitter Paramètres › Paiement."""

    def setUp(self):
        self.user = User.objects.create_user(username='embed', email='embed@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Atelier', owner=self.user, email='embed@test.fr', country='FR')
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def fake_stripe(self):
        calls = []

        def http(method, url, form=None, headers=None, **kwargs):
            calls.append((url.rsplit('/v1', 1)[-1], form or {}, headers or {}))
            if url.endswith('/account_sessions'):
                return {'client_secret': 'accs_secret_123'}
            return {'id': 'acct_embed', 'country': 'FR', 'details_submitted': False, 'charges_enabled': False,
                    'payouts_enabled': False, 'requirements': {'currently_due': []}}
        return http, calls

    def test_session_creates_the_account_and_returns_a_client_secret(self):
        http, calls = self.fake_stripe()
        with mock.patch('apps.payments.stripe_connect.http', http):
            data = self.http.post(reverse('payments:connect-session')).json()
        self.assertEqual(data, {'client_secret': 'accs_secret_123'})
        self.assertEqual([c[0] for c in calls], ['/accounts', '/account_sessions'])
        form = calls[1][1]
        self.assertEqual(form['account'], 'acct_embed')
        self.assertEqual(form['components[account_onboarding][enabled]'], 'true')
        self.assertTrue(StripeConnectAccount.objects.filter(organization=self.org, account_id='acct_embed').exists())

    def test_session_needs_post(self):
        self.assertEqual(self.http.get(reverse('payments:connect-session')).status_code, 405)

    @override_settings(STRIPE_PUBLISHABLE_KEY='')
    def test_falls_back_to_the_stripe_hosted_page_without_publishable_key(self):
        self.assertEqual(self.http.post(reverse('payments:connect-session')).status_code, 503)
        html = self.http.get(reverse('accounts:user-settings') + '?tab=paiement').content.decode()
        self.assertNotIn('data-connect-onboarding', html)
        self.assertIn(reverse('payments:connect-start'), html)

    def test_settings_page_embeds_the_onboarding_and_csp_allows_stripe(self):
        response = self.http.get(reverse('accounts:user-settings') + '?tab=paiement')
        html = response.content.decode()
        self.assertIn('data-connect-onboarding', html)
        self.assertIn('data-publishable-key="pk_test_platform"', html)
        self.assertIn('stripe-connect-onboarding.js', html)
        csp = response.get('Content-Security-Policy', '')
        self.assertIn('https://connect-js.stripe.com', csp)
        self.assertIn('frame-src', csp)
