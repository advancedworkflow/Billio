"""Lien de paiement (aperçu, modèles PDF) et versements Stripe Connect (historique, détail, rapprochement)."""
import os
from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.test import Client as HttpClient, TestCase, override_settings
from django.urls import reverse

from apps.dashboard.models import Notification
from apps.payments import payouts, reconciliation, stripe_connect
from apps.payments.models import BankLine, Payment, StripeConnectAccount, StripePayout
from apps.payments.payment_links import document_context

from .test_stripe_connect import PLATFORM, WEBHOOK, make_invoice, make_org, signed_post


def ts(day):
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=dt_timezone.utc).timestamp())


def payout_obj(**overrides):
    data = {'id': 'po_1', 'object': 'payout', 'amount': 11640, 'currency': 'eur', 'status': 'paid', 'method': 'standard',
            'arrival_date': ts(date(2026, 10, 20)), 'created': ts(date(2026, 10, 18)),
            'destination': {'object': 'bank_account', 'bank_name': 'BNP PARIBAS', 'last4': '1234'}}
    data.update(overrides)
    return data


@override_settings(STRIPE_SECRET_KEY=PLATFORM)
class PaymentLinkTests(TestCase):
    def setUp(self):
        self.user, self.org = make_org()
        self.invoice = make_invoice(self.org)
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def test_preview_shows_payment_link_and_activation_hint(self):
        html = self.http.get(reverse('invoices:invoice-preview', args=[self.invoice.id])).content.decode()
        self.assertIn(reverse('invoices:public-invoice-payment', args=[self.invoice.id]), html)
        self.assertIn('Activer le paiement en ligne', html)
        StripeConnectAccount.objects.create(organization=self.org, account_id='acct_123', charges_enabled=True)
        html = self.http.get(reverse('invoices:invoice-preview', args=[self.invoice.id])).content.decode()
        self.assertNotIn('Activer le paiement en ligne', html)
        self.assertIn('<svg', html)

    def test_no_link_on_paid_invoice(self):
        self.invoice.mark_as_paid()
        html = self.http.get(reverse('invoices:invoice-preview', args=[self.invoice.id])).content.decode()
        self.assertNotIn('Copier le lien', html)

    def test_templates_get_payment_url_only_with_online_payment(self):
        self.assertEqual(document_context(self.invoice)['payment_url'], '')
        StripeConnectAccount.objects.create(organization=self.org, account_id='acct_123', charges_enabled=True)
        context = document_context(self.invoice)
        self.assertTrue(context['payment_url'].endswith(reverse('invoices:public-invoice-payment', args=[self.invoice.id])))
        self.assertIn('<svg', context['payment_qr'])


@override_settings(STRIPE_SECRET_KEY=PLATFORM)
class PayoutTests(TestCase):
    def setUp(self):
        self.user, self.org = make_org()
        self.account = StripeConnectAccount.objects.create(organization=self.org, account_id='acct_123', charges_enabled=True,
                                                           payouts_enabled=True)
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def test_payout_is_recorded_with_destination(self):
        payout = payouts.record_payout(self.org, payout_obj())
        self.assertEqual((payout.amount, payout.status, payout.arrival_date), (Decimal('116.40'), 'paid', date(2026, 10, 20)))
        self.assertEqual(payout.destination, 'BNP PARIBAS •••• 1234')
        payouts.record_payout(self.org, payout_obj(status='paid'))
        self.assertEqual(StripePayout.objects.count(), 1)

    def test_failed_payout_notifies_once(self):
        payouts.record_payout(self.org, payout_obj(status='in_transit'))
        payouts.record_payout(self.org, payout_obj(status='failed', failure_message='Compte clôturé'))
        payouts.record_payout(self.org, payout_obj(status='failed', failure_message='Compte clôturé'))
        notes = Notification.objects.filter(user=self.user, title='Versement Stripe échoué')
        self.assertEqual(notes.count(), 1)
        self.assertIn('Compte clôturé', notes.first().message)

    def test_bank_line_of_payout_is_reconciled_without_new_payment(self):
        line = BankLine.objects.create(organization=self.org, date=date(2026, 10, 21), amount=Decimal('116.40'),
                                       label='VIR STRIPE', fingerprint='x')
        other = BankLine.objects.create(organization=self.org, date=date(2026, 9, 1), amount=Decimal('116.40'),
                                        label='VIR CLIENT', fingerprint='y')
        payout = payouts.record_payout(self.org, payout_obj())
        line.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual((line.status, line.payout), ('matched', payout))
        self.assertEqual(other.status, 'pending')  # trop loin de la date d'arrivée
        self.assertFalse(Payment.objects.exists())

    def test_undo_is_not_redone_automatically(self):
        line = BankLine.objects.create(organization=self.org, date=date(2026, 10, 20), amount=Decimal('116.40'),
                                       label='VIR STRIPE', fingerprint='x')
        payouts.record_payout(self.org, payout_obj())
        line.refresh_from_db()
        reconciliation.undo(line)
        self.http.get(reverse('payments:reconcile'))
        line.refresh_from_db()
        self.assertEqual((line.status, line.payout), ('pending', None))

    def test_refresh_reads_payouts_on_connected_account(self):
        with mock.patch('apps.payments.payouts.http', return_value={'data': [payout_obj(), payout_obj(id='po_2', status='in_transit')]}) as http, \
                mock.patch('apps.payments.stripe_connect.http', return_value={'id': 'acct_123', 'charges_enabled': True, 'payouts_enabled': True,
                    'settings': {'payouts': {'schedule': {'interval': 'weekly', 'weekly_anchor': 'monday'}}},
                    'external_accounts': {'data': [{'object': 'bank_account', 'bank_name': 'QONTO', 'last4': '9876', 'default_for_currency': True}]}}):
            self.http.post(reverse('payments:payouts-refresh'))
        self.assertEqual(http.call_args.kwargs['headers']['Stripe-Account'], 'acct_123')
        self.account.refresh_from_db()
        self.assertEqual((self.account.payout_schedule, self.account.payout_destination), ('Chaque lundi', 'QONTO •••• 9876'))
        html = self.http.get(reverse('payments:payouts')).content.decode()
        self.assertIn('QONTO •••• 9876', html)
        self.assertIn(reverse('payments:payout-detail', args=[StripePayout.objects.get(payout_id='po_2').id]), html)

    def test_detail_links_charges_to_invoices(self):
        invoice = make_invoice(self.org)
        Payment.objects.create(invoice=invoice, amount=Decimal('120'), currency='EUR', status='completed', provider='stripe',
                               provider_payment_id='cs_1', transaction_id='pi_1')
        payout = payouts.record_payout(self.org, payout_obj())
        balance = {'data': [
            {'type': 'charge', 'amount': 12000, 'fee': 360, 'net': 11640, 'created': ts(date(2026, 10, 15)),
             'source': {'object': 'charge', 'payment_intent': 'pi_1'}},
            {'type': 'payout', 'amount': -11640, 'fee': 0, 'net': -11640},
        ]}
        with mock.patch('apps.payments.payouts.http', return_value=balance):
            html = self.http.get(reverse('payments:payout-detail', args=[payout.id])).content.decode()
        self.assertIn(invoice.invoice_number, html)
        self.assertIn('116,40', html)

    def test_other_organization_cannot_see_payout(self):
        payout = payouts.record_payout(self.org, payout_obj())
        from apps.accounts.models import User
        stranger = User.objects.create_user(username='s', email='s@x.test', password='x-Test-1234')
        from apps.organizations.models import Organization
        Organization.objects.create(name='Autre', owner=stranger)
        self.http.force_login(stranger)
        self.assertEqual(self.http.get(reverse('payments:payout-detail', args=[payout.id])).status_code, 404)

    def test_schedule_labels(self):
        self.assertEqual(stripe_connect.schedule_label({'interval': 'daily'}), 'Chaque jour')
        self.assertEqual(stripe_connect.schedule_label({'interval': 'monthly', 'monthly_anchor': 5}), 'Chaque mois, le 5')
        self.assertEqual(stripe_connect.destination_label({'object': 'card', 'brand': 'visa', 'last4': '4242'}), 'Carte Visa •••• 4242')


@override_settings(STRIPE_SECRET_KEY=PLATFORM)
@mock.patch.dict(os.environ, WEBHOOK)
class PayoutWebhookTests(TestCase):
    def test_payout_events_are_recorded(self):
        _, org = make_org()
        StripeConnectAccount.objects.create(organization=org, account_id='acct_123', charges_enabled=True)
        response = signed_post(HttpClient(HTTP_HOST='127.0.0.1'),
                               {'type': 'payout.paid', 'account': 'acct_123', 'data': {'object': payout_obj()}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StripePayout.objects.get(payout_id='po_1').organization, org)
