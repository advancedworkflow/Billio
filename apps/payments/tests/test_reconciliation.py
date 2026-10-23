"""
Rapprochement manuel des paiements : lecture des relevés, suggestions, validation, annulation.

    python manage.py test apps.payments
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as HttpClient, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.invoices.models import Invoice, InvoiceItem
from apps.organizations.models import Organization
from apps.payments import reconciliation as rec
from apps.payments.models import BankLine, Payment

FRENCH_BANK = """Compte courant n° 12345;;;
Période du 01/03/2026 au 31/03/2026;;;
Date opération;Libellé;Débit;Crédit
05/03/2026;VIR SEPA ATELIER RIVE FACTURE INV-0001;;1 200,00
06/03/2026;CB CARREFOUR;45,90;
07/03/2026;VIR M. DUPONT;;350,00
""".encode('cp1252')

ENGLISH_BANK = b"""Date,Description,Amount
2026-03-05,"Payment from Atelier Rive, ref INV-0001","1,200.00"
2026-03-06,Card purchase,-45.90
"""

GERMAN_BANK = """Buchungstag;Verwendungszweck;Betrag
05.03.2026;Rechnung INV-0001 Atelier Rive;1.200,00
""".encode('utf-8')


class StatementParsingTests(TestCase):
    def test_french_bank_with_preamble_and_credit_debit_columns(self):
        entries, debits = rec.parse_statement(FRENCH_BANK)
        self.assertEqual(debits, 1)
        self.assertEqual([(e['date'], e['amount']) for e in entries],
                         [(date(2026, 3, 5), Decimal('1200.00')), (date(2026, 3, 7), Decimal('350.00'))])
        self.assertIn('INV-0001', entries[0]['label'])

    def test_english_and_german_formats(self):
        for content in (ENGLISH_BANK, GERMAN_BANK):
            entries, _debits = rec.parse_statement(content)
            self.assertEqual((entries[0]['date'], entries[0]['amount']), (date(2026, 3, 5), Decimal('1200.00')))

    def test_us_dates_month_first(self):
        entries, _ = rec.parse_statement(b"Date,Description,Amount\n03/05/2026,Deposit,100.00\n", month_first=True)
        self.assertEqual(entries[0]['date'], date(2026, 3, 5))

    def test_amount_formats(self):
        cases = {'1 234,56': '1234.56', '1,234.56': '1234.56', '1.234,56': '1234.56', '-12,00': '-12.00',
                 '(45.10)': '-45.10', '1234': '1234.00', '€ 99,90': '99.90', "1'250.00": '1250.00'}
        for raw, expected in cases.items():
            self.assertEqual(rec.parse_amount(raw), Decimal(expected), raw)

    def test_unreadable_file_explains_what_to_do(self):
        with self.assertRaises(rec.StatementError):
            rec.parse_statement(b'hello;world\n1;2\n')


class ReconciliationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='julie', email='julie@lumen.test', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio Lumen', owner=self.user)
        self.rive = Client.objects.create(organization=self.org, name='Atelier Rive', email='compta@rive.fr')
        self.dupont = Client.objects.create(organization=self.org, name='Paul Dupont', email='p@dupont.fr')
        self.inv1 = self.invoice(self.rive, '1200.00')   # INV-0001
        self.inv2 = self.invoice(self.dupont, '700.00')  # INV-0002
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def invoice(self, client, total):
        total = Decimal(total)
        ht = (total / Decimal('1.2')).quantize(Decimal('0.01'))
        invoice = Invoice.objects.create(organization=self.org, client=client, issue_date=date(2026, 3, 1),
                                         due_date=date(2026, 3, 31), subtotal=ht, tax_amount=total - ht, total_amount=total)
        InvoiceItem.objects.create(invoice=invoice, name='Prestation', quantity=1, unit_price=ht, tax_rate=Decimal('20'))
        invoice.status = 'sent'
        invoice.save()
        return invoice

    def import_french(self):
        return self.http.post(reverse('payments:reconcile-import'),
                              {'statement': SimpleUploadedFile('releve.csv', FRENCH_BANK, 'text/csv')}, follow=True)

    def test_import_suggests_and_is_idempotent(self):
        response = self.import_french()
        self.assertContains(response, 'Encaissements importés : 2 · déjà présents : 0')
        self.assertContains(response, "sorties d&#x27;argent ignorées : 1")
        self.import_french()
        self.assertEqual(BankLine.objects.filter(organization=self.org).count(), 2)

        invoices = rec.open_invoices(self.org)
        rive_line = BankLine.objects.get(amount=Decimal('1200.00'))
        suggestion = rec.suggest(rive_line, invoices)
        self.assertEqual(suggestion['invoice'], self.inv1)
        self.assertTrue(suggestion['sure'])
        self.assertIn('numéro de facture dans le libellé', suggestion['reasons'])

        partial = rec.suggest(BankLine.objects.get(amount=Decimal('350.00')), invoices)
        self.assertEqual(partial['invoice'], self.inv2)  # nom du client, paiement partiel
        self.assertFalse(partial['sure'])

        page = self.http.get(reverse('payments:reconcile'))
        self.assertContains(page, 'Correspondance sûre')
        self.assertContains(page, 'Correspondances sûres : 1')

    def test_validate_all_sure_then_undo(self):
        self.import_french()
        self.http.post(reverse('payments:reconcile-match-sure'))
        self.inv1.refresh_from_db()
        self.assertEqual(self.inv1.status, 'paid')
        line = BankLine.objects.get(amount=Decimal('1200.00'))
        self.assertEqual((line.status, line.payment.invoice), ('matched', self.inv1))
        self.assertEqual(BankLine.objects.get(amount=Decimal('350.00')).status, 'pending')

        self.http.post(reverse('payments:reconcile-undo', args=[line.id]))
        line.refresh_from_db()
        self.inv1.refresh_from_db()
        self.assertEqual(line.status, 'pending')
        self.assertEqual(self.inv1.status, 'overdue')  # échéance passée : la facture rouverte est en retard
        self.assertFalse(Payment.objects.filter(invoice=self.inv1).exists())

    def test_partial_match_and_overpayment_refused(self):
        self.import_french()
        line = BankLine.objects.get(amount=Decimal('350.00'))
        response = self.http.post(reverse('payments:reconcile-match', args=[line.id]), {'invoice_id': self.inv2.id}, follow=True)
        self.assertContains(response, 'reste 350.00')
        self.inv2.refresh_from_db()
        self.assertEqual(self.inv2.status, 'sent')

        big = rec.add_line(self.org, date(2026, 3, 8), Decimal('5000.00'), 'Gros virement')
        response = self.http.post(reverse('payments:reconcile-match', args=[big.id]), {'invoice_id': self.inv1.id}, follow=True)
        self.assertContains(response, 'dépasse le reste dû')
        big.refresh_from_db()
        self.assertEqual(big.status, 'pending')

    def test_ignore_manual_line_and_isolation(self):
        self.http.post(reverse('payments:reconcile-add'), {'date': '2026-03-09', 'amount': '80,00', 'label': 'Remboursement'})
        line = BankLine.objects.get(amount=Decimal('80.00'))
        self.http.post(reverse('payments:reconcile-ignore', args=[line.id]))
        line.refresh_from_db()
        self.assertEqual(line.status, 'ignored')
        future = (timezone.localdate() + timedelta(days=3)).isoformat()
        self.http.post(reverse('payments:reconcile-add'), {'date': future, 'amount': '10'})
        self.assertFalse(BankLine.objects.filter(amount=Decimal('10.00')).exists())

        intruder = User.objects.create_user(username='marc', email='marc@other.test', password='x-Test-1234')
        Organization.objects.create(name='Autre', owner=intruder)
        other = HttpClient(HTTP_HOST='127.0.0.1')
        other.force_login(intruder)
        self.assertEqual(other.post(reverse('payments:reconcile-undo', args=[line.id])).status_code, 404)

    def test_payments_page_links_to_reconciliation(self):
        self.assertContains(self.http.get(reverse('payments:payments-page')), reverse('payments:reconcile'))

    def test_record_payment_form_still_works(self):
        response = self.http.post(reverse('payments:record-payment'),
                                  {'invoice_id': self.inv2.id, 'amount': '700', 'date': '2026-03-10'})
        self.assertEqual(response.json(), {'ok': True, 'fully_paid': True, 'message': 'Facture soldée.'})
        self.inv2.refresh_from_db()
        self.assertEqual(self.inv2.status, 'paid')
