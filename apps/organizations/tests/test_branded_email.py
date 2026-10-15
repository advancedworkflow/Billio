"""Emails aux couleurs de l'organisation : mise en page HTML, textes personnalisés, devis, page de réglages."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.test import Client as HttpClient, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.invoices.models import Quote, QuoteItem
from apps.invoices.tests.test_billing import make_invoice, make_org


class BrandedEmailTests(TestCase):
    def setUp(self):
        self.user, self.org, self.client_obj = make_org('Lumen', 'lumen@test.fr')
        self.org.email_color = '#e11d48'
        self.org.email_signature = 'Camille Martin\nGérante'
        self.org.save()

    def test_invoice_email_is_html_branded_with_button_and_signature(self):
        invoice = make_invoice(self.org, self.client_obj)
        ok, _ = invoice.send_to_client()
        self.assertTrue(ok)
        message = mail.outbox[-1]
        html = message.alternatives[0][0]
        self.assertIn('#e11d48', html)
        self.assertIn('Consulter et payer la facture', html)
        self.assertIn('Camille Martin', html)
        self.assertIn(str(invoice.id), message.body)  # lien de paiement dans la version texte
        self.assertIn('Camille Martin', message.body)

    def test_custom_texts_replace_defaults(self):
        self.org.email_templates = {'invoice': {'subject': 'Votre facture {{numero}} de {{entreprise}}',
                                                'body': 'Coucou {{client}}, voici {{numero}}.'}}
        self.org.save()
        invoice = make_invoice(self.org, self.client_obj)
        invoice.send_to_client()
        invoice.refresh_from_db()
        message = mail.outbox[-1]
        self.assertEqual(message.subject, f'Votre facture {invoice.invoice_number} de Lumen')
        self.assertIn(f'Coucou Client de Lumen, voici {invoice.invoice_number}.', message.body)

    def test_sending_a_quote_emails_the_client(self):
        today = timezone.localdate()
        quote = Quote.objects.create(organization=self.org, client=self.client_obj, issue_date=today,
                                     expiry_date=today + timedelta(days=30), title='Site')
        QuoteItem.objects.create(quote=quote, name='Maquette', quantity=1, unit_price=Decimal('500'), tax_rate=Decimal('20'))
        with mock.patch.object(Quote, 'generate_pdf_bytes', return_value=b'%PDF-1.4 test'):
            ok, _ = quote.send_to_client()
        self.assertTrue(ok)
        message = mail.outbox[-1]
        self.assertEqual(message.to, [self.client_obj.email])
        self.assertIn('Consulter le devis', message.alternatives[0][0])
        self.assertTrue(any(name.endswith('.pdf') for name, *_ in message.attachments))

    def test_settings_page_saves_preview_and_test_send(self):
        http = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr')
        http.force_login(self.user)
        url = reverse('organizations:email-settings')
        self.assertEqual(http.get(url).status_code, 200)
        preview = http.post(reverse('organizations:email-preview'), {'kind': 'quote', 'email_color': '#16a34a'})
        self.assertIn('#16a34a', preview.content.decode())
        self.assertIn('Consulter le devis', preview.content.decode())
        http.post(url, {'form_action': 'test', 'test_kind': 'reminder_j30', 'email_color': '#16a34a',
                        'email_signature': 'Équipe Lumen', 'subject_reminder_j30': 'Dernier rappel {{numero}}'})
        self.org.refresh_from_db()
        self.assertEqual(self.org.email_color, '#16a34a')
        self.assertEqual(self.org.email_templates, {'reminder_j30': {'subject': 'Dernier rappel {{numero}}'}})
        self.assertEqual(mail.outbox[-1].to, ['lumen@test.fr'])
        self.assertEqual(mail.outbox[-1].subject, '[Test] Dernier rappel INV-0042')
