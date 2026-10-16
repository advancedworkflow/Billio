"""Emails du compte : bienvenue à l'inscription, mot de passe oublié de bout en bout."""
import re
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import Client as HttpClient, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User

SITE = 'https://app.billio.test'


@override_settings(SITE_URL=SITE, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   SUPPORT_EMAIL='support@billio.test')
class AccountEmailTests(TestCase):
    def setUp(self):
        cache.clear()
        self.http = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr')

    def signup(self):
        return self.http.post(reverse('accounts:register'), {
            'name': 'Julie Moreau', 'email': 'julie@moreau-photo.fr', 'password': 'Photo-Lumiere-2026',
            'country': 'FR', 'phone': '06 12 34 56 78', 'trade': 'audiovisuel', 'accept_terms': '1'})

    def test_welcome_email_on_signup(self):
        self.signup()
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual((email.subject, email.to, email.reply_to), ('Bienvenue sur Billio', ['julie@moreau-photo.fr'], ['support@billio.test']))
        self.assertIn('Bienvenue Julie', email.body)
        self.assertIn(f"{SITE}{reverse('dashboard:dashboard-home')}", email.body)
        html = email.alternatives[0][0]
        self.assertIn(f'href="{SITE}{reverse("dashboard:dashboard-home")}"', html)
        # Logo Billio en tête, en URL absolue (les messageries ne résolvent pas les chemins relatifs)
        self.assertIn(f'src="{SITE}/static/images/logo/app-tile-512.png"', html)

    def test_signup_still_works_when_smtp_fails(self):
        with mock.patch('django.core.mail.EmailMultiAlternatives.send', side_effect=OSError('SMTP down')):
            response = self.signup()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(email='julie@moreau-photo.fr').exists())

    def test_password_reset_round_trip(self):
        user = User.objects.create_user(username='j', email='julie@moreau-photo.fr', password='Ancien-Mot-2026', first_name='Julie')
        response = self.http.post(reverse('accounts:password-reset'), {'email': 'Julie@Moreau-Photo.fr'})
        self.assertRedirects(response, reverse('accounts:password-reset-done'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ['julie@moreau-photo.fr'])
        self.assertIn('Réinitialisation', email.subject)
        self.assertIn('Bonjour Julie', email.body)
        # Lien absolu bâti sur SITE_URL (jamais sur l'en-tête Host), identique en texte et en HTML
        link = re.search(rf'{re.escape(SITE)}(/accounts/password-reset/[^/\s]+/[^/\s]+/)', email.body).group(1)
        self.assertIn(f'{SITE}{link}', email.alternatives[0][0])
        self.assertIn(f'src="{SITE}/static/images/logo/app-tile-512.png"', email.alternatives[0][0])

        # Le lien ouvre le formulaire, le nouveau mot de passe est accepté, l'ancien ne marche plus
        form_url = self.http.get(link, follow=True).redirect_chain[-1][0]
        response = self.http.post(form_url, {'new_password1': 'Nouveau-Mot-2026', 'new_password2': 'Nouveau-Mot-2026'})
        self.assertRedirects(response, reverse('accounts:password-reset-complete'), fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertTrue(user.check_password('Nouveau-Mot-2026'))
        # Lien à usage unique
        self.assertNotIn('new_password1', self.http.get(link, follow=True).content.decode())

    def test_unknown_email_gives_same_page_and_sends_nothing(self):
        response = self.http.post(reverse('accounts:password-reset'), {'email': 'inconnu@nulle-part.fr'})
        self.assertRedirects(response, reverse('accounts:password-reset-done'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)
