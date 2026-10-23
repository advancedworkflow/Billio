"""
Export FEC : écritures équilibrées, TVA par taux, avoirs, achats, règlements, lettrage, format.

    python manage.py test apps.invoices.tests.test_fec
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.test import Client as HttpClient, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.invoices import fec
from apps.invoices.models import Invoice, InvoiceItem
from apps.organizations.models import Organization, OrganizationMember
from apps.payments.models import Payment

START, END = date(2026, 1, 1), date(2026, 12, 31)


def aware(day):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()).replace(hour=12))


class FecTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='julie', email='julie@lumen.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio Lumen', owner=self.user, registration_number='123 456 789 00012')
        self.client_a = Client.objects.create(organization=self.org, name='Atelier Rive', email='compta@rive.fr')

    def invoice(self, lines, *, day=date(2026, 3, 10), status='sent', invoice_type='sale', client=None):
        ht = sum(Decimal(q) * Decimal(p) for q, p, _r in lines)
        vat = sum((Decimal(q) * Decimal(p) * Decimal(r) / 100).quantize(Decimal('0.01')) for q, p, r in lines)
        invoice = Invoice.objects.create(
            organization=self.org, client=client or self.client_a, issue_date=day, due_date=day + timedelta(days=30),
            subtotal=ht, tax_amount=vat, total_amount=ht + vat, status='draft', invoice_type=invoice_type)
        for q, p, r in lines:
            InvoiceItem.objects.create(invoice=invoice, name='Prestation', quantity=Decimal(q), unit_price=Decimal(p), tax_rate=Decimal(r))
        if status != 'draft':
            invoice.status = status
            invoice.save()
        return invoice

    def pay(self, invoice, amount, day, fee='0'):
        Payment.objects.create(invoice=invoice, amount=Decimal(amount), status='completed', payment_date=aware(day),
                               processing_fee=Decimal(fee), transaction_id=f'pi_{invoice.pk.hex[:8]}')

    def parse(self, content):
        text = content.decode('iso-8859-15')
        self.assertTrue(text.endswith('\r\n'))
        rows = [line.split('\t') for line in text.rstrip('\r\n').split('\r\n')]
        self.assertEqual(rows[0], fec.COLUMNS)
        for row in rows[1:]:
            self.assertEqual(len(row), 18, row)
        return [dict(zip(fec.COLUMNS, row)) for row in rows[1:]]

    @staticmethod
    def amount(text):
        return Decimal(text.replace(',', '.'))

    def assert_balanced(self, rows):
        totals = defaultdict(lambda: [Decimal('0'), Decimal('0')])
        for row in rows:
            totals[row['EcritureNum']][0] += self.amount(row['Debit'])
            totals[row['EcritureNum']][1] += self.amount(row['Credit'])
        for number, (debit, credit) in totals.items():
            self.assertEqual(debit, credit, number)
        return totals

    def test_sale_with_two_vat_rates_payment_fee_and_lettering(self):
        invoice = self.invoice([('1', '100', '20'), ('2', '100', '5.5')])  # HT 300, TVA 20 + 11
        self.pay(invoice, '331.00', date(2026, 4, 2), fee='5.20')
        invoice.mark_as_paid()
        self.invoice([('1', '50', '20')], status='draft')  # brouillon : jamais dans le FEC
        self.invoice([('1', '70', '20')], day=date(2025, 12, 31))  # hors période

        content, count = fec.render(self.org, START, END)
        rows = self.parse(content)
        self.assertEqual(count, 2)
        self.assert_balanced(rows)
        sale = [r for r in rows if r['JournalCode'] == 'VT']
        by_account = {r['CompteNum']: r for r in sale}
        self.assertEqual(by_account['411000']['Debit'], '331,00')
        self.assertEqual(by_account['411000']['CompAuxNum'], f'C{self.client_a.pk:05d}')
        self.assertEqual(by_account['411000']['CompAuxLib'], 'Atelier Rive')
        # Une ligne de ventes par taux de TVA : 100 € à 20 %, 200 € à 5,5 %
        self.assertEqual(sorted(r['Credit'] for r in sale if r['CompteNum'] == '706000'), ['100,00', '200,00'])
        self.assertEqual(by_account['445711']['Credit'], '20,00')
        self.assertEqual(by_account['445713']['Credit'], '11,00')
        self.assertEqual(by_account['445713']['CompteLib'], 'TVA collectée 5,5 %')
        self.assertEqual(sale[0]['PieceRef'], invoice.invoice_number)
        self.assertEqual(sale[0]['EcritureDate'], '20260310')

        bank = {r['CompteNum']: r for r in rows if r['JournalCode'] == 'BQ'}
        self.assertEqual((bank['512000']['Debit'], bank['627000']['Debit'], bank['411000']['Credit']), ('325,80', '5,20', '331,00'))
        letter = by_account['411000']['EcritureLet']
        self.assertEqual(letter, 'AAA')
        self.assertEqual(bank['411000']['EcritureLet'], letter)
        self.assertEqual(bank['411000']['DateLet'], '20260402')
        self.assertEqual(by_account['706000']['EcritureLet'], '')

    def test_credit_note_reverses_the_sale_and_letters_the_cancelled_invoice(self):
        invoice = self.invoice([('1', '100', '20')])
        credit = invoice.create_credit_note(user=self.user)
        credit.status = 'sent'
        credit.save()
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'cancelled')

        rows = self.parse(fec.render(self.org, START, END)[0])
        self.assert_balanced(rows)
        credit_rows = {r['CompteNum']: r for r in rows if r['PieceRef'] == credit.invoice_number}
        self.assertEqual(credit_rows['411000']['Credit'], '120,00')
        self.assertEqual(credit_rows['706000']['Debit'], '100,00')
        self.assertEqual(credit_rows['445711']['Debit'], '20,00')
        receivables = [r for r in rows if r['CompteNum'] == '411000']
        self.assertEqual({r['EcritureLet'] for r in receivables}, {'AAA'})

    def test_purchase_invoice_goes_to_the_purchase_journal(self):
        supplier = Client.objects.create(organization=self.org, name='Imprimerie Nord', email='factures@nord.fr')
        purchase = self.invoice([('1', '40', '20')], invoice_type='purchase', client=supplier)
        self.pay(purchase, '48.00', date(2026, 3, 20))
        rows = self.parse(fec.render(self.org, START, END)[0])
        self.assert_balanced(rows)
        ac = {r['CompteNum']: r for r in rows if r['JournalCode'] == 'AC'}
        self.assertEqual((ac['606000']['Debit'], ac['445660']['Debit'], ac['401000']['Credit']), ('40,00', '8,00', '48,00'))
        self.assertEqual(ac['401000']['CompAuxNum'], f'F{supplier.pk:05d}')
        bq = {r['CompteNum']: r for r in rows if r['JournalCode'] == 'BQ'}
        self.assertEqual((bq['401000']['Debit'], bq['512000']['Credit']), ('48,00', '48,00'))

    def test_discount_and_rounding_still_balance(self):
        invoice = self.invoice([('3', '33.33', '20'), ('1', '10.01', '5.5')])
        invoice.discount_amount = Decimal('10.00')
        invoice.total_amount -= Decimal('10.00')
        invoice.save()
        rows = self.parse(fec.render(self.org, START, END, sales_account='707000')[0])
        self.assert_balanced(rows)
        self.assertTrue(any(r['CompteNum'] == '707000' for r in rows))
        sale_ttc = next(r for r in rows if r['CompteNum'] == '411000')
        self.assertEqual(self.amount(sale_ttc['Debit']), invoice.total_amount)

    def test_entries_are_numbered_continuously_in_date_order(self):
        self.invoice([('1', '10', '20')], day=date(2026, 5, 1))
        self.invoice([('1', '10', '20')], day=date(2026, 2, 1))
        rows = self.parse(fec.render(self.org, START, END)[0])
        self.assertEqual([r['EcritureNum'] for r in rows if r['CompteNum'] == '411000'], ['VT000001', 'VT000002'])
        self.assertEqual([r['EcritureDate'] for r in rows if r['CompteNum'] == '411000'], ['20260201', '20260501'])

    def test_download_view_and_permissions(self):
        self.invoice([('1', '100', '20')])
        http = HttpClient(HTTP_HOST='127.0.0.1')
        http.force_login(self.user)
        url = reverse('invoices:fec-export')
        response = http.get(url, {'organization': self.org.pk, 'start': '2026-01-01', 'end': '2026-12-31'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Disposition'], 'attachment; filename="123456789FEC20261231.txt"')
        self.assertIn('iso-8859-15', response['Content-Type'])
        self.parse(response.content)

        bad = http.get(url, {'organization': self.org.pk, 'start': '2026-12-31', 'end': '2026-01-01'})
        self.assertEqual(bad.status_code, 302)

        member = User.objects.create_user(username='paul', email='paul@lumen.fr', password='x-Test-1234')
        OrganizationMember.objects.create(organization=self.org, user=member, role='member')
        http.force_login(member)
        refused = http.get(url, {'organization': self.org.pk, 'start': '2026-01-01', 'end': '2026-12-31'})
        self.assertEqual(refused.status_code, 302)

    def test_settings_page_shows_the_export(self):
        http = HttpClient(HTTP_HOST='127.0.0.1')
        http.force_login(self.user)
        page = http.get(reverse('accounts:user-settings') + '?tab=facturation')
        self.assertContains(page, 'Export comptable (FEC)')
        self.assertContains(page, reverse('invoices:fec-export'))
