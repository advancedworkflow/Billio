"""
Views for the Projects / Deliverables module: Kanban board, project detail,
deliverables, files, and internal (org-facing) comments.

The public, unauthenticated client-portal views live in `portal_views.py`.
"""
import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.clients.models import Client
from apps.organizations.models import OrganizationMember

from .models import Project, Deliverable, DeliverableFile, ProjectFile, Comment, Milestone, MilestoneFile, Task, ProjectPhase, ProjectProcess, Meeting
from .views import _first_user_organization, _user_org_ids
from .client_notifications import notify_client
from .models import ProjectTemplate
from . import project_templates


def _phases_context(organization, project=None, process=None):
    """
    Étapes sous forme de dicts (id/value/label/color) pour les templates.
    - `project` : étapes de son processus, plus celles qu'il utilise déjà (statut, jalons) pour
      qu'un changement de processus ne fasse rien disparaître ;
    - `process` : étapes de ce processus ;
    - sinon : toutes les étapes de l'organisation.
    """
    all_phases = ProjectPhase.for_organization(organization)
    chosen = all_phases
    if project is not None or process is not None:
        process = process or (project.process if project is not None and project.process_id else None) \
            or ProjectProcess.default_for(organization)
        chosen = process.phases(all_phases)
        if project is not None and project.pk:
            used = {project.status} | set(project.milestones.values_list('phase', flat=True))
            keys = {p.key for p in chosen}
            extra = [p for p in all_phases if p.key in used and p.key not in keys]
            if extra:
                done = [p for p in chosen if p.key == 'completed']
                chosen = [p for p in chosen if p.key != 'completed'] + extra + done
    return [{'id': p.id, 'value': p.key, 'label': p.label, 'color': p.color} for p in chosen]


def add_phase_key(keys, key):
    """Ajoute une étape à la liste d'un processus, juste avant « Terminé »."""
    keys = [k for k in (keys or []) if k != key]
    if 'completed' in keys:
        keys.insert(keys.index('completed'), key)
    else:
        keys.append(key)
    return keys


def _processes_context(organization):
    """Processus de l'organisation (id, nom, étapes) pour les sélecteurs."""
    if organization is None:
        return []
    all_phases = ProjectPhase.for_organization(organization)
    return [{'id': proc.id, 'name': proc.name, 'is_default': proc.is_default,
             'steps': [{'value': p.key, 'label': p.label, 'color': p.color} for p in proc.phases(all_phases)]}
            for proc in ProjectProcess.for_organization(organization)]


def _organization_members_data(organization):
    """Membres assignables d'une organisation (propriétaire + membres), pour les selects d'assignation."""
    members = []
    if organization.owner_id:
        members.append({
            'id': organization.owner_id,
            'name': organization.owner.get_full_name() or organization.owner.email,
        })
    for m in OrganizationMember.objects.filter(organization=organization).select_related('user'):
        if m.user_id and m.user_id != organization.owner_id:
            members.append({'id': m.user_id, 'name': m.user.get_full_name() or m.user.email})
    return members


def _check_storage(organization, uploaded):
    """Stockage du forfait (lève QuotaExceeded, rendu en message par le middleware des forfaits)."""
    from apps.subscriptions.entitlements import forget_storage, require_quota
    require_quota(organization, 'storage_mb', adding=uploaded.size)
    forget_storage(organization)


def _time_access(organization):
    """Options du forfait pour l'onglet Temps (chrono, taux par projet, facturation du temps)."""
    from apps.subscriptions.entitlements import has_feature, plan_with_feature
    access = {
        'tracking': has_feature(organization, 'time_tracking', 'basic'),
        'rate': has_feature(organization, 'time_tracking', 'full'),
        'billing': has_feature(organization, 'time_billing'),
    }
    missing = 'tracking' if not access['tracking'] else ('billing' if not access['billing'] else None)
    if missing:
        plan = plan_with_feature('time_tracking', 'basic') if missing == 'tracking' else plan_with_feature('time_billing')
        access['plan_name'] = plan.name if plan else ''
    return access


def _user_projects_queryset(user):
    org_ids = _user_org_ids(user)
    return Project.objects.filter(organization_id__in=org_ids)


@login_required
def deliverables_list(request):
    """Vue agrégée de tous les livrables de l'utilisateur, tous projets confondus."""
    deliverables = Deliverable.objects.filter(
        project__in=_user_projects_queryset(request.user)
    ).select_related('project', 'project__client').order_by('-created_at')

    status = (request.GET.get('status') or '').strip()
    if status:
        deliverables = deliverables.filter(status=status)

    return render(request, 'dashboard/deliverables_list.html', {
        'deliverables': deliverables,
        'status': status,
        'status_choices': Deliverable.STATUS_CHOICES,
    })


@login_required
def project_board(request):
    """Kanban board réel : les projets de l'utilisateur, groupés par phase."""
    org_ids = _user_org_ids(request.user)
    projects = Project.objects.filter(organization_id__in=org_ids).select_related('client') if org_ids else Project.objects.none()

    today = timezone.localdate()
    for p in projects:
        p.is_late = bool(p.delivery_date and p.delivery_date < today and p.status != 'completed')
        p.is_due_soon = bool(
            p.delivery_date and not p.is_late and 0 <= (p.delivery_date - today).days <= 3 and p.status != 'completed'
        )

    organization = _first_user_organization(request.user)
    processes = _processes_context(organization)
    # Filtre par processus : ses étapes en colonnes et ses projets seulement (vide = tous).
    selected_process = next((p for p in processes if str(p['id']) == request.GET.get('process', '')), None)
    if organization and selected_process:
        process_obj = ProjectProcess.objects.get(id=selected_process['id'])
        phases = _phases_context(organization, process=process_obj)
        default_id = next((p['id'] for p in processes if p['is_default']), None)
        projects = [p for p in projects if p.process_id == process_obj.id or (p.process_id is None and process_obj.id == default_id)]
    else:
        phases = _phases_context(organization) if organization else []

    columns = []
    for phase in phases:
        cards = [p for p in projects if p.status == phase['value']]
        columns.append({
            'id': phase['value'], 'phase_id': phase['id'], 'label': phase['label'],
            'color': phase['color'], 'cards': cards,
        })

    clients = Client.objects.filter(organization=organization, is_active=True) if organization else Client.objects.none()
    clients_data = [
        {
            'id': c.id,
            'name': c.company_name or c.name,
            'initials': (c.company_name or c.name or '—').strip()[:2].upper(),
        }
        for c in clients
    ]

    return render(request, 'dashboard/projects.html', {
        'columns': columns,
        'has_projects': bool(projects),
        'clients': clients,
        'clients_data': clients_data,
        'status_choices': [(p['value'], p['label']) for p in phases],
        'phases': phases,
        'project_templates': ProjectTemplate.objects.filter(organization_id__in=org_ids) if org_ids else [],
        'processes': processes,
        'selected_process': selected_process,
    })


@login_required
def milestones_board(request):
    """
    Kanban jalons+tâches pour UN projet à la fois : les colonnes sont les phases
    du projet (Découverte -> Terminé), les cartes sont les jalons de ce projet
    (avec leurs tâches), et un sélecteur en haut change le projet affiché.
    """
    projects = list(
        _user_projects_queryset(request.user).select_related('client').order_by('-created_at')
    )

    selected_id = request.GET.get('project_id')
    project = None
    if selected_id:
        project = next((p for p in projects if str(p.id) == str(selected_id)), None)
    if project is None and projects:
        project = projects[0]

    columns = []
    tasks_by_milestone = {}
    milestones = []
    org_members = []
    files = []

    if project:
        today = timezone.localdate()
        project.is_late = bool(project.delivery_date and project.delivery_date < today and project.status != 'completed')
        project.is_due_soon = bool(
            project.delivery_date and not project.is_late
            and 0 <= (project.delivery_date - today).days <= 3 and project.status != 'completed'
        )

        from django.db.models import Count
        from .milestone_card import card_badges
        milestones = list(project.milestones.annotate(comment_count=Count('comments', distinct=True)).prefetch_related('members'))
        tasks = list(project.tasks.select_related('assignee').all())
        for t in tasks:
            t.assignee_initials = (
                (t.assignee.get_full_name() or t.assignee.email).strip()[:2].upper() if t.assignee_id else ''
            )
            tasks_by_milestone.setdefault(t.milestone_id, []).append(t)

        files_by_milestone = {}
        for f in MilestoneFile.objects.filter(milestone__in=milestones):
            files_by_milestone.setdefault(f.milestone_id, []).append(f)

        deliverables_by_milestone = {}
        for d in Deliverable.objects.filter(milestone__in=milestones):
            deliverables_by_milestone.setdefault(d.milestone_id, []).append(d)

        for m in milestones:
            m.task_list = tasks_by_milestone.get(m.id, [])
            m.file_list = files_by_milestone.get(m.id, [])
            m.deliverable_list = deliverables_by_milestone.get(m.id, [])
            m.tasks_total = len(m.task_list)
            m.tasks_done = sum(1 for t in m.task_list if t.status == 'done')
            m.progress_percent = round(100 * m.tasks_done / m.tasks_total) if m.tasks_total else 0
            m.form_fields_json = json.dumps(m.form_fields)
            m.badges = card_badges(m, today)
            m.member_list = [{'name': u.get_full_name() or u.email, 'initials': (u.get_full_name() or u.email)[:2].upper()}
                             for u in m.members.all()]

        phases = _phases_context(project.organization, project=project)
        for phase in phases:
            cards = [m for m in milestones if m.phase == phase['value']]
            columns.append({
                'id': phase['value'], 'phase_id': phase['id'], 'label': phase['label'],
                'color': phase['color'], 'cards': cards,
            })

        org_members = _organization_members_data(project.organization)
        files = project.files.all()

    return render(request, 'dashboard/milestones_board.html', {
        'projects': projects,
        'project': project,
        'columns': columns,
        'milestones': milestones,
        'org_members': org_members,
        'label_colors': list(__import__('apps.dashboard.milestone_card', fromlist=['COLOR_NAMES']).COLOR_NAMES.items()),
        'files': files,
        'task_status_choices': Task.STATUS_CHOICES,
    })


@require_POST
@login_required
def phase_create(request):
    """Crée une nouvelle phase (colonne) personnalisée pour l'organisation courante."""
    organization = _first_user_organization(request.user)
    if not organization:
        return JsonResponse({'success': False, 'message': 'Aucune organisation trouvée.'}, status=400)

    label = (request.POST.get('label') or '').strip()
    if not label:
        return JsonResponse({'success': False, 'message': 'Nom de phase requis.'}, status=400)

    existing = ProjectPhase.for_organization(organization)
    base_key = slugify(label)[:26] or 'phase'
    key = base_key
    existing_keys = {p.key for p in existing}
    n = 2
    while key in existing_keys:
        key = f"{base_key}-{n}"
        n += 1

    order = max((p.order for p in existing), default=-1) + 1
    # Une nouvelle étape s'insère avant « Terminé » quand c'est la dernière colonne :
    # sinon le stepper du projet affichait « … → Terminé → Tournage → Post-production ».
    if existing and existing[-1].key == 'completed':
        completed = existing[-1]
        order = completed.order
        completed.order = order + 1
        completed.save(update_fields=['order'])
    phase = ProjectPhase.objects.create(
        organization=organization, key=key, label=label,
        color=request.POST.get('color') or '#6366f1',
        order=order,
    )
    # La nouvelle étape rejoint le processus affiché (ou le processus par défaut), avant « Terminé ».
    process = ProjectProcess.objects.filter(organization=organization, id=request.POST.get('process_id') or 0).first()         or ProjectProcess.default_for(organization)
    process.phase_keys = add_phase_key(process.phase_keys, key)
    process.save(update_fields=['phase_keys'])
    return JsonResponse({'success': True, 'phase': {'value': phase.key, 'label': phase.label, 'color': phase.color}})


@require_POST
@login_required
def phase_delete(request, phase_id):
    """Supprime une phase, si elle n'est plus utilisée par aucun projet/jalon de l'organisation."""
    organization = _first_user_organization(request.user)
    phase = get_object_or_404(ProjectPhase, id=phase_id, organization=organization)

    remaining = ProjectPhase.objects.filter(organization=organization).exclude(id=phase.id).count()
    if remaining == 0:
        return JsonResponse({'success': False, 'message': 'Impossible de supprimer la dernière phase.'}, status=400)

    in_use = (
        Project.objects.filter(organization=organization, status=phase.key).exists()
        or Milestone.objects.filter(project__organization=organization, phase=phase.key).exists()
    )
    if in_use:
        return JsonResponse({
            'success': False,
            'message': 'Cette phase est encore utilisée par des projets ou des jalons. Déplacez-les avant de la supprimer.',
        }, status=400)

    for process in ProjectProcess.objects.filter(organization=organization):
        if phase.key in (process.phase_keys or []):
            process.phase_keys = [k for k in process.phase_keys if k != phase.key]
            process.save(update_fields=['phase_keys'])
    phase.delete()
    return JsonResponse({'success': True})


@require_POST
@login_required
def phase_move(request, phase_id):
    """Déplace une phase (colonne) d'un cran à gauche ou à droite dans le Kanban."""
    organization = _first_user_organization(request.user)
    phase = get_object_or_404(ProjectPhase, id=phase_id, organization=organization)

    direction = request.POST.get('direction')
    if direction not in ('left', 'right'):
        return JsonResponse({'success': False, 'message': 'Direction invalide.'}, status=400)

    ordered = list(ProjectPhase.objects.filter(organization=organization).order_by('order', 'id'))
    index = next((i for i, p in enumerate(ordered) if p.id == phase.id), None)
    swap_index = index - 1 if direction == 'left' else index + 1
    if swap_index < 0 or swap_index >= len(ordered):
        return JsonResponse({'success': True, 'phases': [{'id': p.id, 'order': p.order} for p in ordered]})

    other = ordered[swap_index]
    phase.order, other.order = other.order, phase.order
    ProjectPhase.objects.bulk_update([phase, other], ['order'])

    ordered[index], ordered[swap_index] = ordered[swap_index], ordered[index]
    return JsonResponse({'success': True, 'phases': [{'id': p.id, 'order': p.order} for p in ordered]})


@require_POST
@login_required
def milestone_update_phase(request, milestone_id):
    """Change la phase (colonne) d'un jalon — appelé par le drag & drop du Kanban jalons."""
    milestone = get_object_or_404(
        Milestone.objects.filter(project__in=_user_projects_queryset(request.user)), id=milestone_id
    )
    new_phase = request.POST.get('phase', '')
    valid_phases = {p['value'] for p in _phases_context(milestone.project.organization, project=milestone.project)}
    if new_phase not in valid_phases:
        return JsonResponse({'success': False, 'message': 'Phase invalide.'}, status=400)

    milestone.phase = new_phase
    milestone.save(update_fields=['phase', 'updated_at'])
    return JsonResponse({'success': True})


@login_required
def project_create(request):
    """Créer un nouveau projet."""
    organization = _first_user_organization(request.user)
    phases = _phases_context(organization) if organization else []
    if request.method == 'POST':
        if not organization:
            return JsonResponse({'success': False, 'message': 'Aucune organisation trouvée.'}, status=400)

        client_id = request.POST.get('client_id')
        client = get_object_or_404(Client, id=client_id, organization=organization)

        template = ProjectTemplate.objects.filter(organization=organization, id=request.POST.get('template_id') or 0).first()
        process = ProjectProcess.objects.filter(organization=organization, id=request.POST.get('process_id') or 0).first()
        if process is None and template and (template.data or {}).get('process'):
            process = ProjectProcess.objects.filter(organization=organization, name=template.data['process']).first()
        process = process or ProjectProcess.default_for(organization)
        # Étapes personnalisées à la création : processus propre au projet, ou nouveau processus réutilisable.
        try:
            custom_steps = json.loads(request.POST.get('custom_steps') or '[]')
        except ValueError:
            custom_steps = []
        if isinstance(custom_steps, list) and custom_steps:
            from .process_views import save_steps
            keys = save_steps(organization, custom_steps, rename_shared=False)
            if keys:
                reusable = request.POST.get('save_process') == '1' and (request.POST.get('process_name') or '').strip()
                base = (request.POST.get('process_name') or '').strip()[:70] if reusable else                     f"Étapes de « {(request.POST.get('name') or 'Nouveau projet').strip()[:50]} »"
                name, n = base, 2
                while ProjectProcess.objects.filter(organization=organization, name=name).exists():
                    name, n = f'{base} ({n})', n + 1
                process = ProjectProcess.objects.create(
                    organization=organization, name=name, phase_keys=keys, is_private=not reusable,
                    order=ProjectProcess.objects.filter(organization=organization).count(),
                )
        phases = _phases_context(organization, process=process)
        valid_phases = {p['value'] for p in phases}
        status = request.POST.get('status') or ''
        if status not in valid_phases:
            status = phases[0]['value'] if phases else 'discovery'

        project = Project.objects.create(
            organization=organization,
            client=client,
            process=process,
            name=request.POST.get('name') or 'Nouveau projet',
            reference=request.POST.get('reference', ''),
            description=request.POST.get('description', ''),
            status=status,
            start_date=request.POST.get('start_date') or None,
            delivery_date=request.POST.get('delivery_date') or None,
            created_by=request.user,
        )

        if template:
            project_templates.instantiate(template.data, project, user=request.user)
        elif 'onboarding' in valid_phases:
            Milestone.objects.create(
                project=project, title='Spécifications client', phase='onboarding',
                description="Recueillir les besoins du client via le questionnaire de cadrage.",
                created_by=request.user,
            )

        from .automation_engine import run_automations
        run_automations(
            organization, 'project_created',
            target_type='project', target_id=project.id, client_id=client.id, project_id=project.id,
            variables={'client': client.name, 'projet': project.name},
            context_label=f"Projet « {project.name} » créé pour {client.name}.",
        )

        return redirect('dashboard:project-detail', project_id=project.id)

    clients = Client.objects.filter(organization=organization, is_active=True) if organization else Client.objects.none()
    next_reference = ''
    if organization:
        next_reference = f"PRJ-{Project.objects.filter(organization=organization).count() + 1:04d}"
    return render(request, 'dashboard/project_create.html', {
        'organization': organization,
        'clients': clients,
        'status_choices': [(p['value'], p['label']) for p in phases],
        'next_reference': next_reference,
        'processes': _processes_context(organization),
    })


@login_required
def project_detail(request, project_id):
    """Page détail d'un projet : en-tête, milestones, tâches, livrables, fichiers, commentaires."""
    project = get_object_or_404(_user_projects_queryset(request.user), id=project_id)

    today = timezone.localdate()
    project.is_late = bool(project.delivery_date and project.delivery_date < today and project.status != 'completed')
    project.is_due_soon = bool(
        project.delivery_date and not project.is_late
        and 0 <= (project.delivery_date - today).days <= 3 and project.status != 'completed'
    )

    tasks = list(project.tasks.select_related('assignee', 'milestone').all())
    for t in tasks:
        t.assignee_initials = (
            (t.assignee.get_full_name() or t.assignee.email).strip()[:2].upper() if t.assignee_id else ''
        )
        t.phase = t.milestone.phase if t.milestone_id else ''

    milestones = list(project.milestones.all())
    tasks_by_milestone = {}
    for t in tasks:
        tasks_by_milestone.setdefault(t.milestone_id, []).append(t)
    for m in milestones:
        m_tasks = tasks_by_milestone.get(m.id, [])
        m.tasks_total = len(m_tasks)
        m.tasks_done = sum(1 for t in m_tasks if t.status == 'done')
        m.progress_percent = round(100 * m.tasks_done / m.tasks_total) if m.tasks_total else 0
        m.form_fields_json = json.dumps(m.form_fields)
        m.grouped_tasks = m_tasks
    orphan_tasks = tasks_by_milestone.get(None, [])
    org_phases = _phases_context(project.organization, project=project)
    phase_counts = {p['value']: 0 for p in org_phases}
    for m in milestones:
        phase_counts[m.phase] = phase_counts.get(m.phase, 0) + 1
    phases = [
        {'value': p['value'], 'label': p['label'], 'color': p['color'], 'count': phase_counts.get(p['value'], 0)}
        for p in org_phases
    ]

    # Onglet Plan : jalons (et leurs tâches) regroupés par phase, dans l'ordre des phases.
    milestones_by_phase = {}
    for m in milestones:
        milestones_by_phase.setdefault(m.phase, []).append(m)
    known_phases = {p['value'] for p in phases}
    phase_groups = []
    for p in phases + [
        {'value': key, 'label': key, 'color': '#a1a1aa'} for key in milestones_by_phase if key not in known_phases
    ]:
        group = milestones_by_phase.get(p['value'])
        if not group:
            continue
        group_tasks = [t for m in group for t in m.grouped_tasks]
        phase_groups.append({
            'value': p['value'], 'label': p['label'], 'color': p['color'],
            'is_current': p['value'] == project.status,
            'milestones': group,
            'milestones_done': sum(1 for m in group if m.is_completed),
            'tasks_total': len(group_tasks),
            'tasks_done': sum(1 for t in group_tasks if t.status == 'done'),
        })

    # Résumé par étape pour le sélecteur d'étapes (jalons et tâches atteints / total).
    phase_stats = {p['value']: {'label': p['label'], 'milestones': 0, 'done': 0, 'tasks': 0, 'tasks_done': 0} for p in phases}
    for g in phase_groups:
        phase_stats.setdefault(g['value'], {'label': g['label']}).update(
            milestones=len(g['milestones']), done=g['milestones_done'], tasks=g['tasks_total'], tasks_done=g['tasks_done'])

    meetings = list(project.meetings.all())
    for m in meetings:
        m.is_past_display = m.is_past

    deliverables = list(project.deliverables.select_related('milestone').prefetch_related('files', 'comments'))
    files = list(project.files.all())
    summary = _project_summary(project, tasks, milestones, deliverables, meetings, phases, today)

    return render(request, 'dashboard/project_detail.html', {
        'project': project,
        'summary': summary,
        'next_steps': _project_next_steps(project, tasks, milestones, deliverables, meetings, phases, summary),
        'current_phase': next((p for p in phases if p['value'] == project.status), None),
        'deliverables': deliverables,
        'files': files,
        'milestones': milestones,
        'tasks': tasks,
        'phase_groups': phase_groups,
        'phase_stats_json': json.dumps(phase_stats),
        'time': __import__('apps.dashboard.time_views', fromlist=['time_summary']).time_summary(project),
        'time_access': _time_access(project.organization),
        'orphan_tasks': orphan_tasks,
        'meetings': meetings,
        'org_members': _organization_members_data(project.organization),
        'phases': phases,
        'processes': _processes_context(project.organization),
        'current_process': project.process or ProjectProcess.default_for(project.organization),
        'task_status_choices': Task.STATUS_CHOICES,
        'client_brief_json': json.dumps(project.client_brief),
        'phase_labels_json': json.dumps({p['value']: p['label'] for p in phases}),
    })


def _project_summary(project, tasks, milestones, deliverables, meetings, phases, today):
    """Chiffres clés de l'en-tête du projet."""
    from decimal import Decimal
    now = timezone.now()
    upcoming = [m for m in meetings if m.status == 'scheduled' and m.scheduled_at >= now]
    open_milestones = sorted((m for m in milestones if not m.is_completed), key=lambda m: (m.due_date is None, m.due_date or today))
    unpaid = sum((m.amount or Decimal('0')) for m in milestones if m.amount and not m.is_paid)
    phase_index = next((i for i, p in enumerate(phases) if p['value'] == project.status), 0)
    return {
        'tasks_total': len(tasks),
        'tasks_done': sum(1 for t in tasks if t.status == 'done'),
        'tasks_late': sum(1 for t in tasks if t.is_late),
        'milestones_total': len(milestones),
        'milestones_done': sum(1 for m in milestones if m.is_completed),
        'deliverables_total': len(deliverables),
        'deliverables_approved': sum(1 for d in deliverables if d.status == 'approved'),
        'deliverables_waiting': sum(1 for d in deliverables if d.status == 'submitted'),
        'next_meeting': upcoming[0] if upcoming else None,
        'next_milestone': open_milestones[0] if open_milestones else None,
        'days_left': (project.delivery_date - today).days if project.delivery_date else None,
        'unpaid_amount': unpaid,
        'phase_index': phase_index,
    }


def _project_next_steps(project, tasks, milestones, deliverables, meetings, phases, summary):
    """
    « À faire maintenant » : actions concrètes déduites de l'état du projet, la plus urgente d'abord.
    Chaque étape : {tone: danger|warning|info|success, icon, text, tab}.
    """
    steps = []
    add = lambda tone, icon, text, tab: steps.append({'tone': tone, 'icon': icon, 'text': text, 'tab': tab})
    if project.is_late:
        add('danger', 'alarm-clock', f"La livraison était prévue le {project.delivery_date:%d/%m/%Y} : mettez à jour la date ou prévenez le client.", 'plan')
    for d in deliverables:
        if d.status == 'changes_requested':
            add('danger', 'message-square-warning', f"Le client demande des modifications sur « {d.title} ».", 'livrables')
    if summary['tasks_late']:
        n = summary['tasks_late']
        add('warning', 'clock-alert', f"{n} tâche{'s' if n > 1 else ''} en retard à traiter.", 'plan')
    for d in deliverables:
        if d.status == 'submitted':
            add('info', 'hourglass', f"« {d.title} » attend la validation du client.", 'livrables')
        elif d.status == 'in_progress' and not d.files.all():
            add('info', 'paperclip', f"Joignez un fichier à « {d.title} » puis envoyez-le au client.", 'livrables')
    if not milestones:
        add('info', 'flag', "Découpez le projet en jalons (étapes clés) pour suivre l'avancement et le partager au client.", 'plan')
    elif summary['next_milestone']:
        m = summary['next_milestone']
        when = f" — échéance le {m.due_date:%d/%m}" if m.due_date else ''
        add('info', 'flag', f"Prochain jalon : « {m.title} »{when}.", 'plan')
    brief = (project.client_brief or {}).get(project.status) if isinstance(project.client_brief, dict) else None
    phase_label = next((p['label'] for p in phases if p['value'] == project.status), project.status)
    if not brief:
        add('info', 'clipboard-list', f"Préparez les questions de cadrage de la phase « {phase_label} » : le client y répond depuis son espace.", 'cadrage')
    else:
        empty = sum(1 for f in brief if not f.get('answer'))
        if empty:
            add('warning', 'clipboard-list', f"{empty} question{'s' if empty > 1 else ''} de cadrage sans réponse.", 'cadrage')
    if summary['next_meeting']:
        m = summary['next_meeting']
        add('info', 'video', f"Réunion « {m.title} » le {timezone.localtime(m.scheduled_at):%d/%m à %H:%M}.", 'reunions')
    if project.billing_mode == 'per_milestone' and summary['unpaid_amount']:
        add('warning', 'banknote', f"{summary['unpaid_amount']:.2f} € de jalons restent à encaisser.".replace('.', ','), 'plan')
    if not steps:
        add('success', 'party-popper', "Tout est à jour. Rien d'urgent sur ce projet.", '')
    order = {'danger': 0, 'warning': 1, 'info': 2, 'success': 3}
    return sorted(steps, key=lambda s: order[s['tone']])[:6]


@require_POST
@login_required
def project_update_status(request, project_id):
    """Change la phase d'un projet (appelé par le drag & drop du kanban)."""
    project = get_object_or_404(_user_projects_queryset(request.user), id=project_id)
    new_status = request.POST.get('status', '')
    valid_statuses = {p['value'] for p in _phases_context(project.organization, project=project)}
    if new_status not in valid_statuses:
        return JsonResponse({'success': False, 'message': 'Statut invalide.'}, status=400)

    previous = project.status
    project.status = new_status
    project.save(update_fields=['status', 'updated_at'])
    if new_status != previous:
        label = next((p['label'] for p in _phases_context(project.organization, project=project) if p['value'] == new_status), new_status)
        notify_client(
            'phase_changed', project.client, f"Nouvelle étape « {label} » — {project.name}",
            "Votre projet avance : consultez la nouvelle étape et ce qui est attendu de votre part.", project=project,
        )
    return JsonResponse({'success': True})


@require_POST
@login_required
def project_update_billing(request, project_id):
    """Change le mode de facturation du projet (globale ou paiement par jalon)."""
    project = get_object_or_404(_user_projects_queryset(request.user), id=project_id)
    billing_mode = request.POST.get('billing_mode', '')
    if billing_mode not in dict(Project.BILLING_MODE_CHOICES):
        return JsonResponse({'success': False, 'message': 'Mode de facturation invalide.'}, status=400)

    project.billing_mode = billing_mode
    project.save(update_fields=['billing_mode', 'updated_at'])
    return JsonResponse({'success': True})


@require_POST
@login_required
def project_brief_update(request, project_id):
    """Enregistre le questionnaire de cadrage d'une phase (questions + réponses, modifiable en interne)."""
    project = get_object_or_404(_user_projects_queryset(request.user), id=project_id)

    phase = request.POST.get('phase') or project.status
    valid_phases = {p['value'] for p in _phases_context(project.organization, project=project)}
    if phase not in valid_phases:
        return JsonResponse({'success': False, 'message': 'Phase invalide.'}, status=400)

    try:
        fields = json.loads(request.POST.get('fields', '[]'))
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Formulaire invalide.'}, status=400)

    cleaned = []
    if isinstance(fields, list):
        for field in fields:
            if not isinstance(field, dict):
                continue
            label = (field.get('label') or '').strip()
            if not label:
                continue
            cleaned.append({'label': label, 'answer': (field.get('answer') or '').strip()})

    client_brief = dict(project.client_brief) if isinstance(project.client_brief, dict) else {}
    if cleaned:
        client_brief[phase] = cleaned
    else:
        client_brief.pop(phase, None)
    project.client_brief = client_brief
    project.save(update_fields=['client_brief', 'updated_at'])
    return JsonResponse({'success': True, 'fields': cleaned})


@require_POST
@login_required
def project_duplicate(request, project_id):
    """
    Duplique un projet avec ses jalons, tâches, livrables et questionnaires (sans fichiers,
    ni avancement, ni paiements). Les dates sont recalées pour démarrer aujourd'hui.
    """
    original = get_object_or_404(_user_projects_queryset(request.user), id=project_id)
    today = timezone.localdate()
    shift = (today - original.start_date) if original.start_date else None
    phases = _phases_context(original.organization, process=original.process) if original.process_id else _phases_context(original.organization, process=ProjectProcess.default_for(original.organization))
    duplicate = Project.objects.create(
        organization=original.organization,
        client=original.client,
        process=original.process,
        name=f"{original.name} (copie)",
        description=original.description,
        status=phases[0]['value'] if phases else original.status,
        start_date=today,
        delivery_date=(original.delivery_date + shift) if original.delivery_date and shift is not None else None,
        created_by=request.user,
    )
    project_templates.instantiate(project_templates.snapshot(original), duplicate, user=request.user)
    return JsonResponse({'success': True, 'id': duplicate.id})


@require_POST
@login_required
def project_save_as_template(request, project_id):
    """Fige la structure du projet (jalons, tâches, livrables, questionnaires) en modèle réutilisable."""
    project = get_object_or_404(_user_projects_queryset(request.user), id=project_id)
    name = (request.POST.get('name') or project.name).strip()[:200]
    template, created = ProjectTemplate.objects.update_or_create(
        organization=project.organization, name=name,
        defaults={'description': (request.POST.get('description') or project.description or '')[:300],
                  'trade': project.organization.trade, 'data': project_templates.snapshot(project),
                  'created_by': request.user},
    )
    return JsonResponse({'success': True, 'id': template.id, 'created': created,
                         'message': f"Modèle « {template.name} » {'créé' if created else 'mis à jour'} ({template.milestone_count} jalons)."})


@require_POST
@login_required
def project_template_delete(request, template_id):
    template = get_object_or_404(ProjectTemplate, id=template_id, organization_id__in=_user_org_ids(request.user))
    template.delete()
    return JsonResponse({'success': True})


@require_POST
@login_required
def project_delete(request, project_id):
    """Supprime un projet (et ses jalons/tâches/livrables/fichiers en cascade)."""
    project = get_object_or_404(_user_projects_queryset(request.user), id=project_id)
    project.delete()
    return JsonResponse({'success': True})


@require_POST
@login_required
def milestone_create(request, project_id):
    """Créer un jalon sur un projet."""
    project = get_object_or_404(_user_projects_queryset(request.user), id=project_id)
    valid_phases = {p['value'] for p in _phases_context(project.organization, project=project)}
    phase = request.POST.get('phase') or project.status
    if phase not in valid_phases:
        phase = project.status
    start_date, due_date = _normalized_task_dates(
        request.POST.get('start_date') or None, request.POST.get('due_date') or None
    )
    milestone = Milestone.objects.create(
        project=project,
        title=request.POST.get('title') or 'Nouveau jalon',
        start_date=start_date,
        due_date=due_date,
        phase=phase,
        amount=_parse_amount(request.POST.get('amount')),
        created_by=request.user,
    )

    from .automation_engine import run_automations
    run_automations(
        project.organization, 'milestone_created',
        target_type='milestone', target_id=milestone.id, client_id=project.client_id, project_id=project.id,
        variables={'client': project.client.name, 'projet': project.name},
        context_label=f"Jalon « {milestone.title} » créé sur le projet {project.name}.",
    )

    return JsonResponse({'success': True, 'milestone_id': milestone.id})


@require_POST
@login_required
def milestone_toggle(request, milestone_id):
    """Bascule l'état terminé/non terminé d'un jalon."""
    milestone = get_object_or_404(
        Milestone.objects.filter(project__in=_user_projects_queryset(request.user)), id=milestone_id
    )
    milestone.toggle()
    if milestone.is_completed:
        project = milestone.project
        notify_client('milestone_completed', project.client, f"Jalon atteint : « {milestone.title} »",
                      f"Projet « {project.name} ».", project=project)
    return JsonResponse({'success': True, 'is_completed': milestone.is_completed})


@require_POST
@login_required
def milestone_delete(request, milestone_id):
    """Supprime un jalon."""
    milestone = get_object_or_404(
        Milestone.objects.filter(project__in=_user_projects_queryset(request.user)), id=milestone_id
    )
    milestone.delete()
    return JsonResponse({'success': True})


@require_POST
@login_required
def milestone_update(request, milestone_id):
    """
    Modifie un jalon. Champs partiels : seuls les champs réellement envoyés dans le
    POST sont modifiés (permet un appel léger depuis le drag du Gantt, qui n'envoie
    que start_date/due_date, sans effacer le titre existant).
    """
    milestone = get_object_or_404(
        Milestone.objects.filter(project__in=_user_projects_queryset(request.user)), id=milestone_id
    )
    fields = ['updated_at']

    title = (request.POST.get('title') or '').strip()
    if title:
        milestone.title = title
        fields.append('title')

    if 'start_date' in request.POST or 'due_date' in request.POST:
        start_date = request.POST.get('start_date', milestone.start_date.isoformat() if milestone.start_date else '') or None
        due_date = request.POST.get('due_date', milestone.due_date.isoformat() if milestone.due_date else '') or None
        milestone.start_date, milestone.due_date = _normalized_task_dates(start_date, due_date)
        fields += ['start_date', 'due_date']

    if 'amount' in request.POST:
        milestone.amount = _parse_amount(request.POST.get('amount'))
        fields.append('amount')

    milestone.save(update_fields=fields)
    return JsonResponse({'success': True})


@require_POST
@login_required
def milestone_form_update(request, milestone_id):
    """Enregistre le formulaire libre (liste de questions/réponses) attaché à un jalon."""
    milestone = get_object_or_404(
        Milestone.objects.filter(project__in=_user_projects_queryset(request.user)), id=milestone_id
    )
    try:
        fields = json.loads(request.POST.get('fields', '[]'))
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Formulaire invalide.'}, status=400)

    cleaned = []
    if isinstance(fields, list):
        for field in fields:
            if not isinstance(field, dict):
                continue
            label = (field.get('label') or '').strip()
            if not label:
                continue
            cleaned.append({'label': label, 'answer': (field.get('answer') or '').strip()})

    milestone.form_fields = cleaned
    milestone.save(update_fields=['form_fields', 'updated_at'])
    return JsonResponse({'success': True, 'fields': cleaned})


def _normalized_task_dates(start_date, due_date):
    """Aligne due_date sur start_date si une date de début postérieure à l'échéance est fournie."""
    if start_date and due_date and start_date > due_date:
        due_date = start_date
    return start_date, due_date


def _aware_datetime(raw):
    """Valeur d'un <input type="datetime-local"> (heure locale, sans fuseau) -> datetime aware."""
    value = parse_datetime(raw or '')
    if value and timezone.is_naive(value):
        value = timezone.make_aware(value)
    return value


def _parse_amount(raw):
    """Parse un montant saisi en formulaire ; retourne None si vide ou invalide."""
    raw = (raw or '').strip().replace(',', '.')
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


@require_POST
@login_required
def task_create(request, project_id):
    """Créer une tâche sur un projet, éventuellement rattachée à un jalon."""
    project = get_object_or_404(_user_projects_queryset(request.user), id=project_id)
    assignee_id = request.POST.get('assignee_id') or None
    milestone_id = request.POST.get('milestone_id') or None
    if milestone_id:
        milestone_id = project.milestones.filter(id=milestone_id).values_list('id', flat=True).first()
    start_date, due_date = _normalized_task_dates(
        request.POST.get('start_date') or None, request.POST.get('due_date') or None
    )
    Task.objects.create(
        project=project,
        milestone_id=milestone_id,
        title=request.POST.get('title') or 'Nouvelle tâche',
        start_date=start_date,
        due_date=due_date,
        assignee_id=assignee_id,
        created_by=request.user,
    )
    return JsonResponse({'success': True})


@require_POST
@login_required
def task_update(request, task_id):
    """
    Modifie une tâche. Champs partiels : seuls les champs réellement envoyés dans le
    POST sont modifiés (permet un appel léger depuis le drag du Gantt, qui n'envoie
    que start_date/due_date, sans effacer l'assigné ou le titre existants).
    """
    task = get_object_or_404(
        Task.objects.filter(project__in=_user_projects_queryset(request.user)), id=task_id
    )
    fields = ['updated_at']

    title = (request.POST.get('title') or '').strip()
    if title:
        task.title = title
        fields.append('title')

    if 'start_date' in request.POST or 'due_date' in request.POST:
        start_date = request.POST.get('start_date', task.start_date.isoformat() if task.start_date else '') or None
        due_date = request.POST.get('due_date', task.due_date.isoformat() if task.due_date else '') or None
        task.start_date, task.due_date = _normalized_task_dates(start_date, due_date)
        fields += ['start_date', 'due_date']

    if 'assignee_id' in request.POST:
        task.assignee_id = request.POST.get('assignee_id') or None
        fields.append('assignee_id')

    task.save(update_fields=fields)
    return JsonResponse({'success': True})


@require_POST
@login_required
def task_update_status(request, task_id):
    """Change le statut d'une tâche (à faire / en cours / terminée)."""
    task = get_object_or_404(
        Task.objects.filter(project__in=_user_projects_queryset(request.user)), id=task_id
    )
    new_status = request.POST.get('status', '')
    valid_statuses = {value for value, _label in Task.STATUS_CHOICES}
    if new_status not in valid_statuses:
        return JsonResponse({'success': False, 'message': 'Statut invalide.'}, status=400)

    was_done = task.status == 'done'
    task.status = new_status
    task.completed_at = timezone.now() if new_status == 'done' else None
    task.save(update_fields=['status', 'completed_at', 'updated_at'])

    if new_status == 'done' and not was_done:
        from .automation_engine import run_automations
        run_automations(
            task.project.organization, 'task_completed',
            target_type='task', target_id=task.id,
            context_label=f"Tâche « {task.title} » terminée.",
        )
    return JsonResponse({'success': True})


@require_POST
@login_required
def task_delete(request, task_id):
    """Supprime une tâche."""
    task = get_object_or_404(
        Task.objects.filter(project__in=_user_projects_queryset(request.user)), id=task_id
    )
    task.delete()
    return JsonResponse({'success': True})


@require_POST
@login_required
def deliverable_create(request, project_id):
    """Créer un livrable sur un projet, éventuellement rattaché à un jalon."""
    project = get_object_or_404(_user_projects_queryset(request.user), id=project_id)
    milestone_id = request.POST.get('milestone_id') or None
    if milestone_id:
        milestone_id = project.milestones.filter(id=milestone_id).values_list('id', flat=True).first()
    deliverable = Deliverable.objects.create(
        project=project,
        milestone_id=milestone_id,
        title=request.POST.get('title') or 'Nouveau livrable',
        description=request.POST.get('description', ''),
        due_date=request.POST.get('due_date') or None,
        created_by=request.user,
    )
    return JsonResponse({'success': True, 'deliverable_id': deliverable.id})


@require_POST
@login_required
def deliverable_submit(request, deliverable_id):
    """Soumet un livrable au client (le rend visible/actionnable sur le portail)."""
    deliverable = get_object_or_404(
        Deliverable.objects.filter(project__in=_user_projects_queryset(request.user)), id=deliverable_id
    )
    deliverable.submit()
    project = deliverable.project
    notify_client(
        'deliverable_submitted', project.client, f"Livrable à valider : « {deliverable.title} »",
        f"Projet « {project.name} ». Validez-le ou demandez des modifications depuis votre espace.", project=project,
    )
    return JsonResponse({'success': True})


@require_POST
@login_required
def deliverable_file_upload(request, deliverable_id):
    """Upload d'un fichier sur un livrable."""
    deliverable = get_object_or_404(
        Deliverable.objects.filter(project__in=_user_projects_queryset(request.user)), id=deliverable_id
    )
    uploaded = request.FILES.get('file')
    if not uploaded:
        return JsonResponse({'success': False, 'message': 'Aucun fichier fourni.'}, status=400)

    _check_storage(deliverable.project.organization, uploaded)
    deliverable_file = DeliverableFile.objects.create(
        deliverable=deliverable, file=uploaded, name=request.POST.get('name') or uploaded.name,
        uploaded_by=request.user,
    )
    if deliverable.status != 'in_progress':  # fichier de travail : on ne prévient qu'une fois le livrable envoyé
        notify_client('file_shared', deliverable.project.client, f"Nouveau fichier : {deliverable_file.name}",
                      f"Ajouté au livrable « {deliverable.title} ».", project=deliverable.project)
    return JsonResponse({
        'success': True,
        'file': {'id': deliverable_file.id, 'name': deliverable_file.name, 'url': deliverable_file.file.url},
    })


@require_POST
@login_required
def milestone_file_upload(request, milestone_id):
    """Upload d'un fichier sur un jalon."""
    milestone = get_object_or_404(
        Milestone.objects.filter(project__in=_user_projects_queryset(request.user)), id=milestone_id
    )
    uploaded = request.FILES.get('file')
    if not uploaded:
        return JsonResponse({'success': False, 'message': 'Aucun fichier fourni.'}, status=400)

    _check_storage(milestone.project.organization, uploaded)
    milestone_file = MilestoneFile.objects.create(
        milestone=milestone, file=uploaded, name=request.POST.get('name') or uploaded.name,
        uploaded_by=request.user,
    )
    return JsonResponse({
        'success': True,
        'file': {'id': milestone_file.id, 'name': milestone_file.name, 'url': milestone_file.file.url},
    })


@require_POST
@login_required
def project_file_upload(request, project_id):
    """Upload d'un fichier général sur un projet."""
    project = get_object_or_404(_user_projects_queryset(request.user), id=project_id)
    uploaded = request.FILES.get('file')
    if not uploaded:
        return JsonResponse({'success': False, 'message': 'Aucun fichier fourni.'}, status=400)

    _check_storage(project.organization, uploaded)
    project_file = ProjectFile.objects.create(
        project=project, file=uploaded, name=request.POST.get('name') or uploaded.name,
        uploaded_by=request.user,
    )
    notify_client('file_shared', project.client, f"Nouveau fichier : {project_file.name}",
                  f"Ajouté au projet « {project.name} ».", project=project)
    return JsonResponse({
        'success': True,
        'file': {'id': project_file.id, 'name': project_file.name, 'url': project_file.file.url},
    })


@require_POST
@login_required
def meeting_create(request, project_id):
    """Planifie une réunion client sur un projet."""
    project = get_object_or_404(_user_projects_queryset(request.user), id=project_id)
    scheduled_at = _aware_datetime(request.POST.get('scheduled_at'))
    if not scheduled_at:
        return JsonResponse({'success': False, 'message': 'Date/heure requise.'}, status=400)

    meeting = Meeting.objects.create(
        project=project,
        title=request.POST.get('title') or 'Réunion client',
        scheduled_at=scheduled_at,
        duration_minutes=request.POST.get('duration_minutes') or 30,
        location=request.POST.get('location', ''),
        notes=request.POST.get('notes', ''),
        created_by=request.user,
    )
    meeting.refresh_from_db()
    _run_meeting_automations(meeting, 'meeting_created', target_id=meeting.id)
    _notify_meeting(meeting, 'meeting_scheduled', 'Réunion planifiée')
    return JsonResponse({'success': True, 'meeting_id': meeting.id})


@require_POST
@login_required
def meeting_update(request, meeting_id):
    """Modifie une réunion (titre, date, durée, lieu/lien, notes)."""
    meeting = get_object_or_404(
        Meeting.objects.filter(project__in=_user_projects_queryset(request.user)), id=meeting_id
    )
    before = (meeting.scheduled_at, meeting.location)
    title = (request.POST.get('title') or '').strip()
    if title:
        meeting.title = title
    scheduled_at = _aware_datetime(request.POST.get('scheduled_at'))
    if scheduled_at:
        meeting.scheduled_at = scheduled_at
    meeting.duration_minutes = request.POST.get('duration_minutes') or meeting.duration_minutes
    meeting.location = request.POST.get('location', meeting.location)
    meeting.notes = request.POST.get('notes', meeting.notes)
    meeting.save(update_fields=['title', 'scheduled_at', 'duration_minutes', 'location', 'notes', 'updated_at'])
    meeting.refresh_from_db()
    if (meeting.scheduled_at, meeting.location) != before:  # changement utile au client (pas une note interne)
        _notify_meeting(meeting, 'meeting_changed', 'Réunion modifiée')
    # Une exécution par modification (les workflows sont idempotents par cible).
    _run_meeting_automations(meeting, 'meeting_updated', target_id=f"{meeting.id}@{meeting.updated_at:%Y%m%d%H%M%S%f}")
    return JsonResponse({'success': True})


@require_POST
@login_required
def meeting_update_status(request, meeting_id):
    """Marque une réunion terminée / annulée / à nouveau planifiée."""
    meeting = get_object_or_404(
        Meeting.objects.filter(project__in=_user_projects_queryset(request.user)), id=meeting_id
    )
    new_status = request.POST.get('status', '')
    valid_statuses = {value for value, _label in Meeting.STATUS_CHOICES}
    if new_status not in valid_statuses:
        return JsonResponse({'success': False, 'message': 'Statut invalide.'}, status=400)

    previous = meeting.status
    meeting.status = new_status
    meeting.save(update_fields=['status', 'updated_at'])
    if new_status != previous:
        meeting.refresh_from_db()
        _run_meeting_automations(meeting, 'meeting_updated', target_id=f"{meeting.id}@{meeting.updated_at:%Y%m%d%H%M%S%f}")
        if new_status == 'cancelled':
            _notify_meeting(meeting, 'meeting_changed', 'Réunion annulée')
    return JsonResponse({'success': True})


def _run_meeting_automations(meeting, trigger_key, *, target_id):
    """Déclencheurs « Réunion planifiée » / « Réunion modifiée » (formulaire du projet)."""
    from .automation_engine import run_automations
    project = meeting.project
    when = timezone.localtime(meeting.scheduled_at)
    status = meeting.get_status_display().lower()
    action = 'planifiée' if trigger_key == 'meeting_created' else f'modifiée ({status})'
    run_automations(
        project.organization, trigger_key,
        target_type='meeting', target_id=target_id, client_id=project.client_id, project_id=project.id,
        variables={
            'projet': project.name, 'reunion': meeting.title,
            'date_reunion': when.strftime('%d/%m/%Y à %H:%M'), 'lieu': meeting.location or '',
        },
        context_label=f"Réunion « {meeting.title} » {action} le {when:%d/%m/%Y à %H:%M}.",
    )


def _notify_meeting(meeting, event, verb):
    project = meeting.project
    when = timezone.localtime(meeting.scheduled_at)
    where = f" · {meeting.location}" if meeting.location else ''
    notify_client(event, project.client, f"{verb} : « {meeting.title} »",
                  f"Le {when:%d/%m/%Y à %H:%M}{where} — projet « {project.name} ».", project=project)


@require_POST
@login_required
def meeting_delete(request, meeting_id):
    """Supprime une réunion."""
    meeting = get_object_or_404(
        Meeting.objects.filter(project__in=_user_projects_queryset(request.user)), id=meeting_id
    )
    meeting.delete()
    return JsonResponse({'success': True})


@require_POST
@login_required
def comment_create_org(request, deliverable_id):
    """Ajoute un commentaire (côté organisation) sur un livrable."""
    deliverable = get_object_or_404(
        Deliverable.objects.filter(project__in=_user_projects_queryset(request.user)), id=deliverable_id
    )
    body = (request.POST.get('body') or '').strip()
    if not body:
        return JsonResponse({'success': False, 'message': 'Commentaire vide.'}, status=400)

    comment = Comment.objects.create(
        deliverable=deliverable, author_type='org',
        author_name=request.user.get_full_name() or request.user.email,
        author_user=request.user, body=body,
    )
    notify_client('comment_added', deliverable.project.client,
                  f"{comment.author_name} a commenté « {deliverable.title} »", body[:300], project=deliverable.project)
    return JsonResponse({
        'success': True,
        'comment': {'id': comment.id, 'author_name': comment.author_name, 'body': comment.body},
    })


@login_required
def project_gantt(request, project_id):
    """
    Vue Gantt interactive d'un projet : une ligne d'en-tête par jalon (losange sur sa
    due_date) suivie de ses tâches (barre start_date -> due_date), plus un groupe
    « Sans jalon » pour les tâches orphelines. Les dates sont glissables côté client
    (drag = task-update / milestone-update).
    """
    project = get_object_or_404(_user_projects_queryset(request.user), id=project_id)
    today = timezone.localdate()

    phase_colors = {p['value']: p['color'] for p in _phases_context(project.organization)}
    default_color = '#6366f1'

    milestones = list(project.milestones.all())
    tasks = list(project.tasks.select_related('assignee', 'milestone').all())
    tasks_by_milestone = {}
    for t in tasks:
        tasks_by_milestone.setdefault(t.milestone_id, []).append(t)

    def _task_data(t, color):
        start = t.start_date or t.due_date
        end = t.due_date or t.start_date
        if not start or not end:
            fallback = today
            start = start or fallback
            end = end or fallback
        if end < start:
            end = start
        return {
            'id': t.id,
            'title': t.title,
            'start': start.isoformat(),
            'end': end.isoformat(),
            'status': t.status,
            'color': color,
            'assignee_initials': (
                (t.assignee.get_full_name() or t.assignee.email).strip()[:2].upper() if t.assignee_id else ''
            ),
            'assignee_id': t.assignee_id,
            'is_late': t.is_late,
        }

    groups = []
    for m in milestones:
        color = phase_colors.get(m.phase, default_color)
        groups.append({
            'id': f'milestone-{m.id}',
            'milestone_id': m.id,
            'title': m.title,
            'start': m.start_date.isoformat() if m.start_date else None,
            'due': m.due_date.isoformat() if m.due_date else None,
            'completed': m.is_completed,
            'color': color,
            'tasks': [_task_data(t, color) for t in tasks_by_milestone.get(m.id, [])],
        })

    orphan_tasks = tasks_by_milestone.get(None, [])
    if orphan_tasks or not groups:
        groups.append({
            'id': 'none',
            'milestone_id': None,
            'title': 'Sans jalon',
            'start': None,
            'due': None,
            'completed': False,
            'color': default_color,
            'tasks': [_task_data(t, default_color) for t in orphan_tasks],
        })

    all_starts = [t['start'] for g in groups for t in g['tasks']] + [g['start'] for g in groups if g['start']]
    all_ends = [t['end'] for g in groups for t in g['tasks']] + [g['due'] for g in groups if g['due']]
    project_start = project.start_date or min(all_starts, default=today.isoformat())
    project_end = project.delivery_date or max(all_ends, default=today.isoformat())
    if isinstance(project_start, str):
        project_start = timezone.datetime.fromisoformat(project_start).date()
    if isinstance(project_end, str):
        project_end = timezone.datetime.fromisoformat(project_end).date()
    if project_end < project_start:
        project_end = project_start

    gantt_data = {
        'project': {
            'name': project.name,
            'start': project_start.isoformat(),
            'end': project_end.isoformat(),
        },
        'today': today.isoformat(),
        'groups': groups,
    }

    return render(request, 'dashboard/project_gantt.html', {
        'project': project,
        'gantt_data': gantt_data,
        'org_members': _organization_members_data(project.organization),
        'task_status_choices': Task.STATUS_CHOICES,
    })
