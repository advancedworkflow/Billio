"""
Processus de projet : page de gestion (Projets › Processus) et actions.

Un processus est une suite d'étapes ; les étapes (ProjectPhase) sont partagées entre processus,
si bien que renommer « Terminé » le renomme partout. Chaque projet suit un processus
(vide = processus par défaut).
"""
import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.organizations.trade_packs import TRADE_PACKS, ensure_process

from .models import Milestone, Project, ProjectPhase, ProjectProcess, ProjectTemplate
from .project_views import _phases_context, _user_projects_queryset
from .views import _first_user_organization

MAX_STEPS = 15
_HEX = __import__('re').compile(r'^#[0-9a-fA-F]{6}$')


def _payload(request):
    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _processes_payload(organization):
    all_phases = ProjectPhase.for_organization(organization)
    processes = ProjectProcess.for_organization(organization)
    default = next((p for p in processes if p.is_default), processes[0])
    counts = {}
    for process_id in Project.objects.filter(organization=organization).values_list('process_id', flat=True):
        key = process_id or default.id
        counts[key] = counts.get(key, 0) + 1
    templates = {}
    for template in ProjectTemplate.objects.filter(organization=organization):
        name = (template.data or {}).get('process') or default.name
        templates.setdefault(name, []).append(template.name)
    return [{
        'id': p.id, 'name': p.name, 'description': p.description, 'is_default': p.is_default,
        'projects': counts.get(p.id, 0), 'templates': templates.get(p.name, []),
        'steps': [{'key': ph.key, 'label': ph.label, 'color': ph.color} for ph in p.phases(all_phases)],
    } for p in processes]


def _suggestions(organization):
    """Processus suggérés : ceux du métier de l'organisation d'abord, puis les autres métiers."""
    existing = set(ProjectProcess.objects.filter(organization=organization).values_list('name', flat=True))
    trade = getattr(organization, 'trade', '') or 'autre'
    groups = []
    for key, pack in sorted(TRADE_PACKS.items(), key=lambda item: item[0] != trade):
        items = [{'name': pack['process'], 'description': 'Processus principal du métier', 'phases': pack['phases']}] + pack['processes']
        groups.append({
            'trade': key, 'label': pack['label'], 'mine': key == trade,
            'items': [{'name': item['name'], 'description': item['description'], 'added': item['name'] in existing,
                       'steps': [{'label': label, 'color': color} for _k, label, color in item['phases']]} for item in items],
        })
    return groups


@login_required
def process_list(request):
    organization = _first_user_organization(request.user)
    if organization is None:
        return render(request, 'dashboard/processes.html', {'page_title': 'Processus de projet', 'config': {}})
    config = {
        'processes': _processes_payload(organization),
        'suggestions': _suggestions(organization),
        'phases': [{'key': p.key, 'label': p.label, 'color': p.color} for p in ProjectPhase.for_organization(organization)],
    }
    return render(request, 'dashboard/processes.html', {'page_title': 'Processus de projet', 'config': config})


def save_steps(organization, steps, *, rename_shared=True):
    """
    Étapes saisies → clés d'étapes de l'organisation. Une étape existante (clé connue) est renommée /
    recolorée (partout : elle est partagée) ; une nouvelle étape est créée avec une clé unique.
    `rename_shared=False` (étapes propres à un projet) : une étape modifiée devient une nouvelle étape,
    les processus qui partagent l'originale restent intacts.
    """
    phases = {p.key: p for p in ProjectPhase.objects.filter(organization=organization)}
    order = max((p.order for p in phases.values()), default=-1) + 1
    keys = []
    for step in steps[:MAX_STEPS]:
        if not isinstance(step, dict):
            continue
        label = str(step.get('label') or '').strip()[:50]
        if not label:
            continue
        color = step.get('color') if _HEX.match(str(step.get('color') or '')) else '#6366f1'
        key = step.get('key')
        if key in phases and not rename_shared and (phases[key].label, phases[key].color) != (label, color):
            key = None
        if key in phases:
            phase = phases[key]
            if (phase.label, phase.color) != (label, color):
                phase.label, phase.color = label, color
                phase.save(update_fields=['label', 'color'])
        else:
            key = _unique_key(label, set(phases))
            phases[key] = ProjectPhase.objects.create(organization=organization, key=key, label=label, color=color, order=order)
            order += 1
        if key not in keys:
            keys.append(key)
    return keys


def _unique_key(label, taken):
    base = slugify(label)[:26] or 'etape'
    key, n = base, 2
    while key in taken:
        key, n = f'{base}-{n}', n + 1
    return key


@login_required
@require_POST
def process_save(request):
    """Crée ou met à jour un processus : nom, description et étapes (existantes ou nouvelles)."""
    organization = _first_user_organization(request.user)
    data = _payload(request)
    name = str(data.get('name') or '').strip()[:80]
    if organization is None or not name:
        return JsonResponse({'ok': False, 'error': 'Donnez un nom au processus.'}, status=400)
    steps = [s for s in (data.get('steps') or []) if isinstance(s, dict) and str(s.get('label') or '').strip()][:MAX_STEPS]
    if not steps:
        return JsonResponse({'ok': False, 'error': 'Ajoutez au moins une étape.'}, status=400)
    process = None
    if data.get('id'):
        process = get_object_or_404(ProjectProcess, organization=organization, id=data['id'])
    if ProjectProcess.objects.filter(organization=organization, name=name).exclude(id=getattr(process, 'id', None)).exists():
        return JsonResponse({'ok': False, 'error': 'Un autre processus porte déjà ce nom.'}, status=400)

    with transaction.atomic():
        keys = save_steps(organization, steps)
        if process is None:
            process = ProjectProcess(organization=organization, order=ProjectProcess.objects.filter(organization=organization).count())
        process.name, process.description, process.phase_keys = name, str(data.get('description') or '').strip()[:200], keys
        process.save()
        if not ProjectProcess.objects.filter(organization=organization, is_default=True).exists():
            ProjectProcess.objects.filter(id=process.id).update(is_default=True)
    return JsonResponse({'ok': True, 'processes': _processes_payload(organization),
                         'phases': [{'key': p.key, 'label': p.label, 'color': p.color} for p in ProjectPhase.for_organization(organization)]})


@login_required
@require_POST
def process_default(request, process_id):
    organization = _first_user_organization(request.user)
    process = get_object_or_404(ProjectProcess, organization=organization, id=process_id)
    ProjectProcess.objects.filter(organization=organization).update(is_default=False)
    ProjectProcess.objects.filter(id=process.id).update(is_default=True)
    return JsonResponse({'ok': True, 'processes': _processes_payload(organization)})


@login_required
@require_POST
def process_delete(request, process_id):
    """Supprime un processus : ses projets passent au processus par défaut (leurs étapes restent visibles)."""
    organization = _first_user_organization(request.user)
    process = get_object_or_404(ProjectProcess, organization=organization, id=process_id)
    if process.is_default:
        return JsonResponse({'ok': False, 'error': 'Choisissez d’abord un autre processus par défaut.'}, status=400)
    with transaction.atomic():
        Project.objects.filter(process=process).update(process=None)
        process.delete()
        _remove_orphan_phases(organization)
    return JsonResponse({'ok': True, 'processes': _processes_payload(organization)})


def _remove_orphan_phases(organization):
    """Étapes qui ne servent plus à aucun processus, projet ni jalon : supprimées."""
    used = set()
    for keys in ProjectProcess.objects.filter(organization=organization).values_list('phase_keys', flat=True):
        used.update(keys or [])
    used.update(Project.objects.filter(organization=organization).values_list('status', flat=True))
    used.update(Milestone.objects.filter(project__organization=organization).values_list('phase', flat=True))
    ProjectPhase.objects.filter(organization=organization).exclude(key__in=used).delete()


@login_required
@require_POST
def process_add_suggestion(request):
    """Ajoute un processus suggéré (d'après les packs métier)."""
    organization = _first_user_organization(request.user)
    data = _payload(request)
    for pack in TRADE_PACKS.values():
        items = [{'name': pack['process'], 'description': 'Processus principal du métier', 'phases': pack['phases']}] + pack['processes']
        for item in items:
            if item['name'] == data.get('name'):
                ensure_process(organization, item['name'], item['phases'], description=item['description'])
                return JsonResponse({'ok': True, 'processes': _processes_payload(organization), 'suggestions': _suggestions(organization)})
    return JsonResponse({'ok': False, 'error': 'Processus inconnu.'}, status=404)


@login_required
@require_POST
def project_update_process(request, project_id):
    """Change le processus d'un projet ; s'il n'a pas l'étape en cours, le projet passe à sa première étape."""
    project = get_object_or_404(_user_projects_queryset(request.user), id=project_id)
    process = get_object_or_404(ProjectProcess, organization=project.organization, id=request.POST.get('process_id') or 0)
    project.process = process
    keys = [p['value'] for p in _phases_context(project.organization, process=process)]
    fields = ['process', 'updated_at']
    if project.status not in keys and keys:
        project.status = keys[0]
        fields.append('status')
    project.save(update_fields=fields)
    return JsonResponse({'ok': True, 'status': project.status})
