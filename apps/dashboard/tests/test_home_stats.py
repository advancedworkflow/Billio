"""Accueil du tableau de bord : CA 12 mois, créances par ancienneté, meilleurs clients."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client as HttpClient, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client
from apps.dashboard import home_stats
from apps.invoices.models import Invoice
from apps.organizations.models import Organization
from apps.payments.models import Payment


class HomeStatsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='o', email='o@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Atelier Lumen', owner=self.user, default_currency='EUR')
        prefs = dict(self.org.billing_preferences or {})
        prefs['onboarding'] = {'state': 'done'}
        self.org.billing_preferences = prefs
        self.org.save()
        self.today = timezone.localdate()
        self.pixel = Client.objects.create(organization=self.org, name='Agence Pixel', email='a@pixel.fr')
        self.sol = Client.objects.create(organization=self.org, name='Brasserie Sol', email='b@sol.fr')

    def invoice(self, client, ht, days_ago, status='sent', term=30):
        issue = self.today - timedelta(days=days_ago)
        ht = Decimal(ht)
        invoice = Invoice.objects.create(organization=self.org, client=client, issue_date=issue,
                                         due_date=issue + timedelta(days=term),
                                         subtotal=ht, tax_amount=ht / 5, total_amount=ht * Decimal('1.2'))
        Invoice.objects.filter(pk=invoice.pk).update(status=status)
        invoice.refresh_from_db()
        return invoice

    def test_receivables_by_age_and_partial_payment(self):
        self.invoice(self.pixel, '1000', 5)                 # à échoir : 1200
        late = self.invoice(self.sol, '500', 45, 'overdue')  # 15 j de retard : 600
        self.invoice(self.sol, '100', 120, 'overdue')        # 90 j de retard : 120
        self.invoice(self.pixel, '900', 10, 'paid')          # payée : ignorée
        Payment.objects.create(invoice=late, amount=Decimal('200'), status='completed', payment_date=timezone.now())
        Payment.objects.create(invoice=late, amount=Decimal('50'), status='failed')
        data = home_stats.receivables([self.org.id], self.today, 'EUR')
        amounts = {b['key']: b for b in data['buckets']}
        self.assertEqual(data['total'], Decimal('1720.00'))
        self.assertEqual(data['overdue'], Decimal('520.00'))
        self.assertEqual((amounts['current']['count'], amounts['d30']['count'], amounts['d60p']['count']), (1, 1, 1))
        self.assertTrue(data['upcoming'][0]['is_late'])
        self.assertEqual(data['upcoming'][0]['late_days'], 90)

    def test_revenue_series_and_top_clients(self):
        self.invoice(self.pixel, '3000', 2, 'paid')
        self.invoice(self.sol, '1000', 3)
        self.invoice(self.sol, '9999', 1, 'draft')  # brouillon : hors CA
        series = home_stats.revenue_series([self.org.id], self.today.replace(day=1), 'EUR')
        self.assertEqual(len(series['points']), 12)
        self.assertEqual(series['points'][-1]['amount'], 4000.0)
        self.assertEqual(series['ticks'][0]['label'], '5 k€')
        top = home_stats.top_clients([self.org.id], self.today, 'EUR')
        self.assertEqual([c['name'] for c in top], ['Agence Pixel', 'Brasserie Sol'])
        self.assertEqual(top[0]['share_text'], '75 %')

    def test_home_page_renders(self):
        self.invoice(self.pixel, '1000', 40, 'overdue')
        http = HttpClient(HTTP_HOST='127.0.0.1')
        http.force_login(self.user)
        http.cookies['billio_lang'] = 'fr'
        page = http.get(reverse('dashboard:dashboard-home')).content.decode()
        self.assertIn('Meilleurs clients', page)
        self.assertIn('dh-revenue-data', page)
        self.assertIn('en retard de 10 j', page)
        previous = http.get(reverse('dashboard:dashboard-home') + '?month=2026-01')
        self.assertEqual(previous.status_code, 200)
