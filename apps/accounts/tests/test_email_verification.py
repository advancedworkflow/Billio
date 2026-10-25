"""Vérification de l'adresse email : lien à l'inscription, bandeau, renvoi, blocage des emails aux clients."""
import re
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail, signing
from django.core.cache import cache
from django.test import Client as HttpClient, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts import email_verification
from apps.accounts.models import User
from apps.clients.models import Client
from apps.integrations.models import ConnectionInstance, Connector
from apps.integrations.providers import org_mail
from apps.invoices.models import Invoice, InvoiceItem
from apps.organizations.models import Organization

SITE = 'https://app.billio.test'
PASSWORD = 'Photo-Lumiere-2026'


@override_settings(SITE_URL=SITE, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailVerificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.http = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr')

    def signup(self):
        self.http.post(reverse('accounts:register'), {
            'name': 'Julie Moreau', 'email': 'julie@moreau-photo.fr', 'password': PASSWORD,
            'country': 'FR', 'phone': '06 12 34 56 78', 'trade': 'audiovisuel', 'accept_terms': '1'})
        self.http.post(reverse('accounts:onboarding'), {'form_action': 'skip'})  # assistant de démarrage passé
        return User.objects.get(email='julie@moreau-photo.fr')

    def link_in(self, email):
        return re.search(rf'{re.escape(SITE)}(/accounts/verify-email/[^/\s]+/)', email.body).group(1)

    def make_invoice(self, org):
        client = Client.objects.create(organization=org, name='Atelier Rive', email='compta@rive.fr')
        today = timezone.localdate()
        invoice = Invoice.objects.create(
            organization=org, client=client, issue_date=today, due_date=today + timedelta(days=30),
            subtotal=Decimal('100.00'), tax_amount=Decimal('20.00'), total_amount=Decimal('120.00'), status='draft')
        InvoiceItem.objects.create(invoice=invoice, name='Prestation', quantity=1, unit_price=Decimal('100.00'), tax_rate=Decimal('20'))
        return invoice

    def test_signup_requires_verification_and_welcome_email_carries_the_link(self):
        user = self.signup()
        self.assertTrue(email_verification.needs_verification(user))
        welcome = mail.outbox[0]
        self.assertIn('Confirmer mon adresse email', welcome.alternatives[0][0])
        page = self.http.get(reverse('dashboard:dashboard-home'))
        self.assertContains(page, 'Confirmez votre adresse email.')

        response = self.http.get(self.link_in(welcome), follow=True)
        self.assertContains(response, 'Adresse email confirmée')
        user.refresh_from_db()
        self.assertIsNotNone(user.email_verified_at)
        self.assertNotContains(self.http.get(reverse('dashboard:dashboard-home')), 'Confirmez votre adresse email.')

    def test_link_works_logged_out_and_rejects_tampered_or_stale_tokens(self):
        user = self.signup()
        link = self.link_in(mail.outbox[0])
        self.http.logout()
        bad = self.http.get(link[:-3] + 'xx/', follow=True)
        self.assertContains(bad, 'invalide ou a expiré')
        user.email = 'autre@moreau-photo.fr'  # l'adresse a changé : l'ancien lien ne vaut plus
        user.save()
        self.http.get(link)
        user.refresh_from_db()
        self.assertIsNone(user.email_verified_at)
        user.email = 'julie@moreau-photo.fr'
        user.save()
        with mock.patch('django.core.signing.time.time', return_value=signing.time.time() + 8 * 86400):
            self.http.get(link)
        user.refresh_from_db()
        self.assertIsNone(user.email_verified_at)
        ok = self.http.get(link, follow=True)
        self.assertRedirects(ok, reverse('accounts:login'))
        user.refresh_from_db()
        self.assertIsNotNone(user.email_verified_at)

    def test_resend_is_limited(self):
        self.signup()
        mail.outbox.clear()
        url = reverse('accounts:verify-email-resend')
        for _ in range(3):
            self.http.post(url, {'next': '/dashboard/'})
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(mail.outbox[0].subject, 'Confirmez votre adresse email')
        response = self.http.post(url, {'next': 'https://evil.example/'}, follow=True)
        self.assertEqual(len(mail.outbox), 3)
        self.assertContains(response, 'déjà partis')
        self.assertEqual(response.redirect_chain[-1][0], reverse('dashboard:dashboard-home'))

    def test_unverified_owner_cannot_email_clients_through_billio(self):
        user = self.signup()
        org = Organization.objects.get(owner=user)
        invoice = self.make_invoice(org)
        mail.outbox.clear()
        response = self.http.post(reverse('invoices:send-invoice', args=[invoice.id]), HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Confirmez votre adresse email', response.json()['message'])
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'draft')
        self.assertEqual(mail.outbox, [])
        with self.assertRaises(email_verification.UnverifiedSender):
            org_mail(org)  # automatisations, relances, notifications : même refus

        user.email_verified_at = timezone.now()
        user.save()
        response = self.http.post(reverse('invoices:send-invoice', args=[invoice.id]), HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(mail.outbox[-1].to, ['compta@rive.fr'])

    def test_own_smtp_or_legacy_accounts_are_not_blocked(self):
        user = self.signup()
        org = Organization.objects.get(owner=user)
        connector = Connector.objects.get_or_create(key='email', defaults={'name': 'Email (SMTP)'})[0]
        ConnectionInstance.objects.create(organization=org, connector=connector, status='connected',
                                          config={'host': 'smtp.moreau-photo.fr', 'port': 587, 'username': 'u', 'password': 'p'})
        self.assertEqual(email_verification.client_email_blocked(org), '')
        legacy = User.objects.create_user(username='ancien', email='ancien@test.fr', password=PASSWORD)
        legacy_org = Organization.objects.create(name='Ancien', owner=legacy)
        self.assertEqual(email_verification.client_email_blocked(legacy_org), '')
