"""
Facturation : numérotation légale, verrouillage des factures émises, avoirs,
paiement en ligne Stripe (confirmation serveur, webhook signé, idempotence).

    python manage.py test apps.invoices
"""
import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import Client as HttpClient, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.integrations.models import ConnectionInstance, Connector
from apps.invoices.models import Invoice, InvoiceItem
from apps.organizations.models import Organization
from apps.payments.models import Payment
from apps.payments.stripe_checkout import record_checkout, verify_webhook
from apps.subscriptions.testing import give_plan


def make_org(name, email):
    user = User.objects.create_user(username=email.split('@')[0], email=email, password='x-Test-1234')
    org = Organization.objects.create(name=name, owner=user, email=email)
    client = Client.objects.create(organization=org, name=f'Client de {name}', email=f'client@{name.lower()}.test')
    return user, org, client


def make_invoice(org, client, *, total='120.00', status='draft'):
    today = timezone.localdate()
    invoice = Invoice.objects.create(
        organization=org, client=client, issue_date=today, due_date=today + timedelta(days=30),
        subtotal=Decimal('100.00'), tax_amount=Decimal('20.00'), total_amount=Decimal(total), status='draft',
    )
    InvoiceItem.objects.create(invoice=invoice, name='Prestation', quantity=1, unit_price=Decimal('100.00'), tax_rate=Decimal('20'))
    if status != 'draft':
        invoice.status = status
        invoice.save()
    return invoice


class NumberingTests(TestCase):
    def setUp(self):
        self.user_a, self.org_a, self.client_a = make_org('Alpha', 'alpha@test.fr')
        self.user_b, self.org_b, self.client_b = make_org('Beta', 'beta@test.fr')

    def test_draft_has_provisional_number_and_final_on_issue(self):
        invoice = make_invoice(self.org_a, self.client_a)
        self.assertTrue(invoice.invoice_number.startswith('BROUILLON-'))
        invoice.status = 'sent'
        invoice.save(update_fields=['status'])  # comme les vues d'envoi
        invoice.refresh_from_db()
        self.assertEqual(invoice.invoice_number, 'INV-0001')

    def test_each_organization_has_its_own_continuous_sequence(self):
        a1 = make_invoice(self.org_a, self.client_a, status='sent')
        b1 = make_invoice(self.org_b, self.client_b, status='sent')
        a2 = make_invoice(self.org_a, self.client_a, status='sent')
        self.assertEqual((a1.invoice_number, a2.invoice_number), ('INV-0001', 'INV-0002'))
        self.assertEqual(b1.invoice_number, 'INV-0001')  # même préfixe, autre organisation : pas de saut

    def test_deleted_draft_leaves_no_gap(self):
        make_invoice(self.org_a, self.client_a).delete()
        first = make_invoice(self.org_a, self.client_a, status='sent')
        self.assertEqual(first.invoice_number, 'INV-0001')


class LockTests(TestCase):
    def setUp(self):
        self.user, self.org, self.client_obj = make_org('Gamma', 'gamma@test.fr')
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def test_issued_invoice_cannot_be_edited_or_deleted(self):
        invoice = make_invoice(self.org, self.client_obj, status='sent')
        self.assertTrue(invoice.is_locked)
        response = self.http.post(reverse('invoices:invoice-update', args=[invoice.id]), {'client_id': self.client_obj.id, 'items': '[]'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(invoice.items.count(), 1)
        api = self.http.delete(f'/invoices/api/invoices/{invoice.id}/')
        self.assertEqual(api.status_code, 400)
        self.assertTrue(Invoice.objects.filter(id=invoice.id).exists())
        edit = self.http.get(reverse('invoices:invoice-edit', args=[invoice.id]))
        self.assertRedirects(edit, reverse('invoices:invoice-preview', args=[invoice.id]), fetch_redirect_response=False)

    def test_draft_stays_editable(self):
        invoice = make_invoice(self.org, self.client_obj)
        self.assertFalse(invoice.is_locked)
        self.assertEqual(self.http.delete(f'/invoices/api/invoices/{invoice.id}/').status_code, 204)


class CreditNoteTests(TestCase):
    def setUp(self):
        self.user, self.org, self.client_obj = make_org('Delta', 'delta@test.fr')

    def test_full_credit_note_cancels_unpaid_invoice(self):
        invoice = make_invoice(self.org, self.client_obj, status='sent')
        credit = invoice.create_credit_note(user=self.user, reason='Erreur de client')
        self.assertTrue(credit.invoice_number.startswith('BROUILLON-'))
        self.assertEqual(credit.total_amount, invoice.total_amount)
        self.assertEqual(credit.items.count(), 1)
        credit.status = 'sent'
        credit.save()
        credit.refresh_from_db(); invoice.refresh_from_db()
        self.assertEqual(credit.invoice_number, 'AV-0001')  # séquence propre aux avoirs
        self.assertEqual(invoice.status, 'cancelled')
        self.assertEqual(invoice.amount_due(), Decimal('0'))
        self.assertIn(invoice.invoice_number, credit.notes)

    def test_partial_credit_note_reduces_amount_due(self):
        invoice = make_invoice(self.org, self.client_obj, status='sent')
        credit = invoice.create_credit_note(amount=Decimal('30.00'), reason='Remise')
        self.assertEqual(invoice.amount_due(), Decimal('120.00'))  # brouillon : pas encore d'effet
        credit.status = 'sent'
        credit.save()
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_due(), Decimal('90.00'))
        self.assertEqual(invoice.status, 'sent')
        self.assertEqual(credit.subtotal + credit.tax_amount, Decimal('30.00'))

    def test_credit_note_completes_partially_paid_invoice(self):
        invoice = make_invoice(self.org, self.client_obj, status='sent')
        Payment.objects.create(invoice=invoice, amount=Decimal('100.00'), currency='EUR', status='completed', provider='manual')
        credit = invoice.create_credit_note(amount=Decimal('20.00'))
        credit.status = 'sent'
        credit.save()
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'paid')

    def test_no_credit_note_on_draft(self):
        with self.assertRaises(ValueError):
            make_invoice(self.org, self.client_obj).create_credit_note()


class StripeTests(TestCase):
    def setUp(self):
        self.user, self.org, self.client_obj = make_org('Epsilon', 'epsilon@test.fr')
        connector, _ = Connector.objects.get_or_create(key='stripe', defaults={'name': 'Stripe', 'category': 'payment'})
        ConnectionInstance.objects.create(organization=self.org, connector=connector, status='connected',
                                          config={'secret_key': 'sk_test_x', 'webhook_secret': 'whsec_test'})
        self.invoice = make_invoice(self.org, self.client_obj, status='sent')
        self.http = HttpClient(HTTP_HOST='127.0.0.1')

    def session(self, **overrides):
        data = {'id': 'cs_test_123', 'payment_status': 'paid', 'amount_total': 12000, 'payment_intent': 'pi_123',
                'metadata': {'organization_id': str(self.org.id), 'invoice_id': str(self.invoice.id)}}
        data.update(overrides)
        return data

    def test_clicking_pay_never_marks_invoice_paid(self):
        with mock.patch('apps.payments.stripe_checkout.http', return_value={'url': 'https://checkout.stripe.com/c/pay/cs_test_123'}) as fake:
            response = self.http.post(reverse('invoices:public-invoice-pay', args=[self.invoice.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith('https://checkout.stripe.com/'))
        form = fake.call_args.kwargs['form']
        self.assertEqual(form['line_items[0][price_data][unit_amount]'], 12000)
        self.invoice.refresh_from_db()
        self.assertNotEqual(self.invoice.status, 'paid')

    def test_without_stripe_no_card_payment(self):
        ConnectionInstance.objects.filter(organization=self.org).delete()
        response = self.http.post(reverse('invoices:public-invoice-pay', args=[self.invoice.id]))
        self.assertRedirects(response, reverse('invoices:public-invoice-payment', args=[self.invoice.id]), fetch_redirect_response=False)
        self.invoice.refresh_from_db()
        self.assertNotEqual(self.invoice.status, 'paid')

    def test_confirmed_session_pays_invoice_once(self):
        record_checkout(self.org, self.session())
        record_checkout(self.org, self.session())  # retour + webhook : une seule écriture
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'paid')
        self.assertEqual(Payment.objects.filter(invoice=self.invoice, provider='stripe').count(), 1)

    def test_unpaid_or_foreign_session_is_ignored(self):
        self.assertIsNone(record_checkout(self.org, self.session(payment_status='unpaid')))
        self.assertIsNone(record_checkout(self.org, self.session(metadata={'organization_id': '999999', 'invoice_id': str(self.invoice.id)})))
        self.invoice.refresh_from_db()
        self.assertNotEqual(self.invoice.status, 'paid')

    def test_return_url_verifies_session_server_side(self):
        with mock.patch('apps.payments.stripe_checkout.http', return_value=self.session()):
            response = self.http.get(reverse('invoices:public-invoice-pay-return', args=[self.invoice.id]) + '?session_id=cs_test_123')
        self.assertRedirects(response, reverse('invoices:public-invoice-receipt', args=[self.invoice.id]), fetch_redirect_response=False)
        with mock.patch('apps.payments.stripe_checkout.http', return_value=self.session(payment_status='unpaid')):
            other = make_invoice(self.org, self.client_obj, status='sent')
            self.http.get(reverse('invoices:public-invoice-pay-return', args=[other.id]) + '?session_id=cs_test_999')
        other.refresh_from_db()
        self.assertNotEqual(other.status, 'paid')

    def _signed(self, event, secret='whsec_test', ts=None):
        payload = json.dumps(event).encode()
        ts = str(ts or int(time.time()))
        sig = hmac.new(secret.encode(), f'{ts}.'.encode() + payload, hashlib.sha256).hexdigest()
        return payload, f't={ts},v1={sig}'

    def test_webhook_requires_valid_signature(self):
        event = {'type': 'checkout.session.completed', 'data': {'object': self.session()}}
        url = reverse('payments:stripe-webhook', args=[self.org.id])
        payload, _ = self._signed(event)
        _, bad = self._signed(event, secret='whsec_other')
        self.assertEqual(self.http.post(url, payload, content_type='application/json', HTTP_STRIPE_SIGNATURE=bad).status_code, 400)
        self.invoice.refresh_from_db()
        self.assertNotEqual(self.invoice.status, 'paid')
        payload, good = self._signed(event)
        self.assertEqual(self.http.post(url, payload, content_type='application/json', HTTP_STRIPE_SIGNATURE=good).status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'paid')

    def test_old_signature_rejected(self):
        payload, header = self._signed({'type': 'x'}, ts=int(time.time()) - 3600)
        with self.assertRaises(ValueError):
            verify_webhook(payload, header, 'whsec_test')


class ScheduleTests(TestCase):
    """Relances J+7/14/30 et factures récurrentes (apps.invoices.scheduled)."""

    def setUp(self):
        from django.core import mail
        self.mail = mail
        self.user, self.org, self.client_obj = make_org('Zeta', 'zeta@test.fr')
        give_plan(self.user, 'starter')  # relances automatiques : à partir de Starter

    def test_sending_invoice_emails_client_with_payment_link(self):
        invoice = make_invoice(self.org, self.client_obj)
        ok, _ = invoice.send_to_client()
        self.assertTrue(ok)
        self.assertEqual(len(self.mail.outbox), 1)
        self.assertIn(invoice.invoice_number, self.mail.outbox[0].subject)
        self.assertIn(str(invoice.id), self.mail.outbox[0].body)
        self.assertEqual(self.mail.outbox[0].to, [self.client_obj.email])

    def test_reminders_once_per_stage_without_burst(self):
        from apps.invoices.scheduled import send_overdue_reminders
        self.org.automation_reminder_j7 = self.org.automation_reminder_j14 = self.org.automation_reminder_j30 = True
        self.org.save()
        invoice = make_invoice(self.org, self.client_obj, status='sent')
        due = invoice.due_date
        self.assertEqual(send_overdue_reminders(self.org, due + timedelta(days=3)), 0)  # pas encore J+7
        self.assertEqual(send_overdue_reminders(self.org, due + timedelta(days=8)), 1)
        self.assertEqual(send_overdue_reminders(self.org, due + timedelta(days=9)), 0)  # déjà relancée
        self.assertEqual(send_overdue_reminders(self.org, due + timedelta(days=40)), 1)  # saute J+14 : seule la J+30 part
        self.assertEqual(send_overdue_reminders(self.org, due + timedelta(days=41)), 0)
        invoice.refresh_from_db()
        self.assertEqual(invoice.reminders_sent, ['j14', 'j30', 'j7'])
        self.assertIn('Dernière relance', self.mail.outbox[-1].subject)

    def test_reminders_respect_settings_and_paid_invoices(self):
        from apps.invoices.scheduled import send_overdue_reminders
        invoice = make_invoice(self.org, self.client_obj, status='sent')
        self.assertEqual(send_overdue_reminders(self.org, invoice.due_date + timedelta(days=10)), 0)  # désactivées
        self.org.automation_reminder_j7 = True
        self.org.save()
        invoice.mark_as_paid()
        self.assertEqual(send_overdue_reminders(self.org, invoice.due_date + timedelta(days=10)), 0)

    def test_recurring_invoice_is_issued_once_per_period(self):
        from apps.invoices.scheduled import generate_recurring_invoices
        self.org.automation_recurring_invoices = True
        self.org.save()
        source = make_invoice(self.org, self.client_obj, status='sent')
        source.recurrence = 'monthly'
        source.recurrence_next_date = source.issue_date + timedelta(days=31)
        source.save()
        day = source.recurrence_next_date
        self.assertEqual(generate_recurring_invoices(self.org, day - timedelta(days=1)), [])
        created = generate_recurring_invoices(self.org, day)
        self.assertEqual(len(created), 1)
        copy = created[0]
        copy.refresh_from_db(); source.refresh_from_db()
        self.assertEqual(copy.status, 'sent')
        self.assertEqual(copy.invoice_number, 'INV-0002')
        self.assertEqual(copy.items.count(), 1)
        self.assertEqual(copy.total_amount, source.total_amount)
        self.assertEqual(copy.issue_date, day)
        self.assertEqual(generate_recurring_invoices(self.org, day), [])  # pas de doublon le même jour
        self.assertGreater(source.recurrence_next_date, day)

    def test_recurrence_stops_after_end_date(self):
        from apps.invoices.scheduled import generate_recurring_invoices
        self.org.automation_recurring_invoices = True
        self.org.save()
        source = make_invoice(self.org, self.client_obj, status='sent')
        source.recurrence, source.recurrence_next_date = 'monthly', source.issue_date + timedelta(days=30)
        source.recurrence_end_date = source.issue_date + timedelta(days=10)
        source.save()
        self.assertEqual(generate_recurring_invoices(self.org, source.recurrence_next_date), [])
        source.refresh_from_db()
        self.assertEqual(source.recurrence, 'none')


class SituationTests(TestCase):
    """Factures de situation (BTP) et retenue de garantie."""

    def setUp(self):
        from apps.invoices.models import Quote, QuoteItem
        self.user, self.org, self.client_obj = make_org('Eta', 'eta@test.fr')
        today = timezone.localdate()
        self.quote = Quote.objects.create(organization=self.org, client=self.client_obj, issue_date=today,
                                          expiry_date=today + timedelta(days=30), total_amount=Decimal('12000'), status='accepted')
        QuoteItem.objects.create(quote=self.quote, name='Gros œuvre', quantity=1, unit_price=Decimal('8000'), tax_rate=Decimal('20'))
        QuoteItem.objects.create(quote=self.quote, name='Peinture', quantity=1, unit_price=Decimal('2000'), tax_rate=Decimal('10'))

    def issue(self, invoice):
        invoice.status = 'sent'
        invoice.save()
        invoice.refresh_from_db()
        return invoice

    def test_successive_situations_bill_the_difference(self):
        s1 = self.issue(self.quote.create_situation_invoice(40))
        self.assertEqual((s1.situation_number, s1.subtotal), (1, Decimal('4000.00')))
        self.assertEqual(s1.tax_amount, Decimal('720.00'))  # 3200×20 % + 800×10 %
        self.assertEqual(s1.retention_amount, Decimal('236.00'))  # 5 % de 4720 TTC
        self.assertEqual(s1.amount_due(), Decimal('4484.00'))
        s2 = self.issue(self.quote.create_situation_invoice(100, retention_rate=0))
        self.assertEqual((s2.situation_number, s2.subtotal, s2.retention_amount), (2, Decimal('6000.00'), Decimal('0')))
        with self.assertRaises(ValueError):
            self.quote.create_situation_invoice(100)  # déjà à 100 %

    def test_progress_must_increase_and_previous_must_be_issued(self):
        self.quote.create_situation_invoice(30)
        with self.assertRaises(ValueError):
            self.quote.create_situation_invoice(50)  # situation 1 encore en brouillon
        self.issue(self.quote.situations.get())
        with self.assertRaises(ValueError):
            self.quote.create_situation_invoice(20)  # recul d'avancement

    def test_retention_release_makes_amount_due(self):
        http = HttpClient(HTTP_HOST='127.0.0.1')
        http.force_login(self.user)
        s1 = self.issue(self.quote.create_situation_invoice(100))
        Payment.objects.create(invoice=s1, amount=s1.amount_due(), currency='EUR', status='completed', provider='manual')
        s1.mark_as_paid()
        s1.refresh_from_db()
        self.assertEqual(s1.amount_due(), Decimal('0'))
        http.post(reverse('invoices:invoice-retention-release', args=[s1.id]))
        s1.refresh_from_db()
        self.assertIsNotNone(s1.retention_released_at)
        self.assertEqual(s1.amount_due(), s1.retention_amount)
        self.assertEqual(s1.status, 'sent')

    def test_situation_requires_accepted_quote(self):
        self.quote.status = 'sent'
        self.quote.save()
        with self.assertRaises(ValueError):
            self.quote.create_situation_invoice(10)


class FacturXTests(TestCase):
    """Facture électronique : XML CII EN 16931 valide (XSD officiel) et cohérent."""

    def setUp(self):
        self.user, self.org, self.client_obj = make_org('Theta', 'theta@test.fr')
        give_plan(self.user, 'pro')  # Factur-X : forfait Pro
        self.org.registration_number, self.org.tax_id = '123 456 789 00012', 'FR12123456789'
        self.org.address, self.org.postal_code, self.org.city, self.org.iban = '1 rue de la Paix', '75002', 'Paris', 'FR7630006000011234567890189'
        self.org.save()
        c = self.client_obj
        c.company_name, c.registration_number, c.address, c.postal_code, c.city = 'Nova SAS', '987654321', '2 av. Foch', '69006', 'Lyon'
        c.save()

    def amounts(self, xml):
        import re as _re
        text = xml.decode()
        get = lambda tag: Decimal(_re.search(rf'<ram:{tag}[^>]*>([^<]+)<', text).group(1))
        return {t: get(t) for t in ('LineTotalAmount', 'TaxBasisTotalAmount', 'TaxTotalAmount', 'GrandTotalAmount', 'DuePayableAmount')}

    def test_invoice_xml_is_valid_and_consistent(self):
        from apps.invoices.facturx import build_cii_xml, readiness, validate
        invoice = make_invoice(self.org, self.client_obj, status='sent')
        self.assertEqual(readiness(invoice), {'b2b': True, 'missing': [], 'ready': True})
        xml = build_cii_xml(invoice)
        self.assertEqual(validate(xml), [])
        a = self.amounts(xml)
        self.assertEqual((a['LineTotalAmount'], a['TaxTotalAmount'], a['GrandTotalAmount']), (Decimal('100.00'), Decimal('20.00'), Decimal('120.00')))
        self.assertIn(b'<ram:TypeCode>380</ram:TypeCode>', xml)
        self.assertIn(b'schemeID="0002">123456789<', xml)  # SIREN extrait du SIRET

    def test_credit_note_references_invoice(self):
        from apps.invoices.facturx import build_cii_xml, validate
        invoice = make_invoice(self.org, self.client_obj, status='sent')
        credit = invoice.create_credit_note()
        credit.status = 'sent'
        credit.save()
        xml = build_cii_xml(credit)
        self.assertEqual(validate(xml), [])
        self.assertIn(b'<ram:TypeCode>381</ram:TypeCode>', xml)
        self.assertIn(f'<ram:IssuerAssignedID>{invoice.invoice_number}<'.encode(), xml)

    def test_vat_franchise_and_discount(self):
        from apps.invoices.facturx import build_cii_xml, validate
        self.org.billing_preferences = {'vat_exempt': True}
        self.org.save()
        invoice = make_invoice(self.org, self.client_obj, status='sent')
        invoice.discount_amount = Decimal('10.00')
        invoice.save(update_fields=['discount_amount'])
        xml = build_cii_xml(invoice)
        self.assertEqual(validate(xml), [])
        self.assertIn(b'<ram:CategoryCode>E</ram:CategoryCode>', xml)
        self.assertIn('293 B'.encode(), xml)
        a = self.amounts(xml)
        self.assertEqual((a['TaxBasisTotalAmount'], a['TaxTotalAmount'], a['GrandTotalAmount']), (Decimal('90.00'), Decimal('0.00'), Decimal('90.00')))

    def test_readiness_lists_missing_legal_data(self):
        from apps.invoices.facturx import readiness
        self.org.registration_number = ''
        self.org.save()
        self.client_obj.registration_number = ''
        self.client_obj.save()
        missing = readiness(make_invoice(self.org, self.client_obj))['missing']
        self.assertTrue(any('votre entreprise' in m and 'SIREN' in m for m in missing))
        self.assertTrue(any('SIREN du client' in m for m in missing))

    def test_download_requires_issued_invoice(self):
        http = HttpClient(HTTP_HOST='127.0.0.1')
        http.force_login(self.user)
        draft = make_invoice(self.org, self.client_obj)
        self.assertEqual(http.get(reverse('invoices:invoice-facturx', args=[draft.id, 'xml'])).status_code, 302)
        issued = make_invoice(self.org, self.client_obj, status='sent')
        response = http.get(reverse('invoices:invoice-facturx', args=[issued.id, 'xml']))
        self.assertEqual(response['Content-Type'], 'application/xml')
        self.assertIn(b'CrossIndustryInvoice', response.content)


class SendFromPreviewTests(TestCase):
    def setUp(self):
        self.user, self.org, self.client_obj = make_org('Delta', 'delta@test.fr')
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def test_preview_button_sends_and_returns_to_preview(self):
        invoice = make_invoice(self.org, self.client_obj)
        url = reverse('invoices:send-invoice', args=[invoice.id])
        self.assertContains(self.http.get(reverse('invoices:invoice-preview', args=[invoice.id])), f'action="{url}"')
        response = self.http.post(url)
        self.assertRedirects(response, reverse('invoices:invoice-preview', args=[invoice.id]), fetch_redirect_response=False)
        invoice.refresh_from_db()
        self.assertNotEqual(invoice.status, 'draft')

    def test_list_action_still_gets_json(self):
        invoice = make_invoice(self.org, self.client_obj)
        response = self.http.post(reverse('invoices:send-invoice', args=[invoice.id]), HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])


class DepositInvoiceTests(TestCase):
    """Facture d'acompte : HT + TVA ventilés par taux ; facture finale qui déduit l'acompte."""

    def setUp(self):
        from apps.invoices.models import Quote, QuoteItem, QuotePaymentMilestone
        self.user, self.org, self.client_obj = make_org('Theta', 'theta@test.fr')
        today = timezone.localdate()
        self.quote = Quote.objects.create(organization=self.org, client=self.client_obj, issue_date=today, title='Film',
                                          expiry_date=today + timedelta(days=30), subtotal=Decimal('1500'),
                                          tax_amount=Decimal('250'), total_amount=Decimal('1750'), status='accepted')
        QuoteItem.objects.create(quote=self.quote, name='Tournage', quantity=1, unit_price=Decimal('1000'), tax_rate=Decimal('20'))
        QuoteItem.objects.create(quote=self.quote, name='Livre photo', quantity=1, unit_price=Decimal('500'), tax_rate=Decimal('10'))
        self.milestone = QuotePaymentMilestone.objects.create(quote=self.quote, label='Acompte 30 %', amount=Decimal('525.00'))

    def test_deposit_invoice_splits_vat_by_rate(self):
        invoice = self.quote.generate_invoice_for_milestone(self.milestone, self.user)
        self.assertEqual((invoice.subtotal, invoice.tax_amount, invoice.total_amount),
                         (Decimal('450.00'), Decimal('75.00'), Decimal('525.00')))
        lines = sorted((item.tax_rate, item.unit_price) for item in invoice.items.all())
        self.assertEqual(lines, [(Decimal('10'), Decimal('150.00')), (Decimal('20'), Decimal('300.00'))])
        self.assertIn(self.quote.quote_number, invoice.notes)

    def test_single_rate_rounding_is_exact(self):
        self.quote.items.filter(tax_rate=10).delete()
        self.milestone.amount = Decimal('333.33')
        invoice = self.quote.generate_invoice_for_milestone(self.milestone, self.user)
        self.assertEqual(invoice.subtotal + invoice.tax_amount, Decimal('333.33'))
        self.assertEqual(invoice.items.get().tax_rate, Decimal('20'))

    def test_final_invoice_deducts_deposit(self):
        deposit = self.quote.generate_invoice_for_milestone(self.milestone, self.user)
        deposit.status = 'sent'
        deposit.save()
        final = self.quote.convert_to_invoice(self.user)
        self.assertEqual((final.subtotal, final.tax_amount, final.total_amount),
                         (Decimal('1050.00'), Decimal('175.00'), Decimal('1225.00')))
        deductions = final.items.filter(unit_price__lt=0)
        self.assertEqual(deductions.count(), 2)
        self.assertTrue(all(deposit.invoice_number in item.name for item in deductions))
