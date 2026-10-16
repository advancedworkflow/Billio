"""Double authentification : activation, connexion en deux étapes, codes de secours, API, admin."""
import re
import time

from django.core.cache import cache
from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.accounts import two_factor
from apps.accounts.models import User

PASSWORD = 'Photo-Lumiere-2026'


def current_code(user, offset=1):
    # Pas suivant (toléré à ±30 s) : le code du pas courant a déjà servi à l'activation.
    return two_factor._code(user.totp_secret, int(time.time() // two_factor.STEP) + offset)


class TwoFactorTests(TestCase):
    def setUp(self):
        cache.clear()
        self.http = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr')
        self.user = User.objects.create_user(username='julie', email='julie@moreau-photo.fr', password=PASSWORD)

    def enable(self):
        self.http.force_login(self.user)
        settings_url = reverse('accounts:user-settings')
        self.http.post(settings_url, {'form_action': '2fa_start'})
        page = self.http.get(settings_url + '?tab=securite').content.decode()
        self.assertIn('<svg', page)
        secret = self.http.session[two_factor.SESSION_SETUP]
        wrong = self.http.post(settings_url, {'form_action': '2fa_confirm', 'code': '000000'}, follow=True)
        self.assertContains(wrong, 'Code incorrect')
        code = two_factor._code(secret, int(time.time() // two_factor.STEP))
        page = self.http.post(settings_url, {'form_action': '2fa_confirm', 'code': code}, follow=True).content.decode()
        self.user.refresh_from_db()
        self.assertTrue(self.user.totp_enabled_at)
        self.assertEqual(len(self.user.totp_recovery_codes), 10)
        codes = re.findall(r'<li>([a-z0-9]{4}-[a-z0-9]{4})</li>', page)
        self.assertEqual(len(codes), 10)
        self.http.logout()
        cache.clear()
        return codes

    def login(self, **extra):
        return self.http.post(reverse('accounts:login'), {'email': self.user.email, 'password': PASSWORD, **extra})

    def test_login_requires_code_once_enabled(self):
        self.enable()
        response = self.login(next='/dashboard/invoices/')
        self.assertRedirects(response, reverse('accounts:login-2fa'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.http.session)  # pas encore connecté
        self.assertEqual(self.http.get(reverse('dashboard:dashboard-home')).status_code, 302)

        bad = self.http.post(reverse('accounts:login-2fa'), {'code': '123456'})
        self.assertContains(bad, 'Code incorrect')
        self.user.refresh_from_db()
        code = current_code(self.user)
        response = self.http.post(reverse('accounts:login-2fa'), {'code': code})
        self.assertRedirects(response, '/dashboard/invoices/', fetch_redirect_response=False)
        self.assertEqual(int(self.http.session['_auth_user_id']), self.user.pk)

        # Le même code ne peut pas resservir
        self.http.logout()
        self.login()
        self.assertContains(self.http.post(reverse('accounts:login-2fa'), {'code': code}), 'Code incorrect')

    def test_recovery_code_is_single_use(self):
        codes = self.enable()
        self.login()
        response = self.http.post(reverse('accounts:login-2fa'), {'code': codes[0].upper()})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(len(self.user.totp_recovery_codes), 9)
        self.http.logout()
        self.login()
        self.assertContains(self.http.post(reverse('accounts:login-2fa'), {'code': codes[0]}), 'Code incorrect')

    def test_code_attempts_are_throttled(self):
        self.enable()
        self.login()
        for _ in range(5):
            self.http.post(reverse('accounts:login-2fa'), {'code': '000000'})
        self.user.refresh_from_db()
        response = self.http.post(reverse('accounts:login-2fa'), {'code': current_code(self.user)})
        self.assertContains(response, 'Trop de tentatives')

    def test_verification_page_without_password_step(self):
        self.assertRedirects(self.http.get(reverse('accounts:login-2fa')), reverse('accounts:login'),
                             fetch_redirect_response=False)

    def test_disable_requires_code(self):
        self.enable()
        self.http.force_login(self.user)
        url = reverse('accounts:user-settings')
        self.http.post(url, {'form_action': '2fa_disable', 'code': '000000'})
        self.user.refresh_from_db()
        self.assertTrue(self.user.totp_enabled_at)
        self.http.post(url, {'form_action': '2fa_disable', 'code': current_code(self.user)})
        self.user.refresh_from_db()
        self.assertIsNone(self.user.totp_enabled_at)
        self.assertEqual(self.user.totp_secret, '')
        self.http.logout()
        self.assertRedirects(self.login(), reverse('dashboard:dashboard-home'), fetch_redirect_response=False)

    def test_api_login_requires_otp(self):
        self.enable()
        url = reverse('accounts:api-login')
        response = self.http.post(url, {'email': self.user.email, 'password': PASSWORD})
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.json()['otp_required'])
        self.user.refresh_from_db()
        response = self.http.post(url, {'email': self.user.email, 'password': PASSWORD, 'otp': current_code(self.user)})
        self.assertEqual(response.status_code, 200)
        self.assertIn('token', response.json())

    def test_admin_login_goes_through_billio_login(self):
        response = self.http.get(reverse('admin:login'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(reverse('accounts:login')))
