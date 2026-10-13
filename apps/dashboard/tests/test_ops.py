"""Exploitation : point de santé, worker des tâches planifiées, limitation des connexions."""
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.organizations.models import Organization


class HealthTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_healthz_ignores_host_and_reports_worker(self):
        http = HttpClient(HTTP_HOST='10.0.0.12')  # sonde interne de l'hébergeur : hôte non déclaré
        self.assertEqual(http.get('/healthz/').json(), {'status': 'ok'})
        response = http.get('/healthz/?worker=1')
        self.assertEqual(response.status_code, 503)  # le worker n'a jamais tourné
        call_command('run_automations', stdout=StringIO())
        response = http.get('/healthz/?worker=1')
        self.assertEqual(response.status_code, 200)
        self.assertLess(response.json()['worker_last_run_seconds_ago'], 5)

    def test_one_failing_organization_does_not_stop_the_others(self):
        user = User.objects.create_user(username='a', email='a@test.fr', password='x-Test-1234')
        Organization.objects.create(name='A', owner=user)
        Organization.objects.create(name='B', owner=user)
        out = StringIO()
        with mock.patch('apps.dashboard.automation_engine.sweep_overdue_invoices', side_effect=[RuntimeError('panne'), None]):
            call_command('run_automations', stdout=out)
        self.assertIn('1 organisation(s)', out.getvalue())
        self.assertIn('1 en échec', out.getvalue())


class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_user(username='camille', email='camille@test.fr', password='Bon-Mot-2026')
        self.http = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr')  # textes vérifiés en français

    def login(self, password):
        return self.http.post(reverse('accounts:login'), {'email': 'camille@test.fr', 'password': password})

    def test_fifth_failure_blocks_even_the_right_password(self):
        for _ in range(5):
            self.login('faux')
        response = self.login('Bon-Mot-2026')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Trop de tentatives')
        cache.clear()
        self.assertEqual(self.login('Bon-Mot-2026').status_code, 302)

    def test_success_resets_the_email_counter(self):
        for _ in range(4):
            self.login('faux')
        self.assertEqual(self.login('Bon-Mot-2026').status_code, 302)
        self.http.logout()
        for _ in range(4):
            self.login('faux')
        self.assertEqual(self.login('Bon-Mot-2026').status_code, 302)


class GlobalSearchTests(TestCase):
    def test_search_finds_only_own_records(self):
        from apps.clients.models import Client
        owner = User.objects.create_user(username='o', email='o@test.fr', password='x-Test-1234')
        other = User.objects.create_user(username='p', email='p@test.fr', password='x-Test-1234')
        Client.objects.create(organization=Organization.objects.create(name='A', owner=owner), name='Brasserie du Canal', email='b@test.fr')
        Client.objects.create(organization=Organization.objects.create(name='B', owner=other), name='Brasserie Secrète', email='s@test.fr')
        http = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr')  # textes vérifiés en français
        http.force_login(owner)
        labels = [r['label'] for r in http.get(reverse('dashboard:global-search') + '?q=bras').json()['results']]
        self.assertEqual(labels, ['Brasserie du Canal'])
        self.assertEqual(http.get(reverse('dashboard:global-search') + '?q=b').json()['results'], [])
