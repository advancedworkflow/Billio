"""Prise de rendez-vous en ligne : créneaux, conflits, réservation, annulation."""
from datetime import date, datetime, time, timedelta

from django.core import mail
from django.test import Client as HttpClient, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.dashboard.booking import available_slots
from apps.dashboard.models import Appointment, Meeting, Notification, Project
from apps.organizations.models import Organization
from apps.subscriptions.testing import give_plan


def next_weekday(weekday):
    day = timezone.localdate() + timedelta(days=3)
    while day.isoweekday() != weekday:
        day += timedelta(days=1)
    return day


class BookingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='artisan', email='artisan@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Martin Rénovation', owner=self.user, email='contact@martin.test',
                                               booking_settings={'enabled': True, 'types': [{'name': 'Visite de chantier', 'duration': 60}],
                                                                 'days': [1, 2, 3, 4, 5], 'start': '09:00', 'end': '12:00',
                                                                 'min_notice_hours': 24, 'max_days_ahead': 30})
        give_plan(self.user, 'starter')  # prise de rendez-vous : à partir de Starter
        self.http = HttpClient(HTTP_HOST='127.0.0.1')
        self.monday = next_weekday(1)

    def at(self, day, hh, mm=0):
        return timezone.make_aware(datetime.combine(day, time(hh, mm)))

    def test_slots_follow_opening_hours_and_days(self):
        slots = available_slots(self.org, self.monday, 60)
        self.assertEqual(slots[0], self.at(self.monday, 9))
        self.assertEqual(slots[-1], self.at(self.monday, 11))  # dernier créneau d'1 h avant 12 h
        self.assertEqual(available_slots(self.org, next_weekday(6), 60), [])  # samedi fermé
        self.assertEqual(available_slots(self.org, timezone.localdate(), 60), [])  # délai de prévenance

    def test_existing_appointments_and_meetings_block_slots(self):
        Appointment.objects.create(organization=self.org, type_name='X', start=self.at(self.monday, 9),
                                   end=self.at(self.monday, 10), name='A', email='a@test.fr')
        client = Client.objects.create(organization=self.org, name='C', email='c@test.fr')
        project = Project.objects.create(organization=self.org, client=client, name='P')
        Meeting.objects.create(project=project, title='Point', scheduled_at=self.at(self.monday, 11), duration_minutes=30)
        starts = [s.strftime('%H:%M') for s in available_slots(self.org, self.monday, 60)]
        self.assertEqual(starts, ['10:00'])

    def test_booking_creates_client_notifies_and_confirms(self):
        token = self.org.booking_token
        page = self.http.get(reverse('dashboard:public-booking', args=[token]))
        self.assertContains(page, 'Visite de chantier')
        response = self.http.post(reverse('dashboard:public-booking-submit', args=[token]), {
            'type': 0, 'start': f"{self.monday:%Y-%m-%d}T10:00", 'name': 'Paul Durand', 'email': 'paul@test.fr',
            'notes': 'Salle de bain à refaire',
        })
        appointment = Appointment.objects.get()
        self.assertRedirects(response, reverse('dashboard:public-booking-done', args=[appointment.cancel_token]))
        self.assertEqual(appointment.client.email, 'paul@test.fr')
        self.assertTrue(Notification.objects.filter(user=self.user, title__icontains='Paul Durand').exists())
        self.assertEqual(mail.outbox[-1].to, ['paul@test.fr'])
        # Le même créneau n'est plus réservable.
        self.http.post(reverse('dashboard:public-booking-submit', args=[token]), {
            'type': 0, 'start': f"{self.monday:%Y-%m-%d}T10:00", 'name': 'Autre', 'email': 'autre@test.fr'})
        self.assertEqual(Appointment.objects.count(), 1)
        # Annulation par le visiteur : le créneau se libère.
        self.http.post(reverse('dashboard:public-booking-done', args=[appointment.cancel_token]))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, 'cancelled')
        self.assertIn(self.at(self.monday, 10), available_slots(self.org, self.monday, 60))

    def test_disabled_page_is_not_found(self):
        self.org.booking_settings = {**self.org.booking_settings, 'enabled': False}
        self.org.save()
        self.assertEqual(self.http.get(reverse('dashboard:public-booking', args=[self.org.booking_token])).status_code, 404)

    def test_settings_form(self):
        self.http.force_login(self.user)
        self.http.post(reverse('accounts:user-settings'), {
            'form_action': 'save_booking', 'enabled': 'on', 'type_name': ['Appel découverte', 'Atelier'],
            'type_duration': ['20', '90'], 'days': ['2', '4'], 'start': '14:00', 'end': '17:00',
            'min_notice_hours': '2', 'max_days_ahead': '10', 'location': 'Visio',
        })
        self.org.refresh_from_db()
        config = self.org.booking_settings
        self.assertEqual(config['types'], [{'name': 'Appel découverte', 'duration': 20}, {'name': 'Atelier', 'duration': 90}])
        self.assertEqual((config['days'], config['start'], config['location']), ([2, 4], '14:00', 'Visio'))
