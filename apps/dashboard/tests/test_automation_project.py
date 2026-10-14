"""Action « Créer un projet » : depuis un modèle de projet, pour le client de l'événement ou un client fixé."""
from django.test import TestCase

from apps.accounts.models import User
from apps.clients.models import Client
from apps.dashboard.automation_engine import run_automations
from apps.dashboard.automation_graph import validate_graph
from apps.dashboard.models import AutomationRule, AutomationRun, Project, ProjectProcess, ProjectTemplate
from apps.organizations.models import Organization
from apps.organizations.trade_packs import apply_trade_pack

TRIGGERS = {k for k, _ in AutomationRule.TRIGGER_CHOICES}
ACTIONS = {k for k, _ in AutomationRule.ACTION_CHOICES}


class AutomationProjectTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='o', email='o@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Plomberie Martin', owner=self.user)
        apply_trade_pack(self.org, 'btp')
        self.client_obj = Client.objects.create(organization=self.org, name='Mme Durand', email='durand@test.fr')
        self.template = ProjectTemplate.objects.get(organization=self.org, name='Rénovation de salle de bain')

    def rule(self, params):
        raw = {'nodes': [{'id': 't', 'type': 'trigger', 'key': 'client_created', 'params': {}},
                         {'id': 'a', 'type': 'action', 'key': 'create_project', 'params': params}],
               'edges': [{'from': 't', 'port': 'out', 'to': 'a'}]}
        graph = validate_graph(raw, organization=self.org, valid_triggers=TRIGGERS, valid_actions=ACTIONS)
        return AutomationRule.objects.create(organization=self.org, trigger_key='client_created', action_key='create_project', graph=graph)

    def fire(self, client):
        run_automations(self.org, 'client_created', target_type='client', target_id=client.id, client_id=client.id)

    def test_project_from_template_for_event_client(self):
        rule = self.rule({'template_id': str(self.template.id), 'client': 'event'})
        self.fire(self.client_obj)
        run = AutomationRun.objects.get(rule=rule)
        self.assertTrue(run.success, run.log)
        project = Project.objects.get(client=self.client_obj)
        self.assertEqual(project.name, 'Rénovation de salle de bain — Mme Durand')
        self.assertEqual(project.milestones.count(), 6)
        self.assertEqual(project.process, ProjectProcess.default_for(self.org))   # Chantier
        self.assertIsNotNone(project.start_date)

    def test_fixed_client_and_process_and_foreign_ids_ignored(self):
        other = Client.objects.create(organization=self.org, name='Boulangerie', email='b@test.fr')
        depannage = ProjectProcess.objects.get(organization=self.org, name='Dépannage')
        foreign_org = Organization.objects.create(name='X', owner=User.objects.create_user(username='x', email='x@t.fr', password='x-Test-1234'))
        foreign_client = Client.objects.create(organization=foreign_org, name='Intrus', email='i@t.fr')
        rule = self.rule({'value': 'Fuite {{client}}', 'client': str(other.id), 'process_id': str(depannage.id)})
        self.assertEqual(rule.get_graph()['nodes'][1]['params']['client'], str(other.id))
        self.fire(self.client_obj)
        project = Project.objects.get(client=other)
        self.assertEqual((project.process_id, project.status), (depannage.id, 'call'))
        bad = self.rule({'client': str(foreign_client.id), 'template_id': '999999'})
        params = bad.get_graph()['nodes'][1]['params']
        self.assertEqual((params['client'], params['template_id']), ('event', ''))   # identifiants étrangers écartés


class ConditionReferencesTests(TestCase):
    def test_builder_suggests_real_clients_and_projects(self):
        import json
        from django.test import Client as HttpClient
        from django.urls import reverse
        user = User.objects.create_user(username='r', email='r@test.fr', password='x-Test-1234')
        org = Organization.objects.create(name='Studio', owner=user, city='Paris')
        client = Client.objects.create(organization=org, name='Atelier Néon', email='hello@neon.fr', city='Lyon')
        Project.objects.create(organization=org, client=client, name='Clip Néons', status='onboarding')
        other_org = Organization.objects.create(name='Autre', owner=User.objects.create_user(username='z', email='z@t.fr', password='x-Test-1234'))
        Client.objects.create(organization=other_org, name='Concurrent secret', email='c@t.fr')
        http = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr')
        http.force_login(user)
        page = http.get(reverse('dashboard:automation-builder')).content.decode()
        start = page.index('id="wf-config"')
        config = json.loads(page[page.index('>', start) + 1:page.index('</script>', start)])
        refs = config['conditionRefs']
        self.assertEqual(refs['client_name'], ['Atelier Néon'])
        self.assertEqual(refs['client_city'], ['Lyon'])
        self.assertEqual(refs['projet'], ['Clip Néons'])
        self.assertNotIn('Concurrent secret', json.dumps(refs))


class WebhookClientToProjectTests(TestCase):
    def test_webhook_creates_client_and_project_with_received_data(self):
        import json
        from django.test import Client as HttpClient
        from django.urls import reverse
        from apps.subscriptions.testing import give_plan
        user = User.objects.create_user(username='w', email='w@test.fr', password='x-Test-1234')
        org = Organization.objects.create(name='Studio', owner=user)
        give_plan(user, 'business')
        raw = {'nodes': [{'id': 't', 'type': 'trigger', 'key': 'webhook_received', 'params': {'create_client': True}},
                         {'id': 'a', 'type': 'action', 'key': 'create_project', 'params': {
                             'value': 'Site {{societe_client}}', 'description': '{{donnees_recues}}', 'delivery': '{{date_souhaitee}}'}}],
               'edges': [{'from': 't', 'port': 'out', 'to': 'a'}]}
        graph = validate_graph(raw, organization=org, valid_triggers=TRIGGERS, valid_actions=ACTIONS)
        AutomationRule.objects.create(organization=org, trigger_key='webhook_received', action_key='create_project', graph=graph)
        token = graph['nodes'][0]['params']['token']
        payload = {'email': 'lea@neon.fr', 'name': 'Léa Martin', 'company': 'Néon SAS', 'city': 'Lyon',
                   'zip': '69001', 'budget': '5000', 'date_souhaitee': '30/11/2026', 'message': 'Refonte du site'}
        response = HttpClient().post(reverse('dashboard:automation-webhook', args=[token]), json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 202)
        client = Client.objects.get(organization=org, email='lea@neon.fr')
        self.assertEqual((client.company_name, client.city, client.postal_code), ('Néon SAS', 'Lyon', '69001'))
        project = Project.objects.get(client=client)
        self.assertEqual(project.name, 'Site Néon SAS')
        self.assertIn('Message : Refonte du site', project.description)
        self.assertIn('Budget : 5000', project.description)
        self.assertEqual(str(project.delivery_date), '2026-11-30')


class WorkflowStatusNotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='n', email='n@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio', owner=self.user)
        self.client_obj = Client.objects.create(organization=self.org, name='Mme Durand', email='d@test.fr')

    def rule(self, notify_on, client='event'):
        raw = {'nodes': [{'id': 't', 'type': 'trigger', 'key': 'client_created', 'params': {}},
                         {'id': 'a', 'type': 'action', 'key': 'create_project', 'params': {'value': 'P', 'client': client}}],
               'edges': [{'from': 't', 'port': 'out', 'to': 'a'}]}
        graph = validate_graph(raw, organization=self.org, valid_triggers=TRIGGERS, valid_actions=ACTIONS)
        return AutomationRule.objects.create(organization=self.org, name='Onboarding', trigger_key='client_created',
                                             action_key='create_project', graph=graph, notify_on=notify_on)

    def notes(self):
        from apps.dashboard.models import Notification
        return Notification.objects.filter(user=self.user, notification_type='workflow_status')

    def test_success_notified_only_when_always(self):
        self.rule('failure')
        run_automations(self.org, 'client_created', target_type='client', target_id=self.client_obj.id, client_id=self.client_obj.id)
        self.assertEqual(self.notes().count(), 0)
        AutomationRule.objects.update(notify_on='always')
        other = Client.objects.create(organization=self.org, name='B', email='b@test.fr')
        run_automations(self.org, 'client_created', target_type='client', target_id=other.id, client_id=other.id)
        note = self.notes().get()
        self.assertIn('exécuté', note.title)
        self.assertIn('Projet', note.message)

    def test_failure_notified_by_default(self):
        self.rule('failure')
        # Aucun client rattaché : « Créer un projet » échoue.
        run_automations(self.org, 'client_created', target_type='webhook', target_id='sans-client', client_id=None)
        note = self.notes().get()
        self.assertIn('en échec', note.title)
        self.assertEqual(note.priority, 'high')
