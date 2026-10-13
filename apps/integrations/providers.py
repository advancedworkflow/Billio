"""
Plugins de l'organisation : WhatsApp, Slack, Telegram, Email (SMTP), Notion, Google Drive,
plus les 50 outils du catalogue étendu (apps/integrations/catalog.py).

Pour chaque plugin : champs de configuration, guide pas à pas, test de connexion et
appels aux API officielles. Les requêtes sortantes ne visent que des hôtes connus
(ALLOWED_HOSTS) : une configuration ne peut pas faire appeler une adresse arbitraire.
Les secrets (jetons, mots de passe) ne sont jamais renvoyés au navigateur (voir mask_config).
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

from django.conf import settings
from django.utils import timezone

ALLOWED_HOSTS = {
    'graph.facebook.com', 'hooks.slack.com', 'api.telegram.org', 'api.notion.com',
    'oauth2.googleapis.com', 'www.googleapis.com', 'openidconnect.googleapis.com',
    'api.stripe.com',
}
ALLOWED_SUFFIXES = ()  # sous-domaines par compte (ex. '.atlassian.net'), complétés par le catalogue
TIMEOUT = 12
NOTION_VERSION = '2022-06-28'
GRAPH_VERSION = 'v19.0'


class ProviderError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Définition des plugins (formulaire + guide affichés sur la page Intégrations)
# --------------------------------------------------------------------------- #

PROVIDERS = {
    'stripe': {
        'summary': "Vos clients paient factures et jalons par carte. Le paiement est confirmé par Stripe avant que la facture passe « payée ».",
        'uses': ['Bouton « Payer par carte » sur la page de paiement des factures', "Paiement des jalons depuis l'espace client", 'Déclencheur « Paiement reçu » (origine : en ligne / jalon)'],
        'steps': [
            ("Dans votre tableau de bord Stripe, ouvrez Développeurs › Clés API et copiez la clé secrète (sk_live_… ou sk_test_… pour essayer).", 'https://dashboard.stripe.com/apikeys'),
            ("Créez un webhook (Développeurs › Webhooks › Ajouter un endpoint) avec l'URL affichée après le test de connexion, évènement « checkout.session.completed ».", 'https://dashboard.stripe.com/webhooks'),
            ("Copiez le « secret de signature » du webhook (whsec_…) ci-dessous, puis testez la connexion.", ''),
        ],
        'fields': [
            {'name': 'secret_key', 'label': 'Clé secrète', 'secret': True, 'required': True, 'placeholder': 'sk_live_… ou sk_test_…'},
            {'name': 'webhook_secret', 'label': 'Secret du webhook', 'secret': True, 'placeholder': 'whsec_…',
             'help': "Recommandé : confirme les paiements même si le client ferme la page avant le retour sur Billio."},
        ],
    },
    'whatsapp': {
        'summary': "Envoyez des messages WhatsApp depuis vos automatisations (relances, confirmations…).",
        'uses': ['Action « Envoyer un message » des automatisations', 'Message de test vers votre numéro'],
        'steps': [
            ("Créez une application de type « Business » sur Meta for Developers.", 'https://developers.facebook.com/apps'),
            ("Ajoutez le produit WhatsApp, puis ouvrez « Configuration de l'API ».", ''),
            ("Copiez le « Phone number ID » du numéro d'envoi.", ''),
            ("Créez un utilisateur système (Business Settings › Utilisateurs système) et générez un jeton permanent avec la permission whatsapp_business_messaging.", 'https://business.facebook.com/settings/system-users'),
        ],
        'fields': [
            {'name': 'access_token', 'label': "Jeton d'accès permanent", 'secret': True, 'required': True, 'placeholder': 'EAAG…'},
            {'name': 'phone_number_id', 'label': 'Phone number ID', 'required': True, 'placeholder': '123456789012345'},
            {'name': 'test_recipient', 'label': 'Numéro pour le message de test', 'placeholder': '+33 6 12 34 56 78',
             'help': "Facultatif. Avec un numéro de test Meta, le destinataire doit être autorisé dans l'app."},
        ],
    },
    'slack': {
        'summary': "Publiez des alertes dans un canal Slack (paiement reçu, devis accepté…).",
        'uses': ['Action « Envoyer un message » des automatisations', 'Message de test dans le canal'],
        'steps': [
            ("Ouvrez l'annuaire des applications Slack et créez une app « From scratch ».", 'https://api.slack.com/apps'),
            ("Activez « Incoming Webhooks » puis cliquez « Add New Webhook to Workspace ».", ''),
            ("Choisissez le canal qui recevra les messages et copiez l'URL du webhook.", ''),
        ],
        'fields': [
            {'name': 'webhook_url', 'label': 'URL du webhook', 'secret': True, 'required': True,
             'placeholder': 'https://hooks.slack.com/services/…'},
        ],
    },
    'telegram': {
        'summary': "Recevez ou envoyez des messages Telegram via votre bot.",
        'uses': ['Action « Envoyer un message » des automatisations', 'Message de test dans la conversation choisie'],
        'steps': [
            ("Dans Telegram, ouvrez @BotFather, envoyez /newbot et suivez les étapes.", 'https://t.me/BotFather'),
            ("Copiez le jeton du bot et collez-le ci-dessous.", ''),
            ("Envoyez un message à votre bot (ou ajoutez-le à un groupe), puis cliquez « Trouver mes conversations ».", ''),
        ],
        'fields': [
            {'name': 'access_token', 'label': 'Jeton du bot', 'secret': True, 'required': True, 'placeholder': '123456789:AA…'},
            {'name': 'chat_id', 'label': 'Conversation par défaut (chat ID)', 'placeholder': '-1001234567890',
             'help': "Utilisez « Trouver mes conversations » pour le remplir automatiquement."},
        ],
    },
    'email': {
        'summary': "Envoyez les emails de Billio (relances, automatisations) depuis votre propre adresse.",
        'uses': ['Emails des automatisations', 'Relances de factures', 'Rappels de devis'],
        'steps': [
            ("Récupérez les réglages SMTP de votre messagerie (Gmail, Outlook, OVH, Brevo…).", ''),
            ("Pour Gmail : activez la validation en deux étapes puis créez un « mot de passe d'application ».", 'https://myaccount.google.com/apppasswords'),
            ("Renseignez le serveur, le port et l'adresse d'expédition, puis testez : un email vous est envoyé.", ''),
        ],
        'fields': [
            {'name': 'host', 'label': 'Serveur SMTP', 'required': True, 'placeholder': 'smtp.gmail.com'},
            {'name': 'port', 'label': 'Port', 'required': True, 'placeholder': '587', 'type': 'number'},
            {'name': 'security', 'label': 'Sécurité', 'type': 'select', 'options': [['tls', 'STARTTLS (port 587)'], ['ssl', 'SSL/TLS (port 465)'], ['none', 'Aucune']]},
            {'name': 'username', 'label': 'Identifiant', 'placeholder': 'vous@entreprise.fr'},
            {'name': 'password', 'label': 'Mot de passe', 'secret': True, 'placeholder': "Mot de passe d'application"},
            {'name': 'from_email', 'label': "Adresse d'expédition", 'required': True, 'placeholder': 'factures@entreprise.fr'},
            {'name': 'from_name', 'label': "Nom de l'expéditeur", 'placeholder': 'Atelier Lumen'},
        ],
    },
    'notion': {
        'summary': "Importez un projet depuis Notion et exportez vos factures et paiements dans une base Notion.",
        'uses': ['Importer un projet (page avec cases à cocher ou base de données)', 'Exporter factures / paiements vers une base Notion'],
        'steps': [
            ("Créez une intégration interne dans Notion et copiez son « Internal Integration Secret ».", 'https://www.notion.so/profile/integrations'),
            ("Dans Notion, ouvrez les pages à partager, menu « … › Connexions » et ajoutez votre intégration.", ''),
            ("Pour les exports, collez le lien de la page qui accueillera les tableaux Billio.", ''),
        ],
        'fields': [
            {'name': 'access_token', 'label': "Secret de l'intégration", 'secret': True, 'required': True, 'placeholder': 'ntn_… ou secret_…'},
            {'name': 'page_id', 'label': 'Page des exports (lien ou identifiant)', 'placeholder': 'https://www.notion.so/…',
             'help': 'Facultatif : nécessaire seulement pour exporter vos tableaux.'},
        ],
    },
    'google-drive': {
        'oauth': True,
        'summary': "Rangez vos PDF dans Google Drive, importez des fichiers et exportez vos tableaux en Google Sheets.",
        'uses': ['Copier une facture, un devis ou un document en PDF dans Drive', 'Importer un fichier Drive dans un projet', 'Exporter factures / paiements en Google Sheets'],
        'steps': [
            ("Cliquez « Se connecter avec Google » et choisissez le compte à utiliser.", ''),
            ("Autorisez Billio à créer des fichiers et à lire votre Drive (import de fichiers).", ''),
            ("Les fichiers envoyés par Billio sont rangés dans un dossier « Billio » de votre Drive.", ''),
        ],
        'fields': [],
    },
}
MESSAGING_KEYS = ('whatsapp', 'slack', 'telegram')


def mask_config(key, config):
    """Configuration affichable : les secrets sont remplacés par « •••• 1234 »."""
    config = dict(config or {})
    out = {}
    secret_names = {f['name'] for f in PROVIDERS.get(key, {}).get('fields', []) if f.get('secret')}
    secret_names |= {'refresh_token', 'access_token_google', 'token_expiry'}
    for name, value in config.items():
        if name in secret_names:
            text = str(value or '')
            out[name] = f'•••• {text[-4:]}' if len(text) > 8 else ('••••' if text else '')
        elif name in ('databases',):
            continue
        else:
            out[name] = value
    return out


def clean_config(key, posted, current):
    """Valeurs du formulaire → configuration ; un secret laissé vide conserve l'ancien."""
    current = dict(current or {})
    for field in PROVIDERS.get(key, {}).get('fields', []):
        name = field['name']
        value = str(posted.get(name, '') or '').strip()[:2000]
        if field.get('secret') and not value:
            continue  # inchangé
        if field.get('type') == 'select':
            allowed = [o[0] for o in field.get('options', [])]
            value = value if value in allowed else allowed[0]
        if key == 'notion' and name == 'page_id' and value:
            value = notion_id(value) or value
        if field.get('kind') == 'host' and value:
            value = (urllib.parse.urlparse(value if '//' in value else '//' + value).hostname or '').lower()
        if value and field.get('pattern') and not re.fullmatch(field['pattern'], value):
            hint = f" (ex. {field['placeholder']})" if field.get('placeholder') else ''
            raise ProviderError(f"{field['label']} : format invalide{hint}.")
        current[name] = value
    missing = [f['label'] for f in PROVIDERS.get(key, {}).get('fields', []) if f.get('required') and not current.get(f['name'])]
    if missing:
        raise ProviderError('À renseigner : ' + ', '.join(missing) + '.')
    return current


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def _error_message(raw):
    try:
        data = json.loads(raw)
    except ValueError:
        return raw.strip()[:200] or 'réponse vide'
    if isinstance(data, dict):
        err = data.get('error')
        if isinstance(err, dict):
            return str(err.get('message') or err)[:200]
        return str(data.get('message') or data.get('description') or data.get('error_description') or err or data)[:200]
    return str(data)[:200]


def http(method, url, *, json_body=None, form=None, data=None, headers=None, raw=False, timeout=TIMEOUT):
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not (host in ALLOWED_HOSTS or host.endswith(ALLOWED_SUFFIXES)):
        raise ProviderError('Adresse de service non autorisée.')
    hdrs = dict(headers or {})
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode('utf-8')
        hdrs['Content-Type'] = 'application/json'
    elif form is not None:
        body = urllib.parse.urlencode(form).encode('utf-8')
        hdrs['Content-Type'] = 'application/x-www-form-urlencoded'
    elif data is not None:
        body = data
    request = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:2000].decode('utf-8', 'replace')
        raise ProviderError(f'Erreur {exc.code} du service : {_error_message(detail)}') from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f'Service injoignable : {getattr(exc, "reason", exc)}') from None
    if raw:
        return content
    try:
        return json.loads(content or b'{}')
    except ValueError:
        return {'raw': content.decode('utf-8', 'replace')}


def _digits(value):
    return re.sub(r'\D', '', value or '')


# --------------------------------------------------------------------------- #
# Tests de connexion
# --------------------------------------------------------------------------- #

def test_connection(key, config, user=None, organization=None):
    """Vérifie la configuration auprès du service. Retourne un court message de réussite."""
    config = config or {}
    if key == 'stripe':
        secret = config.get('secret_key', '')
        if not secret.startswith(('sk_live_', 'sk_test_', 'rk_live_', 'rk_test_')):
            raise ProviderError('La clé secrète commence par sk_live_ ou sk_test_.')
        from apps.payments.stripe_checkout import account_label
        detail = account_label(secret)
        if organization is not None:
            from django.urls import reverse
            detail += f" · URL du webhook : {settings.SITE_URL}{reverse('payments:stripe-webhook', args=[organization.id])}"
        if not config.get('webhook_secret'):
            detail += ' · pensez à ajouter le secret du webhook'
        return detail
    if key == 'whatsapp':
        token, pnid = config.get('access_token', ''), config.get('phone_number_id', '')
        if not pnid.isdigit():
            raise ProviderError('Le Phone number ID ne contient que des chiffres.')
        info = http('GET', f'https://graph.facebook.com/{GRAPH_VERSION}/{pnid}?fields=display_phone_number,verified_name',
                    headers={'Authorization': f'Bearer {token}'})
        detail = f"Numéro {info.get('display_phone_number', '?')} ({info.get('verified_name', 'nom non vérifié')})"
        to = _digits(config.get('test_recipient'))
        if to:
            http('POST', f'https://graph.facebook.com/{GRAPH_VERSION}/{pnid}/messages',
                 json_body={'messaging_product': 'whatsapp', 'to': to, 'type': 'text',
                            'text': {'body': '✅ Billio est connecté à WhatsApp.'}},
                 headers={'Authorization': f'Bearer {token}'})
            detail += f' · message de test envoyé au +{to}'
        return detail
    if key == 'slack':
        url = config.get('webhook_url', '')
        if not url.startswith('https://hooks.slack.com/'):
            raise ProviderError("L'URL doit commencer par https://hooks.slack.com/.")
        http('POST', url, json_body={'text': '✅ Billio est connecté à ce canal.'}, raw=True)
        return 'Message de test publié dans le canal'
    if key == 'telegram':
        token = config.get('access_token', '')
        if not re.fullmatch(r'\d+:[\w-]+', token):
            raise ProviderError('Le jeton du bot a la forme 123456789:AA…')
        me = http('GET', f'https://api.telegram.org/bot{token}/getMe').get('result') or {}
        detail = f"Bot @{me.get('username', '?')}"
        chat = (config.get('chat_id') or '').strip()
        if chat:
            http('POST', f'https://api.telegram.org/bot{token}/sendMessage',
                 json_body={'chat_id': chat, 'text': '✅ Billio est connecté à cette conversation.'})
            detail += ' · message de test envoyé'
        return detail
    if key == 'email':
        connection = smtp_connection(config)
        from django.core.mail import EmailMessage
        to = getattr(user, 'email', '') or config.get('from_email')
        try:
            EmailMessage(
                subject='Billio — test de votre adresse d\'envoi',
                body="Ce message confirme que Billio peut envoyer des emails avec votre serveur SMTP.",
                from_email=sender(config), to=[to], connection=connection,
            ).send(fail_silently=False)
        except Exception as exc:  # smtplib remonte des erreurs très variées
            raise ProviderError(f'Envoi impossible : {exc}') from None
        return f'Email de test envoyé à {to}'
    if key == 'notion':
        me = http('GET', 'https://api.notion.com/v1/users/me', headers=notion_headers(config))
        detail = f"Intégration « {me.get('name') or 'Notion'} »"
        if config.get('page_id'):
            page = http('GET', f"https://api.notion.com/v1/pages/{config['page_id']}", headers=notion_headers(config))
            detail += f" · page des exports « {notion_title(page) or 'sans titre'} »"
        return detail
    if key == 'google-drive':
        about = http('GET', 'https://www.googleapis.com/drive/v3/about?fields=user',
                     headers={'Authorization': f'Bearer {google_access_token(config)}'})
        return f"Drive de {(about.get('user') or {}).get('emailAddress', '?')}"
    if key in CHECKS:
        try:
            return CHECKS[key](config)
        except KeyError as exc:
            raise ProviderError(f'Configuration incomplète ({exc.args[0]}) : enregistrez à nouveau le formulaire.') from None
    raise ProviderError('Ce plugin ne se teste pas encore.')


def telegram_chats(config):
    """Conversations récentes du bot (getUpdates) : [{'id', 'title'}]."""
    token = config.get('access_token', '')
    updates = http('GET', f'https://api.telegram.org/bot{token}/getUpdates').get('result') or []
    chats = {}
    for update in updates:
        message = update.get('message') or update.get('channel_post') or update.get('my_chat_member') or {}
        chat = message.get('chat') or {}
        if chat.get('id'):
            title = chat.get('title') or ' '.join(x for x in (chat.get('first_name'), chat.get('last_name')) if x) or chat.get('username') or str(chat['id'])
            chats[str(chat['id'])] = {'id': str(chat['id']), 'title': title, 'type': chat.get('type', '')}
    return list(chats.values())


# --------------------------------------------------------------------------- #
# Email (SMTP de l'organisation)
# --------------------------------------------------------------------------- #

def smtp_connection(config):
    from django.core.mail import get_connection
    security = config.get('security') or 'tls'
    try:
        port = int(config.get('port') or (465 if security == 'ssl' else 587))
    except ValueError:
        raise ProviderError('Le port doit être un nombre.') from None
    return get_connection(
        'django.core.mail.backends.smtp.EmailBackend',
        host=config.get('host'), port=port, username=config.get('username') or '',
        password=config.get('password') or '', use_tls=security == 'tls', use_ssl=security == 'ssl',
        timeout=TIMEOUT, fail_silently=False,
    )


def sender(config):
    name, email = (config.get('from_name') or '').strip(), (config.get('from_email') or '').strip()
    return f'{name} <{email}>' if name else email


def org_mail(organization):
    """(connexion, expéditeur) : le SMTP de l'organisation s'il est connecté, sinon celui de Billio."""
    from .models import ConnectionInstance
    instance = ConnectionInstance.objects.filter(organization=organization, connector__key='email', status='connected').first() if organization else None
    if instance and (instance.config or {}).get('host'):
        return smtp_connection(instance.config), sender(instance.config)
    return None, settings.DEFAULT_FROM_EMAIL


# --------------------------------------------------------------------------- #
# Notion
# --------------------------------------------------------------------------- #

def notion_headers(config):
    return {'Authorization': f"Bearer {config.get('access_token', '')}", 'Notion-Version': NOTION_VERSION}


def notion_id(text):
    """Identifiant Notion (32 caractères hexadécimaux) à partir d'un lien ou d'un identifiant."""
    match = re.search(r'([0-9a-f]{32})(?:[?#]|$)', (text or '').replace('-', ''), re.I)
    if not match:
        return ''
    h = match.group(1).lower()
    return f'{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}'


def _rich(items):
    return ''.join(part.get('plain_text', '') for part in items or [])


def notion_title(obj):
    if obj.get('object') == 'database':
        return _rich(obj.get('title'))
    for prop in (obj.get('properties') or {}).values():
        if prop.get('type') == 'title':
            return _rich(prop.get('title'))
    return ''


def notion_search(config, query=''):
    """Pages et bases partagées avec l'intégration : [{'id', 'title', 'kind', 'url', 'edited'}]."""
    data = http('POST', 'https://api.notion.com/v1/search', headers=notion_headers(config),
                json_body={'query': query[:100], 'page_size': 30, 'sort': {'direction': 'descending', 'timestamp': 'last_edited_time'}})
    out = []
    for obj in data.get('results') or []:
        if obj.get('object') == 'page' and (obj.get('parent') or {}).get('type') == 'database_id':
            continue  # ligne d'une base : on propose la base elle-même
        out.append({
            'id': obj['id'], 'title': notion_title(obj) or 'Sans titre', 'kind': obj.get('object'),
            'url': obj.get('url', ''), 'edited': (obj.get('last_edited_time') or '')[:10],
        })
    return out


DONE_WORDS = {'done', 'terminé', 'termine', 'terminée', 'fait', 'fini', 'complete', 'completed', 'livré', 'validé', 'closed'}


def _prop_value(prop):
    kind = prop.get('type')
    if kind == 'title':
        return _rich(prop.get('title'))
    if kind == 'rich_text':
        return _rich(prop.get('rich_text'))
    if kind in ('select', 'status'):
        return ((prop.get(kind) or {}).get('name') or '')
    if kind == 'checkbox':
        return bool(prop.get('checkbox'))
    if kind == 'date':
        return ((prop.get('date') or {}).get('start') or '')[:10]
    return None


def notion_read_project(config, notion_object_id):
    """
    Lit une base ou une page Notion et renvoie {'name', 'description', 'groups': [{'title', 'tasks': [...]}]}.
    Base de données : une ligne = une tâche (statut / case à cocher / date reconnus), regroupées
    par la propriété de type « select » ou « status » si elle existe. Page : un titre = un jalon,
    les cases à cocher et listes qui suivent = ses tâches.
    """
    headers = notion_headers(config)
    try:
        db = http('GET', f'https://api.notion.com/v1/databases/{notion_object_id}', headers=headers)
    except ProviderError:
        db = None
    if db and db.get('object') == 'database':
        rows, cursor = [], None
        for _ in range(5):  # 500 lignes maximum
            body = {'page_size': 100}
            if cursor:
                body['start_cursor'] = cursor
            page = http('POST', f'https://api.notion.com/v1/databases/{notion_object_id}/query', headers=headers, json_body=body)
            rows += page.get('results') or []
            if not page.get('has_more'):
                break
            cursor = page.get('next_cursor')
        groups = {}
        for row in rows:
            props = row.get('properties') or {}
            title, done, due, group = '', False, '', ''
            for name, prop in props.items():
                value = _prop_value(prop)
                kind = prop.get('type')
                if kind == 'title':
                    title = value
                elif kind == 'checkbox' and value:
                    done = True
                elif kind == 'status' and value:
                    done = done or value.strip().lower() in DONE_WORDS
                    group = group or ''
                elif kind == 'select' and value and not group:
                    group = value
                    done = done or value.strip().lower() in DONE_WORDS
                elif kind == 'date' and value and not due:
                    due = value
            if title:
                groups.setdefault(group or 'Tâches', []).append({'title': title[:200], 'done': done, 'due': due})
        return {
            'name': (_rich(db.get('title')) or 'Projet Notion')[:200],
            'description': _rich(db.get('description'))[:2000],
            'groups': [{'title': g, 'tasks': t} for g, t in groups.items()],
        }
    page = http('GET', f'https://api.notion.com/v1/pages/{notion_object_id}', headers=headers)
    blocks, cursor = [], None
    for _ in range(5):
        url = f'https://api.notion.com/v1/blocks/{notion_object_id}/children?page_size=100' + (f'&start_cursor={cursor}' if cursor else '')
        chunk = http('GET', url, headers=headers)
        blocks += chunk.get('results') or []
        if not chunk.get('has_more'):
            break
        cursor = chunk.get('next_cursor')
    groups, current, description = [], None, []
    for block in blocks:
        kind = block.get('type')
        content = block.get(kind) or {}
        text = _rich(content.get('rich_text'))
        if kind in ('heading_1', 'heading_2', 'heading_3') and text:
            current = {'title': text[:200], 'tasks': []}
            groups.append(current)
        elif kind in ('to_do', 'bulleted_list_item', 'numbered_list_item') and text:
            if current is None:
                current = {'title': 'Tâches', 'tasks': []}
                groups.append(current)
            current['tasks'].append({'title': text[:200], 'done': bool(content.get('checked')), 'due': ''})
        elif kind == 'paragraph' and text and not groups:
            description.append(text)
    return {'name': (notion_title(page) or 'Projet Notion')[:200], 'description': '\n'.join(description)[:2000],
            'groups': [g for g in groups if g['tasks'] or g['title']]}


def notion_export(instance, table_key, title, columns, rows):
    """
    Exporte un tableau dans une base Notion créée sous la page des exports (une base par
    tableau, réutilisée ensuite). Les lignes existantes (même valeur de 1re colonne) sont
    mises à jour plutôt que dupliquées. Retourne (url de la base, créées, mises à jour).
    """
    config = dict(instance.config or {})
    headers = notion_headers(config)
    parent = config.get('page_id')
    if not parent:
        raise ProviderError('Indiquez la page des exports Notion dans la configuration du plugin.')
    databases = dict(config.get('databases') or {})
    db_id = databases.get(table_key)
    kinds = {name: kind for name, kind in columns}
    if db_id:
        try:
            db = http('GET', f'https://api.notion.com/v1/databases/{db_id}', headers=headers)
        except ProviderError:
            db_id = None
    if not db_id:
        props = {}
        for index, (name, kind) in enumerate(columns):
            props[name] = {'title': {}} if index == 0 else {'number': {'format': 'euro'}} if kind == 'money' else {'date': {}} if kind == 'date' else {'rich_text': {}}
        db = http('POST', 'https://api.notion.com/v1/databases', headers=headers, json_body={
            'parent': {'type': 'page_id', 'page_id': parent},
            'title': [{'type': 'text', 'text': {'content': title}}],
            'properties': props,
        })
        db_id = db['id']
        databases[table_key] = db_id
        config['databases'] = databases
        instance.config = config
        instance.save(update_fields=['config', 'updated_at'])
    first = columns[0][0]
    created = updated = 0
    for row in rows[:500]:
        props = {}
        for name, value in row.items():
            kind = kinds.get(name)
            if name == first:
                props[name] = {'title': [{'text': {'content': str(value)[:200]}}]}
            elif kind == 'money':
                props[name] = {'number': float(value or 0)}
            elif kind == 'date':
                props[name] = {'date': {'start': value} if value else None}
            else:
                props[name] = {'rich_text': [{'text': {'content': str(value or '')[:500]}}]}
        found = http('POST', f'https://api.notion.com/v1/databases/{db_id}/query', headers=headers,
                     json_body={'filter': {'property': first, 'title': {'equals': str(row[first])[:200]}}, 'page_size': 1}).get('results') or []
        if found:
            http('PATCH', f"https://api.notion.com/v1/pages/{found[0]['id']}", headers=headers, json_body={'properties': props})
            updated += 1
        else:
            http('POST', 'https://api.notion.com/v1/pages', headers=headers, json_body={'parent': {'database_id': db_id}, 'properties': props})
            created += 1
    return db.get('url', ''), created, updated


# --------------------------------------------------------------------------- #
# Google Drive (OAuth 2.0)
# --------------------------------------------------------------------------- #

GOOGLE_SCOPES = 'openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly'


def google_configured():
    return bool(getattr(settings, 'GOOGLE_CLIENT_ID', '') and getattr(settings, 'GOOGLE_CLIENT_SECRET', ''))


def google_auth_url(state, redirect_uri):
    return 'https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode({
        'client_id': settings.GOOGLE_CLIENT_ID, 'redirect_uri': redirect_uri, 'response_type': 'code',
        'scope': GOOGLE_SCOPES, 'access_type': 'offline', 'prompt': 'consent', 'include_granted_scopes': 'true',
        'state': state,
    })


def google_exchange(code, redirect_uri):
    tokens = http('POST', 'https://oauth2.googleapis.com/token', form={
        'code': code, 'client_id': settings.GOOGLE_CLIENT_ID, 'client_secret': settings.GOOGLE_CLIENT_SECRET,
        'redirect_uri': redirect_uri, 'grant_type': 'authorization_code',
    })
    info = http('GET', 'https://openidconnect.googleapis.com/v1/userinfo',
                headers={'Authorization': f"Bearer {tokens.get('access_token', '')}"})
    return {
        'refresh_token': tokens.get('refresh_token', ''),
        'access_token_google': tokens.get('access_token', ''),
        'token_expiry': int(timezone.now().timestamp()) + int(tokens.get('expires_in') or 3600) - 60,
        'account': info.get('email', ''),
    }


def google_access_token(config, instance=None):
    """Jeton d'accès valide (renouvelé avec le refresh token s'il a expiré)."""
    if config.get('access_token_google') and int(config.get('token_expiry') or 0) > timezone.now().timestamp():
        return config['access_token_google']
    if not config.get('refresh_token'):
        raise ProviderError('Reconnectez Google Drive (autorisation expirée).')
    tokens = http('POST', 'https://oauth2.googleapis.com/token', form={
        'client_id': settings.GOOGLE_CLIENT_ID, 'client_secret': settings.GOOGLE_CLIENT_SECRET,
        'refresh_token': config['refresh_token'], 'grant_type': 'refresh_token',
    })
    config['access_token_google'] = tokens.get('access_token', '')
    config['token_expiry'] = int(timezone.now().timestamp()) + int(tokens.get('expires_in') or 3600) - 60
    if instance is not None:
        instance.config = config
        instance.save(update_fields=['config', 'updated_at'])
    return config['access_token_google']


def _drive_auth(instance):
    config = dict(instance.config or {})
    return {'Authorization': f'Bearer {google_access_token(config, instance)}'}


def drive_folder(instance):
    """Dossier « Billio » du Drive (créé au premier envoi)."""
    config = dict(instance.config or {})
    folder = config.get('folder_id')
    headers = _drive_auth(instance)
    if folder:
        try:
            meta = http('GET', f'https://www.googleapis.com/drive/v3/files/{folder}?fields=id,trashed', headers=headers)
            if not meta.get('trashed'):
                return folder
        except ProviderError:
            pass
    created = http('POST', 'https://www.googleapis.com/drive/v3/files?fields=id,webViewLink', headers=headers,
                   json_body={'name': 'Billio', 'mimeType': 'application/vnd.google-apps.folder'})
    config = dict(instance.config or {})
    config['folder_id'], config['folder_url'] = created['id'], created.get('webViewLink', '')
    instance.config = config
    instance.save(update_fields=['config', 'updated_at'])
    return created['id']


def drive_upload(instance, name, content, mime, *, convert_to=None):
    """Envoie un fichier dans le dossier Billio. Retourne {'id', 'name', 'webViewLink'}."""
    folder = drive_folder(instance)
    boundary = f'billio-{uuid.uuid4().hex}'
    metadata = {'name': name, 'parents': [folder]}
    if convert_to:
        metadata['mimeType'] = convert_to
    body = (
        f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(metadata)}\r\n'
        f'--{boundary}\r\nContent-Type: {mime}\r\n\r\n'
    ).encode('utf-8') + content + f'\r\n--{boundary}--\r\n'.encode('utf-8')
    headers = _drive_auth(instance)
    headers['Content-Type'] = f'multipart/related; boundary={boundary}'
    return http('POST', 'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,webViewLink',
                data=body, headers=headers, timeout=60)


def drive_files(instance, query=''):
    """Fichiers récents du Drive (hors dossiers et corbeille) pour l'import."""
    q = "trashed = false and mimeType != 'application/vnd.google-apps.folder'"
    if query:
        q += " and name contains '" + query.replace('\\', '').replace("'", "\\'")[:80] + "'"
    data = http('GET', 'https://www.googleapis.com/drive/v3/files?' + urllib.parse.urlencode({
        'q': q, 'pageSize': 30, 'orderBy': 'modifiedTime desc',
        'fields': 'files(id,name,mimeType,modifiedTime,size,iconLink,webViewLink)',
    }), headers=_drive_auth(instance))
    return data.get('files') or []


GOOGLE_EXPORTS = {
    'application/vnd.google-apps.document': ('application/pdf', '.pdf'),
    'application/vnd.google-apps.spreadsheet': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx'),
    'application/vnd.google-apps.presentation': ('application/pdf', '.pdf'),
    'application/vnd.google-apps.drawing': ('image/png', '.png'),
}
MAX_IMPORT_BYTES = 25 * 1024 * 1024


def drive_download(instance, file_id):
    """Contenu d'un fichier Drive (documents Google exportés en PDF / XLSX). Retourne (nom, octets)."""
    if not re.fullmatch(r'[\w-]{10,100}', file_id or ''):
        raise ProviderError('Fichier invalide.')
    headers = _drive_auth(instance)
    meta = http('GET', f'https://www.googleapis.com/drive/v3/files/{file_id}?fields=id,name,mimeType,size', headers=headers)
    if int(meta.get('size') or 0) > MAX_IMPORT_BYTES:
        raise ProviderError('Fichier trop volumineux (25 Mo maximum).')
    name = meta.get('name') or 'fichier'
    export = GOOGLE_EXPORTS.get(meta.get('mimeType'))
    if export:
        content = http('GET', f"https://www.googleapis.com/drive/v3/files/{file_id}/export?" + urllib.parse.urlencode({'mimeType': export[0]}),
                       headers=headers, raw=True, timeout=60)
        name = name if name.lower().endswith(export[1]) else name + export[1]
    elif meta.get('mimeType', '').startswith('application/vnd.google-apps'):
        raise ProviderError('Ce type de fichier Google ne peut pas être importé.')
    else:
        content = http('GET', f'https://www.googleapis.com/drive/v3/files/{file_id}?alt=media', headers=headers, raw=True, timeout=60)
    if len(content) > MAX_IMPORT_BYTES:
        raise ProviderError('Fichier trop volumineux (25 Mo maximum).')
    return name[:200], content


# --------------------------------------------------------------------------- #
# Catalogue étendu (50 outils) : formulaires, hôtes autorisés et tests de connexion
# --------------------------------------------------------------------------- #

from .catalog import CHECKS, HOSTS, SUFFIXES, TOOLS  # noqa: E402

PROVIDERS.update(TOOLS)
ALLOWED_HOSTS |= HOSTS
ALLOWED_SUFFIXES = tuple('.' + suffix for suffix in SUFFIXES)
