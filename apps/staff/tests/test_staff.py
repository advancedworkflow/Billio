"""Administration de la plateforme : accès réservé, comptes, clés des intégrations."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.integrations import oauth
from apps.staff.platform import get_setting, source
from apps.subscriptions.entitlements import plan_for_user


class StaffTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='a', email='a@test.fr', password='x-Test-1234')
        self.user = User.objects.create_user(username='u', email='u@test.fr', password='x-Test-1234')
        self.http = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr')

    def test_pages_hidden_from_regular_users(self):
        self.http.force_login(self.user)
        for name in ('staff:overview', 'staff:users', 'staff:keys', 'staff:traffic', 'staff:usage'):
            self.assertEqual(self.http.get(reverse(name)).status_code, 404)

    def test_pages_render_for_superuser(self):
        self.http.force_login(self.admin)
        for name in ('staff:overview', 'staff:users', 'staff:keys', 'staff:traffic', 'staff:usage'):
            self.assertEqual(self.http.get(reverse(name)).status_code, 200)
        self.assertContains(self.http.get(reverse('staff:users'), {'q': 'u@test'}), 'u@test.fr')

    def test_offer_plan_then_remove(self):
        self.http.force_login(self.admin)
        url = reverse('staff:user-action', args=[self.user.id])
        self.http.post(url, {'action': 'offer_plan', 'plan': 'pro'})
        self.assertEqual(plan_for_user(self.user).code, 'pro')
        self.http.post(url, {'action': 'offer_plan', 'plan': ''})
        self.assertEqual(plan_for_user(self.user).code, 'free')

    def test_toggle_active_but_not_self(self):
        self.http.force_login(self.admin)
        self.http.post(reverse('staff:user-action', args=[self.user.id]), {'action': 'toggle_active'})
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.http.post(reverse('staff:user-action', args=[self.admin.id]), {'action': 'toggle_active'})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_keys_saved_enable_oauth(self):
        self.http.force_login(self.admin)
        self.assertFalse(oauth.configured('slack'))
        self.http.post(reverse('staff:keys'), {'tool': 'slack', 'SLACK_CLIENT_ID': 'cid', 'SLACK_CLIENT_SECRET': 'sec'})
        self.assertEqual(get_setting('SLACK_CLIENT_SECRET'), 'sec')
        self.assertEqual(source('SLACK_CLIENT_ID'), 'site')
        self.assertTrue(oauth.configured('slack'))
        # Champ vide : la clé enregistrée est conservée ; « Effacer » la retire.
        self.http.post(reverse('staff:keys'), {'tool': 'slack', 'SLACK_CLIENT_ID': ''})
        self.assertTrue(oauth.configured('slack'))
        self.http.post(reverse('staff:keys'), {'tool': 'slack', 'clear_SLACK_CLIENT_ID': '1'})
        self.assertFalse(oauth.configured('slack'))


class MetricsTests(TestCase):
    def setUp(self):
        from apps.staff import metrics
        from apps.staff.models import RequestMetric
        cache.clear()
        metrics.flush()  # vide le cumul en mémoire laissé par les autres tests
        RequestMetric.objects.all().delete()
        self.user = get_user_model().objects.create_user(username='m', email='m@test.fr', password='x-Test-1234')
        self.http = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr', HTTP_USER_AGENT='Mozilla/5.0 Test')

    def test_requests_counted_per_route_and_visitors_once_per_day(self):
        from apps.staff import metrics
        from apps.staff.models import RequestMetric, VisitorDay
        self.http.get('/')
        self.http.get('/')
        self.http.get('/page-qui-n-existe-pas/')
        self.http.get('/static/css/app.css')
        metrics.flush()
        total = sum(RequestMetric.objects.values_list('count', flat=True))
        self.assertEqual(total, 3)
        self.assertEqual(sum(RequestMetric.objects.values_list('client_errors', flat=True)), 1)
        self.assertEqual(VisitorDay.objects.filter(user__isnull=True).count(), 1)
        self.http.force_login(self.user)
        self.http.get(reverse('dashboard:dashboard-home'))
        self.assertTrue(VisitorDay.objects.filter(user=self.user).exists())

    def test_bots_are_not_visitors(self):
        from apps.staff.models import VisitorDay
        HttpClient(HTTP_HOST='127.0.0.1', HTTP_USER_AGENT='Googlebot/2.1').get('/')
        self.assertFalse(VisitorDay.objects.exists())

    def test_unhandled_exception_is_recorded(self):
        from unittest import mock
        from apps.staff.models import ServerError
        http = HttpClient(HTTP_HOST='127.0.0.1', raise_request_exception=False)
        with mock.patch('apps.landing.views.LandingPageView.get_context_data', side_effect=RuntimeError('boom')):
            response = http.get('/')
        self.assertEqual(response.status_code, 500)
        error = ServerError.objects.get()
        self.assertEqual((error.exception, error.message, error.path), ('RuntimeError', 'boom', '/'))
