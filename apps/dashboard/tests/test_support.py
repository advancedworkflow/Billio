import shutil
import tempfile

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as HttpClient, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.dashboard.models import Notification, SupportMessage, SupportTicket
from apps.organizations.models import Organization

MEDIA = tempfile.mkdtemp(prefix='billio-test-support-')


@override_settings(MEDIA_ROOT=MEDIA, SUPPORT_EMAIL='support@billio.test')
class SupportTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(username='u', email='u@test.fr', password='x-Test-1234')
        Organization.objects.create(name='Studio', owner=self.user)
        self.staff = User.objects.create_user(username='s', email='s@billio.test', password='x-Test-1234', is_staff=True)
        self.other = User.objects.create_user(username='o', email='o@test.fr', password='x-Test-1234')
        self.http = self.login(self.user)

    def login(self, user):
        http = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr')
        http.force_login(user)
        return http

    def open_ticket(self, **extra):
        data = {'subject': 'Facture bloquée', 'body': "Je n'arrive pas à envoyer la facture FAC-12.", 'category': 'bug'}
        data.update(extra)
        return self.http.post(reverse('dashboard:support'), data)

    def test_open_ticket_notifies_support(self):
        self.open_ticket()
        ticket = SupportTicket.objects.get()
        self.assertEqual((ticket.user, ticket.category, ticket.status), (self.user, 'bug', 'open'))
        self.assertEqual(ticket.organization.name, 'Studio')
        self.assertEqual(mail.outbox[-1].to, ['support@billio.test'])

    def test_staff_reply_notifies_user_and_privacy(self):
        self.open_ticket()
        ticket = SupportTicket.objects.get()
        self.assertEqual(self.login(self.other).get(reverse('dashboard:support-ticket', args=[ticket.id])).status_code, 404)
        self.login(self.staff).post(reverse('dashboard:support-ticket', args=[ticket.id]), {'body': 'Corrigé, réessayez.'})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'answered')
        self.assertTrue(SupportMessage.objects.filter(ticket=ticket, from_staff=True).exists())
        self.assertTrue(Notification.objects.filter(user=self.user, notification_type='support_reply').exists())
        self.assertEqual(mail.outbox[-1].to, ['u@test.fr'])
        # L'utilisateur clôt sa demande, mais ne peut pas choisir « répondu » lui-même
        self.http.post(reverse('dashboard:support-ticket-status', args=[ticket.id]), {'status': 'resolved'})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'resolved')
        self.assertEqual(self.http.post(reverse('dashboard:support-ticket-status', args=[ticket.id]), {'status': 'answered'}).status_code, 404)

    def test_attachment_is_private_and_validated(self):
        self.open_ticket(attachment=SimpleUploadedFile('capture.png', b'\x89PNG fake', content_type='image/png'))
        message = SupportMessage.objects.get()
        self.assertNotIn('capture', message.attachment.name)   # nom aléatoire
        url = reverse('dashboard:support-attachment', args=[message.id])
        self.assertEqual(self.http.get(url).status_code, 200)
        self.assertEqual(self.login(self.other).get(url).status_code, 404)
        self.open_ticket(subject='Script', attachment=SimpleUploadedFile('x.html', b'<script>', content_type='text/html'))
        self.assertFalse(SupportTicket.objects.filter(subject='Script').exists())
