"""Automatisations branchées sur les outils connectés : action « Envoyer vers une app » et webhook entrant."""
import json
from unittest import mock

from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.clients.models import Client
from apps.dashboard.automation_graph import GraphError, validate_graph
from apps.dashboard.automation_webhooks import flatten
from apps.dashboard.models import AutomationRule, AutomationRun
from apps.integrations.app_actions import APP_ACTIONS
from apps.integrations.models import ConnectionInstance, Connector
from apps.organizations.models import Organization
from apps.subscriptions.testing import give_plan

TRIGGERS = {k for k, _ in AutomationRule.TRIGGER_CHOICES}
ACTIONS = {k for k, _ in AutomationRule.ACTION_CHOICES}


def graph(trigger_key, action_params, trigger_params=None):
    return {
        'nodes': [
            {'id': 't', 'type': 'trigger', 'key': trigger_key, 'params': trigger_params or {}},
            {'id': 'a', 'type': 'action', 'key': 'app_action', 'params': action_params},
        ],
        'edges': [{'from': 't', 'port': 'out', 'to': 'a'}],
    }


class AutomationAppsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='owner', email='owner@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Atelier Lumen', owner=self.user, email='contact@lumen.test')
        give_plan(self.user, 'business')  # webhooks entrants : forfait Business
        self.client_obj = Client.objects.create(organization=self.org, name='Dupont SARL', email='marie@dupont.fr',
                                                contact_person='Marie Dupont')
        trello = Connector.objects.get_or_create(key='trello', defaults={'name': 'Trello', 'category': 'productivity'})[0]
        ConnectionInstance.objects.create(organization=self.org, connector=trello, status='connected',
                                          config={'api_key': 'a' * 32, 'token': 'tok'})
        self.http = HttpClient(HTTP_HOST='127.0.0.1')

    def validate(self, raw):
        return validate_graph(raw, organization=self.org, valid_triggers=TRIGGERS, valid_actions=ACTIONS)

    def trello_params(self, **values):
        return {'app': 'trello', 'operation': 'create_card',
                'values': {'list_id': 'b' * 24, 'title': 'Relancer {{client}}', 'body': '{{montant}}', **values}}

    # ------------------------------------------------------------------ validation
    def test_every_operation_declares_valid_fields(self):
        for app, operations in APP_ACTIONS.items():
            for operation in operations:
                self.assertTrue(callable(operation['run']), (app, operation['key']))
                for field in operation['fields']:
                    self.assertIn(field['kind'], ('text', 'textarea', 'select', 'id'), (app, field['name']))

    def test_graph_rejects_bad_identifier_and_missing_required(self):
        with self.assertRaises(GraphError):
            self.validate(graph('client_created', self.trello_params(list_id='pas-un-id')))
        with self.assertRaises(GraphError):
            self.validate(graph('client_created', self.trello_params(list_id='')))
        with self.assertRaises(GraphError):
            self.validate(graph('client_created', {'app': 'trello', 'operation': 'inconnue'}))

    def test_webhook_trigger_gets_a_secret_token(self):
        cleaned = self.validate(graph('webhook_received', self.trello_params()))
        token = cleaned['nodes'][0]['params']['token']
        self.assertGreaterEqual(len(token), 32)
        # Le jeton est conservé aux enregistrements suivants.
        again = self.validate(cleaned)
        self.assertEqual(again['nodes'][0]['params']['token'], token)

    # ------------------------------------------------------------------ exécution
    @mock.patch('apps.integrations.providers.http')
    def test_app_action_calls_the_tool_with_rendered_values(self, http):
        http.return_value = {'shortUrl': 'https://trello.com/c/abc'}
        rule = AutomationRule.objects.create(organization=self.org, trigger_key='client_created', action_key='app_action',
                                             graph=self.validate(graph('client_created', self.trello_params())))
        from apps.dashboard.automation_engine import run_automations
        run_automations(self.org, 'client_created', target_type='client', target_id=self.client_obj.id,
                        client_id=self.client_obj.id, amount='120.5')
        run = AutomationRun.objects.get(rule=rule)
        self.assertTrue(run.success, run.log)
        method, url = http.call_args[0]
        self.assertEqual(method, 'POST')
        self.assertIn('api.trello.com/1/cards', url)
        self.assertIn('Relancer+Dupont+SARL', url)
        self.assertIn('120%2C50', url)  # {{montant}} = « 120,50 € »

    def test_app_action_fails_cleanly_when_tool_not_connected(self):
        ConnectionInstance.objects.filter(organization=self.org).update(status='not_connected')
        rule = AutomationRule.objects.create(organization=self.org, trigger_key='client_created', action_key='app_action',
                                             graph=self.validate(graph('client_created', self.trello_params())))
        from apps.dashboard.automation_engine import run_automations
        run_automations(self.org, 'client_created', target_type='client', target_id=self.client_obj.id, client_id=self.client_obj.id)
        run = AutomationRun.objects.get(rule=rule)
        self.assertFalse(run.success)
        self.assertIn("n'est pas connecté", run.log[-1]['detail'])

    # ------------------------------------------------------------------ webhook entrant
    def test_flatten_nested_payload(self):
        flat = flatten({'customer': {'email': 'a@b.fr', 'tags': ['vip', 'pro']}, 'items': [{'name': 'Pose'}], 'total': 99})
        self.assertEqual(flat, {'customer_email': 'a@b.fr', 'customer_tags': 'vip, pro', 'items_0_name': 'Pose', 'total': '99'})

    @mock.patch('apps.integrations.providers.http')
    def test_incoming_webhook_runs_workflow_once(self, http):
        http.return_value = {}
        cleaned = self.validate(graph('webhook_received', self.trello_params(title='Lead {{customer_email}}'), {'create_client': True}))
        rule = AutomationRule.objects.create(organization=self.org, trigger_key='webhook_received', action_key='app_action', graph=cleaned)
        url = reverse('dashboard:automation-webhook', args=[cleaned['nodes'][0]['params']['token']])
        body = json.dumps({'id': 'evt_1', 'customer': {'email': 'new@prospect.fr', 'name': 'Paul Prospect'}, 'amount': '250'})

        response = self.http.post(url, body, content_type='application/json')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['workflows'], 1)
        self.assertTrue(Client.objects.filter(organization=self.org, email='new@prospect.fr', name='Paul Prospect').exists())
        self.assertIn('Lead+new%40prospect.fr', http.call_args[0][1])

        self.http.post(url, body, content_type='application/json')  # même id : pas de second déclenchement
        self.assertEqual(AutomationRun.objects.filter(rule=rule).count(), 1)
        self.assertEqual(http.call_count, 1)

    def test_incoming_webhook_unknown_token_or_inactive(self):
        response = self.http.post(reverse('dashboard:automation-webhook', args=['x' * 40]), '{}', content_type='application/json')
        self.assertEqual(response.status_code, 404)
        cleaned = self.validate(graph('webhook_received', self.trello_params()))
        AutomationRule.objects.create(organization=self.org, trigger_key='webhook_received', action_key='app_action',
                                      graph=cleaned, is_active=False)
        url = reverse('dashboard:automation-webhook', args=[cleaned['nodes'][0]['params']['token']])
        self.assertEqual(self.http.post(url, '{}', content_type='application/json').status_code, 404)
        self.assertEqual(self.http.get(url).status_code, 405)
