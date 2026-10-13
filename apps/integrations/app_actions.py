"""
Actions d'automatisation vers les outils connectés (action « Envoyer vers une app »).

Chaque outil du catalogue peut déclarer des opérations : créer une carte Trello, une
tâche Asana, un contact HubSpot, envoyer l'événement à Make… Une opération décrit ses
champs (affichés dans le board, variables {{client}}… permises dans les textes) et une
fonction run(config, values, event) qui appelle l'API officielle du service via
providers.http (hôtes autorisés uniquement) et renvoie un court détail pour le journal.

Ajouter une opération : la déclarer dans APP_ACTIONS ci-dessous ; le board, la
validation du graphe et le moteur la prennent en compte sans autre modification.

`event` (voir event_payload) : {'source', 'event', 'event_label', 'summary', 'target',
'amount', 'client': {...} | None, 'variables', 'organization', 'sent_at'}.
"""
import hashlib
import re
import urllib.parse
from datetime import datetime, time, timedelta

from django.utils import timezone

from .catalog import _basic, _bearer

MAX_TEXT = 5000


def _http(*args, **kwargs):
    from .providers import http
    return http(*args, **kwargs)


def _fail(message):
    from .providers import ProviderError
    raise ProviderError(message)


def field(name, label, *, kind='text', required=False, placeholder='', help='', options=None, default='', pattern=None):
    """Champ d'une opération. kind : text (variables permises), textarea, select, id (identifiant, sans variable)."""
    spec = {'name': name, 'label': label, 'kind': kind, 'required': required, 'placeholder': placeholder,
            'help': help, 'default': default}
    if options:
        spec['options'] = options
    if pattern:
        spec['pattern'] = pattern
    return spec


def op(key, label, fields, run, *, needs_email=False, desc=''):
    return {'key': key, 'label': label, 'fields': fields, 'run': run, 'needs_email': needs_email, 'desc': desc}


# --------------------------------------------------------------------------- #
# Aides
# --------------------------------------------------------------------------- #

def _client(event):
    client = event.get('client') or {}
    if not client.get('email'):
        _fail("Le client de l'événement n'a pas d'adresse email.")
    return client


def _split_name(client):
    """(prénom, nom) depuis l'interlocuteur du client, à défaut son nom."""
    full = (client.get('contact_person') or client.get('name') or '').strip()
    first, _, last = full.partition(' ')
    return first, last


def _due(days):
    try:
        days = int(str(days).strip())
    except (TypeError, ValueError):
        return None
    return timezone.localdate() + timedelta(days=max(0, min(days, 3650)))


def _amount(values, event, name='value'):
    raw = str(values.get(name) or '').replace('€', '').replace(' ', '').replace(' ', '').replace(',', '.')
    raw = raw or str(event.get('amount') or '')
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _lines(text):
    """« Colonne : valeur » (une par ligne) → {colonne: valeur}."""
    out = {}
    for line in (text or '').splitlines():
        name, sep, value = line.partition(':')
        if sep and name.strip():
            out[name.strip()] = value.strip()
    return out


def _graphql(url, headers, query, variables):
    data = _http('POST', url, headers=headers, json_body={'query': query, 'variables': variables})
    errors = data.get('errors') or ([{'message': data['error_message']}] if data.get('error_message') else [])
    if errors:
        _fail(str(errors[0].get('message') or errors[0])[:200])
    return data.get('data') or {}


def _is_conflict(exc):
    return 'Erreur 409' in str(exc)


# --------------------------------------------------------------------------- #
# Tâches & projets
# --------------------------------------------------------------------------- #

TASK_TITLE = field('title', 'Titre', required=True, default='{{evenement}}', placeholder='Relancer {{client}}')
TASK_BODY = field('body', 'Description', kind='textarea', default='Client : {{client}}\nMontant : {{montant}}')
TASK_DUE = field('due_days', 'Échéance dans (jours)', kind='id', placeholder='Vide = sans échéance', pattern=r'\d{1,4}')


def _trello_card(config, v, event):
    params = {'key': config['api_key'], 'token': config['token'], 'idList': v['list_id'],
              'name': v['title'][:500], 'desc': v.get('body', '')[:MAX_TEXT], 'pos': 'top'}
    due = _due(v.get('due_days'))
    if due:
        params['due'] = due.isoformat()
    card = _http('POST', 'https://api.trello.com/1/cards?' + urllib.parse.urlencode(params))
    return f"Carte Trello créée : {card.get('shortUrl') or card.get('name', '')}"


def _asana_task(config, v, event):
    data = {'name': v['title'][:500], 'notes': v.get('body', '')[:MAX_TEXT], 'projects': [v['project_id']]}
    due = _due(v.get('due_days'))
    if due:
        data['due_on'] = due.isoformat()
    task = _http('POST', 'https://app.asana.com/api/1.0/tasks', headers=_bearer(config['access_token']),
                 json_body={'data': data}).get('data') or {}
    return f"Tâche Asana créée : {task.get('permalink_url') or task.get('name', '')}"


def _clickup_task(config, v, event):
    body = {'name': v['title'][:500], 'description': v.get('body', '')[:MAX_TEXT]}
    due = _due(v.get('due_days'))
    if due:
        body['due_date'] = int(timezone.make_aware(datetime.combine(due, time(9, 0))).timestamp() * 1000)
    task = _http('POST', f"https://api.clickup.com/api/v2/list/{v['list_id']}/task",
                 headers={'Authorization': config['access_token']}, json_body=body)
    return f"Tâche ClickUp créée : {task.get('url') or task.get('name', '')}"


def _todoist_task(config, v, event):
    body = {'content': v['title'][:500], 'description': v.get('body', '')[:MAX_TEXT]}
    if v.get('project_id'):
        body['project_id'] = v['project_id']
    due = _due(v.get('due_days'))
    if due:
        body['due_date'] = due.isoformat()
    task = _http('POST', 'https://api.todoist.com/api/v1/tasks', headers=_bearer(config['access_token']), json_body=body)
    return f"Tâche Todoist créée : {task.get('content', v['title'])}"


def _linear_issue(config, v, event):
    headers = {'Authorization': config['api_key']}
    team = v['team'].strip()
    if not re.fullmatch(r'[0-9a-f-]{36}', team):  # clé d'équipe (ex. ENG) → identifiant
        found = _graphql('https://api.linear.app/graphql', headers,
                         'query($key: String!) { teams(filter: {key: {eq: $key}}) { nodes { id } } }', {'key': team.upper()})
        nodes = (found.get('teams') or {}).get('nodes') or []
        if not nodes:
            _fail(f"Équipe Linear « {team} » introuvable.")
        team = nodes[0]['id']
    data = _graphql('https://api.linear.app/graphql', headers,
                    'mutation($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { identifier url } } }',
                    {'input': {'teamId': team, 'title': v['title'][:500], 'description': v.get('body', '')[:MAX_TEXT]}})
    issue = (data.get('issueCreate') or {}).get('issue') or {}
    return f"Ticket Linear {issue.get('identifier', '')} créé".replace('  ', ' ')


def _jira_issue(config, v, event):
    paragraphs = [{'type': 'paragraph', 'content': [{'type': 'text', 'text': line}]}
                  for line in (v.get('body') or '').splitlines() if line.strip()]
    fields = {
        'project': {'key': v['project_key'].upper()},
        'issuetype': {'name': v.get('issue_type') or 'Task'},
        'summary': v['title'][:250],
        'description': {'type': 'doc', 'version': 1, 'content': paragraphs or [{'type': 'paragraph', 'content': []}]},
    }
    due = _due(v.get('due_days'))
    if due:
        fields['duedate'] = due.isoformat()
    issue = _http('POST', f"https://{config['host']}/rest/api/3/issue", json_body={'fields': fields},
                  headers={'Authorization': _basic(config['email'], config['api_token']), 'Accept': 'application/json'})
    return f"Ticket Jira {issue.get('key', '')} créé"


def _github_issue(config, v, event):
    body = {'title': v['title'][:250], 'body': v.get('body', '')[:MAX_TEXT]}
    labels = [label.strip() for label in (v.get('labels') or '').split(',') if label.strip()]
    if labels:
        body['labels'] = labels[:10]
    issue = _http('POST', f"https://api.github.com/repos/{v['repo']}/issues", json_body=body, headers={
        **_bearer(config['access_token']), 'Accept': 'application/vnd.github+json', 'User-Agent': 'Billio'})
    return f"Issue GitHub #{issue.get('number', '?')} créée"


def _monday_item(config, v, event):
    data = _graphql('https://api.monday.com/v2', {'Authorization': config['access_token'], 'API-Version': '2024-10'},
                    'mutation($board: ID!, $name: String!) { create_item(board_id: $board, item_name: $name) { id } }',
                    {'board': v['board_id'], 'name': v['title'][:255]})
    return f"Élément monday.com créé (n° {(data.get('create_item') or {}).get('id', '?')})"


def _airtable_record(config, v, event):
    fields = _lines(v.get('fields'))
    if not fields:
        _fail('Airtable : indiquez au moins une ligne « Colonne : valeur ».')
    table = urllib.parse.quote(v['table'], safe='')
    data = _http('POST', f"https://api.airtable.com/v0/{v['base_id']}/{table}", headers=_bearer(config['access_token']),
                 json_body={'records': [{'fields': fields}], 'typecast': True})
    return f"Ligne Airtable ajoutée ({len(data.get('records') or [])} enregistrement)"


def _notion_row(config, v, event):
    from .providers import notion_headers, notion_id
    headers = notion_headers(config)
    db_id = notion_id(v['database']) or v['database']
    db = _http('GET', f'https://api.notion.com/v1/databases/{db_id}', headers=headers)
    schema = {name: prop.get('type') for name, prop in (db.get('properties') or {}).items()}
    title_name = next((name for name, kind in schema.items() if kind == 'title'), None)
    values = _lines(v.get('fields'))
    if v.get('title') and title_name:
        values.setdefault(title_name, v['title'])
    props, unknown = {}, []
    for name, value in values.items():
        kind = schema.get(name)
        text = [{'text': {'content': value[:2000]}}]
        if kind == 'title':
            props[name] = {'title': text}
        elif kind == 'rich_text':
            props[name] = {'rich_text': text}
        elif kind == 'number':
            try:
                props[name] = {'number': float(value.replace('€', '').replace(' ', '').replace(',', '.'))}
            except ValueError:
                continue
        elif kind == 'date':
            match = re.match(r'(\d{2})/(\d{2})/(\d{4})', value)
            iso = f'{match.group(3)}-{match.group(2)}-{match.group(1)}' if match else value[:10]
            props[name] = {'date': {'start': iso}}
        elif kind in ('select', 'status'):
            props[name] = {kind: {'name': value[:100]}}
        elif kind == 'multi_select':
            props[name] = {'multi_select': [{'name': x.strip()[:100]} for x in value.split(',') if x.strip()]}
        elif kind in ('email', 'url', 'phone_number'):
            props[name] = {kind: value or None}
        elif kind == 'checkbox':
            props[name] = {'checkbox': value.strip().lower() in ('1', 'oui', 'true', 'vrai', 'x')}
        else:
            unknown.append(name)
    if not props:
        _fail('Notion : aucune colonne reconnue dans la base (vérifiez les noms).')
    page = _http('POST', 'https://api.notion.com/v1/pages', headers=headers,
                 json_body={'parent': {'database_id': db_id}, 'properties': props})
    detail = f"Ligne ajoutée dans Notion : {page.get('url', '')}"
    return detail + (f" (colonnes ignorées : {', '.join(unknown)})" if unknown else '')


# --------------------------------------------------------------------------- #
# CRM & support
# --------------------------------------------------------------------------- #

def _hubspot_contact_id(config, client):
    first, last = _split_name(client)
    properties = {'email': client['email'], 'firstname': first, 'lastname': last, 'phone': client.get('phone') or '',
                  'company': client.get('company') or client.get('name') or '', 'city': client.get('city') or ''}
    data = _http('POST', 'https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert', headers=_bearer(config['access_token']),
                 json_body={'inputs': [{'idProperty': 'email', 'id': client['email'], 'properties': {k: v for k, v in properties.items() if v}}]})
    return ((data.get('results') or [{}])[0]).get('id')


def _hubspot_contact(config, v, event):
    client = _client(event)
    _hubspot_contact_id(config, client)
    return f"Contact HubSpot à jour : {client['email']}"


def _hubspot_deal(config, v, event):
    properties = {'dealname': v['title'][:250], 'pipeline': v.get('pipeline') or 'default',
                  'dealstage': v.get('stage') or 'appointmentscheduled'}
    amount = _amount(v, event)
    if amount is not None:
        properties['amount'] = str(amount)
    body = {'properties': properties}
    if (event.get('client') or {}).get('email'):
        contact_id = _hubspot_contact_id(config, event['client'])
        if contact_id:
            body['associations'] = [{'to': {'id': contact_id}, 'types': [
                {'associationCategory': 'HUBSPOT_DEFINED', 'associationTypeId': 3}]}]
    deal = _http('POST', 'https://api.hubapi.com/crm/v3/objects/deals', headers=_bearer(config['access_token']), json_body=body)
    return f"Transaction HubSpot créée (n° {deal.get('id', '?')})"


def _pipedrive_person_id(config, client):
    token = urllib.parse.quote(config['api_token'])
    base = 'https://api.pipedrive.com/v1'
    found = _http('GET', f"{base}/persons/search?{urllib.parse.urlencode({'term': client['email'], 'fields': 'email', 'exact_match': 'true'})}&api_token={token}")
    items = ((found.get('data') or {}).get('items') or [])
    if items:
        return items[0]['item']['id'], False
    body = {'name': client.get('contact_person') or client.get('name') or client['email'],
            'email': [{'value': client['email'], 'primary': True}]}
    if client.get('phone'):
        body['phone'] = [{'value': client['phone'], 'primary': True}]
    person = _http('POST', f'{base}/persons?api_token={token}', json_body=body).get('data') or {}
    return person.get('id'), True


def _pipedrive_person(config, v, event):
    client = _client(event)
    _, created = _pipedrive_person_id(config, client)
    return f"Contact Pipedrive {'créé' if created else 'déjà présent'} : {client['email']}"


def _pipedrive_deal(config, v, event):
    body = {'title': v['title'][:250], 'currency': 'EUR'}
    amount = _amount(v, event)
    if amount is not None:
        body['value'] = amount
    if (event.get('client') or {}).get('email'):
        body['person_id'], _ = _pipedrive_person_id(config, event['client'])
    deal = _http('POST', f"https://api.pipedrive.com/v1/deals?api_token={urllib.parse.quote(config['api_token'])}",
                 json_body=body).get('data') or {}
    return f"Affaire Pipedrive créée (n° {deal.get('id', '?')})"


def _attio_person(config, v, event):
    client = _client(event)
    first, last = _split_name(client)
    values = {'email_addresses': [client['email']],
              'name': [{'first_name': first, 'last_name': last, 'full_name': f'{first} {last}'.strip()}]}
    _http('PUT', 'https://api.attio.com/v2/objects/people/records?matching_attribute=email_addresses',
          headers=_bearer(config['access_token']), json_body={'data': {'values': values}})
    return f"Personne Attio à jour : {client['email']}"


def _intercom_contact(config, v, event):
    from .providers import ProviderError
    client = _client(event)
    body = {'role': 'user', 'email': client['email'], 'name': client.get('contact_person') or client.get('name') or ''}
    if client.get('phone'):
        body['phone'] = client['phone']
    try:
        _http('POST', 'https://api.intercom.io/contacts', json_body=body,
              headers={**_bearer(config['access_token']), 'Accept': 'application/json'})
    except ProviderError as exc:
        if _is_conflict(exc):
            return f"Contact Intercom déjà présent : {client['email']}"
        raise
    return f"Contact Intercom créé : {client['email']}"


def _close_lead(config, v, event):
    client = _client(event)
    contact = {'name': client.get('contact_person') or client.get('name') or '', 'emails': [{'email': client['email'], 'type': 'office'}]}
    if client.get('phone'):
        contact['phones'] = [{'phone': client['phone'], 'type': 'office'}]
    lead = _http('POST', 'https://api.close.com/api/v1/lead/', headers={'Authorization': _basic(config['api_key'], '')},
                 json_body={'name': client.get('company') or client.get('name'), 'description': v.get('body', '')[:MAX_TEXT],
                            'contacts': [contact]})
    return f"Lead Close créé : {lead.get('display_name', client.get('name', ''))}"


TICKET_PRIORITY = [['low', 'Basse'], ['normal', 'Normale'], ['high', 'Haute'], ['urgent', 'Urgente']]


def _zendesk_ticket(config, v, event):
    client = event.get('client') or {}
    ticket = {'subject': v['title'][:250], 'comment': {'body': v.get('body') or v['title']}, 'priority': v.get('priority') or 'normal'}
    if client.get('email'):
        ticket['requester'] = {'name': client.get('name') or client['email'], 'email': client['email']}
    data = _http('POST', f"https://{config['host']}/api/v2/tickets.json", json_body={'ticket': ticket},
                 headers={'Authorization': _basic(f"{config['email']}/token", config['api_token'])})
    return f"Ticket Zendesk n° {(data.get('ticket') or {}).get('id', '?')} créé"


def _freshdesk_ticket(config, v, event):
    client = _client(event)
    priority = {'low': 1, 'normal': 2, 'high': 3, 'urgent': 4}.get(v.get('priority'), 2)
    ticket = _http('POST', f"https://{config['host']}/api/v2/tickets", headers={'Authorization': _basic(config['api_key'], 'X')},
                   json_body={'subject': v['title'][:250], 'description': (v.get('body') or v['title']).replace('\n', '<br>'),
                              'email': client['email'], 'name': client.get('name') or '', 'priority': priority, 'status': 2})
    return f"Ticket Freshdesk n° {ticket.get('id', '?')} créé"


# --------------------------------------------------------------------------- #
# Marketing (listes de contacts)
# --------------------------------------------------------------------------- #

def _brevo_contact(config, v, event):
    client = _client(event)
    first, last = _split_name(client)
    body = {'email': client['email'], 'updateEnabled': True, 'attributes': {'PRENOM': first, 'NOM': last, 'FIRSTNAME': first, 'LASTNAME': last}}
    if v.get('list_id'):
        body['listIds'] = [int(v['list_id'])]
    headers = {'api-key': config['api_key'], 'Accept': 'application/json'}
    from .providers import ProviderError
    try:
        _http('POST', 'https://api.brevo.com/v3/contacts', json_body=body, headers=headers)
    except ProviderError as exc:
        if 'attribute' not in str(exc).lower():
            raise
        # Les noms d'attributs dépendent de la langue du compte (PRENOM / FIRSTNAME) : on réessaie sans.
        body.pop('attributes')
        _http('POST', 'https://api.brevo.com/v3/contacts', json_body=body, headers=headers)
    return f"Contact Brevo à jour : {client['email']}" + (f" (liste {v['list_id']})" if v.get('list_id') else '')


def _mailchimp_member(config, v, event):
    client = _client(event)
    first, last = _split_name(client)
    dc = config['api_key'].rsplit('-', 1)[-1]
    member = hashlib.md5(client['email'].lower().encode('utf-8')).hexdigest()  # noqa: S324 (identifiant imposé par Mailchimp)
    base = f"https://{dc}.api.mailchimp.com/3.0/lists/{v['list_id']}/members/{member}"
    headers = {'Authorization': _basic('billio', config['api_key'])}
    _http('PUT', base, headers=headers, json_body={'email_address': client['email'], 'status_if_new': v.get('status') or 'subscribed',
                                                    'merge_fields': {'FNAME': first, 'LNAME': last}})
    tags = [t.strip() for t in (v.get('tags') or '').split(',') if t.strip()]
    if tags:
        _http('POST', base + '/tags', headers=headers, raw=True, json_body={'tags': [{'name': t, 'status': 'active'} for t in tags[:10]]})
    return f"Abonné Mailchimp à jour : {client['email']}"


def _mailerlite_subscriber(config, v, event):
    client = _client(event)
    first, last = _split_name(client)
    body = {'email': client['email'], 'fields': {'name': first, 'last_name': last, 'company': client.get('company') or '',
                                                 'city': client.get('city') or '', 'phone': client.get('phone') or ''}}
    if v.get('group_id'):
        body['groups'] = [v['group_id']]
    _http('POST', 'https://connect.mailerlite.com/api/subscribers', json_body=body,
          headers={**_bearer(config['api_key']), 'Accept': 'application/json'})
    return f"Abonné MailerLite à jour : {client['email']}"


def _klaviyo_profile(config, v, event):
    client = _client(event)
    first, last = _split_name(client)
    headers = {'Authorization': f"Klaviyo-API-Key {config['api_key']}", 'revision': '2024-10-15',
               'Accept': 'application/vnd.api+json', 'Content-Type': 'application/vnd.api+json'}
    attributes = {'email': client['email'], 'first_name': first, 'last_name': last, 'organization': client.get('company') or ''}
    profile = _http('POST', 'https://a.klaviyo.com/api/profile-import', headers=headers,
                    json_body={'data': {'type': 'profile', 'attributes': attributes}}).get('data') or {}
    if v.get('list_id') and profile.get('id'):
        _http('POST', f"https://a.klaviyo.com/api/lists/{v['list_id']}/relationships/profiles", headers=headers, raw=True,
              json_body={'data': [{'type': 'profile', 'id': profile['id']}]})
    return f"Profil Klaviyo à jour : {client['email']}"


def _kit_subscriber(config, v, event):
    client = _client(event)
    headers = {'X-Kit-Api-Key': config['api_key'], 'Accept': 'application/json'}
    _http('POST', 'https://api.kit.com/v4/subscribers', headers=headers,
          json_body={'email_address': client['email'], 'first_name': _split_name(client)[0]})
    if v.get('tag_id'):
        _http('POST', f"https://api.kit.com/v4/tags/{v['tag_id']}/subscribers", headers=headers, json_body={'email_address': client['email']})
    return f"Abonné Kit à jour : {client['email']}"


def _activecampaign_contact(config, v, event):
    client = _client(event)
    first, last = _split_name(client)
    headers = {'Api-Token': config['api_key']}
    data = _http('POST', f"https://{config['host']}/api/3/contact/sync", headers=headers,
                 json_body={'contact': {'email': client['email'], 'firstName': first, 'lastName': last, 'phone': client.get('phone') or ''}})
    contact_id = (data.get('contact') or {}).get('id')
    if v.get('list_id') and contact_id:
        _http('POST', f"https://{config['host']}/api/3/contactLists", headers=headers,
              json_body={'contactList': {'list': v['list_id'], 'contact': contact_id, 'status': 1}})
    return f"Contact ActiveCampaign à jour : {client['email']}"


# --------------------------------------------------------------------------- #
# Plateformes d'automatisation : l'événement complet en JSON
# --------------------------------------------------------------------------- #

def _send_event(config, v, event):
    payload = dict(event)
    if v.get('note'):
        payload['note'] = v['note']
    _http('POST', config['webhook_url'], raw=True, json_body=payload)
    return "Événement transmis (JSON complet)"


def _ifttt_event(config, v, event):
    _http('POST', f"https://maker.ifttt.com/trigger/{config['event']}/with/key/{config['key']}", raw=True,
          json_body={'value1': v.get('value1', ''), 'value2': v.get('value2', ''), 'value3': v.get('value3', '')})
    return f"Évènement IFTTT « {config['event']} » déclenché"


SEND_EVENT = op('send_event', "Envoyer l'événement (JSON)",
                [field('note', 'Note ajoutée au JSON', help="Facultatif. Le JSON contient déjà l'événement, le client, le montant et toutes les variables.")],
                _send_event, desc="Transmet tout l'événement au scénario : client, montant, numéro, variables.")

CONTACT_DESC = "Crée ou met à jour le contact du client de l'événement (email, nom, téléphone)."

APP_ACTIONS = {
    # Tâches & projets
    'trello': [op('create_card', 'Créer une carte', [
        field('list_id', 'ID de la liste', kind='id', required=True, pattern=r'[0-9a-fA-F]{24}',
              help="Ouvrez une carte de la liste, ajoutez « .json » à son adresse et copiez la valeur « idList »."),
        TASK_TITLE, TASK_BODY, TASK_DUE], _trello_card)],
    'asana': [op('create_task', 'Créer une tâche', [
        field('project_id', 'ID du projet', kind='id', required=True, pattern=r'\d{5,25}',
              help="Le nombre dans l'adresse du projet : app.asana.com/0/<ID>/…"),
        TASK_TITLE, TASK_BODY, TASK_DUE], _asana_task)],
    'clickup': [op('create_task', 'Créer une tâche', [
        field('list_id', 'ID de la liste', kind='id', required=True, pattern=r'\d{3,25}',
              help="Menu « … » de la liste › Copier le lien : le nombre à la fin de l'adresse."),
        TASK_TITLE, TASK_BODY, TASK_DUE], _clickup_task)],
    'todoist': [op('create_task', 'Créer une tâche', [
        field('project_id', 'ID du projet', kind='id', pattern=r'[\w-]{1,40}',
              help="Facultatif (Boîte de réception si vide) : fin de l'adresse du projet dans Todoist."),
        TASK_TITLE, TASK_BODY, TASK_DUE], _todoist_task)],
    'linear': [op('create_issue', 'Créer un ticket', [
        field('team', "Équipe (clé ou ID)", kind='id', required=True, placeholder='ENG', pattern=r'[\w-]{1,40}',
              help="La clé courte de l'équipe, visible devant les numéros de tickets (ex. ENG-123)."),
        TASK_TITLE, TASK_BODY], _linear_issue)],
    'jira': [op('create_issue', 'Créer un ticket', [
        field('project_key', 'Clé du projet', kind='id', required=True, placeholder='PROJ', pattern=r'[A-Za-z][A-Za-z0-9_]{0,19}'),
        field('issue_type', 'Type de ticket', kind='id', default='Task', placeholder='Task',
              help="Nom exact du type dans votre projet (Task, Tâche, Bug…)."),
        TASK_TITLE, TASK_BODY, TASK_DUE], _jira_issue)],
    'github': [op('create_issue', 'Créer une issue', [
        field('repo', 'Dépôt', kind='id', required=True, placeholder='organisation/depot', pattern=r'[\w.-]+/[\w.-]+'),
        TASK_TITLE, TASK_BODY, field('labels', 'Étiquettes', placeholder='client, facturation', help='Séparées par des virgules.')],
        _github_issue)],
    'monday': [op('create_item', 'Créer un élément', [
        field('board_id', 'ID du tableau', kind='id', required=True, pattern=r'\d{3,25}', help="Le nombre dans l'adresse du tableau : …/boards/<ID>"),
        TASK_TITLE], _monday_item)],
    'airtable': [op('create_record', 'Ajouter une ligne', [
        field('base_id', 'ID de la base', kind='id', required=True, placeholder='app…', pattern=r'app\w{10,20}',
              help="Début de l'adresse de la base : airtable.com/<appXXXX>/…"),
        field('table', 'Table (nom ou ID)', kind='id', required=True, placeholder='Clients'),
        field('fields', 'Colonnes', kind='textarea', required=True, default='Nom : {{client}}\nMontant : {{montant}}\nDate : {{date}}',
              help="Une ligne par colonne : « Nom de la colonne : valeur ». Les colonnes doivent exister dans la table.")],
        _airtable_record)],
    'notion': [op('create_row', 'Ajouter une ligne à une base', [
        field('database', 'Base Notion (lien ou ID)', kind='id', required=True, placeholder='https://www.notion.so/…',
              help="La base doit être partagée avec l'intégration (menu « … › Connexions »)."),
        field('title', 'Titre de la ligne', default='{{evenement}}'),
        field('fields', 'Autres colonnes', kind='textarea', default='Client : {{client}}\nMontant : {{montant}}',
              help="« Colonne : valeur », une par ligne. Texte, nombre, date, sélection, email, URL et case à cocher sont reconnus.")],
        _notion_row)],
    # CRM & support
    'hubspot': [
        op('upsert_contact', 'Créer / mettre à jour le contact', [], _hubspot_contact, needs_email=True, desc=CONTACT_DESC),
        op('create_deal', 'Créer une transaction', [
            field('title', 'Nom de la transaction', required=True, default='{{client}} — {{numero}}'),
            field('value', 'Montant', placeholder="Vide = montant de l'événement"),
            field('pipeline', 'Pipeline', kind='id', default='default'),
            field('stage', 'Étape', kind='id', default='appointmentscheduled',
                  help="ID interne de l'étape (Paramètres › Objets › Transactions › Pipelines).")],
            _hubspot_deal, desc='Crée une transaction reliée au contact du client.'),
    ],
    'pipedrive': [
        op('upsert_person', 'Créer le contact', [], _pipedrive_person, needs_email=True, desc=CONTACT_DESC),
        op('create_deal', 'Créer une affaire', [
            field('title', "Titre de l'affaire", required=True, default='{{client}} — {{numero}}'),
            field('value', 'Montant', placeholder="Vide = montant de l'événement")],
            _pipedrive_deal, desc='Crée une affaire reliée au contact du client.'),
    ],
    'attio': [op('upsert_person', 'Créer / mettre à jour la personne', [], _attio_person, needs_email=True, desc=CONTACT_DESC)],
    'intercom': [op('create_contact', 'Créer le contact', [], _intercom_contact, needs_email=True, desc=CONTACT_DESC)],
    'close': [op('create_lead', 'Créer un lead', [field('body', 'Description', kind='textarea', default='{{evenement}}')],
                 _close_lead, needs_email=True)],
    'zendesk': [op('create_ticket', 'Créer un ticket', [
        TASK_TITLE, TASK_BODY, field('priority', 'Priorité', kind='select', options=TICKET_PRIORITY, default='normal')], _zendesk_ticket)],
    'freshdesk': [op('create_ticket', 'Créer un ticket', [
        TASK_TITLE, TASK_BODY, field('priority', 'Priorité', kind='select', options=TICKET_PRIORITY, default='normal')],
        _freshdesk_ticket, needs_email=True)],
    # Marketing
    'brevo': [op('add_contact', 'Ajouter le contact', [
        field('list_id', 'ID de la liste', kind='id', pattern=r'\d{1,10}', help='Facultatif : Contacts › Listes, colonne « ID ».')],
        _brevo_contact, needs_email=True, desc=CONTACT_DESC)],
    'mailchimp': [op('add_member', "Ajouter à l'audience", [
        field('list_id', "ID de l'audience", kind='id', required=True, pattern=r'[0-9a-f]{10}',
              help="Audience › Paramètres › « Audience name and defaults » : Audience ID."),
        field('status', 'Inscription', kind='select', default='subscribed',
              options=[['subscribed', 'Directe (clients existants)'], ['pending', 'Double opt-in (email de confirmation)']]),
        field('tags', 'Tags', placeholder='client, billio', help='Séparés par des virgules.')],
        _mailchimp_member, needs_email=True)],
    'mailerlite': [op('add_subscriber', 'Ajouter l’abonné', [
        field('group_id', 'ID du groupe', kind='id', pattern=r'\d{1,25}', help='Facultatif : Abonnés › Groupes, dans l’adresse du groupe.')],
        _mailerlite_subscriber, needs_email=True, desc=CONTACT_DESC)],
    'klaviyo': [op('upsert_profile', 'Créer / mettre à jour le profil', [
        field('list_id', 'ID de la liste', kind='id', pattern=r'\w{6}', help='Facultatif : Listes et segments › la liste › Paramètres.')],
        _klaviyo_profile, needs_email=True, desc=CONTACT_DESC)],
    'kit': [op('add_subscriber', "Ajouter l'abonné", [
        field('tag_id', 'ID du tag', kind='id', pattern=r'\d{1,15}', help="Facultatif : le nombre dans l'adresse du tag.")],
        _kit_subscriber, needs_email=True, desc=CONTACT_DESC)],
    'activecampaign': [op('sync_contact', 'Créer / mettre à jour le contact', [
        field('list_id', 'ID de la liste', kind='id', pattern=r'\d{1,10}', help='Facultatif : Listes, survolez la liste pour voir son ID.')],
        _activecampaign_contact, needs_email=True, desc=CONTACT_DESC)],
    # Automatisation
    'make': [SEND_EVENT],
    'n8n': [SEND_EVENT],
    'zapier': [SEND_EVENT],
    'ifttt': [op('trigger', "Déclencher l'applet", [
        field('value1', 'Value1', default='{{evenement}}'), field('value2', 'Value2', default='{{client}}'),
        field('value3', 'Value3', default='{{montant}}')], _ifttt_event)],
}


def operation(app, key):
    return next((o for o in APP_ACTIONS.get(app, []) if o['key'] == key), None)


def app_label(app):
    from . import catalog
    return {'notion': 'Notion'}.get(app) or catalog.META.get(app, (app,))[0]


def board_catalog(connected):
    """Opérations pour le board (sans les fonctions) : [{'key', 'label', 'connected', 'operations': [...]}]."""
    out = []
    for app, operations in APP_ACTIONS.items():
        out.append({
            'key': app, 'label': app_label(app), 'connected': app in connected,
            'operations': [{k: v for k, v in o.items() if k != 'run'} for o in operations],
        })
    return sorted(out, key=lambda a: (not a['connected'], a['label'].lower()))


def clean_values(operation_spec, raw):
    """Valeurs saisies dans le board → valeurs enregistrées. Lève ValueError (message lisible)."""
    raw = raw if isinstance(raw, dict) else {}
    values = {}
    for spec in operation_spec['fields']:
        value = str(raw.get(spec['name'], '') if raw.get(spec['name']) is not None else '').strip()
        value = value[:MAX_TEXT if spec['kind'] == 'textarea' else 500]
        if spec['kind'] == 'select':
            allowed = [o[0] for o in spec['options']]
            value = value if value in allowed else (spec['default'] or allowed[0])
        if spec['kind'] == 'id' and value and spec.get('pattern') and not re.fullmatch(spec['pattern'], value):
            raise ValueError(f"« {spec['label']} » : format invalide" + (f" (ex. {spec['placeholder']})" if spec['placeholder'] else '') + '.')
        if spec['required'] and not value:
            raise ValueError(f"« {spec['label']} » est obligatoire.")
        values[spec['name']] = value
    return values


def event_payload(ctx, client=None):
    """Données de l'événement transmises aux outils (et telles quelles à Make / n8n / Zapier)."""
    from apps.dashboard.models import AutomationRule
    variables = {k: v for k, v in (ctx.get('variables') or {}).items() if not str(k).startswith('_')}
    return {
        'source': 'billio',
        'event': ctx['trigger_key'],
        'event_label': str(dict(AutomationRule.TRIGGER_CHOICES).get(ctx['trigger_key'], ctx['trigger_key'])),
        'summary': ctx.get('context_label') or '',
        'target': {'type': ctx['target_type'], 'id': str(ctx['target_id'])},
        'amount': ctx.get('amount'),
        'currency': 'EUR',
        'client': {
            'id': str(client.id), 'name': client.name, 'email': client.email, 'phone': client.phone or '',
            'company': client.company_name or '', 'contact_person': client.contact_person or '',
            'address': client.address or '', 'postal_code': client.postal_code or '', 'city': client.city or '',
            'country': client.country or '', 'tax_id': client.tax_id or '',
        } if client else None,
        'project_id': ctx.get('project_id'),
        'variables': variables,
        'organization': ctx['organization'].name if ctx.get('organization') else '',
        'sent_at': timezone.now().isoformat(),
    }


def run_app_action(organization, app, operation_key, values, ctx, *, client=None, render=None):
    """Exécute l'opération sur l'outil connecté de l'organisation. Retourne le détail pour le journal."""
    from .models import ConnectionInstance
    from .providers import ProviderError
    spec = operation(app, operation_key)
    if not spec:
        raise ValueError('Opération inconnue pour cet outil.')
    instance = ConnectionInstance.objects.filter(organization=organization, connector__key=app, status='connected').first()
    if not instance:
        raise ValueError(f"{app_label(app)} n'est pas connecté (page Intégrations).")
    rendered = {}
    for f in spec['fields']:
        value = values.get(f['name'], '')
        rendered[f['name']] = render(value) if render and f['kind'] in ('text', 'textarea') else value
    event = event_payload(ctx, client)
    try:
        detail = spec['run'](dict(instance.config or {}), rendered, event)
    except KeyError as exc:
        message = f"{app_label(app)} : configuration incomplète ({exc.args[0]}), enregistrez à nouveau le plugin."
        instance.last_error = message
        instance.save(update_fields=['last_error', 'updated_at'])
        raise ValueError(message) from None
    except ProviderError as exc:
        instance.last_error = str(exc)[:500]
        instance.save(update_fields=['last_error', 'updated_at'])
        raise ValueError(f"{app_label(app)} : {exc}") from None
    if instance.last_error:
        instance.last_error = ''
        instance.save(update_fields=['last_error', 'updated_at'])
    return detail
