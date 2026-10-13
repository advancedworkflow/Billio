"""Suivi du temps : durées, chrono, facturation du temps passé."""
from datetime import timedelta
from decimal import Decimal

from django.test import Client as HttpClient, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.dashboard.models import Project, TimeEntry
from apps.dashboard.time_views import parse_duration
from apps.invoices.models import Invoice
from apps.organizations.models import Organization
from apps.subscriptions.testing import give_plan


class TimeTrackingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='conseil', email='conseil@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Conseil', owner=self.user, billing_preferences={'tjm': '700', 'hours_per_day': 7})
        client = Client.objects.create(organization=self.org, name='ACME', email='acme@test.fr')
        self.project = Project.objects.create(organization=self.org, client=client, name='Audit')
        give_plan(self.user, 'pro')  # suivi et facturation du temps : forfait Pro
        self.task = self.project.tasks.create(title='Entretiens')
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.http.force_login(self.user)

    def test_parse_duration(self):
        cases = {'1h30': 90, '1,5': 90, '2': 120, '45 min': 45, '90': 90, '2h': 120, '0h45': 45, '': None, 'abc': None}
        for raw, expected in cases.items():
            self.assertEqual(parse_duration(raw), expected, raw)

    def test_timer_start_stop(self):
        self.http.post(reverse('dashboard:time-timer-start', args=[self.project.id]))
        entry = TimeEntry.objects.get()
        self.assertIsNotNone(entry.started_at)
        self.assertEqual(self.http.post(reverse('dashboard:time-timer-start', args=[self.project.id])).status_code, 400)  # un seul chrono
        TimeEntry.objects.filter(id=entry.id).update(started_at=timezone.now() - timedelta(minutes=50))
        self.http.post(reverse('dashboard:time-timer-stop', args=[entry.id]))
        entry.refresh_from_db()
        self.assertIsNone(entry.started_at)
        self.assertEqual(entry.minutes, 50)

    def test_invoice_billable_time_once(self):
        self.http.post(reverse('dashboard:time-entry-create', args=[self.project.id]), {'duration': '3h', 'task_id': self.task.id, 'description': 'Entretien DG'})
        self.http.post(reverse('dashboard:time-entry-create', args=[self.project.id]), {'duration': '1h30', 'task_id': self.task.id})
        self.http.post(reverse('dashboard:time-entry-create', args=[self.project.id]), {'duration': '2h', 'billable': 'off'})
        response = self.http.post(reverse('dashboard:time-invoice', args=[self.project.id]))
        self.assertTrue(response.json()['success'])
        invoice = Invoice.objects.get(organization=self.org)
        line = invoice.items.get()
        self.assertEqual((line.quantity, line.unit, line.unit_price), (Decimal('4.50'), 'heure', Decimal('100.00')))  # 700 € / 7 h
        self.assertEqual(invoice.subtotal, Decimal('450.00'))
        self.assertEqual(invoice.total_amount, Decimal('540.00'))
        self.assertEqual(invoice.status, 'draft')
        self.assertEqual(self.http.post(reverse('dashboard:time-invoice', args=[self.project.id])).status_code, 400)  # rien à refacturer
        invoiced = TimeEntry.objects.filter(invoice=invoice).first()
        self.assertEqual(self.http.post(reverse('dashboard:time-entry-delete', args=[invoiced.id])).status_code, 400)

    def test_project_rate_overrides_tjm(self):
        self.http.post(reverse('dashboard:time-rate-update', args=[self.project.id]), {'hourly_rate': '85,50'})
        self.http.post(reverse('dashboard:time-entry-create', args=[self.project.id]), {'duration': '2h'})
        self.http.post(reverse('dashboard:time-invoice', args=[self.project.id]))
        self.assertEqual(Invoice.objects.get().items.get().unit_price, Decimal('85.50'))

    def test_timer_status_for_widget(self):
        url = reverse('dashboard:time-timer-status')
        data = self.http.get(url).json()
        self.assertIsNone(data['running'])
        self.assertEqual(data['projects'], [{'id': self.project.id, 'name': 'Audit', 'client': 'ACME'}])
        self.http.post(reverse('dashboard:time-timer-start', args=[self.project.id]), {'description': 'Entretien DG'})
        running = self.http.get(url).json()['running']
        self.assertEqual((running['project'], running['client'], running['description']), ('Audit', 'ACME', 'Entretien DG'))
        self.assertTrue(running['url'].endswith('#temps'))
        # Projets d'une autre organisation : jamais proposés
        other = User.objects.create_user(username='autre', email='autre@test.fr', password='x-Test-1234')
        other_org = Organization.objects.create(name='Autre', owner=other)
        Project.objects.create(organization=other_org, client=Client.objects.create(organization=other_org, name='Z'), name='Secret')
        self.assertNotIn('Secret', [p['name'] for p in self.http.get(url).json()['projects']])

    def test_timer_widget_page(self):
        html = self.http.get(reverse('dashboard:time-widget')).content.decode()
        self.assertIn('data-bt-mount', html)
        self.assertIn('time-widget.js', html)
        self.assertIn('data-bt-chip', self.http.get(reverse('dashboard:project-detail', args=[self.project.id])).content.decode())

    def test_project_page_shows_time_tab(self):
        self.http.post(reverse('dashboard:time-entry-create', args=[self.project.id]), {'duration': '1h15'})
        html = self.http.get(reverse('dashboard:project-detail', args=[self.project.id])).content.decode()
        self.assertIn('Temps passé', html)
        self.assertIn('1 h 15', html)
