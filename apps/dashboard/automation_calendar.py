"""
Déclencheur « Date du calendrier » (trigger_key 'calendar_date').

Deux façons de choisir la date, réglées dans le bloc déclencheur du board :
- une date fixe (avec répétition éventuelle : chaque jour / semaine / mois / année) ;
- une date liée aux données : livraison ou début d'un projet, échéance d'un jalon,
  échéance d'une facture, date d'une réunion — avec un décalage avant / après.

Pas de worker planifié dans ce projet : `sweep_calendar_triggers` est appelé au
chargement du tableau de bord et par la commande `manage.py run_automations`.
Chaque échéance ne déclenche le workflow qu'une fois (AutomationRun est idempotent
par cible) ; une date déplacée redéclenche pour la nouvelle date.
"""
import calendar
import re
from datetime import datetime, time, timedelta

from django.utils import timezone

SOURCES = {
    'fixed': 'Date fixe',
    'project_delivery': 'Date de livraison du projet',
    'project_start': 'Date de début du projet',
    'milestone_due': "Échéance d'un jalon",
    'invoice_due': "Échéance d'une facture",
    'meeting': "Date d'une réunion",
}
REPEATS = {'none', 'daily', 'weekly', 'monthly', 'yearly'}
DIRECTIONS = {'before', 'after'}
OFFSET_UNITS = {'days', 'hours'}
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


class CalendarParamsError(ValueError):
    pass


def clean_params(raw):
    """Paramètres du bloc déclencheur, validés (lève CalendarParamsError)."""
    raw = raw if isinstance(raw, dict) else {}
    source = raw.get('source') if raw.get('source') in SOURCES else 'fixed'
    at_time = raw.get('time') if _TIME_RE.match(str(raw.get('time') or '')) else '09:00'
    params = {'source': source, 'time': at_time}
    if source == 'fixed':
        date_value = str(raw.get('date') or '')
        if not _DATE_RE.match(date_value):
            raise CalendarParamsError('Choisissez la date du déclencheur « Date du calendrier ».')
        try:
            datetime.strptime(date_value, '%Y-%m-%d')
        except ValueError:
            raise CalendarParamsError('Date du déclencheur invalide.')
        params['date'] = date_value
        params['repeat'] = raw.get('repeat') if raw.get('repeat') in REPEATS else 'none'
    else:
        try:
            offset = int(raw.get('offset') or 0)
        except (TypeError, ValueError):
            raise CalendarParamsError('Décalage du déclencheur invalide.')
        unit = raw.get('unit') if raw.get('unit') in OFFSET_UNITS else 'days'
        params['offset'] = max(0, min(offset, 365 if unit == 'days' else 24 * 30))
        params['unit'] = unit
        params['direction'] = raw.get('direction') if raw.get('direction') in DIRECTIONS else 'before'
    return params


def _at(day, hhmm):
    hour, minute = (int(x) for x in hhmm.split(':'))
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def _add_months(day, months):
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def last_fixed_occurrence(params, now):
    """Dernière occurrence ≤ now d'une date fixe (répétée ou non), sinon None."""
    first = _at(datetime.strptime(params['date'], '%Y-%m-%d').date(), params['time'])
    if first > now:
        return None
    repeat = params.get('repeat', 'none')
    if repeat == 'none':
        return first
    if repeat in ('daily', 'weekly'):
        step = timedelta(days=1 if repeat == 'daily' else 7)
        return first + step * ((now - first) // step)
    months = 1 if repeat == 'monthly' else 12
    count = (now.year - first.year) * 12 + now.month - first.month
    count -= count % months
    candidate = _at(_add_months(first.date(), count), params['time'])
    while candidate > now:
        count -= months
        candidate = _at(_add_months(first.date(), count), params['time'])
    return candidate


def next_fixed_occurrence(params, now):
    """Prochaine occurrence > now (affichage dans le board)."""
    first = _at(datetime.strptime(params['date'], '%Y-%m-%d').date(), params['time'])
    if first > now:
        return first
    repeat = params.get('repeat', 'none')
    if repeat == 'none':
        return None
    last = last_fixed_occurrence(params, now)
    if repeat == 'daily':
        return last + timedelta(days=1)
    if repeat == 'weekly':
        return last + timedelta(days=7)
    # Toujours compté depuis la date d'origine : un « 31 » reste le 31 quand le mois le permet.
    months = 1 if repeat == 'monthly' else 12
    count = (last.year - first.year) * 12 + last.month - first.month + months
    return _at(_add_months(first.date(), count), params['time'])


def _shift(moment, params):
    delta = timedelta(**{params['unit']: params['offset']})
    return moment - delta if params['direction'] == 'before' else moment + delta


def _dated_targets(organization, source, params):
    """[(type, id, moment, client_id, project_id, variables, label)] pour une source liée aux données."""
    from apps.invoices.models import Invoice
    from .models import Meeting, Milestone, Project

    targets = []
    if source in ('project_delivery', 'project_start'):
        field = 'delivery_date' if source == 'project_delivery' else 'start_date'
        word = 'Livraison' if source == 'project_delivery' else 'Début'
        projects = (Project.objects.filter(organization=organization, **{f'{field}__isnull': False})
                    .exclude(status='completed').select_related('client'))
        for project in projects:
            day = getattr(project, field)
            targets.append(('project', f"{project.id}@{field}:{day}", _at(day, params['time']), project.client_id, project.id,
                            {'projet': project.name, 'date_echeance': day.strftime('%d/%m/%Y')},
                            f"{word} du projet « {project.name} » le {day:%d/%m/%Y}."))
    elif source == 'milestone_due':
        milestones = (Milestone.objects.filter(project__organization=organization, due_date__isnull=False, is_completed=False)
                      .select_related('project'))
        for milestone in milestones:
            project = milestone.project
            targets.append(('milestone', f"{milestone.id}@{milestone.due_date}", _at(milestone.due_date, params['time']),
                            project.client_id, project.id,
                            {'projet': project.name, 'jalon': milestone.title, 'date_echeance': milestone.due_date.strftime('%d/%m/%Y')},
                            f"Jalon « {milestone.title} » ({project.name}) à échéance le {milestone.due_date:%d/%m/%Y}."))
    elif source == 'invoice_due':
        invoices = Invoice.objects.filter(organization=organization, invoice_type='sale', due_date__isnull=False,
                                          status__in=['sent', 'viewed', 'overdue'])
        for invoice in invoices:
            targets.append(('invoice', f"{invoice.id}@{invoice.due_date}", _at(invoice.due_date, params['time']),
                            invoice.client_id, None,
                            {'numero': invoice.invoice_number, 'date_echeance': invoice.due_date.strftime('%d/%m/%Y'),
                             'montant': f"{invoice.total_amount:.2f} €".replace('.', ',')},
                            f"Facture {invoice.invoice_number} à échéance le {invoice.due_date:%d/%m/%Y}."))
    elif source == 'meeting':
        meetings = (Meeting.objects.filter(project__organization=organization, status='scheduled')
                    .select_related('project'))
        for meeting in meetings:
            project = meeting.project
            when = timezone.localtime(meeting.scheduled_at)
            targets.append(('meeting', f"{meeting.id}@{when:%Y%m%d%H%M}", meeting.scheduled_at, project.client_id, project.id,
                            {'projet': project.name, 'reunion': meeting.title, 'lieu': meeting.location or '',
                             'date_reunion': when.strftime('%d/%m/%Y à %H:%M')},
                            f"Réunion « {meeting.title} » le {when:%d/%m/%Y à %H:%M}."))
    return targets


def sweep_calendar_triggers(organization, now=None):
    """Déclenche les workflows « Date du calendrier » dont l'heure est arrivée."""
    from .automation_engine import run_automations
    from .models import AutomationRule

    now = now or timezone.now()
    rules = AutomationRule.objects.filter(organization=organization, trigger_key='calendar_date', is_active=True)
    for rule in rules:
        trigger = next((n for n in rule.get_graph().get('nodes', []) if n['type'] == 'trigger'), None)
        try:
            params = clean_params((trigger or {}).get('params'))
        except CalendarParamsError:
            continue
        # Une date déjà passée au moment où le workflow est créé ne le déclenche pas.
        not_before = rule.created_at
        if params['source'] == 'fixed':
            moment = last_fixed_occurrence(params, now)
            if moment and moment >= not_before:
                run_automations(
                    organization, 'calendar_date', target_type='calendar', target_id=f"{rule.id}@{moment:%Y-%m-%dT%H:%M}",
                    variables={'date_echeance': timezone.localtime(moment).strftime('%d/%m/%Y')},
                    context_label=f"Date programmée : {timezone.localtime(moment):%d/%m/%Y à %H:%M}.",
                    only_rule=rule,
                )
            continue
        for target_type, target_id, moment, client_id, project_id, variables, label in _dated_targets(organization, params['source'], params):
            fire_at = _shift(moment, params)
            if not_before <= fire_at <= now:
                run_automations(
                    organization, 'calendar_date', target_type=target_type, target_id=target_id,
                    client_id=client_id, project_id=project_id, variables=variables, context_label=label,
                    only_rule=rule,
                )
