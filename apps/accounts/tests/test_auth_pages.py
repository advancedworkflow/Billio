"""Connexion / inscription : message d'erreur unique, redirection ?next= limitée à Billio, pages légales."""
from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.accounts.models import User


class LoginTests(TestCase):
    def setUp(self):
        User.objects.create_user(username='camille', email='camille@test.fr', password='Bon-Mot-2026')
        self.http = HttpClient(HTTP_HOST='127.0.0.1')

    def login(self, email, password, next_url=None):
        url = reverse('accounts:login') + (f'?next={next_url}' if next_url else '')
        return self.http.post(url, {'email': email, 'password': password})

    def test_same_error_for_unknown_email_and_wrong_password(self):
        unknown = self.login('personne@test.fr', 'x').content.decode()
        wrong = self.login('camille@test.fr', 'mauvais').content.decode()
        for html in (unknown, wrong):
            self.assertIn('Email ou mot de passe incorrect.', html)
            self.assertNotIn('Aucun compte', html)

    def test_next_is_followed_only_inside_billio(self):
        self.assertRedirects(self.login('camille@test.fr', 'Bon-Mot-2026', '/clients/list/'), '/clients/list/', fetch_redirect_response=False)
        self.http.logout()
        response = self.login('camille@test.fr', 'Bon-Mot-2026', 'https://evil.example/')
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('evil.example', response['Location'])

    def test_inactive_user_cannot_log_in(self):
        User.objects.filter(email='camille@test.fr').update(is_active=False)
        self.assertEqual(self.login('camille@test.fr', 'Bon-Mot-2026').status_code, 200)


class LegalPagesTests(TestCase):
    def test_legal_pages_and_links(self):
        http = HttpClient(HTTP_HOST='127.0.0.1')
        for name, title in (('landing:legal-notice', 'Mentions légales'), ('landing:terms', "Conditions générales d"),
                            ('landing:privacy', 'Politique de confidentialité')):
            self.assertContains(http.get(reverse(name)), title)
        register = http.get(reverse('accounts:register') + '?email=julie@test.fr').content.decode()
        self.assertIn(reverse('landing:terms'), register)
        self.assertIn('value="julie@test.fr"', register)
        home = http.get(reverse('landing:home')).content.decode()
        self.assertIn(reverse('landing:privacy'), home)
        self.assertNotIn('href="#">CGU', home)
