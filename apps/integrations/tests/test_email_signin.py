"""Connexion email « adresse + mot de passe » : serveur SMTP trouvé par Billio, identifiants vérifiés."""
import json
import smtplib
import socket
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.integrations.models import ConnectionInstance, Connector
from apps.organizations.models import Organization
from apps.subscriptions.testing import give_plan


def fake_smtp(working=(), refuse=()):
    """smtp_connection factice : les hôtes de `working` acceptent, ceux de `refuse` refusent le mot de passe."""
    tried = []

    def factory(config, timeout=None):
        connection = mock.Mock()
        tried.append((config['host'], int(config['port']), config['security']))

        def open_():
            if config['host'] in refuse:
                raise smtplib.SMTPAuthenticationError(535, b'bad credentials')
            if config['host'] not in working:
                raise socket.gaierror('not found')
        connection.open.side_effect = open_
        return connection
    return factory, tried


class EmailSigninTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='o', email='o@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio', owner=self.user)
        give_plan(self.user, 'business')
        Connector.objects.get_or_create(key='email', defaults={'name': 'Email', 'category': 'communication'})
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def _signin(self, **data):
        response = self.http.post(reverse('integrations:email-signin'), json.dumps(data), content_type='application/json')
        return response, response.json()

    def test_page_shows_a_signin_card(self):
        page = self.http.get(reverse('integrations:oauth-authorize', args=['email'])).content.decode()
        self.assertIn('Connectez votre adresse email', page)
        self.assertIn('autocomplete="current-password"', page)

    def test_known_provider_is_configured_from_the_address(self):
        factory, tried = fake_smtp(working={'smtp.orange.fr'})
        with mock.patch('apps.integrations.providers.smtp_connection', side_effect=factory):
            response, data = self._signin(email='julie@orange.fr', password='secret', name='Atelier Lumen')
        self.assertTrue(data['ok'])
        self.assertEqual(tried, [('smtp.orange.fr', 465, 'ssl')])
        config = ConnectionInstance.objects.get(organization=self.org, connector__key='email').config
        self.assertEqual((config['from_email'], config['username'], config['from_name']),
                         ('julie@orange.fr', 'julie@orange.fr', 'Atelier Lumen'))
        follow = self.http.get(data['next']).content.decode()
        self.assertIn('Votre adresse email est connectée', follow)

    def test_gmail_refusal_explains_app_password(self):
        factory, _ = fake_smtp(refuse={'smtp.gmail.com'})
        with mock.patch('apps.integrations.providers.smtp_connection', side_effect=factory):
            response, data = self._signin(email='julie@gmail.com', password='wrong')
        self.assertEqual(response.status_code, 400)
        self.assertIn("mot de passe d'application", data['error'])
        self.assertFalse(ConnectionInstance.objects.filter(organization=self.org, status='connected').exists())

    def test_own_domain_is_probed_then_asks_for_the_host(self):
        factory, tried = fake_smtp(working={'mail.lumen.fr'})
        with mock.patch('apps.integrations.providers.smtp_connection', side_effect=factory):
            _, data = self._signin(email='julie@lumen.fr', password='secret')
        self.assertTrue(data['ok'])
        self.assertEqual(tried[:2], [('smtp.lumen.fr', 587, 'tls'), ('mail.lumen.fr', 587, 'tls')])

        factory, _ = fake_smtp(working={'ssl0.ovh.net'})
        with mock.patch('apps.integrations.providers.smtp_connection', side_effect=factory):
            _, data = self._signin(email='paul@atelier.fr', password='secret')
            self.assertTrue(data['need_server'])
            _, data = self._signin(email='paul@atelier.fr', password='secret',
                                   manual={'host': 'ssl0.ovh.net', 'port': 465, 'security': 'ssl'})
        self.assertTrue(data['ok'])

    def test_manual_port_is_restricted(self):
        _, data = self._signin(email='paul@atelier.fr', password='secret', manual={'host': 'example.com', 'port': 22})
        self.assertIn('Port SMTP non pris en charge', data['error'])
