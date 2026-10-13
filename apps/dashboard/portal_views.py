"""
Public, unauthenticated Client Portal views.

Access is via `Client.portal_token` (an unguessable UUID) acting as a bearer
token — same philosophy as the public Invoice/Quote links in
`apps/invoices/quote_views.py`. No login, no password, no session for clients.

Nothing in this file should ever carry a `@login_required` decorator.
"""
import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.clients.models import Client

from .models import Deliverable, Comment, ProjectFile, DeliverableFile, Meeting, Milestone, Notification
from .project_views import _phases_context


def portal_full_required(view):
    """
    Actions du portail complet (valider, commenter, déposer, répondre aux formulaires) :
    incluses à partir du forfait Starter. Sur le forfait Free, le portail reste en consultation.
    """
    from functools import wraps

    @wraps(view)
    def wrapper(request, portal_token, *args, **kwargs):
        from django.contrib import messages
        from apps.subscriptions.entitlements import has_feature
        client = get_object_or_404(Client, portal_token=portal_token)
        if not has_feature(client.organization, 'portal', 'full'):
            messages.info(request, "Cette action n'est pas disponible dans cet espace client : contactez directement votre interlocuteur.")
            return redirect('dashboard:public-portal-overview', portal_token=portal_token)
        return view(request, portal_token, *args, **kwargs)
    return wrapper


def _client_projects(client):
    return client.projects.all().order_by('-created_at')


def _client_safe_project_events(project):
    """
    Timeline simplifiée pour le Client Portal : uniquement les événements que le client
    a le droit de voir (livrables soumis/approuvés/modifications demandées, fichiers,
    jalons) — jamais de factures/paiements/webhooks internes ou de notes internes.
    """
    events = []

    for d in project.deliverables.all():
        if d.submitted_at:
            events.append({
                'icon': 'send', 'title': f"Livrable « {d.title} » envoyé",
                'description': '', 'date': d.submitted_at, 'is_milestone': False,
            })
        if d.approved_at:
            events.append({
                'icon': 'circle-check-big', 'title': f"Livrable « {d.title} » approuvé",
                'description': 'Vous avez approuvé ce livrable.', 'date': d.approved_at, 'is_milestone': True,
            })
        if d.changes_requested_at:
            events.append({
                'icon': 'rotate-ccw', 'title': f"Modifications demandées — « {d.title} »",
                'description': d.change_request_reason or '', 'date': d.changes_requested_at, 'is_milestone': False,
            })

    for f in ProjectFile.objects.filter(project=project):
        events.append({
            'icon': 'paperclip', 'title': f"Fichier « {f.name or f.file.name} » ajouté",
            'description': '', 'date': f.uploaded_at, 'is_milestone': False,
        })
    for f in DeliverableFile.objects.filter(deliverable__project=project):
        events.append({
            'icon': 'paperclip', 'title': f"Fichier « {f.name or f.file.name} » ajouté",
            'description': '', 'date': f.uploaded_at, 'is_milestone': False,
        })

    for m in project.milestones.filter(is_completed=True, completed_at__isnull=False):
        events.append({
            'icon': 'flag', 'title': f"Étape clé atteinte — « {m.title} »",
            'description': '', 'date': m.completed_at, 'is_milestone': True,
        })
    for t in project.tasks.filter(status='done', completed_at__isnull=False):
        events.append({
            'icon': 'check', 'title': f"Tâche terminée — « {t.title} »",
            'description': '', 'date': t.completed_at, 'is_milestone': False,
        })

    events.sort(key=lambda e: e['date'], reverse=True)
    return events


def portal_overview(request, portal_token):
    """Vue d'ensemble du portail : projets du client + éléments en attente."""
    client = get_object_or_404(Client, portal_token=portal_token)
    projects = _client_projects(client)
    pending_deliverables = Deliverable.objects.filter(
        project__client=client, status='submitted'
    ).select_related('project')
    upcoming_meetings = Meeting.objects.filter(
        project__client=client, status='scheduled'
    ).select_related('project').order_by('scheduled_at')
    invoices = client.invoices.exclude(status='draft').order_by('-issue_date')[:10]

    active_projects_count = sum(1 for p in projects if p.progress_percent < 100)
    completed_projects_count = sum(1 for p in projects if p.progress_percent >= 100 and (p.deliverables.exists() or p.milestones.exists()))
    average_progress = round(sum(p.progress_percent for p in projects) / len(projects)) if projects else 0
    next_milestone = Milestone.objects.filter(
        project__client=client, is_completed=False, due_date__isnull=False
    ).select_related('project').order_by('due_date').first()
    balance_due = sum(
        (inv.total_amount for inv in invoices if inv.status in ('sent', 'viewed', 'overdue')),
        start=0,
    )

    invoices_to_pay = [inv for inv in invoices if inv.status in ('sent', 'viewed', 'overdue')]

    context = {
        'client': client,
        'projects': projects,
        'pending_deliverables': pending_deliverables,
        'invoices_to_pay': invoices_to_pay,
        'pending_forms': client.forms.filter(status='pending'),
        'todo_count': pending_deliverables.count() + len(invoices_to_pay) + client.forms.filter(status='pending').count(),
        'upcoming_meetings': upcoming_meetings,
        'invoices': invoices,
        'quotes': client.quotes.exclude(status='draft').order_by('-issue_date')[:10],
        'documents': client.documents.exclude(status='draft').order_by('-created_at')[:10],
        'active_projects_count': active_projects_count,
        'completed_projects_count': completed_projects_count,
        'average_progress': average_progress,
        'next_milestone': next_milestone,
        'pending_actions_count': pending_deliverables.count(),
        'next_meeting': upcoming_meetings.first(),
        'balance_due': balance_due,
        'page_title': f"Espace client — {client.get_display_name()}",
    }
    return render(request, 'dashboard/public_portal_overview.html', context)


@require_POST
def portal_notifications_read(request, portal_token):
    """Le client ouvre la cloche : ses notifications passent en « lues »."""
    client = get_object_or_404(Client, portal_token=portal_token)
    client.portal_notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    return JsonResponse({'success': True})


def portal_document_view(request, portal_token, document_id):
    """Vue publique en lecture seule d'un document envoyé au client (variables résolues)."""
    client = get_object_or_404(Client, portal_token=portal_token)
    document = get_object_or_404(client.documents.exclude(status='draft'), id=document_id)

    from apps.documents.canvas_render import WEB_CANVAS_CSS, render_canvas_pages
    from .automation_engine import run_automations

    # Une seule exécution par document et par workflow (AutomationRun est idempotent).
    run_automations(
        document.organization, 'document_viewed',
        target_type='document', target_id=document.id, client_id=client.id,
        variables={'client': client.get_display_name(), 'numero': document.number},
        context_label=f"{client.get_display_name()} a consulté « {document.title} ».",
    )

    # Document avec champs de formulaire (sondage, demande…) : le client répond ici.
    from apps.documents.canvas_render import form_fields, read_form_answers
    from apps.documents.models import DocumentResponse
    fields = form_fields(document.canvas_data)
    response = DocumentResponse.objects.filter(document=document, client=client).first() if fields else None
    answers = dict(response.answers) if response else {}
    errors = {}
    if fields and request.method == 'POST':
        answers, errors = read_form_answers(document.canvas_data, request.POST)
        if not errors:
            response, _created = DocumentResponse.objects.update_or_create(
                document=document, client=client,
                defaults={'answers': answers, 'labels': {f['id']: f['label'] or 'Champ' for f in fields}},
            )
            owner = document.organization.owner
            if owner:
                summary = ' · '.join(f"{label} : {value}" for label, value in response.rows() if value)[:480]
                Notification.objects.create(
                    user=owner, notification_type='automation_task', priority='medium',
                    title=f"{client.get_display_name()} a répondu à « {document.title} »",
                    message=summary or 'Réponses envoyées.',
                )
            run_automations(
                document.organization, 'form_submitted',
                # Une exécution par envoi (le client peut modifier ses réponses plus tard).
                target_type='document', target_id=f"{document.id}@{int(response.updated_at.timestamp())}", client_id=client.id,
                variables={'client': client.get_display_name(), 'formulaire': document.title, 'numero': document.number},
                context_label=f"{client.get_display_name()} a répondu au formulaire « {document.title} ».",
            )
            return redirect(f"{request.path}?sent=1")

    context = {
        'client': client,
        'document': document,
        'pages': render_canvas_pages(
            document.canvas_data,
            page_format=document.get_style('page_format') or 'A4',
            orientation=document.get_style('page_orientation') or 'portrait',
            resolve=document.resolve_variables,
            interactive=bool(fields), answers=answers, sources=document.table_sources(),
        ),
        'is_form': bool(fields),
        # Le document a déjà son bouton « Envoyer » : pas de bouton de secours sous les pages.
        'has_button': any(e.get('type') == 'button' and not e.get('hidden') for p in (document.canvas_data or {}).get('pages') or [] for e in p.get('elements') or []),
        'response': response,
        'sent': request.GET.get('sent') == '1',
        'form_errors': [f"{f['label'] or 'Champ'} : {errors[f['id']]}" for f in fields if f['id'] in errors],
        'canvas_css': WEB_CANVAS_CSS,
        'page_title': f"{document.title} — {client.get_display_name()}",
    }
    return render(request, 'dashboard/public_portal_document.html', context)


def portal_project_detail(request, portal_token, project_id):
    """Détail d'un projet, scopé au client résolu par le jeton (pas juste l'ID)."""
    client = get_object_or_404(Client, portal_token=portal_token)
    project = get_object_or_404(_client_projects(client), id=project_id)

    today = timezone.localdate()
    milestones = list(project.milestones.all())
    tasks_by_milestone = {}
    for t in project.tasks.all():
        tasks_by_milestone.setdefault(t.milestone_id, []).append(t)
    for m in milestones:
        m.form_fields_json = json.dumps(m.form_fields)
        m_tasks = tasks_by_milestone.get(m.id, [])
        m.tasks_total = len(m_tasks)
        m.tasks_done = sum(1 for t in m_tasks if t.status == 'done')
        m.progress_percent = round(100 * m.tasks_done / m.tasks_total) if m.tasks_total else 0
        m.is_late = bool(m.due_date and m.due_date < today and not m.is_completed)

    phase_labels = {p['value']: p['label'] for p in _phases_context(project.organization)}
    client_brief = project.client_brief if isinstance(project.client_brief, dict) else {}
    brief_sections = [
        {'phase': phase, 'phase_label': phase_labels.get(phase, phase), 'fields_json': json.dumps(fields)}
        for phase, fields in client_brief.items() if fields
    ]

    context = {
        'client': client,
        'project': project,
        'milestones': milestones,
        'deliverables': project.deliverables.exclude(status='in_progress').prefetch_related('files', 'comments'),
        'files': project.files.all(),
        'meetings': project.meetings.exclude(status='cancelled'),
        'timeline_events': _client_safe_project_events(project),
        'page_title': f"{project.name} — {client.get_display_name()}",
        'brief_sections': brief_sections,
        'portal_full': __import__('apps.subscriptions.entitlements', fromlist=['has_feature']).has_feature(project.organization, 'portal', 'full'),
    }
    from apps.payments.stripe_checkout import stripe_instance
    context['card_payment'] = bool(stripe_instance(client.organization))
    return render(request, 'dashboard/public_portal_project.html', context)


@require_POST
@portal_full_required
def portal_project_brief_update(request, portal_token, project_id):
    """
    Action publique : le client répond au questionnaire de cadrage d'une phase (questions
    déjà définies côté organisation — le client ne peut que renseigner les réponses).
    """
    client = get_object_or_404(Client, portal_token=portal_token)
    project = get_object_or_404(_client_projects(client), id=project_id)

    phase = request.POST.get('phase') or ''
    client_brief = project.client_brief if isinstance(project.client_brief, dict) else {}
    if phase not in client_brief:
        return redirect('dashboard:public-portal-project-detail', portal_token=portal_token, project_id=project.id)

    try:
        submitted = json.loads(request.POST.get('fields', '[]'))
    except json.JSONDecodeError:
        submitted = []
    answers_by_label = {
        (f.get('label') or '').strip(): (f.get('answer') or '').strip()
        for f in submitted if isinstance(f, dict)
    }

    client_brief = dict(client_brief)
    client_brief[phase] = [
        {'label': field['label'], 'answer': answers_by_label.get(field['label'], field.get('answer', ''))}
        for field in client_brief[phase]
    ]
    project.client_brief = client_brief
    project.save(update_fields=['client_brief', 'updated_at'])
    return redirect('dashboard:public-portal-project-detail', portal_token=portal_token, project_id=project.id)


@require_POST
@portal_full_required
def portal_milestone_form_update(request, portal_token, milestone_id):
    """
    Action publique : le client répond au formulaire d'un jalon (questions déjà
    définies côté organisation — le client ne peut que renseigner les réponses,
    pas ajouter/renommer des questions). Notifie le(s) responsable(s) une fois soumis.
    """
    client = get_object_or_404(Client, portal_token=portal_token)
    milestone = get_object_or_404(Milestone.objects.filter(project__in=_client_projects(client)), id=milestone_id)

    try:
        submitted = json.loads(request.POST.get('fields', '[]'))
    except json.JSONDecodeError:
        submitted = []
    answers_by_label = {
        (f.get('label') or '').strip(): (f.get('answer') or '').strip()
        for f in submitted if isinstance(f, dict)
    }

    milestone.form_fields = [
        {'label': field['label'], 'answer': answers_by_label.get(field['label'], field.get('answer', ''))}
        for field in milestone.form_fields
    ]
    milestone.save(update_fields=['form_fields', 'updated_at'])

    organization = milestone.project.organization
    recipients = {organization.owner}
    if milestone.project.created_by_id:
        recipients.add(milestone.project.created_by)
    for user in recipients:
        if not user:
            continue
        Notification.objects.create(
            user=user,
            notification_type='milestone_form_submitted',
            title=f"Formulaire rempli — « {milestone.title} »",
            message=f"{client.get_display_name()} a rempli le formulaire du jalon « {milestone.title} » sur le projet {milestone.project.name}.",
            priority='medium',
            related_project=milestone.project,
        )

    return redirect('dashboard:public-portal-project-detail', portal_token=portal_token, project_id=milestone.project_id)


@require_POST
def portal_milestone_pay(request, portal_token, milestone_id):
    """
    Le client paie un jalon (projet en paiement par jalon) : session Stripe Checkout.
    Le jalon n'est marqué payé qu'après confirmation de Stripe (retour ou webhook).
    """
    from django.contrib import messages
    from django.urls import reverse
    from apps.integrations.providers import ProviderError
    from apps.payments.stripe_checkout import create_checkout

    client = get_object_or_404(Client, portal_token=portal_token)
    milestone = get_object_or_404(Milestone.objects.filter(project__in=_client_projects(client)), id=milestone_id)
    project = milestone.project
    project_url = reverse('dashboard:public-portal-project-detail', args=[portal_token, project.id])
    if project.billing_mode != 'per_milestone' or not milestone.amount or milestone.is_paid:
        return redirect(project_url)
    try:
        url = create_checkout(
            project.organization, amount=milestone.amount, currency='EUR',
            label=f"{project.name} — jalon « {milestone.title} »",
            metadata={'organization_id': project.organization_id, 'milestone_id': milestone.id},
            success_url=request.build_absolute_uri(
                reverse('dashboard:public-portal-milestone-pay-return', args=[portal_token, milestone.id])) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.build_absolute_uri(project_url),
            customer_email=client.email or '',
        )
    except ProviderError as exc:
        messages.error(request, str(exc))
        return redirect(project_url)
    return redirect(url)


def portal_milestone_pay_return(request, portal_token, milestone_id):
    """Retour de Stripe Checkout pour un jalon : session relue côté serveur."""
    from django.contrib import messages
    from apps.integrations.providers import ProviderError
    from apps.payments.stripe_checkout import record_checkout, retrieve_session

    client = get_object_or_404(Client, portal_token=portal_token)
    milestone = get_object_or_404(Milestone.objects.filter(project__in=_client_projects(client)), id=milestone_id)
    try:
        session = retrieve_session(milestone.project.organization, request.GET.get('session_id', ''))
    except ProviderError:
        session = None
    if session and str((session.get('metadata') or {}).get('milestone_id')) == str(milestone.id):
        record_checkout(milestone.project.organization, session)
    milestone.refresh_from_db()
    if milestone.is_paid:
        messages.success(request, f"Merci ! Le jalon « {milestone.title} » est réglé.")
    else:
        messages.info(request, 'Paiement en cours de confirmation par la banque.')
    return redirect('dashboard:public-portal-project-detail', portal_token=portal_token, project_id=milestone.project_id)


@require_POST
@portal_full_required
def portal_deliverable_approve(request, portal_token, deliverable_id):
    """Action publique : le client approuve un livrable soumis."""
    client = get_object_or_404(Client, portal_token=portal_token)
    deliverable = get_object_or_404(
        Deliverable.objects.filter(project__client=client, status='submitted'), id=deliverable_id
    )
    deliverable.approve(client_name=client.name)

    from apps.dashboard.automation_engine import run_automations
    project = deliverable.project
    run_automations(
        project.organization, 'deliverable_validated',
        target_type='deliverable', target_id=deliverable.id, client_id=client.id, project_id=project.id,
        variables={'client': client.name, 'projet': project.name, 'produit': deliverable.title},
        context_label=f"{client.get_display_name()} a validé le livrable « {deliverable.title} » sur le projet {project.name}.",
    )

    return redirect('dashboard:public-portal-project-detail', portal_token=portal_token, project_id=deliverable.project_id)


@require_POST
@portal_full_required
def portal_deliverable_request_changes(request, portal_token, deliverable_id):
    """Action publique : le client demande des modifications sur un livrable soumis."""
    client = get_object_or_404(Client, portal_token=portal_token)
    deliverable = get_object_or_404(
        Deliverable.objects.filter(project__client=client, status='submitted'), id=deliverable_id
    )
    reason = request.POST.get('reason', '')
    deliverable.request_changes(reason=reason, client_name=client.name)
    return redirect('dashboard:public-portal-project-detail', portal_token=portal_token, project_id=deliverable.project_id)


@require_POST
@portal_full_required
def portal_project_file_upload(request, portal_token, project_id):
    """Action publique : le client envoie un fichier dans le dossier du projet."""
    client = get_object_or_404(Client, portal_token=portal_token)
    project = get_object_or_404(_client_projects(client), id=project_id)

    uploaded = request.FILES.get('file')
    if uploaded:
        from django.contrib import messages
        from apps.subscriptions.entitlements import QuotaExceeded, enforce, forget_storage, require_quota
        try:
            with enforce():
                require_quota(project.organization, 'storage_mb', adding=uploaded.size)
        except QuotaExceeded:
            messages.error(request, "L'espace de stockage de votre interlocuteur est plein : envoyez-lui le fichier autrement.")
            return redirect('dashboard:public-portal-project-detail', portal_token=portal_token, project_id=project_id)
        forget_storage(project.organization)
        ProjectFile.objects.create(
            project=project, file=uploaded, name=uploaded.name, uploaded_by_client=True,
        )
    return redirect('dashboard:public-portal-project-detail', portal_token=portal_token, project_id=project_id)


@require_POST
@portal_full_required
def portal_comment_create(request, portal_token, deliverable_id):
    """Action publique : le client ajoute un commentaire sur un livrable de son projet."""
    client = get_object_or_404(Client, portal_token=portal_token)
    deliverable = get_object_or_404(
        Deliverable.objects.filter(project__client=client), id=deliverable_id
    )
    body = (request.POST.get('body') or '').strip()
    if body:
        Comment.objects.create(
            deliverable=deliverable, author_type='client', author_name=client.name, body=body,
        )
    return redirect('dashboard:public-portal-project-detail', portal_token=portal_token, project_id=deliverable.project_id)


def public_client_form(request, token):
    """
    Formulaire envoyé au client par une automatisation (« Envoyer un formulaire »).
    Public via son jeton ; une fois envoyé il passe en lecture seule. La soumission
    déclenche les automatisations « Formulaire client envoyé ».
    """
    from .models import ClientForm
    from .automation_engine import run_automations

    form = get_object_or_404(ClientForm.objects.select_related('client', 'organization', 'project'), token=token)
    client = form.client
    errors = {}
    values = dict(form.answers or {})

    if request.method == 'POST' and form.status == 'pending':
        values = {}
        for field in form.fields or []:
            fid, ftype = field.get('id'), field.get('type', 'text')
            if ftype == 'checkbox':
                value = 'Oui' if request.POST.get(fid) else 'Non'
            else:
                value = (request.POST.get(fid) or '').strip()[:5000]
            if ftype == 'select' and value:
                options = [o.strip() for o in (field.get('options') or '').split(',') if o.strip()]
                if value not in options:
                    errors[fid] = 'Choisissez une option de la liste.'
            if field.get('required') and ftype != 'checkbox' and not value:
                errors[fid] = 'Ce champ est obligatoire.'
            values[fid] = value

        if not errors:
            form.answers = values
            form.status = 'submitted'
            form.submitted_at = timezone.now()
            form.save(update_fields=['answers', 'status', 'submitted_at'])

            owner = form.organization.owner
            if owner:
                summary = ' · '.join(f"{a['label']} : {a['value']}" for a in form.answered_fields() if a['value'])[:480]
                Notification.objects.create(
                    user=owner, notification_type='automation_task', priority='medium',
                    title=f"{client.get_display_name()} a rempli « {form.title} »",
                    message=summary or 'Formulaire envoyé.',
                    **({'related_project': form.project} if form.project_id else {}),
                )
            run_automations(
                form.organization, 'form_submitted',
                target_type='form', target_id=form.id, client_id=client.id, project_id=form.project_id,
                variables={
                    'client': client.get_display_name(), 'formulaire': form.title,
                    'projet': form.project.name if form.project_id else '',
                },
                context_label=f"{client.get_display_name()} a envoyé le formulaire « {form.title} ».",
            )
            return redirect('dashboard:public-client-form', token=form.token)

    return render(request, 'dashboard/public_client_form.html', {
        'client': client,
        'form': form,
        'errors': errors,
        'values': values,
        'page_title': f"{form.title} — {client.get_display_name()}",
    })
