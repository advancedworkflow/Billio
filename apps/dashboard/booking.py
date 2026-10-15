"""
Prise de rendez-vous en ligne : page publique /dashboard/book/<jeton>/ de l'organisation.

Les créneaux proposés respectent les jours et horaires d'ouverture, le délai de
prévenance, l'horizon de réservation, et évitent les rendez-vous et réunions déjà
planifiés. Une réservation crée (ou retrouve) le client, prévient l'organisation,
envoie une confirmation avec un lien d'annulation et déclenche les automatisations
« Rendez-vous réservé ».
"""
import logging
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Appointment, Meeting, Notification

logger = logging.getLogger(__name__)

DEFAULTS = {
    'enabled': False,
    'types': [{'name': 'Premier rendez-vous', 'duration': 30}],
    'days': [1, 2, 3, 4, 5],
    'start': '09:00',
    'end': '18:00',
    'min_notice_hours': 24,
    'max_days_ahead': 30,
    'location': '',
    'intro': '',
}
STEP_MINUTES = 15


def booking_config(organization):
    config = dict(DEFAULTS)
    config.update({k: v for k, v in (organization.booking_settings or {}).items() if k in DEFAULTS})
    config['types'] = [t for t in config['types'] if t.get('name') and int(t.get('duration') or 0) > 0] or DEFAULTS['types']
    return config


def clean_settings(post):
    """Formulaire des réglages → booking_settings validés."""
    types = []
    for name, duration in zip(post.getlist('type_name'), post.getlist('type_duration')):
        name = (name or '').strip()[:120]
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            continue
        if name and 5 <= duration <= 480:
            types.append({'name': name, 'duration': duration})

    def hhmm(value, default):
        try:
            return datetime.strptime(value or '', '%H:%M').strftime('%H:%M')
        except ValueError:
            return default

    def bounded(value, default, low, high):
        try:
            return max(low, min(high, int(value)))
        except (TypeError, ValueError):
            return default

    start, end = hhmm(post.get('start'), '09:00'), hhmm(post.get('end'), '18:00')
    if end <= start:
        raise ValueError("L'heure de fin doit être après l'heure de début.")
    return {
        'enabled': post.get('enabled') == 'on',
        'types': types or DEFAULTS['types'],
        'days': sorted({int(d) for d in post.getlist('days') if d in {'1', '2', '3', '4', '5', '6', '7'}}) or DEFAULTS['days'],
        'start': start, 'end': end,
        'min_notice_hours': bounded(post.get('min_notice_hours'), 24, 0, 24 * 14),
        'max_days_ahead': bounded(post.get('max_days_ahead'), 30, 1, 180),
        'location': (post.get('location') or '').strip()[:255],
        'intro': (post.get('intro') or '').strip()[:500],
    }


def _busy(organization, day_start, day_end):
    busy = [(a.start, a.end) for a in Appointment.objects.filter(
        organization=organization, status='confirmed', start__lt=day_end, end__gt=day_start)]
    for meeting in Meeting.objects.filter(project__organization=organization, status='scheduled',
                                          scheduled_at__lt=day_end, scheduled_at__gte=day_start - timedelta(hours=8)):
        busy.append((meeting.scheduled_at, meeting.scheduled_at + timedelta(minutes=meeting.duration_minutes)))
    return busy


def available_slots(organization, day, duration, *, now=None):
    """Débuts de créneaux libres (datetime aware) pour `day` et une durée en minutes."""
    config = booking_config(organization)
    now = now or timezone.now()
    if day.isoweekday() not in config['days']:
        return []
    if day > timezone.localdate(now) + timedelta(days=config['max_days_ahead']):
        return []
    open_at = timezone.make_aware(datetime.combine(day, time.fromisoformat(config['start'])))
    close_at = timezone.make_aware(datetime.combine(day, time.fromisoformat(config['end'])))
    earliest = now + timedelta(hours=config['min_notice_hours'])
    busy = _busy(organization, open_at, close_at)
    slots, cursor, length = [], open_at, timedelta(minutes=duration)
    while cursor + length <= close_at:
        end = cursor + length
        if cursor >= earliest and not any(start < end and cursor < stop for start, stop in busy):
            slots.append(cursor)
        cursor += timedelta(minutes=STEP_MINUTES)
    return slots


def _organization_for(token):
    from apps.organizations.models import Organization
    organization = Organization.objects.filter(booking_token=token).first()
    from apps.subscriptions.entitlements import has_feature
    if not organization or not booking_config(organization)['enabled'] or not has_feature(organization, 'booking'):
        raise Http404('Prise de rendez-vous indisponible.')
    return organization


def public_booking(request, token):
    """Page publique : choix du motif, du jour, du créneau, puis coordonnées."""
    organization = _organization_for(token)
    config = booking_config(organization)
    type_index = request.GET.get('type', '0')
    type_index = int(type_index) if type_index.isdigit() and int(type_index) < len(config['types']) else 0
    appointment_type = config['types'][type_index]
    today = timezone.localdate()
    days = []
    for offset in range(config['max_days_ahead'] + 1):
        day = today + timedelta(days=offset)
        if day.isoweekday() in config['days']:
            slots = available_slots(organization, day, int(appointment_type['duration']))
            if slots:
                days.append({'date': day, 'slots': [timezone.localtime(s) for s in slots]})
        if len(days) >= 14:
            break
    try:
        selected = datetime.strptime(request.GET.get('day', ''), '%Y-%m-%d').date()
    except ValueError:
        selected = days[0]['date'] if days else None
    return render(request, 'booking/public.html', {
        'organization': organization, 'config': config, 'types': list(enumerate(config['types'])),
        'type_index': type_index, 'appointment_type': appointment_type, 'days': days,
        'selected_day': next((d for d in days if d['date'] == selected), days[0] if days else None),
        'page_title': f"Prendre rendez-vous — {organization.name}",
    })


@require_POST
def public_booking_submit(request, token):
    from apps.clients.models import Client

    organization = _organization_for(token)
    config = booking_config(organization)
    try:
        appointment_type = config['types'][int(request.POST.get('type', 0))]
        start = timezone.make_aware(datetime.strptime(request.POST.get('start', ''), '%Y-%m-%dT%H:%M'))
    except (ValueError, IndexError):
        messages.error(request, 'Créneau invalide.')
        return redirect('dashboard:public-booking', token=token)
    name = (request.POST.get('name') or '').strip()[:150]
    email = (request.POST.get('email') or '').strip()[:254]
    if not name or '@' not in email:
        messages.error(request, 'Indiquez votre nom et une adresse email valide.')
        return redirect(f"{reverse('dashboard:public-booking', args=[token])}?day={start:%Y-%m-%d}")
    duration = int(appointment_type['duration'])
    with transaction.atomic():
        # Verrou logique : on revérifie la disponibilité au moment d'enregistrer.
        if start not in available_slots(organization, timezone.localtime(start).date(), duration):
            messages.error(request, 'Ce créneau vient d\'être pris. Choisissez-en un autre.')
            return redirect(f"{reverse('dashboard:public-booking', args=[token])}?day={start:%Y-%m-%d}")
        client = Client.objects.filter(organization=organization, email__iexact=email).first()
        if not client:
            client = Client.objects.create(organization=organization, name=name, email=email,
                                           phone=(request.POST.get('phone') or '').strip()[:20] or None)
        appointment = Appointment.objects.create(
            organization=organization, client=client, type_name=appointment_type['name'][:120],
            start=start, end=start + timedelta(minutes=duration), name=name, email=email,
            phone=(request.POST.get('phone') or '').strip()[:30], notes=(request.POST.get('notes') or '').strip()[:2000],
        )
    _after_booking(organization, appointment, config)
    return redirect('dashboard:public-booking-done', token=appointment.cancel_token)


def _after_booking(organization, appointment, config):
    when = timezone.localtime(appointment.start)
    label = f"{appointment.type_name} avec {appointment.name} le {when:%d/%m/%Y à %H:%M}"
    if organization.owner:
        Notification.objects.create(user=organization.owner, notification_type='automation_task', priority='high',
                                    title=f"Nouveau rendez-vous : {appointment.name}",
                                    message=label + (f" — « {appointment.notes[:200]} »" if appointment.notes else ''))
    try:
        from apps.organizations.branded_email import branded_message
        cancel_url = f"{settings.SITE_URL}{reverse('dashboard:public-booking-done', args=[appointment.cancel_token])}"
        branded_message(
            organization,
            subject=f"[{organization.name}] Rendez-vous confirmé le {when:%d/%m/%Y à %H:%M}",
            body=(f"Bonjour {appointment.name},\n\nVotre rendez-vous « {appointment.type_name} » est confirmé le "
                  f"{when:%d/%m/%Y à %H:%M} ({int((appointment.end - appointment.start).total_seconds() // 60)} min)."
                  + (f"\nLieu : {config['location']}" if config['location'] else '')),
            to=[appointment.email], button=("Gérer ou annuler le rendez-vous", cancel_url),
        ).send(fail_silently=False)
    except Exception:
        logger.exception('Confirmation de rendez-vous non envoyée (%s)', appointment.id)
    from .automation_engine import run_automations
    run_automations(organization, 'appointment_booked', target_type='appointment', target_id=appointment.id,
                    client_id=appointment.client_id,
                    variables={'reunion': appointment.type_name, 'date_reunion': f"{when:%d/%m/%Y à %H:%M}",
                               'lieu': config['location'], 'client': appointment.name},
                    context_label=f"Rendez-vous réservé : {label}.")


def public_booking_done(request, token):
    """Confirmation (et annulation) côté visiteur, via le jeton personnel du rendez-vous."""
    appointment = get_object_or_404(Appointment.objects.select_related('organization'), cancel_token=token)
    if request.method == 'POST' and appointment.status == 'confirmed' and appointment.start > timezone.now():
        appointment.status = 'cancelled'
        appointment.save(update_fields=['status'])
        organization = appointment.organization
        if organization.owner:
            when = timezone.localtime(appointment.start)
            Notification.objects.create(user=organization.owner, notification_type='automation_task', priority='medium',
                                        title=f"Rendez-vous annulé : {appointment.name}",
                                        message=f"{appointment.type_name} du {when:%d/%m/%Y à %H:%M} annulé par le client.")
        return redirect('dashboard:public-booking-done', token=token)
    return render(request, 'booking/done.html', {
        'appointment': appointment, 'organization': appointment.organization,
        'config': booking_config(appointment.organization),
        'can_cancel': appointment.status == 'confirmed' and appointment.start > timezone.now(),
        'page_title': f"Rendez-vous — {appointment.organization.name}",
    })


@require_POST
@login_required
def appointment_cancel(request, appointment_id):
    from .views import _user_org_ids
    appointment = get_object_or_404(Appointment, id=appointment_id, organization_id__in=_user_org_ids(request.user))
    appointment.status = 'cancelled'
    appointment.save(update_fields=['status'])
    messages.success(request, f"Rendez-vous avec {appointment.name} annulé.")
    return redirect(f"{reverse('accounts:user-settings')}?tab=rdv")
