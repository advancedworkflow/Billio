"""
Fenêtre de détail d'un jalon, façon carte Trello (Kanban jalons) : titre, description,
étiquettes de couleur, couverture, membres, dates, checklist (les tâches du jalon),
pièces jointes, livrables, formulaire, montant et commentaires de l'équipe.

La carte du tableau reste compacte ; tout se modifie dans la fenêtre, sans recharger la page.
Les tâches passent par les vues existantes (task_create / task_update_status / task_delete).
"""
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import Milestone, MilestoneComment, MilestoneFile

# Couleurs d'étiquettes et de couverture : fond doux, texte lisible (pas de couleurs fluo).
LABEL_COLORS = {
    'green': ('#dcfce7', '#166534'), 'yellow': ('#fef9c3', '#854d0e'), 'orange': ('#ffedd5', '#9a3412'),
    'red': ('#fee2e2', '#991b1b'), 'purple': ('#ede9fe', '#5b21b6'), 'blue': ('#dbeafe', '#1e40af'),
    'sky': ('#e0f2fe', '#075985'), 'pink': ('#fce7f3', '#9d174d'), 'gray': ('#f4f4f5', '#3f3f46'),
}
COLOR_NAMES = {'green': 'Vert', 'yellow': 'Jaune', 'orange': 'Orange', 'red': 'Rouge', 'purple': 'Violet',
               'blue': 'Bleu', 'sky': 'Ciel', 'pink': 'Rose', 'gray': 'Gris'}
MAX_LABELS = 8


def _milestone(request, milestone_id):
    from .project_views import _user_projects_queryset
    return get_object_or_404(
        Milestone.objects.filter(project__in=_user_projects_queryset(request.user)).select_related('project', 'project__organization'),
        id=milestone_id,
    )


def _initials(user):
    return ((user.get_full_name() or user.email or '?').strip()[:2]).upper()


def clean_labels(raw):
    labels = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or item.get('color') not in LABEL_COLORS:
            continue
        labels.append({'text': str(item.get('text') or '').strip()[:30], 'color': item['color']})
    return labels[:MAX_LABELS]


def card_badges(milestone, today=None):
    """Infos courtes de la carte du tableau : échéance, checklist, pièces jointes, commentaires."""
    today = today or timezone.localdate()
    due = milestone.due_date
    return {
        'due_state': ('done' if milestone.is_completed else 'late' if due and due < today
                      else 'soon' if due and (due - today).days <= 2 else '') if due else '',
        'labels': [{'text': l['text'], 'bg': LABEL_COLORS[l['color']][0], 'fg': LABEL_COLORS[l['color']][1]}
                   for l in clean_labels(milestone.labels)],
        'cover': LABEL_COLORS.get(milestone.cover, ('', ''))[0],
    }


@require_GET
@login_required
def milestone_detail(request, milestone_id):
    from .project_views import _organization_members_data, _phases_context

    m = _milestone(request, milestone_id)
    project = m.project
    phase = next((p['label'] for p in _phases_context(project.organization, project=project) if p['value'] == m.phase), m.phase)
    tasks = list(m.tasks.select_related('assignee').order_by('order', 'created_at'))
    return JsonResponse({
        'id': m.id, 'project_id': project.id, 'project_name': project.name, 'phase': phase,
        'title': m.title, 'description': m.description,
        'start_date': m.start_date.isoformat() if m.start_date else '',
        'due_date': m.due_date.isoformat() if m.due_date else '',
        'is_completed': m.is_completed,
        'per_milestone': project.billing_mode == 'per_milestone',
        'amount': f'{m.amount}' if m.amount is not None else '', 'is_paid': m.is_paid,
        'labels': clean_labels(m.labels), 'cover': m.cover,
        'members': [{'id': u.id, 'name': u.get_full_name() or u.email, 'initials': _initials(u)} for u in m.members.all()],
        'org_members': _organization_members_data(project.organization),
        'tasks': [{'id': t.id, 'title': t.title, 'done': t.status == 'done', 'status': t.status,
                   'due_date': t.due_date.isoformat() if t.due_date else '',
                   'assignee': (t.assignee.get_full_name() or t.assignee.email) if t.assignee_id else ''} for t in tasks],
        'files': [{'id': f.id, 'name': f.name or f.file.name, 'url': f.file.url} for f in m.files.order_by('-id')],
        'deliverables': [{'title': d.title, 'status': d.get_status_display()} for d in m.deliverables.all()]
                        if hasattr(m, 'deliverables') else [],
        'form_fields': m.form_fields or [],
        'comments': [{'id': c.id, 'author': (c.author.get_full_name() or c.author.email) if c.author_id else 'Ancien membre',
                      'initials': _initials(c.author) if c.author_id else '?', 'body': c.body,
                      'date': timezone.localtime(c.created_at).strftime('%d/%m/%Y %H:%M'), 'own': c.author_id == request.user.id}
                     for c in m.comments.select_related('author')[:100]],
    })


@require_POST
@login_required
def milestone_card_update(request, milestone_id):
    """Mise à jour partielle (JSON) : seuls les champs envoyés changent."""
    from .project_views import _normalized_task_dates, _organization_members_data, _parse_amount

    m = _milestone(request, milestone_id)
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Données invalides.'}, status=400)
    fields = {'updated_at'}
    if 'title' in data and str(data['title']).strip():
        m.title = str(data['title']).strip()[:200]
        fields.add('title')
    if 'description' in data:
        m.description = str(data['description'] or '')[:20000]
        fields.add('description')
    if 'start_date' in data or 'due_date' in data:
        start = data.get('start_date', m.start_date.isoformat() if m.start_date else '') or None
        due = data.get('due_date', m.due_date.isoformat() if m.due_date else '') or None
        m.start_date, m.due_date = _normalized_task_dates(start, due)
        fields |= {'start_date', 'due_date'}
    if 'amount' in data:
        m.amount = _parse_amount(str(data['amount'] or ''))
        fields.add('amount')
    if 'labels' in data:
        m.labels = clean_labels(data['labels'])
        fields.add('labels')
    if 'cover' in data:
        m.cover = data['cover'] if data['cover'] in LABEL_COLORS else ''
        fields.add('cover')
    if 'is_completed' in data and bool(data['is_completed']) != m.is_completed:
        m.is_completed = bool(data['is_completed'])
        m.completed_at = timezone.now() if m.is_completed else None
        fields |= {'is_completed', 'completed_at'}
    m.save(update_fields=list(fields))
    if 'member_ids' in data:
        allowed = {member['id'] for member in _organization_members_data(m.project.organization)}
        m.members.set([int(i) for i in data['member_ids'] or [] if str(i).isdigit() and int(i) in allowed])
    return JsonResponse({'success': True})


@require_POST
@login_required
def milestone_comment_add(request, milestone_id):
    m = _milestone(request, milestone_id)
    body = (request.POST.get('body') or '').strip()
    if not body:
        return JsonResponse({'success': False, 'message': 'Écrivez un commentaire.'}, status=400)
    MilestoneComment.objects.create(milestone=m, author=request.user, body=body[:5000])
    return JsonResponse({'success': True})


@require_POST
@login_required
def milestone_comment_delete(request, comment_id):
    from .project_views import _user_projects_queryset
    comment = get_object_or_404(MilestoneComment, id=comment_id, author=request.user,
                                milestone__project__in=_user_projects_queryset(request.user))
    comment.delete()
    return JsonResponse({'success': True})


@require_POST
@login_required
def milestone_file_delete(request, file_id):
    from .project_views import _user_projects_queryset
    attachment = get_object_or_404(MilestoneFile, id=file_id, milestone__project__in=_user_projects_queryset(request.user))
    attachment.file.delete(save=False)
    attachment.delete()
    return JsonResponse({'success': True})
