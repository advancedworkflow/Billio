"""Assistant de démarrage : proposé après l'inscription, chaque étape peut être passée."""
from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.onboarding import state
from apps.invoices.models import Tax
from apps.organizations.models import Organization, OrganizationMember
from apps.organizations import jurisdictions


class OnboardingTests(TestCase):
    def setUp(self):
        self.http = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr')
        response = self.http.post(reverse('accounts:register'), {
            'name': 'Julie Moreau', 'email': 'julie@moreau-photo.fr', 'password': 'Photo-Lumiere-2026',
            'country': 'FR', 'phone': '06 12 34 56 78', 'trade': 'audiovisuel', 'accept_terms': '1'})
        self.assertRedirects(response, reverse('accounts:onboarding'), fetch_redirect_response=False)
        self.org = Organization.objects.get(owner__email='julie@moreau-photo.fr')

    def submit(self, **data):
        fields = {'name': 'Studio Lumen', 'trade': 'web', 'country': 'CA', 'status': 'pme', 'tax_registered': 'yes',
                  'payment_days': '15', 'doc_language': 'en', 'invoice_prefix': 'inv', 'interests': ['online', 'time']}
        fields.update(data)
        return self.http.post(reverse('accounts:onboarding'), fields)

    def test_dashboard_sends_new_account_to_onboarding_until_done(self):
        self.assertEqual(state(self.org), 'pending')
        self.assertRedirects(self.http.get(reverse('dashboard:dashboard-home')), reverse('accounts:onboarding'),
                             fetch_redirect_response=False)
        page = self.http.get(reverse('accounts:onboarding'))
        self.assertContains(page, 'Quelle est votre activité ?')
        self.assertContains(page, 'Passer cette étape')
        self.submit()
        self.assertEqual(self.http.get(reverse('dashboard:dashboard-home')).status_code, 200)

    def test_all_steps_configure_billio(self):
        response = self.submit()
        self.assertRedirects(response, f"{reverse('accounts:onboarding')}?done=1", fetch_redirect_response=False)
        self.org.refresh_from_db()
        prof = jurisdictions.profile(self.org)
        self.assertEqual((self.org.name, self.org.trade), ('Studio Lumen', 'web'))
        self.assertEqual((prof['country'], prof['status'], prof['tax_registered'], prof['confirmed']), ('CA', 'pme', True, True))
        self.assertEqual((self.org.default_currency, prof['doc_language']), ('CAD', 'en'))
        self.assertEqual((self.org.default_payment_terms, self.org.billing_preferences['payment_days']), (15, 15))
        self.assertEqual(self.org.invoice_prefix, 'INV')
        self.assertEqual(state(self.org), 'done')
        done = self.http.get(f"{reverse('accounts:onboarding')}?done=1")
        self.assertContains(done, 'Billio est prêt')
        self.assertContains(done, 'Activer le paiement en ligne')
        self.assertContains(done, 'Ajouter votre premier client')

    def test_skipped_steps_keep_current_settings(self):
        before = jurisdictions.profile(self.org)
        self.submit(skip_activity='1', skip_country='1')
        self.org.refresh_from_db()
        self.assertEqual(self.org.trade, 'audiovisuel')
        self.assertNotEqual(self.org.name, 'Studio Lumen')
        self.assertEqual(jurisdictions.profile(self.org)['country'], before['country'])
        self.assertEqual(self.org.default_currency, 'EUR')
        self.assertEqual(self.org.default_payment_terms, 15)  # l'étape préférences, elle, est appliquée

    def test_skip_everything(self):
        response = self.http.post(reverse('accounts:onboarding'), {'form_action': 'skip'})
        self.assertRedirects(response, reverse('dashboard:dashboard-home'), fetch_redirect_response=False)
        self.org.refresh_from_db()
        self.assertEqual(state(self.org), 'skipped')
        self.assertEqual(self.org.trade, 'audiovisuel')
        self.assertEqual(self.http.get(reverse('dashboard:dashboard-home')).status_code, 200)

    def test_no_tax_registration_adds_exemption(self):
        self.submit(country='FR', tax_registered='no')
        self.org.refresh_from_db()
        self.assertTrue(self.org.billing_preferences['vat_exempt'])
        self.assertTrue(Tax.objects.filter(organization=self.org, rate=0).exists())

    def test_can_be_relaunched_from_settings(self):
        self.submit()
        self.assertContains(self.http.get(reverse('accounts:user-settings')), reverse('accounts:onboarding'))
        self.assertContains(self.http.get(reverse('accounts:onboarding')), 'Quelle est votre activité ?')

    def test_existing_accounts_and_members_are_not_redirected(self):
        member = User.objects.create_user(username='m', email='m@studio.test', password='x-Test-1234')
        OrganizationMember.objects.create(organization=self.org, user=member, role='member')
        http = HttpClient(HTTP_HOST='127.0.0.1')
        http.force_login(member)
        self.assertEqual(http.get(reverse('dashboard:dashboard-home')).status_code, 200)
        owner = User.objects.create_user(username='o', email='o@old.test', password='x-Test-1234')
        Organization.objects.create(name='Ancien', owner=owner)
        http.force_login(owner)
        self.assertEqual(http.get(reverse('dashboard:dashboard-home')).status_code, 200)
