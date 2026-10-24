"""« Se connecter avec… » : redirection vers l'outil, retour signé, configuration enregistrée."""
import os
import urllib.parse
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.integrations import oauth
from apps.integrations.models import ConnectionInstance, Connector
from apps.organizations.models import Organization
from apps.subscriptions.testing import give_plan

ENV = {'SLACK_CLIENT_ID': 'cid', 'SLACK_CLIENT_SECRET': 'sec', 'TRELLO_API_KEY': 'k' * 32}


@mock.patch.dict(os.environ, ENV)
class OAuthTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='o', email='o@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio', owner=self.user)
        give_plan(self.user, 'business')
        for key, name in (('slack', 'Slack'), ('trello', 'Trello'), ('notion', 'Notion')):
            Connector.objects.get_or_create(key=key, defaults={'name': name, 'category': 'communication'})
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def _start(self, key):
        response = self.http.get(reverse('integrations:oauth-connect', args=[key]))
        self.assertEqual(response.status_code, 302)
        return urllib.parse.urlparse(response['Location'])

    def test_slack_round_trip_stores_webhook(self):
        url = self._start('slack')
        self.assertEqual(url.hostname, 'slack.com')
        state = urllib.parse.parse_qs(url.query)['state'][0]
        reply = {'ok': True, 'team': {'name': 'Lumen'}, 'incoming_webhook': {'url': 'https://hooks.slack.com/services/T/B/X', 'channel': '#ventes'}}
        with mock.patch('apps.integrations.oauth.http', return_value=reply):
            self.http.get(reverse('integrations:oauth-callback', args=['slack']), {'code': 'abc', 'state': state})
        instance = ConnectionInstance.objects.get(organization=self.org, connector__key='slack')
        self.assertEqual(instance.status, 'connected')
        self.assertEqual(instance.config['webhook_url'], 'https://hooks.slack.com/services/T/B/X')

    def test_forged_or_replayed_state_is_refused(self):
        url = self._start('slack')
        state = urllib.parse.parse_qs(url.query)['state'][0]
        reply = {'ok': True, 'incoming_webhook': {'url': 'https://hooks.slack.com/services/T/B/X'}}
        with mock.patch('apps.integrations.oauth.http', return_value=reply) as http:
            self.http.get(reverse('integrations:oauth-callback', args=['slack']), {'code': 'abc', 'state': 'forged'})
            self.http.get(reverse('integrations:oauth-callback', args=['slack']), {'code': 'abc', 'state': state})
            self.http.get(reverse('integrations:oauth-callback', args=['slack']), {'code': 'abc', 'state': state})  # rejoué
        self.assertEqual(http.call_count, 1)

    def test_unconfigured_tool_falls_back_to_form(self):
        response = self.http.get(reverse('integrations:oauth-connect', args=['notion']))
        self.assertIn('?plugin=notion', response['Location'])
        self.assertFalse(oauth.configured('notion'))

    def test_trello_token_flow(self):
        url = self._start('trello')
        self.assertEqual(url.hostname, 'trello.com')
        return_url = urllib.parse.parse_qs(url.query)['return_url'][0]
        state = urllib.parse.parse_qs(urllib.parse.urlparse(return_url).query)['state'][0]
        self.http.post(reverse('integrations:oauth-trello-finish'), {'state': state, 'token': 'abc123'})
        config = ConnectionInstance.objects.get(organization=self.org, connector__key='trello').config
        self.assertEqual((config['api_key'], config['token']), ('k' * 32, 'abc123'))

    def test_page_exposes_one_click_only_when_ready(self):
        page = self.http.get(reverse('integrations:integrations-page')).content.decode()
        self.assertIn('"slack": {"name": "Slack", "ready": true', page)
        self.assertIn('"notion": {"name": "Notion", "ready": false', page)

    def test_authorize_page_explains_then_shows_result(self):
        page = self.http.get(reverse('integrations:oauth-authorize', args=['slack'])).content.decode()
        self.assertIn('Autoriser Billio à utiliser Slack', page)
        self.assertIn(reverse('integrations:oauth-connect', args=['slack']), page)
        # Retour de Slack : on revient sur la page, qui affiche le résultat.
        state = urllib.parse.parse_qs(self._start('slack').query)['state'][0]
        reply = {'ok': True, 'team': {'name': 'Lumen'}, 'incoming_webhook': {'url': 'https://hooks.slack.com/services/T/B/X', 'channel': '#ventes'}}
        with mock.patch('apps.integrations.oauth.http', return_value=reply):
            response = self.http.get(reverse('integrations:oauth-callback', args=['slack']), {'code': 'abc', 'state': state}, follow=True)
        self.assertContains(response, 'Slack est connecté à Billio')
        self.assertContains(response, 'Lumen · #ventes')
        cancelled = self.http.get(reverse('integrations:oauth-callback', args=['slack']), {'error': 'access_denied'}, follow=True)
        self.assertContains(cancelled, 'Connexion annulée')

    def test_authorize_page_falls_back_to_form_when_not_ready(self):
        response = self.http.get(reverse('integrations:oauth-authorize', args=['notion']))
        self.assertIn('?plugin=notion', response['Location'])
