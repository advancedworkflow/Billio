"""Kanban jalons : carte compacte façon Trello et fenêtre de détail (étiquettes, membres, checklist, commentaires)."""
import json
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as HttpClient, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.dashboard.models import Milestone, MilestoneComment, MilestoneFile, Project, Task
from apps.organizations.models import Organization, OrganizationMember


class MilestoneCardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='julie', email='julie@lumen.test', password='x-Test-1234', first_name='Julie')
        self.org = Organization.objects.create(name='Studio Lumen', owner=self.user)
        self.mate = User.objects.create_user(username='paul', email='paul@lumen.test', password='x-Test-1234', first_name='Paul')
        OrganizationMember.objects.create(organization=self.org, user=self.mate, role='member')
        client = Client.objects.create(organization=self.org, name='Atelier Rive', email='r@rive.fr')
        self.project = Project.objects.create(organization=self.org, client=client, name='Refonte du site')
        self.milestone = Milestone.objects.create(project=self.project, title='Maquettes', phase='discovery',
                                                  due_date=timezone.localdate() - timedelta(days=1))
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def update(self, **data):
        return self.http.post(reverse('dashboard:milestone-card-update', args=[self.milestone.id]),
                              json.dumps(data), content_type='application/json')

    def detail(self):
        return self.http.get(reverse('dashboard:milestone-detail', args=[self.milestone.id])).json()

    def test_partial_update_of_card_fields(self):
        self.update(description='Trois pistes graphiques', labels=[{'text': 'Urgent', 'color': 'red'},
                    {'text': 'x', 'color': 'fluo'}], cover='blue', member_ids=[self.mate.id, 999999])
        self.milestone.refresh_from_db()
        self.assertEqual(self.milestone.title, 'Maquettes')  # non envoyé : inchangé
        self.assertEqual(self.milestone.description, 'Trois pistes graphiques')
        self.assertEqual(self.milestone.labels, [{'text': 'Urgent', 'color': 'red'}])  # couleur inconnue refusée
        self.assertEqual(self.milestone.cover, 'blue')
        self.assertEqual(list(self.milestone.members.all()), [self.mate])  # seuls les membres de l'organisation
        self.update(is_completed=True)
        self.milestone.refresh_from_db()
        self.assertTrue(self.milestone.is_completed)
        self.assertIsNotNone(self.milestone.completed_at)

    def test_detail_returns_checklist_files_and_comments(self):
        Task.objects.create(project=self.project, milestone=self.milestone, title='Moodboard', status='done')
        Task.objects.create(project=self.project, milestone=self.milestone, title='Piste A')
        MilestoneFile.objects.create(milestone=self.milestone, name='brief.pdf',
                                     file=SimpleUploadedFile('brief.pdf', b'%PDF', 'application/pdf'))
        self.http.post(reverse('dashboard:milestone-comment-add', args=[self.milestone.id]), {'body': 'Le client préfère la piste A'})
        data = self.detail()
        self.assertEqual([t['title'] for t in data['tasks']], ['Moodboard', 'Piste A'])
        self.assertEqual([t['done'] for t in data['tasks']], [True, False])
        self.assertEqual(data['files'][0]['name'], 'brief.pdf')
        self.assertEqual(data['comments'][0]['body'], 'Le client préfère la piste A')
        self.assertTrue(data['comments'][0]['own'])
        self.assertEqual({m['id'] for m in data['org_members']}, {self.user.id, self.mate.id})

    def test_only_the_author_deletes_a_comment(self):
        comment = MilestoneComment.objects.create(milestone=self.milestone, author=self.mate, body='Vu')
        response = self.http.post(reverse('dashboard:milestone-comment-delete', args=[comment.id]))
        self.assertEqual(response.status_code, 404)
        own = MilestoneComment.objects.create(milestone=self.milestone, author=self.user, body='OK')
        self.http.post(reverse('dashboard:milestone-comment-delete', args=[own.id]))
        self.assertFalse(MilestoneComment.objects.filter(id=own.id).exists())

    def test_board_shows_compact_card_badges(self):
        self.update(labels=[{'text': 'Urgent', 'color': 'red'}], member_ids=[self.mate.id])
        Task.objects.create(project=self.project, milestone=self.milestone, title='Moodboard', status='done')
        MilestoneComment.objects.create(milestone=self.milestone, author=self.user, body='Vu')
        page = self.http.get(reverse('dashboard:milestones-board') + f'?project_id={self.project.id}')
        self.assertContains(page, 'Urgent')
        self.assertContains(page, 'mcard-due is-late')  # échéance passée
        self.assertContains(page, '1/1')
        self.assertContains(page, 'openCard(')

    def test_other_accounts_cannot_open_the_card(self):
        intruder = User.objects.create_user(username='marc', email='marc@other.test', password='x-Test-1234')
        Organization.objects.create(name='Autre', owner=intruder)
        other = HttpClient(HTTP_HOST='127.0.0.1')
        other.force_login(intruder)
        self.assertEqual(other.get(reverse('dashboard:milestone-detail', args=[self.milestone.id])).status_code, 404)
        response = other.post(reverse('dashboard:milestone-card-update', args=[self.milestone.id]),
                              json.dumps({'title': 'Piraté'}), content_type='application/json')
        self.assertEqual(response.status_code, 404)
