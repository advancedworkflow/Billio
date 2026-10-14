"""
Déclencheur « Webhook entrant » : chaque workflow reçoit une adresse secrète
(/dashboard/automations/hook/<jeton>/) que l'on colle dans un outil externe (formulaire
de site, Typeform, Calendly, Shopify, Make, Zapier, n8n…). Chaque requête POST lance
le workflow avec les données reçues :

- le JSON (ou le formulaire) est aplati en variables : {"customer": {"email": "…"}}
  devient {{customer_email}} ; les listes sont numérotées ({{items_0_name}}) ;
- un champ email est rapproché d'un client de l'organisation (créé si l'option est
  cochée), ce qui rend disponibles {{client}} et les actions « au client » ;
- un champ amount / montant / total renseigne {{montant}} et les conditions de montant ;
- l'en-tête Idempotency-Key (ou un champ id / event_id) évite un double déclenchement
  quand l'outil renvoie la même requête.
"""
import json
import logging
import re
import secrets
import uuid
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{32,64}$')
MAX_BODY = 256 * 1024
MAX_VARIABLES = 150
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
AMOUNT_KEYS = ('amount', 'montant', 'total', 'total_price', 'price', 'prix', 'value')
NAME_KEYS = ('name', 'nom', 'full_name', 'fullname', 'company', 'societe', 'entreprise')
ID_KEYS = ('id', 'event_id', 'eventid', 'uuid')


def _token_taken(token, organization):
    """Jeton déjà utilisé par le workflow d'une autre organisation."""
    from .models import AutomationRule
    return AutomationRule.objects.filter(trigger_key='webhook_received', graph__icontains=token).exclude(
        organization=organization).exists()


def clean_trigger_params(raw, organization):
    token = str(raw.get('token') or '')
    if not TOKEN_RE.match(token) or _token_taken(token, organization):
        token = secrets.token_urlsafe(32)
    return {'token': token, 'create_client': bool(raw.get('create_client'))}


def _key(text):
    return re.sub(r'[^a-z0-9]+', '_', str(text).lower()).strip('_')[:60]


def flatten(data, prefix='', out=None):
    """{"a": {"b": 1}, "l": [{"c": 2}]} → {"a_b": "1", "l_0_c": "2"} (valeurs texte, 500 caractères)."""
    out = {} if out is None else out
    if len(out) >= MAX_VARIABLES:
        return out
    if isinstance(data, dict):
        for k, v in data.items():
            flatten(v, f'{prefix}_{_key(k)}' if prefix else _key(k), out)
    elif isinstance(data, list):
        if prefix and all(not isinstance(x, (dict, list)) for x in data):
            out[prefix] = ', '.join(str(x) for x in data)[:500]
        else:
            for index, item in enumerate(data[:20]):
                flatten(item, f'{prefix}_{index}' if prefix else str(index), out)
    elif prefix:
        out[prefix] = '' if data is None else str(data)[:500]
    return out


def _read_payload(request):
    if len(request.body) > MAX_BODY:
        raise ValueError('Requête trop volumineuse (256 Ko maximum).')
    content_type = (request.content_type or '').lower()
    if 'json' in content_type or request.body[:1] in (b'{', b'['):
        try:
            return json.loads(request.body.decode('utf-8') or '{}')
        except ValueError:
            raise ValueError('JSON invalide.') from None
    return {k: (v if len(v) > 1 else v[0]) for k, v in request.POST.lists()}


def _find(variables, keys, check=None):
    """Première variable dont le nom vaut (ou se termine par) une des clés."""
    for wanted in keys:
        for name, value in variables.items():
            if (name == wanted or name.endswith('_' + wanted)) and value and (check is None or check(value)):
                return name, value
    return None, None


def _as_amount(value):
    try:
        return Decimal(str(value).replace('€', '').replace(' ', '').replace(' ', '').replace(',', '.'))
    except InvalidOperation:
        return None


def _rules_for(token):
    from .models import AutomationRule
    if not TOKEN_RE.match(token or ''):
        return []
    candidates = AutomationRule.objects.filter(trigger_key='webhook_received', is_active=True, graph__icontains=token).select_related('organization')
    rules = []
    for rule in candidates:
        trigger = next((n for n in rule.get_graph().get('nodes', []) if n.get('type') == 'trigger'), None)
        if trigger and secrets.compare_digest(str((trigger.get('params') or {}).get('token') or ''), token):
            rules.append((rule, trigger.get('params') or {}))
    return rules


@csrf_exempt
@require_POST
def receive_webhook(request, token):
    from apps.clients.models import Client
    from .automation_engine import run_automations

    from apps.subscriptions.entitlements import has_feature
    matches = [(rule, params) for rule, params in _rules_for(token) if has_feature(rule.organization, 'inbound_webhooks')]
    if not matches:
        return JsonResponse({'ok': False, 'error': 'Webhook inconnu ou workflow désactivé.'}, status=404)
    try:
        payload = _read_payload(request)
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    variables = flatten(payload if isinstance(payload, (dict, list)) else {'value': payload})
    _, email = _find(variables, ('email', 'email_address', 'mail', 'courriel'), lambda v: bool(EMAIL_RE.match(v)))
    _, amount_raw = _find(variables, AMOUNT_KEYS, lambda v: _as_amount(v) is not None)
    amount = _as_amount(amount_raw) if amount_raw else None
    _, name = _find(variables, NAME_KEYS)
    first, last = variables.get('first_name') or variables.get('prenom') or '', variables.get('last_name') or ''
    name = name or f'{first} {last}'.strip()
    if email:
        variables.setdefault('email', email)
    # Toutes les données reçues, lisibles : « Champ : valeur » (description du projet, e-mail…).
    variables.setdefault('donnees_recues', '\n'.join(
        f"{key.replace('_', ' ').capitalize()} : {value}" for key, value in list(variables.items())[:MAX_VARIABLES] if value
    )[:4000])
    # Coordonnées reconnues pour la fiche d'un client créé à la volée.
    client_details = {
        field: (_find(variables, keys)[1] or '')[:limit]
        for field, keys, limit in (
            ('company_name', ('company', 'company_name', 'entreprise', 'societe', 'organization'), 200),
            ('address', ('address', 'adresse', 'street', 'address_line1', 'rue'), 500),
            ('postal_code', ('postal_code', 'zip', 'zipcode', 'code_postal', 'cp'), 20),
            ('city', ('city', 'ville', 'town'), 100),
            ('country', ('country', 'pays'), 100),
        )
    }

    delivery = request.headers.get('Idempotency-Key') or _find(variables, ID_KEYS)[1] or uuid.uuid4().hex
    started = 0
    for rule, params in matches:
        organization = rule.organization
        client = Client.objects.filter(organization=organization, email__iexact=email).first() if email else None
        if not client and email and params.get('create_client'):
            client = Client.objects.create(organization=organization, email=email, name=(name or email)[:200],
                                           phone=(variables.get('phone') or variables.get('telephone') or '')[:20] or None,
                                           **{k: v or None for k, v in client_details.items()})
        target_id = f'{rule.id}:{delivery}'[:64]
        try:
            run_automations(
                organization, 'webhook_received', target_type='webhook', target_id=target_id,
                amount=amount, client_id=client.id if client else None, variables=dict(variables),
                context_label=f"Webhook reçu{f' ({email})' if email else ''}", only_rule=rule,
            )
            started += 1
        except Exception:  # un workflow en échec n'empêche pas les autres
            logger.exception('Webhook entrant : échec du workflow %s', rule.id)
    return JsonResponse({'ok': True, 'workflows': started, 'variables': sorted(variables)[:MAX_VARIABLES]}, status=202)
