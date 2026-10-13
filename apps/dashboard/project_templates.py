"""
Modèles de projet : instancier un modèle dans un projet, ou figer un projet en modèle.

Les dates sont stockées en jours relatifs au début du projet ; à l'instanciation elles
sont recalées sur la date de début du nouveau projet (ou aujourd'hui). Une phase
absente du tableau de l'organisation est remplacée par la première phase existante.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import Deliverable, Milestone, ProjectPhase, Task


def _offset(day, base):
    return (day - base).days if day and base else None


def snapshot(project):
    """Structure réutilisable d'un projet (jalons, tâches, livrables, questionnaires)."""
    milestones = list(project.milestones.order_by('order', 'due_date', 'id'))
    dates = [d for m in milestones for d in (m.start_date, m.due_date) if d]
    base = project.start_date or (min(dates) if dates else None)
    tasks_by_milestone = {}
    for task in project.tasks.order_by('order', 'due_date', 'id'):
        tasks_by_milestone.setdefault(task.milestone_id, []).append(task)
    deliverables_by_milestone = {}
    for deliverable in project.deliverables.order_by('id'):
        deliverables_by_milestone.setdefault(deliverable.milestone_id, []).append(deliverable.title)
    data = {
        'billing_mode': project.billing_mode,
        'client_brief': {phase: [{'label': f.get('label', ''), 'answer': ''} for f in fields]
                         for phase, fields in (project.client_brief or {}).items()},
        'milestones': [{
            'title': m.title, 'phase': m.phase, 'description': m.description,
            'start': _offset(m.start_date, base), 'due': _offset(m.due_date, base),
            'amount': str(m.amount) if m.amount else '',
            'form_fields': [{'label': f.get('label', ''), 'answer': ''} for f in (m.form_fields or [])],
            'tasks': [{'title': t.title, 'start': _offset(t.start_date, base), 'due': _offset(t.due_date, base)}
                      for t in tasks_by_milestone.get(m.id, [])],
            'deliverables': deliverables_by_milestone.get(m.id, []),
        } for m in milestones],
        'loose_tasks': [{'title': t.title, 'start': _offset(t.start_date, base), 'due': _offset(t.due_date, base)}
                        for t in tasks_by_milestone.get(None, [])],
    }
    return data


def instantiate(data, project, *, user=None):
    """Crée jalons, tâches et livrables du modèle dans `project`. Retourne le nombre de jalons créés."""
    data = data or {}
    start = project.start_date
    if isinstance(start, str):  # projet tout juste créé depuis un formulaire
        from django.utils.dateparse import parse_date
        start = parse_date(start)
    base = start or timezone.localdate()
    phases = list(ProjectPhase.for_organization(project.organization))
    valid = {p.key for p in phases}
    fallback = phases[0].key if phases else 'discovery'

    def day(offset):
        return base + timedelta(days=int(offset)) if offset not in (None, '') else None

    with transaction.atomic():
        update_fields = []
        if data.get('billing_mode') in ('global', 'per_milestone'):
            project.billing_mode = data['billing_mode']
            update_fields.append('billing_mode')
        if data.get('client_brief') and not project.client_brief:
            project.client_brief = data['client_brief']
            update_fields.append('client_brief')
        if update_fields:
            project.save(update_fields=update_fields + ['updated_at'])
        count = 0
        for index, spec in enumerate(data.get('milestones') or []):
            try:
                amount = Decimal(str(spec.get('amount'))) if spec.get('amount') else None
            except InvalidOperation:
                amount = None
            milestone = Milestone.objects.create(
                project=project, title=(spec.get('title') or 'Jalon')[:200], description=spec.get('description') or '',
                phase=spec.get('phase') if spec.get('phase') in valid else fallback,
                start_date=day(spec.get('start')), due_date=day(spec.get('due')), order=index,
                amount=amount, form_fields=spec.get('form_fields') or [], created_by=user,
            )
            for task_index, task in enumerate(spec.get('tasks') or []):
                Task.objects.create(project=project, milestone=milestone, title=(task.get('title') or 'Tâche')[:200],
                                    start_date=day(task.get('start')), due_date=day(task.get('due')),
                                    order=task_index, created_by=user)
            for title in spec.get('deliverables') or []:
                Deliverable.objects.create(project=project, milestone=milestone, title=str(title)[:200], created_by=user)
            count += 1
        for task_index, task in enumerate(data.get('loose_tasks') or []):
            Task.objects.create(project=project, title=(task.get('title') or 'Tâche')[:200],
                                start_date=day(task.get('start')), due_date=day(task.get('due')),
                                order=task_index, created_by=user)
    return count
