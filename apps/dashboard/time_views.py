"""
Suivi du temps par projet : chrono, saisie manuelle, facturation du temps passé.

Le taux horaire vient du projet (`Project.hourly_rate`), sinon du TJM de l'organisation
(Centre de ressources) divisé par ses heures par jour (7 par défaut).
"""
import re
from collections import OrderedDict
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.subscriptions.entitlements import has_feature, plan_with_feature, require_feature

from .models import Task, TimeEntry
from .project_views import _user_projects_queryset

_DURATION_RE = re.compile(r'^\s*(?:(\d+(?:[.,]\d+)?)\s*h)?\s*(\d+)?\s*(?:min|m)?\s*$', re.I)


def parse_duration(raw):
    """« 1h30 », « 1,5h », « 90 », « 45 min », « 2h » → minutes (ou None)."""
    raw = str(raw or '').strip().lower().replace(' ', '')
    if not raw:
        return None
    if re.fullmatch(r'\d+([.,]\d+)?', raw):  # nombre seul : des heures si décimal ou ≤ 12, sinon des minutes
        value = Decimal(raw.replace(',', '.'))
        return int(value * 60) if ('.' in raw or ',' in raw or value <= 12) else int(value)
    match = _DURATION_RE.match(raw)
    if not match or not any(match.groups()):
        return None
    hours = Decimal((match.group(1) or '0').replace(',', '.'))
    minutes = int(match.group(2) or 0)
    total = int(hours * 60) + minutes
    return total or None


def minutes_label(minutes):
    hours, rest = divmod(int(minutes or 0), 60)
    return f"{hours} h {rest:02d}" if rest else f"{hours} h"


def hourly_rate(project):
    if project.hourly_rate:
        return project.hourly_rate
    prefs = project.organization.billing_preferences or {}
    try:
        tjm = Decimal(str(prefs.get('tjm') or 0))
        per_day = Decimal(str(prefs.get('hours_per_day') or 7))
    except Exception:
        return Decimal('0')
    return (tjm / per_day).quantize(Decimal('0.01')) if tjm and per_day else Decimal('0')


def time_summary(project):
    entries = list(project.time_entries.select_related('task', 'user'))
    rate = hourly_rate(project)
    done = [e for e in entries if not e.started_at]
    pending = [e for e in done if e.billable and not e.invoice_id]
    pending_minutes = sum(e.minutes for e in pending)
    summary = {
        'entries': entries,
        'rate': rate,
        'total_minutes': sum(e.minutes for e in done),
        'billable_minutes': sum(e.minutes for e in done if e.billable),
        'pending_minutes': pending_minutes,
        'pending_amount': (rate * pending_minutes / 60).quantize(Decimal('0.01')) if rate else Decimal('0'),
        'running': next((e for e in entries if e.started_at), None),
    }
    for key in ('total', 'billable', 'pending'):
        summary[f'{key}_label'] = minutes_label(summary[f'{key}_minutes'])
    return summary


def _project(request, project_id):
    return get_object_or_404(_user_projects_queryset(request.user), id=project_id)


@require_POST
@login_required
def time_entry_create(request, project_id):
    project = _project(request, project_id)
    require_feature(project.organization, 'time_tracking', 'basic')
    minutes = parse_duration(request.POST.get('duration'))
    if not minutes or minutes > 24 * 60:
        return JsonResponse({'success': False, 'message': 'Durée invalide (ex. 1h30, 45 min, 2,5).'}, status=400)
    try:
        day = datetime.strptime(request.POST.get('date') or '', '%Y-%m-%d').date()
    except ValueError:
        day = timezone.localdate()
    task = Task.objects.filter(project=project, id=request.POST.get('task_id') or 0).first()
    TimeEntry.objects.create(project=project, task=task, user=request.user, date=day, minutes=minutes,
                             description=(request.POST.get('description') or '').strip()[:255],
                             billable=request.POST.get('billable', 'on') == 'on')
    return JsonResponse({'success': True})


@require_POST
@login_required
def time_timer_start(request, project_id):
    project = _project(request, project_id)
    require_feature(project.organization, 'time_tracking', 'basic')
    if TimeEntry.objects.filter(user=request.user, started_at__isnull=False).exists():
        return JsonResponse({'success': False, 'message': 'Un chrono tourne déjà : arrêtez-le d\'abord.'}, status=400)
    task = Task.objects.filter(project=project, id=request.POST.get('task_id') or 0).first()
    entry = TimeEntry.objects.create(project=project, task=task, user=request.user, started_at=timezone.now(),
                                     description=(request.POST.get('description') or '').strip()[:255])
    return JsonResponse({'success': True, 'id': entry.id})


@require_POST
@login_required
def time_timer_stop(request, entry_id):
    entry = get_object_or_404(TimeEntry, id=entry_id, user=request.user, started_at__isnull=False)
    elapsed = timezone.now() - entry.started_at
    entry.minutes = max(1, round(elapsed.total_seconds() / 60))
    entry.date = timezone.localtime(entry.started_at).date()
    entry.started_at = None
    entry.save(update_fields=['minutes', 'date', 'started_at'])
    return JsonResponse({'success': True, 'minutes': entry.minutes})


@login_required
def time_timer_status(request):
    """État du chrono de l'utilisateur pour le widget (barre du haut, fenêtre détachée)."""
    running = (TimeEntry.objects.filter(user=request.user, started_at__isnull=False)
               .select_related('project__client', 'task').first())
    projects = _user_projects_queryset(request.user).select_related('client')
    from apps.organizations.models import Organization
    from django.db.models import Q
    organization = Organization.objects.filter(Q(owner=request.user) | Q(members__user=request.user)).select_related('owner').first()
    if organization and not running and not has_feature(organization, 'time_tracking', 'basic'):
        plan = plan_with_feature('time_tracking', 'basic')
        return JsonResponse({'now': timezone.now().isoformat(), 'running': None, 'projects': [],
                             'locked': f"Le suivi du temps est disponible à partir du forfait {plan.name if plan else 'Starter'}.",
                             'upgrade_url': reverse('subscriptions:billing')})
    recent_ids = list(TimeEntry.objects.filter(user=request.user, project__in=projects)
                      .order_by('-created_at').values_list('project_id', flat=True)[:50])
    recent_ids = list(dict.fromkeys(recent_ids))
    ordered = sorted(projects.order_by('-updated_at')[:40],
                     key=lambda p: recent_ids.index(p.id) if p.id in recent_ids else len(recent_ids))
    return JsonResponse({
        'now': timezone.now().isoformat(),
        'running': {
            'id': running.id,
            'project_id': running.project_id,
            'project': running.project.name,
            'client': running.project.client.name if running.project.client_id else '',
            'task': running.task.title if running.task_id else '',
            'description': running.description,
            'started_at': running.started_at.isoformat(),
            'url': reverse('dashboard:project-detail', args=[running.project_id]) + '#temps',
        } if running else None,
        'projects': [{'id': p.id, 'name': p.name, 'client': p.client.name if p.client_id else ''} for p in ordered],
    })


@login_required
def time_widget(request):
    """Mini-fenêtre du chrono, à garder ouverte à côté de son travail."""
    return render(request, 'dashboard/time_widget.html')


@require_POST
@login_required
def time_entry_delete(request, entry_id):
    entry = get_object_or_404(TimeEntry.objects.filter(project__in=_user_projects_queryset(request.user)), id=entry_id)
    if entry.invoice_id:
        return JsonResponse({'success': False, 'message': 'Temps déjà facturé : il ne peut plus être supprimé.'}, status=400)
    entry.delete()
    return JsonResponse({'success': True})


@require_POST
@login_required
def time_invoice(request, project_id):
    """Crée une facture brouillon avec le temps facturable non facturé (une ligne par tâche)."""
    from apps.invoices.models import Invoice, InvoiceItem

    project = _project(request, project_id)
    require_feature(project.organization, 'time_billing')
    rate = hourly_rate(project)
    if not rate:
        return JsonResponse({'success': False, 'message': "Indiquez un taux horaire pour le projet ou votre TJM dans les réglages de facturation."}, status=400)
    entries = list(project.time_entries.filter(billable=True, invoice__isnull=True, started_at__isnull=True).select_related('task'))
    if not entries:
        return JsonResponse({'success': False, 'message': 'Aucun temps facturable à facturer.'}, status=400)
    prefs = project.organization.billing_preferences or {}
    tax_rate = Decimal('0') if prefs.get('vat_exempt') else Decimal('20')
    groups = OrderedDict()
    for entry in sorted(entries, key=lambda e: (e.task.title if e.task_id else '~', e.date)):
        label = entry.task.title if entry.task_id else 'Temps passé'
        groups.setdefault(label, []).append(entry)
    today = timezone.localdate()
    period = f"du {min(e.date for e in entries):%d/%m/%Y} au {max(e.date for e in entries):%d/%m/%Y}"
    with transaction.atomic():
        invoice = Invoice.objects.create(
            organization=project.organization, client=project.client, created_by=request.user, status='draft',
            title=f"Temps passé — {project.name}", issue_date=today,
            due_date=today + timedelta(days=int(prefs.get('payment_days') or project.organization.default_payment_terms or 30)),
            notes=f"Projet « {project.name} » — temps passé {period}.", total_amount=Decimal('0'),
        )
        subtotal = Decimal('0')
        for order, (label, group) in enumerate(groups.items()):
            hours = (Decimal(sum(e.minutes for e in group)) / 60).quantize(Decimal('0.01'), ROUND_HALF_UP)
            InvoiceItem.objects.create(invoice=invoice, name=f"{project.name} — {label}", quantity=hours, unit='heure',
                                       unit_price=rate, tax_rate=tax_rate, order=order,
                                       description='; '.join(sorted({e.description for e in group if e.description}))[:500])
            subtotal += (hours * rate).quantize(Decimal('0.01'))
        tax = (subtotal * tax_rate / 100).quantize(Decimal('0.01'))
        invoice.subtotal, invoice.tax_amount, invoice.total_amount = subtotal, tax, subtotal + tax
        invoice.save(update_fields=['subtotal', 'tax_amount', 'total_amount'])
        TimeEntry.objects.filter(id__in=[e.id for e in entries]).update(invoice=invoice)
    return JsonResponse({'success': True, 'url': reverse('invoices:invoice-edit', args=[invoice.id])})


@require_POST
@login_required
def time_rate_update(request, project_id):
    project = _project(request, project_id)
    require_feature(project.organization, 'time_tracking', 'full')
    raw = (request.POST.get('hourly_rate') or '').replace(',', '.').strip()
    try:
        project.hourly_rate = Decimal(raw).quantize(Decimal('0.01')) if raw else None
    except Exception:
        return JsonResponse({'success': False, 'message': 'Taux horaire invalide.'}, status=400)
    if project.hourly_rate is not None and project.hourly_rate < 0:
        return JsonResponse({'success': False, 'message': 'Taux horaire invalide.'}, status=400)
    project.save(update_fields=['hourly_rate', 'updated_at'])
    return JsonResponse({'success': True})
