"""
Plugins (page Intégrations) : configuration + test, connexion Google, actions Drive / Notion.

Toutes les réponses sont en JSON sauf la redirection OAuth Google et l'export CSV.
Les secrets ne sont jamais renvoyés au navigateur (providers.mask_config).
"""
import json
import uuid
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import exports, providers
from .models import ConnectionInstance, Connector
from .providers import PROVIDERS, ProviderError
from .views import _can_manage_integrations, _get_user_primary_organization, _notify_integration_event

GOOGLE_STATE_SALT = 'billio-google-drive'


def _payload(request):
    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body or b'{}')
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}
    return request.POST


def _error(message, status=400):
    return JsonResponse({'ok': False, 'error': str(message)}, status=status)


def _connected(organization, key):
    """Connexion active d'un plugin, ou ProviderError avec un message clair."""
    instance = ConnectionInstance.objects.filter(organization=organization, connector__key=key, status='connected').select_related('connector').first()
    if not instance:
        name = dict(Connector.objects.values_list('key', 'name')).get(key, key)
        raise ProviderError(f"{name} n'est pas connecté : ouvrez la page Intégrations.")
    return instance


def plugin_state(organization):
    """État des plugins pour la page Intégrations : {clé: {status, config masquée, erreur, …}}."""
    out = {}
    instances = {i.connector.key: i for i in ConnectionInstance.objects.filter(organization=organization).select_related('connector')} if organization else {}
    for key in PROVIDERS:
        instance = instances.get(key)
        out[key] = {
            'id': instance.id if instance else None,
            'status': instance.status if instance else 'not_connected',
            'config': providers.mask_config(key, instance.config if instance else {}),
            'error': instance.last_error if instance else '',
            'connected_at': timezone.localtime(instance.connected_at).strftime('%d/%m/%Y %H:%M') if instance and instance.connected_at else '',
        }
    return out


# --------------------------------------------------------------------------- #
# Configuration et test
# --------------------------------------------------------------------------- #

@login_required
@require_POST
def plugin_save(request, connector_key):
    """Enregistre la configuration d'un plugin puis la teste auprès du service."""
    organization = _get_user_primary_organization(request.user)
    if not organization or not _can_manage_integrations(request.user, organization):
        return _error("Vous n'avez pas les droits pour gérer les intégrations.", 403)
    connector = get_object_or_404(Connector, key=connector_key, is_active=True)
    spec = PROVIDERS.get(connector_key)
    if not spec or spec.get('oauth'):
        return _error('Ce plugin se connecte autrement.')
    from apps.subscriptions.entitlements import require_quota
    from .views import INTERNAL_CONNECTORS
    if connector_key not in INTERNAL_CONNECTORS and not ConnectionInstance.objects.filter(
            organization=organization, connector=connector, status='connected').exists():
        require_quota(organization, 'integrations')
    instance, _ = ConnectionInstance.objects.get_or_create(organization=organization, connector=connector)
    was_connected = instance.status == 'connected'
    try:
        config = providers.clean_config(connector_key, _payload(request), instance.config)
    except ProviderError as exc:
        return _error(exc)
    instance.config = config
    try:
        detail = providers.test_connection(connector_key, config, request.user, organization=organization)
        instance.status, instance.last_error = 'connected', ''
        instance.connected_at = instance.connected_at if was_connected else timezone.now()
        instance.connected_by = request.user
        instance.disconnected_at = None
    except ProviderError as exc:
        detail = str(exc)
        instance.status, instance.last_error = 'error', detail[:500]
    instance.save()
    if instance.status == 'connected' and not was_connected:
        _notify_integration_event(instance, 'integration_connected', request.user)
    return JsonResponse({
        'ok': instance.status == 'connected', 'detail': detail, 'status': instance.status,
        'config': providers.mask_config(connector_key, instance.config),
    })


@login_required
@require_POST
def plugin_test(request, connector_key):
    organization = _get_user_primary_organization(request.user)
    instance = ConnectionInstance.objects.filter(organization=organization, connector__key=connector_key).first() if organization else None
    if not instance or not instance.config:
        return _error("Enregistrez d'abord la configuration.")
    try:
        from .oauth import fresh_config
        detail = providers.test_connection(connector_key, fresh_config(instance), request.user, organization=instance.organization)
    except ProviderError as exc:
        if _can_manage_integrations(request.user, organization):
            instance.status, instance.last_error = 'error', str(exc)[:500]
            instance.save(update_fields=['status', 'last_error', 'updated_at'])
        return JsonResponse({'ok': False, 'detail': str(exc), 'status': instance.status})
    if instance.status != 'connected' and _can_manage_integrations(request.user, organization):
        instance.status, instance.last_error, instance.connected_at = 'connected', '', timezone.now()
        instance.save(update_fields=['status', 'last_error', 'connected_at', 'updated_at'])
    return JsonResponse({'ok': True, 'detail': detail, 'status': instance.status})


@login_required
@require_POST
def telegram_chats(request):
    """Conversations où le bot a reçu un message (pour choisir le chat ID sans le chercher)."""
    organization = _get_user_primary_organization(request.user)
    if not organization or not _can_manage_integrations(request.user, organization):
        return _error("Vous n'avez pas les droits pour gérer les intégrations.", 403)
    data = _payload(request)
    instance = ConnectionInstance.objects.filter(organization=organization, connector__key='telegram').first()
    token = (data.get('access_token') or '').strip() or (instance.config or {}).get('access_token', '') if instance else (data.get('access_token') or '').strip()
    if not token:
        return _error("Collez d'abord le jeton du bot.")
    try:
        chats = providers.telegram_chats({'access_token': token})
    except ProviderError as exc:
        return _error(exc)
    return JsonResponse({'ok': True, 'chats': chats})


# --------------------------------------------------------------------------- #
# Google Drive : connexion OAuth
# --------------------------------------------------------------------------- #

def _google_redirect_uri(request):
    return request.build_absolute_uri(reverse('integrations:google-callback'))


@login_required
def google_connect(request):
    organization = _get_user_primary_organization(request.user)
    if not organization or not _can_manage_integrations(request.user, organization):
        messages.error(request, "Vous n'avez pas les droits pour gérer les intégrations.")
        return redirect('integrations:integrations-page')
    if not providers.google_configured():
        messages.error(request, "Google Drive n'est pas encore activé sur ce serveur (identifiants Google manquants).")
        return redirect(f"{reverse('integrations:integrations-page')}?plugin=google-drive")
    from apps.subscriptions.entitlements import require_quota
    if not ConnectionInstance.objects.filter(organization=organization, connector__key='google-drive', status='connected').exists():
        require_quota(organization, 'integrations')
    nonce = uuid.uuid4().hex
    request.session['google_oauth_nonce'] = nonce
    state = signing.dumps({'org': organization.id, 'user': request.user.id, 'nonce': nonce}, salt=GOOGLE_STATE_SALT)
    return redirect(providers.google_auth_url(state, _google_redirect_uri(request)))


@login_required
def google_callback(request):
    target = f"{reverse('integrations:integrations-page')}?plugin=google-drive"
    if request.GET.get('error'):
        messages.error(request, 'Connexion Google annulée.')
        return redirect(target)
    try:
        state = signing.loads(request.GET.get('state', ''), salt=GOOGLE_STATE_SALT, max_age=900)
    except signing.BadSignature:
        messages.error(request, 'Lien de connexion expiré : recommencez.')
        return redirect(target)
    organization = _get_user_primary_organization(request.user)
    if (not organization or state.get('org') != organization.id or state.get('user') != request.user.id
            or state.get('nonce') != request.session.pop('google_oauth_nonce', None)
            or not _can_manage_integrations(request.user, organization)):
        messages.error(request, 'Connexion Google refusée (session différente).')
        return redirect(target)
    try:
        tokens = providers.google_exchange(request.GET.get('code', ''), _google_redirect_uri(request))
    except ProviderError as exc:
        messages.error(request, f'Connexion Google impossible : {exc}')
        return redirect(target)
    connector = get_object_or_404(Connector, key='google-drive')
    instance, _ = ConnectionInstance.objects.get_or_create(organization=organization, connector=connector)
    config = dict(instance.config or {})
    if not tokens.get('refresh_token') and config.get('refresh_token'):
        tokens['refresh_token'] = config['refresh_token']
    config.update(tokens)
    instance.config = config
    instance.status, instance.last_error = 'connected', ''
    instance.connected_by, instance.connected_at, instance.disconnected_at = request.user, timezone.now(), None
    instance.save()
    _notify_integration_event(instance, 'integration_connected', request.user)
    messages.success(request, f"Google Drive connecté ({tokens.get('account') or 'compte Google'}).")
    return redirect(target)


# --------------------------------------------------------------------------- #
# « Se connecter avec… » : OAuth générique (Slack, Notion, Mailchimp, HubSpot, Trello)
# --------------------------------------------------------------------------- #

OAUTH_STATE_SALT = 'billio-oauth'


def oauth_redirect_uri(request, key):
    return request.build_absolute_uri(reverse('integrations:oauth-callback', args=[key]))


def _oauth_target(key):
    return f"{reverse('integrations:integrations-page')}?plugin={key}"


@login_required
def oauth_connect(request, connector_key):
    from . import oauth
    target = _oauth_target(connector_key)
    organization = _get_user_primary_organization(request.user)
    if not organization or not _can_manage_integrations(request.user, organization):
        messages.error(request, "Vous n'avez pas les droits pour gérer les intégrations.")
        return redirect(target)
    if not oauth.configured(connector_key):
        messages.error(request, "La connexion en un clic n'est pas encore activée pour cet outil : utilisez le formulaire.")
        return redirect(target)
    get_object_or_404(Connector, key=connector_key, is_active=True)
    from apps.subscriptions.entitlements import require_quota
    if not ConnectionInstance.objects.filter(organization=organization, connector__key=connector_key, status='connected').exists():
        require_quota(organization, 'integrations')
    nonce = uuid.uuid4().hex
    request.session[f'oauth_nonce_{connector_key}'] = nonce
    state = signing.dumps({'org': organization.id, 'user': request.user.id, 'nonce': nonce, 'key': connector_key},
                          salt=OAUTH_STATE_SALT)
    return redirect(oauth.authorize_url(connector_key, state, oauth_redirect_uri(request, connector_key)))


def _check_state(request, connector_key, raw_state):
    """Organisation si l'état signé correspond à cette session et à cet outil, sinon None."""
    try:
        state = signing.loads(raw_state or '', salt=OAUTH_STATE_SALT, max_age=900)
    except signing.BadSignature:
        return None
    organization = _get_user_primary_organization(request.user)
    if (not organization or state.get('org') != organization.id or state.get('user') != request.user.id
            or state.get('key') != connector_key
            or state.get('nonce') != request.session.pop(f'oauth_nonce_{connector_key}', None)
            or not _can_manage_integrations(request.user, organization)):
        return None
    return organization


def _save_oauth(request, organization, connector_key, config):
    from . import oauth
    connector = get_object_or_404(Connector, key=connector_key)
    instance, _ = ConnectionInstance.objects.get_or_create(organization=organization, connector=connector)
    instance.config = dict(instance.config or {}, **config)
    instance.status, instance.last_error = 'connected', ''
    instance.connected_by, instance.connected_at, instance.disconnected_at = request.user, timezone.now(), None
    instance.save()
    _notify_integration_event(instance, 'integration_connected', request.user)
    messages.success(request, f"{oauth.OAUTH[connector_key]['name']} connecté ({config.get('account') or 'compte'}).")


@login_required
def oauth_callback(request, connector_key):
    from . import oauth
    if connector_key not in oauth.OAUTH:
        return redirect('integrations:integrations-page')
    target = _oauth_target(connector_key)
    if connector_key == 'trello':
        # Le jeton est dans le fragment (#token=…) : une page le lit et l'envoie à oauth_trello_finish.
        from django.shortcuts import render
        return render(request, 'integrations/oauth_trello.html', {'state': request.GET.get('state', ''), 'target': target})
    if request.GET.get('error'):
        messages.error(request, 'Connexion annulée.')
        return redirect(target)
    organization = _check_state(request, connector_key, request.GET.get('state'))
    if not organization:
        messages.error(request, 'Lien de connexion expiré ou session différente : recommencez.')
        return redirect(target)
    try:
        config = oauth.exchange(connector_key, request.GET.get('code', ''), oauth_redirect_uri(request, connector_key))
    except ProviderError as exc:
        messages.error(request, f'Connexion impossible : {exc}')
        return redirect(target)
    _save_oauth(request, organization, connector_key, config)
    return redirect(target)


@login_required
@require_POST
def oauth_trello_finish(request):
    from . import oauth
    target = _oauth_target('trello')
    organization = _check_state(request, 'trello', request.POST.get('state'))
    if not organization:
        messages.error(request, 'Lien de connexion expiré ou session différente : recommencez.')
        return redirect(target)
    try:
        config = oauth.trello_config(request.POST.get('token'))
    except ProviderError as exc:
        messages.error(request, str(exc))
        return redirect(target)
    _save_oauth(request, organization, 'trello', config)
    return redirect(target)


# --------------------------------------------------------------------------- #
# Google Drive : envoi de PDF, import de fichiers
# --------------------------------------------------------------------------- #

def _pdf_for(organization, kind, object_id):
    """(nom de fichier, octets PDF) d'une facture, d'un devis ou d'un document de l'organisation."""
    if kind == 'invoice':
        from apps.invoices.models import Invoice
        obj = get_object_or_404(Invoice, id=object_id, organization=organization)
        return f'Facture {obj.invoice_number}.pdf', obj.generate_pdf_bytes()
    if kind == 'quote':
        from apps.invoices.models import Quote
        obj = get_object_or_404(Quote, id=object_id, organization=organization)
        return f'Devis {obj.quote_number}.pdf', obj.generate_pdf_bytes()
    if kind == 'document':
        from apps.documents.models import Document
        obj = get_object_or_404(Document, id=object_id, organization=organization)
        return f'{obj.title} — {obj.number}.pdf', obj.generate_pdf_bytes()
    raise ProviderError('Type de document inconnu.')


@login_required
@require_POST
def drive_upload_pdf(request):
    organization = _get_user_primary_organization(request.user)
    data = _payload(request)
    try:
        instance = _connected(organization, 'google-drive')
        name, content = _pdf_for(organization, data.get('kind'), data.get('id'))
        file = providers.drive_upload(instance, name.replace('/', '-'), content, 'application/pdf')
    except ProviderError as exc:
        return _error(exc)
    except Exception as exc:  # rendu PDF
        return _error(f'PDF impossible : {exc}')
    return JsonResponse({'ok': True, 'name': file.get('name', name), 'link': file.get('webViewLink', '')})


@login_required
@require_GET
def drive_list(request):
    organization = _get_user_primary_organization(request.user)
    try:
        files = providers.drive_files(_connected(organization, 'google-drive'), request.GET.get('q', '').strip())
    except ProviderError as exc:
        return _error(exc)
    return JsonResponse({'ok': True, 'files': files})


@login_required
@require_POST
def drive_import(request):
    """Copie un fichier Drive dans les fichiers d'un projet."""
    from apps.dashboard.models import Project, ProjectFile
    organization = _get_user_primary_organization(request.user)
    data = _payload(request)
    project = get_object_or_404(Project, id=data.get('project_id'), organization=organization)
    try:
        name, content = providers.drive_download(_connected(organization, 'google-drive'), data.get('file_id', ''))
    except ProviderError as exc:
        return _error(exc)
    item = ProjectFile(project=project, name=name, uploaded_by=request.user)
    item.file.save(name, ContentFile(content), save=True)
    return JsonResponse({'ok': True, 'name': name})


# --------------------------------------------------------------------------- #
# Exports de tableaux (CSV, Google Sheets, Notion)
# --------------------------------------------------------------------------- #

@login_required
def export_table(request, table):
    organization = _get_user_primary_organization(request.user)
    if table not in exports.TABLES or not organization:
        return _error('Tableau inconnu.', 404)
    target = (request.POST.get('target') if request.method == 'POST' else request.GET.get('target')) or 'csv'
    columns, rows = exports.table_rows(organization, table)
    label = exports.TABLES[table]
    stamp = timezone.localdate().isoformat()
    if target == 'csv':
        response = HttpResponse(exports.to_csv(columns, rows), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="billio-{table}-{stamp}.csv"'
        return response
    if request.method != 'POST':
        return _error('Méthode non autorisée.', 405)
    try:
        if target == 'drive':
            instance = _connected(organization, 'google-drive')
            file = providers.drive_upload(instance, f'Billio — {label} ({stamp})', exports.to_csv(columns, rows, for_sheets=True).encode('utf-8'),
                                          'text/csv', convert_to='application/vnd.google-apps.spreadsheet')
            return JsonResponse({'ok': True, 'detail': f'{len(rows)} lignes exportées dans Google Sheets.', 'link': file.get('webViewLink', '')})
        if target == 'notion':
            instance = _connected(organization, 'notion')
            url, created, updated = providers.notion_export(instance, table, f'Billio — {label}', columns, rows)
            return JsonResponse({'ok': True, 'detail': f'{created} ligne(s) ajoutée(s), {updated} mise(s) à jour dans Notion.', 'link': url})
    except ProviderError as exc:
        return _error(exc)
    return _error('Destination inconnue.')


# --------------------------------------------------------------------------- #
# Notion : import d'un projet
# --------------------------------------------------------------------------- #

@login_required
@require_GET
def notion_search(request):
    organization = _get_user_primary_organization(request.user)
    try:
        items = providers.notion_search(_connected(organization, 'notion').config or {}, request.GET.get('q', '').strip())
    except ProviderError as exc:
        return _error(exc)
    return JsonResponse({'ok': True, 'items': items})


@login_required
@require_GET
def notion_preview(request):
    organization = _get_user_primary_organization(request.user)
    notion_id = providers.notion_id(request.GET.get('id', ''))
    if not notion_id:
        return _error('Page Notion invalide.')
    try:
        project = providers.notion_read_project(_connected(organization, 'notion').config or {}, notion_id)
    except ProviderError as exc:
        return _error(exc)
    return JsonResponse({'ok': True, 'project': project})


def _parse_date(value):
    try:
        return date.fromisoformat((value or '')[:10])
    except ValueError:
        return None


@login_required
@require_POST
def notion_import(request):
    """Crée un projet Billio (jalons + tâches) à partir d'une page ou d'une base Notion."""
    from apps.clients.models import Client
    from apps.dashboard.models import Milestone, Project, ProjectPhase, Task
    organization = _get_user_primary_organization(request.user)
    data = _payload(request)
    client = get_object_or_404(Client, id=data.get('client_id'), organization=organization)
    notion_id = providers.notion_id(data.get('id', ''))
    if not notion_id:
        return _error('Page Notion invalide.')
    try:
        source = providers.notion_read_project(_connected(organization, 'notion').config or {}, notion_id)
    except ProviderError as exc:
        return _error(exc)
    phase = ProjectPhase.for_organization(organization)[0].key
    now = timezone.now()
    with transaction.atomic():
        project = Project.objects.create(
            organization=organization, client=client, name=(data.get('name') or source['name'])[:200],
            description=(source['description'] or 'Importé depuis Notion.')[:5000], status=phase, created_by=request.user,
        )
        tasks_count = 0
        for order, group in enumerate(source['groups']):
            tasks = group['tasks']
            done_all = bool(tasks) and all(t['done'] for t in tasks)
            dues = [d for d in (_parse_date(t['due']) for t in tasks) if d]
            milestone = Milestone.objects.create(
                project=project, title=group['title'][:200], phase=phase, order=order,
                due_date=max(dues) if dues else None, is_completed=done_all, completed_at=now if done_all else None,
                created_by=request.user,
            )
            for index, task in enumerate(tasks):
                Task.objects.create(
                    project=project, milestone=milestone, title=task['title'][:200], order=index,
                    status='done' if task['done'] else 'todo', due_date=_parse_date(task['due']),
                    completed_at=now if task['done'] else None, created_by=request.user,
                )
                tasks_count += 1
    return JsonResponse({
        'ok': True, 'url': reverse('dashboard:project-detail', args=[project.id]),
        'detail': f"Projet « {project.name} » créé : {len(source['groups'])} jalon(s), {tasks_count} tâche(s).",
    })
