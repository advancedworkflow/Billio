"""Rappel « Terminez votre profil de paiement » sur l'accueil tant que Stripe n'est pas entièrement configuré."""
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
