"""Page Contact : enregistrement, email au support, champ piège et limite par IP."""
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.landing.models import ContactMessage

VALID = {'name': 'Awa Diallo', 'email': 'awa@studio.fr', 'company': 'Studio Lumen',
         'subject': 'demo', 'message': "J'aimerais voir les workflows en démo."}


@override_settings(SUPPORT_EMAIL='support@billio.test')
class ContactPageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.cookies['billio_lang'] = 'fr'
        self.url = reverse('landing:contact')

    def test_page_renders(self):
        page = self.client.get(self.url, HTTP_HOST='127.0.0.1')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Parlons de votre activité')
        self.assertContains(page, 'support@billio.test')

    def test_message_saved_and_emailed(self):
        response = self.client.post(self.url, VALID, HTTP_HOST='127.0.0.1')
        self.assertRedirects(response, self.url + '?envoye=1#formulaire', fetch_redirect_response=False)
        msg = ContactMessage.objects.get()
        self.assertEqual((msg.email, msg.subject), ('awa@studio.fr', 'demo'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['support@billio.test'])
        self.assertEqual(mail.outbox[0].reply_to, ['awa@studio.fr'])
        done = self.client.get(self.url + '?envoye=1', HTTP_HOST='127.0.0.1')
        self.assertContains(done, 'Message envoyé')

    def test_invalid_form_shows_errors(self):
        response = self.client.post(self.url, {**VALID, 'email': 'pas-un-email', 'message': 'court'}, HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-invalid="true"')
        self.assertFalse(ContactMessage.objects.exists())

    def test_honeypot_is_silently_dropped(self):
        response = self.client.post(self.url, {**VALID, 'website': 'http://spam.example'}, HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ContactMessage.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_rate_limited_per_ip(self):
        for _ in range(5):
            self.client.post(self.url, VALID, HTTP_HOST='127.0.0.1')
        blocked = self.client.post(self.url, VALID, HTTP_HOST='127.0.0.1')
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(ContactMessage.objects.count(), 5)
