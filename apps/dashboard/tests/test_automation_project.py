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
