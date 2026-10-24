"""Paiement en ligne : moyen réellement utilisé, QR code de virement EPC, moyens conseillés par pays."""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.clients.models import Client
from apps.integrations.models import ConnectionInstance, Connector
from apps.invoices.models import Invoice, InvoiceItem
from apps.organizations.jurisdictions import apply_profile
from apps.organizations.models import Organization
from apps.payments import local_methods
from apps.payments.models import Payment
from apps.payments.stripe_checkout import record_checkout


class OnlinePaymentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='julie', email='julie@lumen.test', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio Lumen', owner=self.user,
                                               iban='FR76 3000 6000 0112 3456 7890 189', bic_swift='AGRIFRPP')
        self.client_obj = Client.objects.create(organization=self.org, name='Atelier Rive', email='r@rive.fr')
        self.invoice = Invoice.objects.create(organization=self.org, client=self.client_obj, issue_date=date(2026, 3, 1),
                                              due_date=date(2026, 3, 31), subtotal=Decimal('100'), tax_amount=Decimal('20'),
                                              total_amount=Decimal('120'), currency='EUR')
        InvoiceItem.objects.create(invoice=self.invoice, name='Design', quantity=1, unit_price=Decimal('100'), tax_rate=Decimal('20'))
        self.invoice.status = 'sent'
        self.invoice.save()

    def test_epc_payload_follows_the_standard(self):
        lines = local_methods.epc_payload(self.org, self.invoice, Decimal('120')).split('\n')
        self.assertEqual(lines[:8], ['BCD', '002', '1', 'SCT', 'AGRIFRPP', 'Studio Lumen',
                                     'FR7630006000011234567890189', 'EUR120.00'])
        self.assertEqual(lines[-1], f'Facture {self.invoice.invoice_number}')
        self.invoice.currency = 'USD'
        self.assertEqual(local_methods.epc_payload(self.org, self.invoice, Decimal('120')), '')

    def test_public_page_shows_transfer_qr_for_euro_invoices(self):
        page = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr').get(
            reverse('invoices:public-invoice-payment', args=[self.invoice.id]))
        self.assertContains(page, 'QR code de virement')
        self.assertContains(page, '<svg')

    def test_recorded_payment_says_which_method_was_used(self):
        connector = Connector.objects.get_or_create(key='stripe', defaults={'name': 'Stripe', 'category': 'payment'})[0]
        ConnectionInstance.objects.create(organization=self.org, connector=connector, status='connected',
                                          config={'secret_key': 'sk_test_x', 'webhook_secret': 'whsec_x'})
        session = {'id': 'cs_test_1', 'payment_status': 'paid', 'amount_total': 12000, 'payment_intent': 'pi_1',
                   'metadata': {'organization_id': str(self.org.id), 'invoice_id': str(self.invoice.id)}}
        intent = {'id': 'pi_1', 'payment_method': {'type': 'sepa_debit'}}
        with mock.patch('apps.payments.stripe_checkout.http', return_value=intent):
            record_checkout(self.org, session)
        payment = Payment.objects.get(invoice=self.invoice)
        self.assertIn('Prélèvement SEPA', payment.notes)
        self.assertEqual(payment.provider_data, {'method': 'sepa_debit'})
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'paid')

    def test_apple_pay_is_reported_from_the_card_wallet(self):
        connector = Connector.objects.get_or_create(key='stripe', defaults={'name': 'Stripe', 'category': 'payment'})[0]
        ConnectionInstance.objects.create(organization=self.org, connector=connector, status='connected',
                                          config={'secret_key': 'sk_test_x'})
        from apps.payments.stripe_checkout import used_method
        intent = {'payment_method': {'type': 'card', 'card': {'wallet': {'type': 'apple_pay'}}}}
        with mock.patch('apps.payments.stripe_checkout.http', return_value=intent):
            self.assertEqual(used_method(self.org, {'payment_intent': 'pi_2'}), 'apple_pay')

    def test_settings_recommend_local_methods_for_the_country(self):
        apply_profile(self.org, {'country': 'BE', 'status': 'freelance', 'tax_registered': True})
        http = HttpClient(HTTP_HOST='127.0.0.1')
        http.force_login(self.user)
        page = http.get(reverse('accounts:user-settings') + '?tab=paiement')
        self.assertContains(page, 'Moyens conseillés pour vos clients')
        self.assertContains(page, 'Bancontact')
        self.assertContains(page, local_methods.STRIPE_SETTINGS_URL)
        self.assertEqual([name for name, _ in local_methods.recommended('AU')][-1], 'Prélèvement BECS')
