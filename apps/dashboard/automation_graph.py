"""
Workflows d'automatisation en graphe : catalogue des nœuds, validation du graphe
envoyé par le board (static/js/automation-workflow.js) et évaluation des conditions.

Format : {'nodes': [{'id', 'type', 'key', 'x', 'y', 'params'}],
          'edges': [{'from', 'port', 'to'}]}

- trigger   : un seul par workflow, port 'out'
- condition : key 'if', params {'match': 'all'|'any', 'rules': [{'field', 'op', 'value'}]},
              ports 'true' / 'false'
- wait      : key 'delay', params {'amount', 'unit'}, port 'out'
- action    : key = AutomationRule.ACTION_CHOICES, params selon l'action, port 'out'
              (les actions s'enchaînent)
"""
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone

MAX_NODES = 60
MAX_GROUPS = 30
MAX_FORM_FIELDS = 20
FORM_FIELD_TYPES = {'text', 'textarea', 'email', 'phone', 'number', 'date', 'select', 'checkbox'}
GROUP_COLORS = {'violet', 'blue', 'green', 'amber', 'rose', 'slate'}
MAX_RULES_PER_CONDITION = 10
_ID_RE = re.compile(r'^[\w-]{1,40}$')

NODE_PORTS = {
    'trigger': ('out',),
    'condition': ('true', 'false'),
    'wait': ('out',),
    'action': ('out',),
}

WAIT_UNITS = {'minutes': 'minutes', 'hours': 'hours', 'days': 'days'}

CONDITION_FIELDS = {
    'amount': 'number',
    'client': 'client',
    'client_name': 'text',
    'client_email': 'text',
    'client_city': 'text',
    'projet': 'text',
    'formulaire': 'text',
    'produit': 'text',
    'weekday': 'number',
    'hour': 'number',
    'day_of_month': 'number',
}
CONDITION_OPS = {
    'number': {'eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'empty', 'not_empty'},
    'text': {'eq', 'neq', 'contains', 'not_contains', 'starts_with', 'empty', 'not_empty'},
    'client': {'eq', 'neq', 'empty', 'not_empty'},
}

PRIORITIES = {'low', 'medium', 'high'}
EMAIL_RECIPIENTS = {'owner', 'client', 'custom'}
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class GraphError(ValueError):
    pass


def _str(value, max_length=255):
    return str(value if value is not None else '').strip()[:max_length]


def _clean_params(node_type, key, raw, *, organization):
    raw = raw if isinstance(raw, dict) else {}
    if node_type == 'trigger':
        if key == 'payment_received':
            from .automation_engine import PAYMENT_ORIGINS
            return {'origin': raw.get('origin') if raw.get('origin') in PAYMENT_ORIGINS else 'any'}
        if key == 'calendar_date':
            from .automation_calendar import CalendarParamsError, clean_params
            try:
                return clean_params(raw)
            except CalendarParamsError as exc:
                raise GraphError(str(exc))
        if key == 'webhook_received':
            from .automation_webhooks import clean_trigger_params
            return clean_trigger_params(raw, organization)
        return {}
    if node_type == 'wait':
        try:
            amount = int(raw.get('amount') or 1)
        except (TypeError, ValueError):
            raise GraphError("Durée d'attente invalide.")
        unit = raw.get('unit') if raw.get('unit') in WAIT_UNITS else 'days'
        return {'amount': max(1, min(amount, 365 if unit == 'days' else 10_000)), 'unit': unit}
    if node_type == 'condition':
        rules = []
        for rule in (raw.get('rules') or [])[:MAX_RULES_PER_CONDITION]:
            if not isinstance(rule, dict):
                continue
            field = rule.get('field')
            if field not in CONDITION_FIELDS:
                raise GraphError('Champ de condition inconnu.')
            op = rule.get('op')
            if op not in CONDITION_OPS[CONDITION_FIELDS[field]]:
                raise GraphError('Opérateur de condition invalide.')
            value = _str(rule.get('value'))
            if CONDITION_FIELDS[field] == 'number' and op not in ('empty', 'not_empty'):
                try:
                    Decimal(value.replace(',', '.') or 'x')
                except InvalidOperation:
                    raise GraphError('Une condition attend une valeur numérique.')
            rules.append({'field': field, 'op': op, 'value': value})
        if not rules:
            raise GraphError('Chaque bloc « Si » doit contenir au moins une règle.')
        return {'match': 'any' if raw.get('match') == 'any' else 'all', 'rules': rules}

    # actions
    params = {}
    if key == 'send_email':
        recipient = raw.get('recipient') if raw.get('recipient') in EMAIL_RECIPIENTS else 'owner'
        params['recipient'] = recipient
        params['to'] = _str(raw.get('to'))
        if recipient == 'custom' and not all(_EMAIL_RE.match(a.strip()) for a in params['to'].split(',') if a.strip()):
            raise GraphError("Adresse email du destinataire invalide.")
        if recipient == 'custom' and not params['to']:
            raise GraphError("Indiquez l'adresse email du destinataire.")
        params['subject'] = _str(raw.get('subject'))
        params['body'] = _str(raw.get('body'), 5000)
        params['attachments'] = _clean_attachments(raw.get('attachments'), organization)
    elif key in ('notify', 'create_task'):
        params['title'] = _str(raw.get('title'))
        params['message'] = _str(raw.get('message'), 2000)
        params['priority'] = raw.get('priority') if raw.get('priority') in PRIORITIES else ('high' if key == 'create_task' else 'medium')
    elif key == 'create_document':
        template = _document_template(raw.get('template_id'), organization)
        if not template:
            raise GraphError('Sélectionnez un modèle de document pour « Créer un document ».')
        params['template_id'] = str(template.id)
        params['title'] = _str(raw.get('title'))
        params['field_values'] = _clean_field_values(raw.get('field_values'), template)
        params['var_values'] = _clean_var_values(raw.get('var_values'))
        params['share'] = bool(raw.get('share'))
    elif key == 'create_project':
        from apps.clients.models import Client
        from .models import ProjectProcess, ProjectTemplate
        params['value'] = _str(raw.get('value'))
        # Modèle de projet et processus de l'organisation seulement ; client = celui de l'événement ou un client fixé.
        template_id = str(raw.get('template_id') or '')
        params['template_id'] = template_id if template_id.isdigit() and ProjectTemplate.objects.filter(
            organization=organization, id=int(template_id)).exists() else ''
        process_id = str(raw.get('process_id') or '')
        params['process_id'] = process_id if process_id.isdigit() and ProjectProcess.objects.filter(
            organization=organization, id=int(process_id)).exists() else ''
        client = str(raw.get('client') or 'event')
        params['client'] = client if client == 'event' or (client.isdigit() and Client.objects.filter(
            organization=organization, id=int(client)).exists()) else 'event'
    elif key in ('create_phase', 'create_milestone', 'create_deliverable'):
        params['value'] = _str(raw.get('value'))
    elif key == 'create_form':
        params['title'] = _str(raw.get('title')) or 'Formulaire'
        params['intro'] = _str(raw.get('intro'), 1000)
        params['notify_client'] = bool(raw.get('notify_client', True))
        fields = []
        for index, field in enumerate((raw.get('fields') or [])[:MAX_FORM_FIELDS]):
            if not isinstance(field, dict) or not _str(field.get('label')):
                continue
            ftype = field.get('type') if field.get('type') in FORM_FIELD_TYPES else 'text'
            fields.append({
                'id': f'f{index + 1}',
                'label': _str(field.get('label'), 200),
                'type': ftype,
                'required': bool(field.get('required')),
                'options': _str(field.get('options'), 500) if ftype == 'select' else '',
            })
        if not fields:
            raise GraphError('« Envoyer un formulaire » : ajoutez au moins une question.')
        params['fields'] = fields
    elif key == 'drive_upload':
        # PDF de la facture / du devis de l'événement, et éventuellement des documents créés avant.
        params['include_created'] = bool(raw.get('include_created'))
    elif key == 'send_message':
        from apps.integrations.messaging import CHANNELS
        channel = raw.get('channel')
        if channel not in CHANNELS:
            raise GraphError('« Envoyer un message » : choisissez une messagerie.')
        params['channel'] = channel
        params['recipient_mode'] = raw.get('recipient_mode') if raw.get('recipient_mode') in ('default', 'client', 'custom') else 'default'
        params['recipient'] = _str(raw.get('recipient'), 60)
        params['text'] = _str(raw.get('text'), 3500)
        if not params['text']:
            raise GraphError('« Envoyer un message » : le message est vide.')
    elif key == 'app_action':
        from apps.integrations.app_actions import clean_values, operation
        spec = operation(raw.get('app'), raw.get('operation'))
        if not spec:
            raise GraphError('« Envoyer vers une app » : choisissez un outil et une opération.')
        params['app'], params['operation'] = raw['app'], raw['operation']
        try:
            params['values'] = clean_values(spec, raw.get('values'))
        except ValueError as exc:
            raise GraphError(f"« {spec['label']} » : {exc}")
    elif key == 'create_meeting':
        params['title'] = _str(raw.get('title')) or 'Réunion'
        try:
            params['in_days'] = max(0, min(365, int(raw.get('in_days') or 0)))
            params['duration'] = max(5, min(600, int(raw.get('duration') or 30)))
        except (TypeError, ValueError):
            raise GraphError('« Planifier une réunion » : délai ou durée invalide.')
        time_value = _str(raw.get('time'), 5) or '10:00'
        if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', time_value):
            raise GraphError('« Planifier une réunion » : heure invalide (HH:MM).')
        params['time'] = time_value
        params['location'] = _str(raw.get('location'))
        params['notes'] = _str(raw.get('notes'), 1000)
    return params


def _document_template(template_id, organization):
    from django.db.models import Q
    from apps.documents.models import DocumentTemplate
    template_id = str(template_id or '').strip()
    if not template_id.isdigit():
        return None
    return DocumentTemplate.objects.filter(
        Q(organization__isnull=True) | Q(organization=organization), id=int(template_id)
    ).first()


def _clean_field_values(raw, template):
    """Valeurs des champs personnalisés du modèle (clés connues seulement, choix vérifiés)."""
    fields = {f.get('id'): f for f in ((template.canvas_data or {}).get('fields') or []) if isinstance(f, dict)}
    values = {}
    for fid, value in (raw.items() if isinstance(raw, dict) else []):
        field = fields.get(fid)
        if not field:
            continue
        value = _str(value, 500)
        # Une liste de choix accepte une des options… ou une variable du workflow ({{client}}).
        if field.get('type') == 'choice' and value and value not in (field.get('options') or []) and '{{' not in value:
            raise GraphError(f"« {field.get('label')} » : choisissez une valeur de la liste.")
        values[fid] = value
    return values


def _clean_var_values(raw):
    """Variables automatiques du document remplacées (texte ou variables du workflow) ; vides = automatiques."""
    from apps.documents.models import clean_overrides
    return clean_overrides({k: _str(v, 500) for k, v in (raw.items() if isinstance(raw, dict) else [])})


def _clean_attachments(raw, organization):
    """Pièces jointes d'un email : PDF de l'événement, documents du workflow, documents à générer."""
    items = []
    for item in (raw if isinstance(raw, list) else [])[:5]:
        if not isinstance(item, dict):
            continue
        kind = item.get('kind')
        if kind in ('event', 'created') and not any(i['kind'] == kind for i in items):
            items.append({'kind': kind})
        elif kind == 'template':
            template = _document_template(item.get('template_id'), organization)
            if not template:
                raise GraphError('Pièce jointe : choisissez le document à joindre.')
            items.append({'kind': 'template', 'template_id': str(template.id),
                          'field_values': _clean_field_values(item.get('field_values'), template),
                          'var_values': _clean_var_values(item.get('var_values'))})
    return items


def _clean_groups(raw_groups):
    """Cadres de regroupement visuels du board (n'influencent pas l'exécution)."""
    groups = []
    for raw in (raw_groups if isinstance(raw_groups, list) else [])[:MAX_GROUPS]:
        if not isinstance(raw, dict) or not isinstance(raw.get('id'), str) or not _ID_RE.match(raw['id']):
            continue
        try:
            x, y = float(raw.get('x') or 0), float(raw.get('y') or 0)
            w, h = float(raw.get('w') or 320), float(raw.get('h') or 200)
        except (TypeError, ValueError):
            continue
        groups.append({
            'id': raw['id'],
            'label': _str(raw.get('label'), 80) or 'Groupe',
            'color': raw.get('color') if raw.get('color') in GROUP_COLORS else 'violet',
            'x': round(max(-5000, min(20000, x))), 'y': round(max(-5000, min(20000, y))),
            'w': round(max(160, min(6000, w))), 'h': round(max(120, min(6000, h))),
        })
    return groups


def validate_graph(raw, *, organization, valid_triggers, valid_actions):
    """Valide et normalise le graphe envoyé par le board. Lève GraphError (message lisible)."""
    if not isinstance(raw, dict):
        raise GraphError('Workflow invalide.')
    raw_nodes = raw.get('nodes') if isinstance(raw.get('nodes'), list) else []
    raw_edges = raw.get('edges') if isinstance(raw.get('edges'), list) else []
    if not raw_nodes:
        raise GraphError('Le workflow est vide.')
    if len(raw_nodes) > MAX_NODES:
        raise GraphError(f'Un workflow est limité à {MAX_NODES} blocs.')

    nodes, seen = [], set()
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            continue
        node_id, node_type, key = raw_node.get('id'), raw_node.get('type'), raw_node.get('key')
        if not isinstance(node_id, str) or not _ID_RE.match(node_id) or node_id in seen:
            raise GraphError('Identifiant de bloc invalide.')
        if node_type not in NODE_PORTS:
            raise GraphError('Type de bloc inconnu.')
        if node_type == 'trigger' and key not in valid_triggers:
            raise GraphError('Déclencheur invalide.')
        if node_type == 'action' and key not in valid_actions:
            raise GraphError('Action invalide.')
        if node_type == 'condition':
            key = 'if'
        if node_type == 'wait':
            key = 'delay'
        seen.add(node_id)
        try:
            x, y = float(raw_node.get('x') or 0), float(raw_node.get('y') or 0)
        except (TypeError, ValueError):
            x, y = 0, 0
        nodes.append({
            'id': node_id, 'type': node_type, 'key': key,
            'x': round(max(-5000, min(20000, x))), 'y': round(max(-5000, min(20000, y))),
            'label': _str(raw_node.get('label'), 80),
            'params': _clean_params(node_type, key, raw_node.get('params'), organization=organization),
        })

    triggers = [n for n in nodes if n['type'] == 'trigger']
    if len(triggers) != 1:
        raise GraphError('Un workflow doit commencer par exactement un déclencheur.')

    by_id = {n['id']: n for n in nodes}
    edges, edge_keys = [], set()
    for edge in raw_edges:
        if not isinstance(edge, dict):
            continue
        source, target, port = edge.get('from'), edge.get('to'), edge.get('port') or 'out'
        if source not in by_id or target not in by_id or source == target:
            continue
        if port not in NODE_PORTS[by_id[source]['type']]:
            continue
        if by_id[target]['type'] == 'trigger':
            raise GraphError('Un déclencheur ne peut pas recevoir de lien entrant.')
        if (source, port, target) in edge_keys:
            continue
        edge_keys.add((source, port, target))
        edges.append({'from': source, 'port': port, 'to': target})

    # Pas de boucle : un workflow s'exécute de gauche à droite, une seule fois par événement.
    children = {}
    for edge in edges:
        children.setdefault(edge['from'], []).append(edge['to'])
    state = {}

    def visit(node_id):
        state[node_id] = 'visiting'
        for child in children.get(node_id, []):
            if state.get(child) == 'visiting':
                raise GraphError('Le workflow contient une boucle : retirez le lien qui revient en arrière.')
            if child not in state:
                visit(child)
        state[node_id] = 'done'

    for node in nodes:
        if node['id'] not in state:
            visit(node['id'])

    reachable, stack = set(), [triggers[0]['id']]
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        stack.extend(children.get(current, []))
    if not any(by_id[n]['type'] == 'action' for n in reachable):
        raise GraphError('Reliez au moins une action au déclencheur.')

    return {'nodes': nodes, 'edges': edges, 'groups': _clean_groups(raw.get('groups'))}


def successors(graph, node_id, port='out'):
    return [e['to'] for e in graph.get('edges', []) if e['from'] == node_id and (e.get('port') or 'out') == port]


def wait_delta(params):
    amount = int(params.get('amount') or 1)
    unit = params.get('unit') or 'days'
    return timedelta(**{WAIT_UNITS.get(unit, 'days'): amount})


def _context_value(field, ctx):
    now = timezone.localtime()
    if field == 'amount':
        return ctx.get('amount')
    if field == 'client':
        return ctx.get('client_id')
    if field in ('client_name', 'client_email', 'client_city'):
        client = ctx.get('_client')
        if client is None and ctx.get('client_id'):
            from apps.clients.models import Client
            client = Client.objects.filter(id=ctx['client_id']).first() or False
            ctx['_client'] = client
        if not client:
            return ''
        return {'client_name': client.name, 'client_email': client.email, 'client_city': client.city}[field] or ''
    if field in ('projet', 'produit', 'formulaire'):
        return (ctx.get('variables') or {}).get(field, '')
    if field == 'weekday':
        return now.isoweekday()
    if field == 'hour':
        return now.hour
    if field == 'day_of_month':
        return now.day
    return None


def _compare(field, op, actual, expected):
    kind = CONDITION_FIELDS[field]
    empty = actual is None or str(actual).strip() == ''
    if op == 'empty':
        return empty
    if op == 'not_empty':
        return not empty
    if empty:
        return op == 'neq'
    if kind == 'number':
        try:
            a = Decimal(str(actual))
            b = Decimal(str(expected).replace(',', '.'))
        except InvalidOperation:
            return False
        return {'eq': a == b, 'neq': a != b, 'gt': a > b, 'gte': a >= b, 'lt': a < b, 'lte': a <= b}.get(op, False)
    a, b = str(actual).strip().lower(), str(expected).strip().lower()
    return {
        'eq': a == b, 'neq': a != b, 'contains': b in a, 'not_contains': b not in a, 'starts_with': a.startswith(b),
    }.get(op, False)


def evaluate_condition(params, ctx):
    """Retourne (résultat, détail lisible) pour un bloc « Si »."""
    results = []
    for rule in params.get('rules', []):
        actual = _context_value(rule['field'], ctx)
        results.append(_compare(rule['field'], rule['op'], actual, rule.get('value', '')))
    if not results:
        return True, ''
    outcome = any(results) if params.get('match') == 'any' else all(results)
    detail = f"{sum(results)}/{len(results)} règle{'s' if len(results) > 1 else ''} vérifiée{'s' if sum(results) > 1 else ''}"
    return outcome, detail
