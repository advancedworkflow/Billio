import json

from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.clients.models import Client
from apps.dashboard.models import Milestone, Project, ProjectPhase, ProjectProcess
from apps.organizations.models import Organization
from apps.organizations.trade_packs import apply_trade_pack


class ProjectProcessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='camille', email='camille@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Plomberie Martin', owner=self.user)
        self.client_obj = Client.objects.create(organization=self.org, name='Mme Durand', email='durand@test.fr')
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)
        apply_trade_pack(self.org, 'btp')

    def keys(self, name):
        return ProjectProcess.objects.get(organization=self.org, name=name).phase_keys

    def test_trade_pack_creates_main_and_suggested_processes(self):
        self.assertEqual(ProjectProcess.default_for(self.org).name, 'Chantier')
        self.assertEqual(self.keys('Dépannage'), ['call', 'diagnosis', 'intervention', 'invoicing', 'completed'])
        self.assertEqual(ProjectPhase.objects.filter(organization=self.org, key='completed').count(), 1)   # étape partagée

    def test_project_follows_its_process(self):
        depannage = ProjectProcess.objects.get(organization=self.org, name='Dépannage')
        self.http.post(reverse('dashboard:project-create'), {'client_id': self.client_obj.id, 'name': 'Fuite', 'process_id': depannage.id})
        project = Project.objects.get(name='Fuite')
        self.assertEqual((project.process_id, project.status), (depannage.id, 'call'))
        page = self.http.get(reverse('dashboard:project-detail', args=[project.id])).content.decode()
        self.assertIn('Diagnostic', page)
        self.assertNotIn('Approvisionnement', page)   # étape du chantier, pas du dépannage
        # Passage à une étape d'un autre processus refusé
        response = self.http.post(reverse('dashboard:project-update-status', args=[project.id]), {'status': 'supply'})
        project.refresh_from_db()
        self.assertEqual(project.status, 'call')

    def test_changing_process_keeps_used_steps_visible(self):
        project = Project.objects.create(organization=self.org, client=self.client_obj, name='Salle de bain', status='worksite')
        Milestone.objects.create(project=project, title='Pose', phase='worksite')
        entretien = ProjectProcess.objects.get(organization=self.org, name='Entretien annuel')
        self.http.post(reverse('dashboard:project-update-process', args=[project.id]), {'process_id': entretien.id})
        project.refresh_from_db()
        self.assertEqual((project.process_id, project.status), (entretien.id, 'scheduling'))
        page = self.http.get(reverse('dashboard:project-detail', args=[project.id])).content.decode()
        self.assertIn('Chantier', page)   # le jalon garde son étape, toujours affichée

    def test_save_rename_and_delete_process(self):
        response = self.http.post(reverse('dashboard:process-save'), json.dumps({
            'name': 'Urgence', 'steps': [{'label': 'Appel'}, {'label': 'Intervention express', 'color': '#ff0000'}, {'key': 'completed', 'label': 'Clôturé', 'color': '#16a34a'}]}),
            content_type='application/json')
        self.assertTrue(response.json()['ok'])
        urgence = ProjectProcess.objects.get(organization=self.org, name='Urgence')
        self.assertEqual(urgence.phase_keys[-1], 'completed')
        self.assertEqual(ProjectPhase.objects.get(organization=self.org, key='completed').label, 'Clôturé')   # renommée partout
        Project.objects.create(organization=self.org, client=self.client_obj, name='P', status=urgence.phase_keys[0], process=urgence)
        self.assertTrue(self.http.post(reverse('dashboard:process-delete', args=[urgence.id])).json()['ok'])
        self.assertEqual(Project.objects.get(name='P').process_id, None)   # repasse au processus par défaut
        default = ProjectProcess.default_for(self.org)
        self.assertEqual(self.http.post(reverse('dashboard:process-delete', args=[default.id])).status_code, 400)

    def test_page_and_suggestion(self):
        page = self.http.get(reverse('dashboard:process-list'))
        self.assertContains(page, 'process-config')
        response = self.http.post(reverse('dashboard:process-add-suggestion'), json.dumps({'name': 'Formation'}), content_type='application/json')
        self.assertTrue(response.json()['ok'])
        self.assertIn('convocation', self.keys('Formation'))

    def test_create_project_with_custom_steps(self):
        steps = [{'key': 'call', 'label': 'Appel urgent', 'color': '#3b82f6'}, {'label': 'Devis express', 'color': '#ff0000'},
                 {'key': 'completed', 'label': 'Terminé', 'color': '#16a34a'}]
        self.http.post(reverse('dashboard:project-create'), {
            'client_id': self.client_obj.id, 'name': 'Urgence', 'custom_steps': json.dumps(steps)})
        project = Project.objects.get(name='Urgence')
        self.assertTrue(project.process.is_private)
        self.assertEqual(len(project.process.phase_keys), 3)
        self.assertNotEqual(project.status, 'call')   # « Appel » renommé : nouvelle étape, l'originale est intacte
        self.assertEqual(ProjectPhase.objects.get(organization=self.org, key='call').label, 'Appel / demande')
        self.assertNotIn(project.process.name, [p.name for p in ProjectProcess.for_organization(self.org)])   # absent des listes
        # Version réutilisable : visible pour les prochains projets
        self.http.post(reverse('dashboard:project-create'), {
            'client_id': self.client_obj.id, 'name': 'Urgence 2', 'custom_steps': json.dumps(steps),
            'save_process': '1', 'process_name': 'Urgence express'})
        reusable = Project.objects.get(name='Urgence 2').process
        self.assertEqual((reusable.name, reusable.is_private), ('Urgence express', False))
        self.assertIn('Urgence express', [p.name for p in ProjectProcess.for_organization(self.org)])
