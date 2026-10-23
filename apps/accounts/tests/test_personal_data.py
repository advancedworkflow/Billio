"""RGPD : export des données (ZIP), fermeture du compte, effacement après le délai de grâce."""
import io
import json
import shutil
import tempfile
import zipfile
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import Client as HttpClient, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.accounts import closure
from apps.accounts.models import User
from apps.clients.models import Client
from apps.invoices.models import Invoice, InvoiceItem
from apps.organizations.models import Organization, OrganizationMember
from apps.payments.models import PaymentMethod
from apps.subscriptions.billing import BillingError
from apps.subscriptions.models import Subscription
from apps.subscriptions.testing import give_plan

PASSWORD = 'Photo-Lumiere-2026'
MEDIA = tempfile.mkdtemp(prefix='billio-test-media-')


def make_account(email, org_name):
    user = User.objects.create_user(username=email.split('@')[0], email=email, password=PASSWORD)
    org = Organization.objects.create(name=org_name, owner=user, email=email)
    client = Client.objects.create(organization=org, name=f'Client de {org_name}', email=f'client@{org_name.lower()}.test')
    return user, org, client


def make_invoice(org, client, status='draft'):
    today = timezone.localdate()
    invoice = Invoice.objects.create(
        organization=org, client=client, issue_date=today, due_date=today + timedelta(days=30),
        subtotal=Decimal('100.00'), tax_amount=Decimal('20.00'), total_amount=Decimal('120.00'), status='draft')
    InvoiceItem.objects.create(invoice=invoice, name='Prestation', quantity=1, unit_price=Decimal('100.00'), tax_rate=Decimal('20'))
    if status != 'draft':
        invoice.status = status
        invoice.save()
    return invoice


@override_settings(MEDIA_ROOT=MEDIA, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   SUPPORT_EMAIL='support@billio.test')
class PersonalDataTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.http = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr')
        self.user, self.org, self.client = make_account('julie@moreau-photo.fr', 'Lumen')
        self.other, self.other_org, self.other_client = make_account('marc@atelier.fr', 'Atelier')
        self.settings_url = reverse('accounts:user-settings')

    def export(self):
        self.http.force_login(self.user)
        response = self.http.post(self.settings_url, {'form_action': 'export_data'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment; filename="billio-export-', response['Content-Disposition'])
        return zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content)))

    # ---------- Export ----------

    def test_export_contains_account_and_organization_data_without_secrets(self):
        invoice = make_invoice(self.org, self.client, status='sent')
        invoice.create_credit_note(user=self.user, amount=Decimal('20.00'), reason='Remise')
        PaymentMethod.objects.create(organization=self.org, name='Stripe', method_type='stripe', api_key='sk_live_secret')
        self.user.avatar.save('julie.png', ContentFile(b'png-bytes'))
        make_invoice(self.other_org, self.other_client)

        zf = self.export()
        names = zf.namelist()
        self.assertIn('LISEZMOI.txt', names)
        self.assertIn('csv/invoices.invoice.csv', names)
        self.assertIn(f'fichiers/{self.user.avatar.name}', names)
        self.assertEqual(zf.read(f'fichiers/{self.user.avatar.name}'), b'png-bytes')

        invoices = json.loads(zf.read('donnees/invoices.invoice.json'))
        self.assertEqual({i['organization'] for i in invoices}, {self.org.pk})  # rien de l'autre compte
        self.assertEqual(len(invoices), 2)  # facture + avoir
        self.assertEqual(len(json.loads(zf.read('donnees/invoices.invoiceitem.json'))), 2)
        clients = json.loads(zf.read('donnees/clients.client.json'))
        self.assertEqual([c['name'] for c in clients], ['Client de Lumen'])
        self.assertNotIn('portal_token', clients[0])

        account = json.loads(zf.read('donnees/accounts.user.json'))[0]
        self.assertEqual(account['email'], 'julie@moreau-photo.fr')
        self.assertNotIn('password', account)
        self.assertNotIn('totp_secret', account)
        everything = b''.join(zf.read(n) for n in names if not n.startswith('fichiers/'))
        self.assertNotIn(b'sk_live_secret', everything)
        self.assertNotIn(b'pbkdf2', everything)
        self.assertNotIn(b'Atelier', everything)

    def test_simple_member_does_not_export_the_organization(self):
        OrganizationMember.objects.create(organization=self.other_org, user=self.user, role='member')
        zf = self.export()
        clients = json.loads(zf.read('donnees/clients.client.json'))
        self.assertEqual([c['name'] for c in clients], ['Client de Lumen'])
        memberships = json.loads(zf.read('donnees/organizations.organizationmember.json'))
        self.assertEqual(len(memberships), 1)  # sa propre adhésion, sans les données de l'organisation

    def test_export_is_rate_limited(self):
        for _ in range(5):
            self.export()
        response = self.http.post(self.settings_url, {'form_action': 'export_data'}, follow=True)
        self.assertContains(response, 'plusieurs exports')

    # ---------- Fermeture ----------

    def close(self, **data):
        self.http.force_login(self.user)
        return self.http.post(self.settings_url, {'form_action': 'close_account', 'password': PASSWORD,
                                                  'confirm': 'fermer', **data}, follow=True)

    def test_wrong_password_or_missing_confirmation_keeps_the_account(self):
        self.assertContains(self.close(password='nope'), 'Mot de passe incorrect')
        self.assertContains(self.close(confirm='oui'), 'Écrivez FERMER')
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertIsNone(self.user.closed_at)

    def test_close_deactivates_pauses_organizations_and_logs_out(self):
        Token.objects.create(user=self.user)
        response = self.close()
        self.assertContains(response, 'Votre compte est fermé')
        self.user.refresh_from_db()
        self.org.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertIsNotNone(self.user.closed_at)
        self.assertFalse(self.org.is_active)  # plus de relances automatiques aux clients
        self.assertFalse(Token.objects.filter(user=self.user).exists())
        self.assertNotIn('_auth_user_id', self.http.session)
        self.assertFalse(self.http.login(email='julie@moreau-photo.fr', password=PASSWORD))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, 'Votre compte Billio est fermé')
        self.assertIn(closure.deletion_date(self.user).strftime('%d/%m/%Y'), mail.outbox[0].body)
        self.assertIn('support@billio.test', mail.outbox[0].body)

    def test_close_cancels_the_stripe_subscription_first(self):
        give_plan(self.user, 'pro')
        Subscription.objects.filter(user=self.user).update(stripe_subscription_id='sub_123', status='active', comped=False)
        with mock.patch('apps.subscriptions.billing.cancel_now', side_effect=BillingError('Stripe injoignable')) as cancel:
            response = self.close()
        cancel.assert_called_once()
        self.assertContains(response, "n&#x27;a pas pu être résilié")
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        with mock.patch('apps.subscriptions.billing.cancel_now') as cancel:
            self.close()
        cancel.assert_called_once()
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_settings_warn_about_organizations_shared_with_others(self):
        member = User.objects.create_user(username='paul', email='paul@lumen.fr', password=PASSWORD)
        OrganizationMember.objects.create(organization=self.org, user=member, role='member')
        self.http.force_login(self.user)
        page = self.http.get(self.settings_url + '?tab=donnees')
        self.assertContains(page, 'personnes travaillent dans vos organisations')
        self.assertContains(page, 'Lumen (1 membre)')

    def test_reopen_during_grace_period(self):
        closure.close_account(self.user)
        closure.reopen_account(self.user)
        self.user.refresh_from_db()
        self.org.refresh_from_db()
        self.assertTrue(self.user.is_active and self.org.is_active)
        self.assertIsNone(self.user.closed_at)

    # ---------- Effacement ----------

    def test_purge_after_grace_period_erases_everything_of_the_account_only(self):
        invoice = make_invoice(self.org, self.client, status='sent')
        invoice.create_credit_note(user=self.user, amount=Decimal('120.00'), reason='Annulation')
        self.user.avatar.save('julie.png', ContentFile(b'png-bytes'))
        avatar_path = self.user.avatar.path
        other_invoice = make_invoice(self.other_org, self.other_client, status='sent')
        closure.close_account(self.user)

        self.assertEqual(closure.purge_closed_accounts(), 0)  # encore dans le délai de grâce
        later = timezone.now() + timedelta(days=closure.grace_days() + 1)
        self.assertEqual(closure.purge_closed_accounts(now=later), 1)

        self.assertFalse(User.objects.filter(email='julie@moreau-photo.fr').exists())
        self.assertFalse(Organization.objects.filter(pk=self.org.pk).exists())
        self.assertFalse(Invoice.objects.filter(organization_id=self.org.pk).exists())
        self.assertFalse(Client.objects.filter(pk=self.client.pk).exists())
        self.assertFalse(self.user.avatar.storage.exists(avatar_path))
        self.assertTrue(Invoice.objects.filter(pk=other_invoice.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.other.pk).exists())

    def test_active_accounts_are_never_purged(self):
        later = timezone.now() + timedelta(days=365)
        self.assertEqual(closure.purge_closed_accounts(now=later), 0)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
