"""
Adaptation par métier : inscription avec métier, packs (phases, modèles, mentions),
modèles de projet, duplication complète.

    python manage.py test apps.dashboard
"""
from datetime import date, timedelta

from django.test import Client as HttpClient, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.dashboard.models import Milestone, Project, ProjectPhase, ProjectTemplate
from apps.organizations.models import Organization, OrganizationMember
from apps.organizations.trade_packs import TRADE_PACKS, apply_trade_pack


class RegistrationTests(TestCase):
    def test_signup_asks_trade_and_prepares_organization(self):
        http = HttpClient(HTTP_HOST='127.0.0.1')
        response = http.post(reverse('accounts:register'), {
            'name': 'Inès Martin', 'email': 'ines@atelier.test', 'password': 'Tr3s-Solide-2026', 'trade': 'btp',
        })
        self.assertEqual(response.status_code, 302, response.content[:500])
        user = User.objects.get(email='ines@atelier.test')
        org = Organization.objects.get(owner=user)
        self.assertEqual((org.name, org.trade), ('Inès Martin', 'btp'))  # nom modifiable ensuite dans Paramètres
        self.assertTrue(OrganizationMember.objects.get(organization=org, user=user).can_manage_members)
        labels = list(ProjectPhase.objects.filter(organization=org).values_list('label', flat=True))
        self.assertEqual(labels[0], 'Visite & métré')
        self.assertEqual(labels[-1], 'Terminé')
        self.assertTrue(ProjectTemplate.objects.filter(organization=org, name='Rénovation de salle de bain').exists())
        self.assertIn('décennale', org.billing_texts()['legal_mentions'])

    def test_signup_without_trade_is_refused(self):
        http = HttpClient(HTTP_HOST='127.0.0.1')
        http.post(reverse('accounts:register'), {'name': 'A B', 'email': 'nobody@test.fr', 'password': 'Tr3s-Solide-2026'})
        self.assertFalse(User.objects.filter(email='nobody@test.fr').exists())


class PackAndTemplateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='studio', email='studio@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio', owner=self.user)
        OrganizationMember.objects.create(organization=self.org, user=self.user, role='owner')
        self.client_obj = Client.objects.create(organization=self.org, name='Nova', email='nova@test.fr')
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def test_every_pack_is_consistent(self):
        for key, pack in TRADE_PACKS.items():
            phase_keys = [k for k, *_ in pack['phases']]
            self.assertEqual(phase_keys[-1], 'completed', key)
            self.assertEqual(len(phase_keys), len(set(phase_keys)), key)
            for template in pack['templates']:
                for milestone in template['milestones']:
                    self.assertIn(milestone['phase'], phase_keys, f"{key} / {template['name']}")

    def test_reapplying_pack_keeps_phases_in_use(self):
        ProjectPhase.for_organization(self.org)  # phases par défaut (agence web)
        Project.objects.create(organization=self.org, client=self.client_obj, name='En cours', status='design')
        apply_trade_pack(self.org, 'audiovisuel')
        keys = list(ProjectPhase.objects.filter(organization=self.org).values_list('key', flat=True))
        self.assertIn('design', keys)  # porte un projet : conservée
        self.assertNotIn('development', keys)  # inutilisée : remplacée
        self.assertEqual(keys[-1], 'completed')
        self.assertEqual(keys[-2], 'design')  # rangée juste avant « Terminé »

    def test_project_from_template_creates_dated_structure(self):
        apply_trade_pack(self.org, 'audiovisuel')
        template = ProjectTemplate.objects.get(organization=self.org, name='Clip / film promotionnel')
        start = date(2026, 11, 2)
        self.http.post(reverse('dashboard:project-create'), {
            'client_id': self.client_obj.id, 'name': 'Clip Néons', 'start_date': start.isoformat(), 'template_id': template.id,
        })
        project = Project.objects.get(name='Clip Néons')
        milestones = list(project.milestones.order_by('order'))
        self.assertEqual(len(milestones), 6)
        self.assertEqual(milestones[0].title, 'Brief validé & acompte')
        self.assertEqual(milestones[-1].due_date, start + timedelta(days=30))
        self.assertEqual(project.tasks.count(), sum(len(m['tasks']) for m in template.data['milestones']))
        self.assertGreater(project.deliverables.count(), 0)
        self.assertFalse(project.milestones.filter(title='Spécifications client').exists())

    def test_duplicate_copies_structure_and_shifts_dates(self):
        original = Project.objects.create(organization=self.org, client=self.client_obj, name='Source',
                                          start_date=date(2026, 1, 1), delivery_date=date(2026, 1, 31))
        milestone = Milestone.objects.create(project=original, title='Jalon A', phase='onboarding',
                                             due_date=date(2026, 1, 11), is_completed=True)
        original.tasks.create(title='Tâche A', milestone=milestone, status='done', due_date=date(2026, 1, 5))
        original.deliverables.create(title='Livrable A', milestone=milestone, status='approved')
        response = self.http.post(reverse('dashboard:project-duplicate', args=[original.id]))
        copy = Project.objects.get(id=response.json()['id'])
        today = timezone.localdate()
        self.assertEqual(copy.start_date, today)
        self.assertEqual(copy.delivery_date, today + timedelta(days=30))
        m = copy.milestones.get()
        self.assertEqual((m.title, m.due_date, m.is_completed), ('Jalon A', today + timedelta(days=10), False))
        self.assertEqual(copy.tasks.get().status, 'todo')
        self.assertEqual(copy.deliverables.get().status, 'in_progress')

    def test_save_as_template(self):
        project = Project.objects.create(organization=self.org, client=self.client_obj, name='Mariage Dupont', start_date=date(2026, 6, 1))
        Milestone.objects.create(project=project, title='Jour J', phase='onboarding', due_date=date(2026, 6, 20))
        response = self.http.post(reverse('dashboard:project-save-as-template', args=[project.id]), {'name': 'Mariage'})
        self.assertTrue(response.json()['success'])
        template = ProjectTemplate.objects.get(organization=self.org, name='Mariage')
        self.assertEqual(template.data['milestones'][0]['due'], 19)
