"""« Mot de passe oublié » : email, lien construit sur SITE_URL, changement du mot de passe."""
import re

from django.core import mail
from django.test import Client as HttpClient, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User


@override_settings(SITE_URL='https://app.billio.test', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='julie', email='julie@test.fr', password='Ancien-Mot-2026', first_name='Julie')
        self.http = HttpClient(HTTP_HOST='127.0.0.1')

    def test_login_page_links_to_reset(self):
        self.assertContains(self.http.get(reverse('accounts:login')), reverse('accounts:password-reset'))

    def test_full_reset_flow(self):
        response = self.http.post(reverse('accounts:password-reset'), {'email': 'JULIE@test.fr'})
        self.assertRedirects(response, reverse('accounts:password-reset-done'))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['julie@test.fr'])
        self.assertIn('Bonjour Julie', message.body)
        link = re.search(r'https://app\.billio\.test(/accounts/password-reset/\S+/)', message.body)
        self.assertIsNotNone(link, message.body)  # jamais l'hôte de la requête (empoisonnement Host)
        self.assertNotIn('127.0.0.1', message.body)

        confirm = self.http.get(link.group(1), follow=True)
        self.assertContains(confirm, 'Nouveau mot de passe')
        done = self.http.post(confirm.redirect_chain[-1][0], {'new_password1': 'Nouveau-Mot-2026!', 'new_password2': 'Nouveau-Mot-2026!'})
        self.assertRedirects(done, reverse('accounts:password-reset-complete'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Nouveau-Mot-2026!'))
        self.assertContains(self.http.get(link.group(1), follow=True), 'Lien expiré')  # lien à usage unique

    def test_unknown_email_reveals_nothing(self):
        response = self.http.post(reverse('accounts:password-reset'), {'email': 'inconnu@test.fr'})
        self.assertRedirects(response, reverse('accounts:password-reset-done'))
        self.assertEqual(len(mail.outbox), 0)
