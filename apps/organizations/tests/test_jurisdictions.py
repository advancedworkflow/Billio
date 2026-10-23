"""
Facturation multi-pays : profil de conformité, documents localisés, mentions automatiques,
vérification avant envoi, export comptable universel.

    python manage.py test apps.organizations.tests.test_jurisdictions
"""
import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.clients.models import Client
from apps.invoices import accounting_export
from apps.invoices.document_language import localize
from apps.invoices.models import Invoice, InvoiceItem, Tax
from apps.organizations import jurisdictions as j
from apps.organizations.models import Organization
from apps.templates_app.models import InvoiceTemplate
from apps.templates_app.pro_templates import PRO_TEMPLATES

PASSWORD = 'x-Test-1234'


class JurisdictionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='julie', email='julie@lumen.test', password=PASSWORD)
        self.org = Organization.objects.create(name='Studio Lumen', owner=self.user, address='8 avenue de la République',
                                               city='Lyon', postal_code='69002')

    def make_invoice(self, client, rate='20', tax=True, total=None):
        ht = Decimal('100.00')
        vat = (ht * Decimal(rate) / 100).quantize(Decimal('0.01')) if tax else Decimal('0')
        template, _ = InvoiceTemplate.objects.get_or_create(
            organization=self.org, name='Essentiel',
            defaults={'html_structure': PRO_TEMPLATES[0]['html'], 'css_styles': PRO_TEMPLATES[0]['css']})
        invoice = Invoice.objects.create(organization=self.org, client=client, issue_date=date(2026, 3, 1),
                                         due_date=date(2026, 3, 31), subtotal=ht, tax_amount=vat,
                                         total_amount=total or ht + vat, template=template)
        InvoiceItem.objects.create(invoice=invoice, name='Design', quantity=1, unit_price=ht,
                                   tax_rate=Decimal(rate) if tax else Decimal('0'))
        return invoice

    # ---------- Profil ----------

    def test_legacy_account_without_country_stays_french_and_unchanged(self):
        self.org.billing_preferences = {'payment_days': 30}
        self.org.save()
        prof = j.profile(self.org)
        self.assertEqual((prof['country'], prof['doc_language']), ('FR', 'fr'))
        texts = self.org.billing_texts()
        self.assertIn('indemnité forfaitaire de 40 €', texts['legal_mentions'])
        self.assertEqual(texts['payment_terms'], 'Paiement à 30 jours à réception de facture, par virement bancaire.')
        html = '<p>Facture n° INV-0001</p><td>TVA</td><p>SIRET 123</p>'
        self.assertEqual(localize(html, self.org), html)

    def test_australia_registered_sets_currency_gst_and_tax_invoice_title(self):
        j.apply_profile(self.org, {'country': 'AU', 'status': 'pme', 'tax_registered': True})
        self.org.refresh_from_db()
        self.assertEqual((self.org.default_currency, self.org.country), ('AUD', 'Australie'))
        default = Tax.objects.get(organization=self.org, is_default=True)
        self.assertEqual((default.name, default.rate), ('GST 10 %', Decimal('10.00')))
        self.assertEqual(j.document_title(self.org), 'Tax invoice')
        j.apply_profile(self.org, {'country': 'AU', 'status': 'freelance', 'tax_registered': False})
        self.assertEqual(j.document_title(self.org), 'Invoice')
        self.assertEqual(Tax.objects.get(organization=self.org, is_default=True).rate, Decimal('0'))
        self.assertIn('Not registered for GST', self.org.billing_texts()['legal_mentions'])

    def test_canada_rates_follow_the_province(self):
        j.apply_profile(self.org, {'country': 'CA', 'status': 'freelance', 'tax_registered': True, 'region': 'ON'})
        default = Tax.objects.get(organization=self.org, is_default=True)
        self.assertEqual(default.rate, Decimal('13.00'))

    def test_small_business_exemption_mentions_in_local_language(self):
        j.apply_profile(self.org, {'country': 'DE', 'status': 'freelance', 'tax_registered': False})
        self.assertIn('§ 19 UStG', self.org.billing_texts()['legal_mentions'])
        j.apply_profile(self.org, {'country': 'DE', 'status': 'freelance', 'tax_registered': False, 'doc_language': 'en'})
        self.assertIn('Article 284', self.org.billing_texts()['legal_mentions'])
        self.assertIn('Payment due within', self.org.billing_texts()['payment_terms'])

    def test_checklist_validates_identifiers(self):
        j.apply_profile(self.org, {'country': 'AU', 'status': 'freelance', 'tax_registered': True})
        self.org.tax_id = '12 345 678 901'  # clé ABN invalide
        self.org.save()
        items = {i['label']: i for i in j.checklist(self.org)}
        self.assertFalse(items['ABN']['ok'])
        self.assertEqual(j.readiness(list(items.values())), 'todo')
        self.org.tax_id = '51 824 753 556'
        self.org.save()
        self.assertTrue({i['label']: i for i in j.checklist(self.org)}['ABN']['ok'])

        j.apply_profile(self.org, {'country': 'FR', 'status': 'pme', 'tax_registered': True})
        self.org.registration_number = '732 829 320 00074'
        self.org.tax_id = 'FR44732829320'
        self.org.save()
        items = {i['label']: i for i in j.checklist(self.org)}
        self.assertTrue(items['SIRET']['ok'])
        self.assertTrue(items['Numéro de TVA intracommunautaire']['ok'])
        self.assertFalse(items['Mentions de votre société']['ok'])

    def test_other_country_is_simple_with_a_clear_warning(self):
        self.org.country = 'Maroc'
        self.org.save()
        prof = j.profile(self.org)
        self.assertFalse(j.pack_for(prof['country'])['supported'])
        checks = j.invoice_checks(self.make_invoice(Client.objects.create(organization=self.org, name='Atlas', email='a@a.ma')))
        self.assertEqual(checks[0]['level'], 'info')
        self.assertIn('comptable local', checks[0]['message'])

    # ---------- Documents ----------

    def test_uk_invoice_is_printed_in_english_with_vat(self):
        j.apply_profile(self.org, {'country': 'GB', 'status': 'pme', 'tax_registered': True,
                                   'company_details': 'Registered in England and Wales, company no. 01234567'})
        self.org.tax_id, self.org.registration_number = 'GB123456789', '01234567'
        self.org.save()
        client = Client.objects.create(organization=self.org, name='Rive Ltd', email='r@rive.uk', address='1 High St')
        html = self.make_invoice(client).render_html()
        for english in ('Invoice', 'VAT', 'Amount due', 'Company no. 01234567', 'VAT no. GB123456789',
                        'Registered in England and Wales'):
            self.assertIn(english, html)
        for french in ('Facture', 'TVA', 'Net à payer', 'SIRET', 'Désignation'):
            self.assertNotIn(french, html)

    def test_us_dates_are_month_first(self):
        j.apply_profile(self.org, {'country': 'US', 'status': 'freelance', 'tax_registered': False})
        client = Client.objects.create(organization=self.org, name='Acme', email='a@acme.us')
        self.assertIn('03/31/2026', self.make_invoice(client, tax=False).render_html())

    def test_intra_eu_reverse_charge_and_export_mentions(self):
        j.apply_profile(self.org, {'country': 'FR', 'status': 'pme', 'tax_registered': True})
        belgian = Client.objects.create(organization=self.org, name='Atelier BXL', email='a@bxl.be', country='Belgique',
                                        tax_id='BE0123456789', address='Rue Haute 1')
        invoice = self.make_invoice(belgian, tax=False)
        self.assertIn('Autoliquidation – art. 283-2 du CGI', invoice.render_html())
        self.assertIn('ok', [c['level'] for c in j.invoice_checks(invoice)])

        taxed = self.make_invoice(belgian)
        self.assertNotIn('Autoliquidation', taxed.render_html())
        self.assertTrue(any('autoliquidation' in c['message'] for c in j.invoice_checks(taxed) if c['level'] == 'warning'))

        american = Client.objects.create(organization=self.org, name='Acme', company_name='Acme Inc.', email='a@acme.us',
                                         country='United States', address='1 Main St')
        self.assertIn('art. 259-1 du CGI', self.make_invoice(american, tax=False).render_html())

    def test_checks_flag_tax_on_exempt_seller_and_odd_rates(self):
        j.apply_profile(self.org, {'country': 'FR', 'status': 'freelance', 'tax_registered': False})
        client = Client.objects.create(organization=self.org, name='Rive', email='r@rive.fr', address='1 rue')
        checks = j.invoice_checks(self.make_invoice(client))
        self.assertTrue(any(c['level'] == 'error' and 'ne pas facturer' in c['message'] for c in checks))
        j.apply_profile(self.org, {'country': 'FR', 'status': 'freelance', 'tax_registered': True})
        checks = j.invoice_checks(self.make_invoice(client, rate='19'))
        self.assertTrue(any('Taux inhabituel' in c['message'] for c in checks))

    # ---------- Écrans ----------

    def test_settings_assistant_saves_and_preview_shows_checks(self):
        http = HttpClient(HTTP_HOST='127.0.0.1')
        http.force_login(self.user)
        url = reverse('accounts:user-settings')
        page = http.get(url + '?tab=conformite')
        self.assertContains(page, 'Vos règles de facturation')
        self.assertContains(page, 'Royaume-Uni')
        http.post(url, {'form_action': 'save_compliance', 'country': 'NZ', 'status': 'freelance',
                        'tax_registered': 'yes', 'doc_language': 'en'})
        self.org.refresh_from_db()
        prof = j.profile(self.org)
        self.assertEqual((prof['country'], prof['tax_registered'], prof['confirmed']), ('NZ', True, True))
        self.assertEqual(self.org.default_currency, 'NZD')

        client = Client.objects.create(organization=self.org, name='Kiwi', email='k@kiwi.nz')
        preview = http.get(reverse('invoices:invoice-preview', args=[self.make_invoice(client, rate='15').id]))
        self.assertContains(preview, 'Vérification de conformité')
        self.assertNotContains(preview, 'Factur-X')

    def test_signup_country_presets_the_profile(self):
        cache.clear()
        http = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr')
        http.post(reverse('accounts:register'), {
            'name': 'Jack Smith', 'email': 'jack@smith.co.uk', 'password': 'Photo-Lumiere-2026',
            'country': 'GB', 'phone': '07700 900123', 'trade': 'audiovisuel', 'accept_terms': '1'})
        org = Organization.objects.get(owner__email='jack@smith.co.uk')
        prof = j.profile(org)
        self.assertEqual((prof['country'], prof['doc_language'], prof['confirmed']), ('GB', 'en', False))
        self.assertEqual(org.default_currency, 'GBP')

    def test_universal_accounting_export(self):
        j.apply_profile(self.org, {'country': 'GB', 'status': 'freelance', 'tax_registered': True})
        client = Client.objects.create(organization=self.org, name='Rive Ltd', email='r@rive.uk')
        invoice = self.make_invoice(client)
        invoice.status = 'sent'
        invoice.save()
        archive = zipfile.ZipFile(io.BytesIO(accounting_export.build(self.org, date(2026, 1, 1), date(2026, 12, 31))))
        self.assertEqual(sorted(archive.namelist()), ['invoices.csv', 'lines.csv', 'payments.csv'])
        rows = archive.read('invoices.csv').decode('utf-8-sig').splitlines()
        self.assertTrue(rows[0].startswith('Date;Number;Type'))
        self.assertIn(';Invoice;', rows[1])
        self.assertIn('100.00;20.00;120.00', rows[1])

        http = HttpClient(HTTP_HOST='127.0.0.1')
        http.force_login(self.user)
        response = http.get(reverse('invoices:accounting-export'),
                            {'organization': self.org.pk, 'start': '2026-01-01', 'end': '2026-12-31'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')
