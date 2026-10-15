"""
Moteur des workflows d'automatisation. Chaque AutomationRule porte un graphe
(déclencheur → blocs « Si », « Attendre », actions chaînées) que l'on parcourt
de façon synchrone depuis le code qui produit l'événement (aucun worker Celery
n'est branché dans ce projet). Les attentes sont persistées sur AutomationRun
(`pending_steps`) et reprises par run_pending_waits au chargement du dashboard.
"""
from decimal import Decimal

import logging

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.integrations.providers import org_mail

from .models import AutomationRule, AutomationRun, Notification

logger = logging.getLogger(__name__)

TOKEN_PATTERN_FIELDS = ('client', 'projet', 'produit', 'date', 'montant', 'evenement', 'formulaire', 'lien_formulaire', 'numero', 'reunion', 'date_reunion', 'lieu', 'document', 'lien_document')


# Origine d'un paiement reçu (paramètre `origin` du déclencheur, variable {{origine}}).
PAYMENT_ORIGINS = {
    'invoice_online': 'Facture payée en ligne',
    'milestone': "Jalon payé depuis l'espace client",
    'manual': 'Paiement enregistré manuellement',
}


def _render_tokens(text, variables):
    """Remplace {{client}}, {{projet}}, {{produit}}, {{date}}, {{montant}}, {{evenement}} par leur valeur."""
    if not text:
        return text
    values = {k: v for k, v in (variables or {}).items() if not str(k).startswith('_')}
    values.setdefault('date', timezone.localdate().strftime('%d/%m/%Y'))
    for key in TOKEN_PATTERN_FIELDS:
        values.setdefault(key, '')
    rendered = text
    for key, value in values.items():
        replacement = str(value) if value is not None else ''
        rendered = rendered.replace('{{' + key + '}}', replacement).replace('{{ ' + key + ' }}', replacement)
    return rendered


def _build_context(organization, trigger_key, *, target_type, target_id, amount=None, client_id=None,
                   project_id=None, variables=None, context_label=''):
    variables = dict(variables or {})
    if client_id:
        from apps.clients.models import Client
        client = Client.objects.filter(id=client_id).first()
        if client:
            variables.setdefault('client', client.name)
            # Coordonnées du client : à reporter dans un projet, un e-mail, un document…
            city_line = ' '.join(p for p in (client.postal_code or '', client.city or '') if p)
            for key, value in (('email_client', client.email), ('telephone_client', client.phone),
                               ('societe_client', client.company_name), ('ville_client', city_line),
                               ('adresse_client', ', '.join(p for p in (client.address, city_line, client.country) if p))):
                variables.setdefault(key, value or '')
    if 'numero' not in variables and target_type in ('invoice', 'quote', 'document'):
        # {{numero}} disponible pour tous les événements de facture / devis / document.
        from apps.documents.models import Document
        from apps.invoices.models import Invoice, Quote
        model, field = {'invoice': (Invoice, 'invoice_number'), 'quote': (Quote, 'quote_number'),
                        'document': (Document, 'number')}[target_type]
        number = model.objects.filter(id=target_id).values_list(field, flat=True).first()
        if number:
            variables['numero'] = number
    if amount is not None:
        variables.setdefault('montant', f"{Decimal(str(amount)):.2f} €".replace('.', ','))
    variables.setdefault('evenement', context_label)
    return {
        'organization': organization,
        'trigger_key': trigger_key,
        'target_type': target_type,
        'target_id': str(target_id),
        'amount': str(amount) if amount is not None else None,
        'client_id': str(client_id) if client_id else None,
        'project_id': project_id,
        'variables': variables,
        'context_label': context_label,
    }


def _serializable_context(ctx):
    """Ce qu'on persiste sur AutomationRun pour reprendre un workflow après une attente."""
    return dict(ctx['variables'], _ctx={
        'trigger_key': ctx['trigger_key'], 'amount': ctx['amount'], 'client_id': ctx['client_id'],
    })


def _restore_context(run):
    stored = dict(run.variables or {})
    meta = stored.pop('_ctx', {}) or {}
    return {
        'organization': run.rule.organization,
        'trigger_key': meta.get('trigger_key') or run.rule.trigger_key,
        'target_type': run.target_type,
        'target_id': run.target_id,
        'amount': meta.get('amount'),
        'client_id': meta.get('client_id'),
        'project_id': run.project_id,
        'variables': stored,
        'context_label': run.detail,
    }


def walk_graph(rule, graph, start_ids, ctx, *, dry_run=False, max_steps=200):
    """
    Parcourt le workflow à partir de `start_ids`. Retourne (log, pending) :
    - log : [{'node', 'status': ok|error|true|false|waiting, 'detail', 'at'}]
    - pending : étapes différées par un bloc « Attendre » [{'node', 'at'}]
    En `dry_run`, aucune action n'est exécutée et les attentes sont traversées
    immédiatement (simulation affichée par le bouton « Tester » du board).
    """
    from .automation_graph import evaluate_condition, successors, wait_delta

    nodes = {n['id']: n for n in graph.get('nodes', [])}
    queue = list(start_ids)
    log, pending, steps = [], [], 0
    now = timezone.now()

    def entry(node_id, status, detail=''):
        log.append({'node': node_id, 'status': status, 'detail': str(detail)[:255], 'at': timezone.now().isoformat()})

    while queue and steps < max_steps:
        steps += 1
        node = nodes.get(queue.pop(0))
        if not node:
            continue
        node_type, params = node['type'], node.get('params') or {}

        if node_type == 'trigger':
            entry(node['id'], 'ok', ctx.get('context_label') or '')
            queue.extend(successors(graph, node['id'], 'out'))

        elif node_type == 'condition':
            result, detail = evaluate_condition(params, ctx)
            entry(node['id'], 'true' if result else 'false', detail)
            queue.extend(successors(graph, node['id'], 'true' if result else 'false'))

        elif node_type == 'wait':
            delta = wait_delta(params)
            if dry_run:
                entry(node['id'], 'ok', f"Attente de {params.get('amount')} {_unit_label(params.get('unit'))} (simulée)")
                queue.extend(successors(graph, node['id'], 'out'))
            else:
                resume_at = (now + delta).isoformat()
                for child in successors(graph, node['id'], 'out'):
                    pending.append({'node': child, 'at': resume_at})
                entry(node['id'], 'waiting', f"Reprise le {timezone.localtime(now + delta).strftime('%d/%m/%Y %H:%M')}")

        elif node_type == 'action':
            if dry_run:
                entry(node['id'], 'ok', _describe_action(node['key'], params, ctx))
                queue.extend(successors(graph, node['id'], 'out'))
                continue
            try:
                # Savepoint : une action en échec ne doit pas casser la transaction de
                # l'appelant (envoi de facture, création de client...).
                with transaction.atomic():
                    detail = _execute_action(rule, node['key'], params, ctx)
                entry(node['id'], 'ok', detail or '')
                queue.extend(successors(graph, node['id'], 'out'))
            except Exception as exc:  # une action en échec stoppe sa branche, pas les autres
                entry(node['id'], 'error', exc)
    return log, pending


def _unit_label(unit):
    return {'minutes': 'min', 'hours': 'h', 'days': 'j'}.get(unit, unit or '')


def _find_trigger(graph):
    return next((n['id'] for n in graph.get('nodes', []) if n['type'] == 'trigger'), None)


def run_automations(organization, trigger_key, *, target_type, target_id, amount=None, client_id=None,
                     project_id=None, variables=None, context_label='', only_rule=None, source=None):
    """
    Exécute chaque workflow actif de `organization` dont le déclencheur est `trigger_key`,
    pour une cible donnée (facture, paiement, client...). Idempotent : un workflow ne
    s'exécute qu'une fois par cible (AutomationRun garde aussi le journal nœud par nœud
    et les étapes en attente).
    """
    if not organization:
        return

    rules = AutomationRule.objects.filter(organization=organization, trigger_key=trigger_key, is_active=True)
    if only_rule is not None:  # déclencheur paramétré (ex. « Date du calendrier ») : un seul workflow visé
        rules = rules.filter(id=only_rule.id)
    for rule in rules:
        if AutomationRun.objects.filter(rule=rule, target_type=target_type, target_id=str(target_id)).exists():
            continue
        graph = rule.get_graph()
        trigger_id = _find_trigger(graph)
        if not trigger_id:
            continue
        # Déclencheur filtré par origine (ex. « Paiement reçu » : en ligne / jalon / manuel).
        wanted = next(n for n in graph['nodes'] if n['id'] == trigger_id).get('params', {}).get('origin') or 'any'
        if wanted != 'any' and wanted != source:
            continue
        if source:
            variables = dict(variables or {}, origine=PAYMENT_ORIGINS.get(source, source))
        ctx = _build_context(
            organization, trigger_key, target_type=target_type, target_id=target_id, amount=amount,
            client_id=client_id, project_id=project_id, variables=variables, context_label=context_label,
        )
        log, pending = walk_graph(rule, graph, [trigger_id], ctx)
        _save_run(rule, graph, ctx, log, pending, context_label=context_label)


def _save_run(rule, graph, ctx, log, pending, *, context_label='', run=None):
    types = {n['id']: n['type'] for n in graph.get('nodes', [])}
    errors = [e for e in log if e['status'] == 'error']
    actions_done = any(e['status'] == 'ok' and types.get(e['node']) == 'action' for e in log)
    scheduled_for = min((parse_datetime(p['at']) for p in pending), default=None)
    if run is None:
        run = AutomationRun.objects.create(
            rule=rule, target_type=ctx['target_type'], target_id=ctx['target_id'],
            project_id=ctx['project_id'], variables=_serializable_context(ctx),
            success=not errors, detail=(errors[0]['detail'] if errors else context_label)[:255],
            scheduled_for=scheduled_for, executed=not pending, pending_steps=pending, log=log,
        )
    else:
        run.log = (run.log or []) + log
        run.pending_steps = pending
        run.scheduled_for = scheduled_for
        run.executed = not pending
        run.success = run.success and not errors
        # Une action « Créer un projet » a pu fournir un projet aux étapes suivantes.
        run.project_id = ctx.get('project_id') or run.project_id
        run.variables = _serializable_context(ctx)
        run.save(update_fields=['log', 'pending_steps', 'scheduled_for', 'executed', 'success', 'project_id', 'variables'])
    if actions_done:
        rule.last_triggered_at = timezone.now()
        rule.run_count = F('run_count') + 1
        rule.save(update_fields=['last_triggered_at', 'run_count'])
    _notify_status(rule, run, log, types, errors, pending, ctx)
    return run


def _notify_status(rule, run, log, types, errors, pending, ctx):
    """Prévient le propriétaire du statut d'une exécution, selon le réglage du workflow."""
    mode = getattr(rule, 'notify_on', 'failure') or 'failure'
    owner = ctx['organization'].owner
    if mode == 'never' or owner is None or (mode == 'failure' and not errors):
        return
    if not errors and not any(e['status'] == 'ok' and types.get(e['node']) == 'action' for e in log):
        return  # rien d'exécuté (conditions non remplies) : pas de bruit
    name = rule.name or rule.get_trigger_key_display()
    done = [e['detail'] for e in log if e['status'] == 'ok' and types.get(e['node']) == 'action']
    if errors:
        title = f"Workflow « {name} » en échec"
        message = f"Étape en erreur : {errors[0]['detail']}"
        if done:
            message += f" — déjà fait : {'; '.join(done[:3])}"
        priority = 'high'
    else:
        title = f"Workflow « {name} » exécuté" + (' (en attente de la suite)' if pending else '')
        message = '; '.join(done[:4]) or (ctx.get('context_label') or '')
        priority = 'low'
    Notification.objects.create(user=owner, notification_type='workflow_status', title=title[:200],
                                message=message[:1000], priority=priority)


def run_pending_waits():
    """
    Reprend les workflows dont un bloc « Attendre » est écoulé. Pas de worker planifié
    dans ce projet : appelé à chaque chargement du tableau de bord.
    """
    from .automation_graph import successors

    now = timezone.now()
    pending_runs = AutomationRun.objects.filter(
        executed=False, scheduled_for__isnull=False, scheduled_for__lte=now,
    ).select_related('rule', 'rule__organization')

    for run in pending_runs:
        rule = run.rule
        graph = rule.get_graph()
        steps = list(run.pending_steps or [])
        if not steps:
            # Attente créée avant les workflows en graphe : on reprend après le nœud 'wait'.
            steps = [{'node': child, 'at': now.isoformat()} for child in successors(graph, 'wait', 'out')]
        due = [s for s in steps if parse_datetime(s['at']) <= now]
        later = [s for s in steps if parse_datetime(s['at']) > now]
        ctx = _restore_context(run)
        log, new_pending = walk_graph(rule, graph, [s['node'] for s in due], ctx)
        _save_run(rule, graph, ctx, log, later + new_pending, run=run)


def dry_run(organization, graph, *, amount=None, client_id=None, variables=None):
    """Simulation sans effet de bord (bouton « Tester » du board). Retourne le journal."""
    trigger_id = _find_trigger(graph)
    trigger_key = next(n['key'] for n in graph['nodes'] if n['id'] == trigger_id)
    ctx = _build_context(
        organization, trigger_key, target_type='test', target_id='test',
        amount=amount, client_id=client_id, variables=variables, context_label='Événement de test',
    )
    log, _ = walk_graph(None, graph, [trigger_id], ctx, dry_run=True)
    return log


def _template_name(template_id):
    from apps.documents.models import DocumentTemplate
    return DocumentTemplate.objects.filter(id=template_id).values_list('name', flat=True).first() or 'document'


def _describe_action(key, params, ctx):
    variables = ctx.get('variables') or {}
    if key == 'send_email':
        to = {'owner': 'vous', 'client': 'le client', 'custom': params.get('to')}.get(params.get('recipient'), 'vous')
        subject = _render_tokens(params.get('subject'), variables) or 'objet par défaut'
        labels = {'event': 'PDF de la facture / du devis', 'created': 'documents du workflow'}
        files = [labels.get(a['kind']) or _template_name(a.get('template_id')) for a in params.get('attachments') or []]
        return f"Email à {to} — « {subject} »" + (f" · pièces jointes : {', '.join(files)}" if files else '')
    if key in ('notify', 'create_task'):
        return _render_tokens(params.get('title'), variables) or 'Titre par défaut'
    if key == 'create_project':
        from .models import ProjectTemplate
        template = ProjectTemplate.objects.filter(id=params.get('template_id') or 0).first()
        name = _render_tokens(params.get('value'), variables) or (template.name if template else 'Nom par défaut')
        return f"Projet « {name} »" + (f" depuis le modèle « {template.name} »" if template else '')
    if key in ('create_phase', 'create_milestone', 'create_deliverable'):
        return _render_tokens(params.get('value'), variables) or 'Nom par défaut'
    if key == 'create_document':
        filled = sum(1 for v in (params.get('field_values') or {}).values() if v)
        custom = len(params.get('var_values') or {})
        variables.setdefault('document', _render_tokens(params.get('title'), variables) or _template_name(params.get('template_id')))
        return (f"Document « {variables['document']} » créé" + (f", {filled} champ(s) rempli(s)" if filled else '')
                + (f", {custom} variable(s) personnalisée(s)" if custom else '') + (' et partagé au client' if params.get('share') else ''))
    if key == 'mark_late':
        return 'Facture marquée en retard'
    if key == 'drive_upload':
        extra = ' et documents du workflow' if params.get('include_created') else ''
        return f"PDF de l'événement{extra} copié(s) dans Google Drive (dossier Billio)"
    if key == 'create_form':
        questions = len(params.get('fields') or [])
        return f"Formulaire « {_render_tokens(params.get('title'), variables)} » ({questions} question{'s' if questions > 1 else ''}) envoyé au client"
    if key == 'send_message':
        from apps.integrations.messaging import CHANNELS, connected_channels
        channel = params.get('channel')
        status = '' if channel in connected_channels(ctx.get('organization')) else ' — ⚠ non connecté'
        return f"{CHANNELS.get(channel, channel)} : « {_render_tokens(params.get('text'), variables)[:80]} »{status}"
    if key == 'app_action':
        from apps.integrations.app_actions import app_label, operation
        from apps.integrations.models import ConnectionInstance
        spec = operation(params.get('app'), params.get('operation')) or {'label': params.get('operation'), 'fields': []}
        connected = ConnectionInstance.objects.filter(organization=ctx.get('organization'), connector__key=params.get('app'),
                                                      status='connected').exists()
        title = next((params.get('values', {}).get(f['name']) for f in spec['fields'] if f['name'] in ('title', 'name')), '')
        return (f"{app_label(params.get('app'))} › {spec['label']}" + (f" « {_render_tokens(title, variables)[:80]} »" if title else '')
                + ('' if connected else ' — ⚠ non connecté'))
    if key == 'create_meeting':
        days = int(params.get('in_days') or 0)
        when = "aujourd'hui" if days == 0 else ('demain' if days == 1 else f'dans {days} jours')
        return f"Réunion « {_render_tokens(params.get('title'), variables)} » {when} à {params.get('time')} ({params.get('duration')} min)"
    return 'Action exécutée'


def _document_from_template(template, ctx, *, title='', field_values=None, var_values=None, share=False):
    """
    Crée un document pour le client de l'événement à partir d'un modèle, champs personnalisés
    remplis (les variables du workflow y sont permises). Expose {{document}} / {{lien_document}}.
    """
    from django.urls import reverse
    from apps.clients.models import Client
    from apps.documents.models import Document

    variables = ctx['variables']
    client_id = ctx.get('client_id') or _target_client_id(ctx['target_type'], ctx['target_id'])
    canvas = dict(template.canvas_data or {})
    fields = []
    for field in canvas.get('fields') or []:
        field = dict(field)
        if field.get('id') in (field_values or {}):
            field['value'] = _render_tokens(field_values[field['id']], variables)[:500]
        fields.append(field)
    canvas['fields'] = fields
    # Variables automatiques remplacées dans le workflow (« Nom du client » = {{client}} en majuscules…).
    overrides = {key: _render_tokens(value, variables)[:500] for key, value in (var_values or {}).items()}
    canvas['overrides'] = {key: value for key, value in overrides.items() if value.strip()}
    # Un document né d'un devis / d'une facture remplit ses tableaux reliés avec ses lignes.
    if ctx['target_type'] in ('quote', 'invoice') and ctx['target_id']:
        canvas['sources'] = {**(canvas.get('sources') or {}), ctx['target_type']: str(ctx['target_id']).split('@')[0]}
    document = Document.objects.create(
        organization=ctx['organization'], client_id=client_id, document_type=template.category,
        title=(_render_tokens(title, variables) or template.name)[:200],
        header_html=template.header_html, body_html=template.body_html, footer_html=template.footer_html,
        style_config=dict(template.style_config or {}), layout_mode=template.layout_mode, canvas_data=canvas,
        status='sent' if share and client_id else 'draft',
    )
    variables['document'] = document.title
    if share and client_id:
        token = Client.objects.filter(id=client_id).values_list('portal_token', flat=True).first()
        if token:
            variables['lien_document'] = f"{settings.SITE_URL}{reverse('dashboard:public-portal-document-view', args=[token, document.id])}"
    created = [x for x in str(variables.get('_documents') or '').split(',') if x]
    variables['_documents'] = ','.join(created + [str(document.id)])
    return document


def _safe_filename(label):
    import re
    return (re.sub(r'[^\w\-]+', '-', label, flags=re.UNICODE).strip('-') or 'document')[:80] + '.pdf'


def _email_attachments(items, ctx, organization):
    """PDF à joindre : (fichiers [(nom, contenu)], libellés non joints). Un échec n'empêche pas l'envoi."""
    from apps.documents.models import Document, DocumentTemplate
    from apps.invoices.models import Invoice, Quote
    files, missing = [], []

    def add(label, producer):
        try:
            files.append((_safe_filename(label), producer()))
        except Exception:
            logger.exception('Pièce jointe impossible : %s', label)
            missing.append(label)

    target_type, target_id = ctx['target_type'], ctx['target_id']
    for item in items:
        kind = item.get('kind')
        if kind == 'event':
            invoice = quote = None
            if target_type == 'invoice':
                invoice = Invoice.objects.filter(id=target_id, organization=organization).first()
            elif target_type == 'payment':
                from apps.payments.models import Payment
                payment = Payment.objects.filter(id=target_id).select_related('invoice').first()
                invoice = payment.invoice if payment and payment.invoice.organization_id == organization.id else \
                    Invoice.objects.filter(id=target_id, organization=organization).first()
            elif target_type == 'quote':
                quote = Quote.objects.filter(id=target_id, organization=organization).first()
            if invoice:
                add(f"Facture-{invoice.invoice_number}", invoice.ensure_pdf)
            elif quote:
                add(f"Devis-{quote.quote_number}", quote.generate_pdf_bytes)
            elif target_type == 'document':
                doc = Document.objects.filter(id=target_id, organization=organization).first()
                if doc:
                    add(doc.title, doc.generate_pdf_bytes)
            else:
                missing.append("PDF de l'événement (aucune facture ni devis concerné)")
        elif kind == 'created':
            ids = [x for x in str(ctx['variables'].get('_documents') or '').split(',') if x]
            for doc in Document.objects.filter(id__in=ids, organization=organization):
                add(doc.title, doc.generate_pdf_bytes)
        elif kind == 'template':
            template = DocumentTemplate.objects.filter(id=item.get('template_id')).first()
            if template:
                document = _document_from_template(template, ctx, field_values=item.get('field_values'),
                                                   var_values=item.get('var_values'), share=True)
                add(document.title, document.generate_pdf_bytes)
    return files, missing


def _email_recipients(params, ctx, owner):
    recipient = params.get('recipient') or 'owner'
    if recipient == 'custom':
        return [a.strip() for a in (params.get('to') or '').split(',') if a.strip()]
    if recipient == 'client':
        client_id = ctx.get('client_id') or _target_client_id(ctx['target_type'], ctx['target_id'])
        if client_id:
            from apps.clients.models import Client
            email = Client.objects.filter(id=client_id).values_list('email', flat=True).first()
            if email:
                return [email]
        raise ValueError("Le client de l'événement n'a pas d'adresse email.")
    return [owner.email] if owner and owner.email else []


def _parse_delivery(raw, today):
    """Date de livraison saisie ou reçue : 2026-11-30, 30/11/2026, ou un nombre de jours (« 30 »)."""
    import datetime as dt
    raw = (raw or '').strip()
    if not raw:
        return None
    if raw.isdigit() and len(raw) <= 4:
        return today + dt.timedelta(days=int(raw))
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%SZ'):
        try:
            return dt.datetime.strptime(raw[:19] if 'T' in raw else raw, fmt.replace('Z', '') if 'T' in raw else fmt).date()
        except ValueError:
            continue
    return None


def _execute_action(rule, action_key, params, ctx):
    """Exécute une action du workflow. Retourne un court détail pour le journal."""
    organization = ctx['organization']
    owner = organization.owner
    rule_name = rule.name or rule.get_trigger_key_display()
    trigger_label = dict(AutomationRule.TRIGGER_CHOICES).get(ctx['trigger_key'], ctx['trigger_key'])
    variables = ctx.get('variables') or {}
    target_type, target_id = ctx['target_type'], ctx['target_id']
    project_id = ctx.get('project_id')
    context_label = ctx.get('context_label') or ''
    value = _render_tokens(params.get('value', ''), variables)

    if action_key == 'send_email':
        recipients = _email_recipients(params, ctx, owner)
        if not recipients:
            raise ValueError('Aucun destinataire pour cet email.')
        # Les pièces jointes passent en premier : un document généré fournit {{document}} / {{lien_document}}.
        files, missing = _email_attachments(params.get('attachments') or [], ctx, organization)
        subject = _render_tokens(params.get('subject'), variables) or f"[{organization.name}] Automatisation : {trigger_label}"
        body = _render_tokens(params.get('body'), variables) or (
            f"Le workflow « {rule_name} » s'est déclenché.\n{context_label}".strip()
        )
        from apps.organizations.branded_email import branded_message
        connection, from_email = org_mail(organization)  # SMTP de l'organisation s'il est connecté
        message = branded_message(organization, subject=subject, body=body, to=recipients,
                                  connection=connection, from_email=from_email)
        for filename, content in files:
            message.attach(filename, content, 'application/pdf')
        message.send(fail_silently=False)
        detail = f"Email envoyé à {', '.join(recipients)}"
        if files:
            detail += f" avec {', '.join(name for name, _ in files)}"
        if missing:
            detail += f" (non joint : {', '.join(missing)})"
        return detail

    if action_key == 'notify':
        if owner:
            Notification.objects.create(
                user=owner,
                notification_type=_notification_type_for_trigger(ctx['trigger_key']),
                title=_render_tokens(params.get('title'), variables) or f"Automatisation : {trigger_label}",
                message=_render_tokens(params.get('message'), variables) or context_label or f"Le workflow « {rule_name} » s'est déclenché.",
                priority=params.get('priority') or 'medium',
                **_notification_relation_kwargs(target_type, target_id),
            )
        return 'Notification créée'

    if action_key == 'create_task':
        if owner:
            Notification.objects.create(
                user=owner,
                notification_type='automation_task',
                title=_render_tokens(params.get('title'), variables) or f"À faire : {context_label or trigger_label}",
                message=_render_tokens(params.get('message'), variables) or f"Créé automatiquement par le workflow « {rule_name} ».",
                priority=params.get('priority') or 'high',
                **_notification_relation_kwargs(target_type, target_id),
            )
        return 'Tâche créée'

    if action_key == 'create_document':
        from apps.documents.models import DocumentTemplate
        template = DocumentTemplate.objects.filter(id=params.get('template_id') or rule.document_template_id).first()
        if not template:
            raise ValueError('Modèle de document introuvable.')
        document = _document_from_template(
            template, ctx, title=params.get('title'), field_values=params.get('field_values'),
            var_values=params.get('var_values'), share=params.get('share'),
        )
        if owner:
            Notification.objects.create(
                user=owner, notification_type='automation_task',
                title=f"Document créé : {document.title}",
                message=f"Créé automatiquement par le workflow « {rule_name} ».",
                priority='medium',
            )
        return f"Document {document.number} créé"

    if action_key == 'drive_upload':
        from apps.integrations.models import ConnectionInstance
        from apps.integrations.providers import ProviderError, drive_upload
        instance = ConnectionInstance.objects.filter(organization=organization, connector__key='google-drive', status='connected').first()
        if not instance:
            raise ValueError("Google Drive n'est pas connecté (page Intégrations).")
        sources = [{'kind': 'event'}] + ([{'kind': 'created'}] if params.get('include_created') else [])
        files, _missing = _email_attachments(sources, ctx, organization)
        if not files:
            raise ValueError("Aucun PDF à copier : l'événement ne concerne ni facture ni devis, et aucun document n'a été créé.")
        try:
            uploaded = [drive_upload(instance, name, content, 'application/pdf') for name, content in files]
        except ProviderError as exc:
            raise ValueError(str(exc)) from None
        return f"{len(uploaded)} PDF copié(s) dans Google Drive : {', '.join(f.get('name', '') for f in uploaded)}"

    if action_key == 'mark_late':
        if target_type != 'invoice':
            raise ValueError("« Marquer en retard » ne s'applique qu'aux factures.")
        from apps.invoices.models import Invoice
        invoice = Invoice.objects.filter(id=target_id).first()
        if invoice and invoice.status in ('sent', 'viewed'):
            invoice.status = 'overdue'
            invoice.save(update_fields=['status', 'updated_at'])
            return f"Facture {invoice.invoice_number} marquée en retard"
        return 'Facture déjà à jour'

    if action_key == 'create_project':
        from django.utils import timezone as dj_timezone
        from apps.clients.models import Client
        from . import project_templates
        from .models import Project, ProjectProcess, ProjectTemplate
        # Client : celui de l'événement (par défaut) ou un client choisi dans l'action.
        fixed = str(params.get('client') or 'event')
        if fixed != 'event':
            resolved_client_id = Client.objects.filter(organization=organization, id=fixed).values_list('id', flat=True).first()
        else:
            resolved_client_id = ctx.get('client_id') or _target_client_id(target_type, target_id)
        if not resolved_client_id:
            raise ValueError("Aucun client rattaché à l'événement : impossible de créer un projet.")
        template = ProjectTemplate.objects.filter(organization=organization, id=params.get('template_id') or 0).first()
        process = ProjectProcess.objects.filter(organization=organization, id=params.get('process_id') or 0).first()
        if process is None and template and (template.data or {}).get('process'):
            process = ProjectProcess.objects.filter(organization=organization, name=template.data['process']).first()
        process = process or ProjectProcess.default_for(organization)
        first_stage = (process.phases() or [None])[0]
        client_name = Client.objects.filter(id=resolved_client_id).values_list('name', flat=True).first() or ''
        description = _render_tokens(params.get('description'), variables).strip()
        project = Project.objects.create(
            organization=organization,
            client_id=resolved_client_id,
            process=process,
            name=value or (f"{template.name} — {client_name}" if template else f"Nouveau projet — {trigger_label}"),
            description=description or f"Créé automatiquement par le workflow « {rule_name} ».",
            status=first_stage.key if first_stage else 'discovery',
            start_date=dj_timezone.localdate(),
            delivery_date=_parse_delivery(_render_tokens(params.get('delivery'), variables), dj_timezone.localdate()),
        )
        if template:
            # Jalons, tâches et livrables du modèle, datés à partir d'aujourd'hui.
            project_templates.instantiate(template.data, project, user=owner)
        ctx['client_id'] = resolved_client_id
        # Les actions suivantes du workflow (jalon, livrable...) visent ce nouveau projet.
        ctx['project_id'] = project.id
        variables['projet'] = project.name
        if owner:
            Notification.objects.create(
                user=owner, notification_type='automation_task',
                title=f"Projet créé : {project.name}",
                message=f"Créé automatiquement par le workflow « {rule_name} ».",
                priority='medium', related_project=project,
            )
        return f"Projet « {project.name} » créé" + (f" depuis le modèle « {template.name} »" if template else '')

    if action_key == 'create_phase':
        from .models import ProjectPhase
        from django.utils.text import slugify
        label = value or 'Nouvelle phase'
        existing = ProjectPhase.objects.filter(organization=organization)
        if existing.filter(label=label).exists():
            return f"Phase « {label} » déjà existante"
        base_key = slugify(label)[:26] or 'phase'
        key = base_key
        existing_keys = set(existing.values_list('key', flat=True))
        n = 2
        while key in existing_keys:
            key = f"{base_key}-{n}"
            n += 1
        ProjectPhase.objects.create(
            organization=organization, key=key, label=label, color='#6366f1',
            order=(max((p.order for p in existing), default=-1) + 1),
        )
        from .models import ProjectProcess
        from .project_views import add_phase_key
        process = ProjectProcess.default_for(organization)
        process.phase_keys = add_phase_key(process.phase_keys, key)
        process.save(update_fields=['phase_keys'])
        return f"Phase « {label} » créée"

    if action_key == 'create_milestone':
        from .models import Milestone, Project
        if not project_id:
            raise ValueError("Aucun projet rattaché à l'événement : impossible de créer un jalon.")
        project_status = Project.objects.filter(id=project_id).values_list('status', flat=True).first()
        milestone = Milestone.objects.create(
            project_id=project_id,
            title=value or 'Nouvelle étape',
            phase=variables.get('phase') or project_status or 'discovery',
        )
        return f"Jalon « {milestone.title} » créé"

    if action_key == 'create_deliverable':
        from .models import Deliverable
        if not project_id:
            raise ValueError("Aucun projet rattaché à l'événement : impossible d'ajouter un livrable.")
        deliverable = Deliverable.objects.create(project_id=project_id, title=value or 'Nouveau livrable', status='in_progress')
        return f"Livrable « {deliverable.title} » ajouté"

    if action_key == 'create_form':
        from django.urls import reverse
        from .models import ClientForm
        client_id = ctx.get('client_id') or _target_client_id(target_type, target_id)
        if not client_id:
            raise ValueError("Aucun client rattaché à l'événement : impossible d'envoyer un formulaire.")
        form = ClientForm.objects.create(
            organization=organization, client_id=client_id, project_id=project_id,
            title=_render_tokens(params.get('title'), variables) or 'Formulaire',
            intro=_render_tokens(params.get('intro'), variables) or '',
            fields=params.get('fields') or [],
        )
        link = f"{settings.SITE_URL}{reverse('dashboard:public-client-form', args=[form.token])}"
        variables['formulaire'] = form.title
        variables['lien_formulaire'] = link
        if params.get('notify_client', True) and form.client.email:
            from apps.organizations.branded_email import branded_message
            branded_message(
                organization, subject=f"{organization.name} — {form.title}",
                body=(f"Bonjour {form.client.name},\n\n"
                      f"{form.intro + chr(10) + chr(10) if form.intro else ''}"
                      "Merci de compléter ce formulaire."),
                to=[form.client.email], button=('Compléter le formulaire', link),
            ).send(fail_silently=False)
            return f"Formulaire « {form.title} » envoyé à {form.client.email}"
        return f"Formulaire « {form.title} » créé (visible dans le portail client)"

    if action_key == 'send_message':
        from apps.integrations.messaging import MessagingError, send_message
        recipient = ''
        mode = params.get('recipient_mode') or 'default'
        if mode == 'custom':
            recipient = params.get('recipient', '')
        elif mode == 'client':
            client_id = ctx.get('client_id') or _target_client_id(target_type, target_id)
            from apps.clients.models import Client
            recipient = (Client.objects.filter(id=client_id).values_list('phone', flat=True).first() or '') if client_id else ''
            if not recipient:
                raise ValueError("Le client de l'événement n'a pas de numéro de téléphone.")
        try:
            return send_message(organization, params.get('channel'), _render_tokens(params.get('text'), variables), recipient=recipient)
        except MessagingError as exc:
            raise ValueError(str(exc))

    if action_key == 'app_action':
        from apps.clients.models import Client
        from apps.integrations.app_actions import run_app_action
        client_id = ctx.get('client_id') or _target_client_id(target_type, target_id)
        client = Client.objects.filter(id=client_id, organization=organization).first() if client_id else None
        return run_app_action(organization, params.get('app'), params.get('operation'), params.get('values') or {}, ctx,
                              client=client, render=lambda text: _render_tokens(text, variables))

    if action_key == 'create_meeting':
        from datetime import datetime, time as dtime, timedelta
        from .models import Meeting
        if not project_id:
            raise ValueError("Aucun projet rattaché à l'événement : impossible de planifier une réunion.")
        hour, minute = (int(part) for part in (params.get('time') or '10:00').split(':'))
        day = timezone.localdate() + timedelta(days=int(params.get('in_days') or 0))
        scheduled = timezone.make_aware(datetime.combine(day, dtime(hour, minute)))
        meeting = Meeting.objects.create(
            project_id=project_id,
            title=_render_tokens(params.get('title'), variables) or 'Réunion',
            scheduled_at=scheduled,
            duration_minutes=int(params.get('duration') or 30),
            location=_render_tokens(params.get('location'), variables) or '',
            notes=_render_tokens(params.get('notes'), variables) or '',
        )
        return f"Réunion « {meeting.title} » le {timezone.localtime(scheduled).strftime('%d/%m/%Y à %H:%M')}"

    raise ValueError(f"Action inconnue : {action_key}")


def _notification_type_for_trigger(trigger_key):
    return {
        'invoice_sent': 'invoice_sent',
        'invoice_overdue': 'invoice_overdue',
        'payment_received': 'payment_received',
        'client_created': 'client_created',
        'quote_sent': 'quote_sent',
        'quote_accepted': 'quote_accepted',
        'quote_rejected': 'quote_rejected',
        'quote_expired': 'quote_expiring',
    }.get(trigger_key, 'system_maintenance')


def _target_client_id(target_type, target_id):
    """Retrouve le client rattaché à la cible d'un trigger (invoice/quote/client)."""
    if target_type == 'client':
        return target_id
    if target_type == 'invoice':
        from apps.invoices.models import Invoice
        return Invoice.objects.filter(id=target_id).values_list('client_id', flat=True).first()
    if target_type == 'quote':
        from apps.invoices.models import Quote
        return Quote.objects.filter(id=target_id).values_list('client_id', flat=True).first()
    if target_type == 'payment':
        from apps.invoices.models import Invoice
        from apps.payments.models import Payment
        client_id = Payment.objects.filter(id=target_id).values_list('invoice__client_id', flat=True).first()
        return client_id or Invoice.objects.filter(id=target_id).values_list('client_id', flat=True).first()
    if target_type == 'document':
        from apps.documents.models import Document
        return Document.objects.filter(id=target_id).values_list('client_id', flat=True).first()
    if target_type == 'form':
        from .models import ClientForm
        return ClientForm.objects.filter(id=target_id).values_list('client_id', flat=True).first()
    return None


def _notification_relation_kwargs(target_type, target_id):
    if target_type == 'invoice':
        return {'related_invoice_id': target_id}
    if target_type == 'payment':
        # Historiquement certains appels passent l'id de la facture : on relie au bon objet.
        from apps.payments.models import Payment
        if Payment.objects.filter(id=target_id).exists():
            return {'related_payment_id': target_id}
        from apps.invoices.models import Invoice
        if Invoice.objects.filter(id=target_id).exists():
            return {'related_invoice_id': target_id}
        return {}
    if target_type == 'quote':
        return {'related_quote_id': target_id}
    return {}


def sweep_overdue_invoices(organization):
    """
    Aucun worker planifié n'existe dans ce projet : on détecte les factures
    tout juste passées en retard à chaque chargement du tableau de bord, on
    bascule leur statut, puis on déclenche les automatisations concernées.
    """
    from apps.invoices.models import Invoice

    today = timezone.localdate()
    overdue_invoices = Invoice.objects.filter(
        organization=organization, invoice_type='sale', status__in=['sent', 'viewed'], due_date__lt=today,
    )
    for invoice in overdue_invoices:
        invoice.status = 'overdue'
        invoice.save(update_fields=['status', 'updated_at'])
        run_automations(
            organization, 'invoice_overdue',
            target_type='invoice', target_id=invoice.id,
            amount=invoice.total_amount, client_id=invoice.client_id,
            context_label=f"Facture {invoice.invoice_number} en retard.",
        )


def sweep_expired_quotes(organization):
    """Bascule les devis dont la date de validité est dépassée, puis déclenche les automatisations."""
    from apps.invoices.models import Quote

    today = timezone.localdate()
    candidates = Quote.objects.filter(
        organization=organization, status__in=['sent', 'viewed'], expiry_date__lt=today,
    )
    for quote in candidates:
        quote.mark_as_expired()
        run_automations(
            organization, 'quote_expired',
            target_type='quote', target_id=quote.id,
            amount=quote.total_amount, client_id=quote.client_id,
            context_label=f"Devis {quote.quote_number} expiré.",
        )


def sweep_overdue_tasks(organization):
    """Détecte les tâches non terminées dont l'échéance est dépassée et déclenche les automatisations."""
    from .models import Task

    today = timezone.localdate()
    overdue_tasks = Task.objects.filter(
        project__organization=organization, status__in=['todo', 'in_progress'], due_date__lt=today,
    )
    for task in overdue_tasks:
        run_automations(
            organization, 'task_overdue',
            target_type='task', target_id=task.id,
            context_label=f"Tâche « {task.title} » en retard.",
        )
