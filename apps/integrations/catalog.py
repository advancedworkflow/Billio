"""
Catalogue étendu des intégrations : 50 outils configurables depuis la page Intégrations.

Chaque outil déclare son formulaire et son guide (TOOLS, fusionné dans providers.PROVIDERS)
et une vérification de connexion qui appelle l'API officielle du service (CHECKS).
Les messageries et webhooks (Teams, Discord, Google Chat, SMS Twilio, Make, n8n, IFTTT)
servent aussi de canal à l'action d'automatisation « Envoyer un message » (SENDERS).

Les requêtes passent par providers.http : seuls les hôtes de HOSTS (ou les sous-domaines
de SUFFIXES pour les services hébergés par compte, ex. acme.atlassian.net) sont appelés.
"""
import base64

CATEGORIES = [
    ('accounting', 'Banque & comptabilité'),
    ('crm', 'CRM & support'),
    ('marketing', 'Marketing & e-commerce'),
]

HOSTS = {
    'discord.com', 'discordapp.com', 'chat.googleapis.com', 'api.twilio.com', 'api.sendgrid.com',
    'api.mailgun.net', 'api.eu.mailgun.net', 'api.postmarkapp.com', 'api.crisp.chat',
    'api.trello.com', 'app.asana.com', 'api.clickup.com', 'api.monday.com', 'api.airtable.com',
    'api.linear.app', 'api.github.com', 'api.calendly.com', 'api.track.toggl.com',
    'api.harvestapp.com', 'api.clockify.me', 'api.typeform.com', 'api.todoist.com',
    'api.yousign.app', 'api-sandbox.yousign.app', 'api.pandadoc.com',
    'api.gocardless.com', 'api-sandbox.gocardless.com', 'api.sumup.com', 'api.mollie.com', 'api.payplug.com',
    'thirdparty.qonto.com', 'api.transferwise.com', 'api.sandbox.transferwise.tech', 'app.pennylane.com',
    'quickbooks.api.intuit.com', 'sandbox-quickbooks.api.intuit.com',
    'api.hubapi.com', 'api.pipedrive.com', 'api.attio.com', 'login.sellsy.com', 'api.intercom.io', 'api.close.com',
    'api.brevo.com', 'a.klaviyo.com', 'connect.mailerlite.com', 'api.kit.com', 'api.webflow.com',
    'maker.ifttt.com', 'hooks.zapier.com',
}
# Services hébergés sur un sous-domaine propre à chaque compte.
SUFFIXES = (
    'webhook.office.com', 'logic.azure.com', 'api.powerplatform.com',  # Microsoft Teams
    'atlassian.net', 'zendesk.com', 'freshdesk.com', 'myshopify.com', 'api.mailchimp.com',
    'api-us1.com', 'activehosted.com', 'make.com', 'app.n8n.cloud',
)

HOST_FIELD = 'host'  # champ « adresse du compte » : on ne garde que le nom d'hôte


# --------------------------------------------------------------------------- #
# Aides
# --------------------------------------------------------------------------- #

def _http(*args, **kwargs):
    from .providers import http
    return http(*args, **kwargs)


def _fail(message):
    from .providers import ProviderError
    raise ProviderError(message)


def _basic(user, password=''):
    return 'Basic ' + base64.b64encode(f'{user}:{password}'.encode('utf-8')).decode('ascii')


def _bearer(token):
    return {'Authorization': f'Bearer {token}'}


def _first(*values):
    return next((str(v) for v in values if v), '')


def F(name, label, *, secret=False, required=True, placeholder='', help='', pattern=None, kind=None, options=None):
    """Champ de formulaire (même format que providers.PROVIDERS)."""
    field = {'name': name, 'label': label, 'placeholder': placeholder}
    if secret:
        field['secret'] = True
    if required:
        field['required'] = True
    if help:
        field['help'] = help
    if pattern:
        field['pattern'] = pattern
    if kind:
        field['kind'] = kind
    if options:
        field['type'] = 'select'
        field['options'] = options
    return field


ENV_OPTIONS = [['live', 'Production'], ['sandbox', 'Test (sandbox)']]
TEST_MESSAGE = '✅ Billio est connecté.'

TOOLS = {}    # clé → spec affichée (summary, uses, steps, fields)
META = {}     # clé → (nom, catégorie, icône Lucide) pour le catalogue en base
CHECKS = {}   # clé → fonction(config) → détail du test de connexion
SENDERS = {}  # clé → fonction(config, texte, destinataire) → détail (action « Envoyer un message »)


def tool(key, name, category, icon, summary, steps, fields, uses=()):
    def register(check):
        TOOLS[key] = {'summary': summary, 'uses': list(uses), 'steps': steps, 'fields': fields}
        META[key] = (name, category, icon)
        CHECKS[key] = check
        return check
    return register


MESSAGE_USE = 'Action « Envoyer un message » des automatisations'


# =========================================================================== #
# Communication
# =========================================================================== #

def _teams_send(config, text, recipient=''):
    _http('POST', config['webhook_url'], raw=True, json_body={
        'type': 'message',
        'attachments': [{
            'contentType': 'application/vnd.microsoft.card.adaptive',
            'content': {
                '$schema': 'http://adaptivecards.io/schemas/adaptive-card.json', 'type': 'AdaptiveCard', 'version': '1.4',
                'body': [{'type': 'TextBlock', 'text': text, 'wrap': True}],
            },
        }],
    })
    return 'Message Teams publié'


@tool('microsoft-teams', 'Microsoft Teams', 'communication', 'users',
      "Publiez des alertes dans un canal Teams (paiement reçu, devis accepté…).",
      [("Dans Teams, ouvrez le canal voulu, menu « … › Workflows ».", ''),
       ("Choisissez le modèle « Publier dans un canal lorsqu'une requête webhook est reçue » et validez.", ''),
       ("Copiez l'URL HTTP POST affichée à la fin et collez-la ci-dessous.", '')],
      [F('webhook_url', 'URL du webhook', secret=True, placeholder='https://…logic.azure.com/workflows/…',
         pattern=r'https://[\w.-]+\.(webhook\.office\.com|logic\.azure\.com|api\.powerplatform\.com)(:443)?/\S+')],
      uses=[MESSAGE_USE, 'Message de test dans le canal'])
def _teams(config):
    _teams_send(config, TEST_MESSAGE)
    return 'Message de test publié dans le canal Teams'


def _discord_send(config, text, recipient=''):
    _http('POST', config['webhook_url'], raw=True, json_body={'content': text[:2000], 'username': 'Billio'})
    return 'Message Discord publié'


@tool('discord', 'Discord', 'communication', 'message-square',
      "Publiez les évènements de Billio dans un salon de votre serveur Discord.",
      [("Ouvrez les paramètres du serveur › Intégrations › Webhooks.", ''),
       ("Cliquez « Nouveau webhook », choisissez le salon puis « Copier l'URL du webhook ».", '')],
      [F('webhook_url', 'URL du webhook', secret=True, placeholder='https://discord.com/api/webhooks/…',
         pattern=r'https://(discord|discordapp)\.com/api/webhooks/\d+/[\w-]+')],
      uses=[MESSAGE_USE, 'Message de test dans le salon'])
def _discord(config):
    _discord_send(config, TEST_MESSAGE)
    return 'Message de test publié dans le salon'


def _gchat_send(config, text, recipient=''):
    _http('POST', config['webhook_url'], json_body={'text': text})
    return 'Message Google Chat publié'


@tool('google-chat', 'Google Chat', 'communication', 'messages-square',
      "Publiez des alertes dans un espace Google Chat (compte Google Workspace).",
      [("Dans Google Chat, ouvrez l'espace puis son menu › Applications et intégrations.", 'https://chat.google.com/'),
       ("Cliquez « Ajouter des webhooks », nommez-le « Billio » et copiez l'URL.", '')],
      [F('webhook_url', 'URL du webhook', secret=True, placeholder='https://chat.googleapis.com/v1/spaces/…',
         pattern=r'https://chat\.googleapis\.com/v1/spaces/\S+')],
      uses=[MESSAGE_USE, "Message de test dans l'espace"])
def _gchat(config):
    _gchat_send(config, TEST_MESSAGE)
    return "Message de test publié dans l'espace"


def _phone(value):
    digits = ''.join(c for c in (value or '') if c.isdigit())
    return f'+{digits}' if len(digits) >= 8 else ''


def _twilio_send(config, text, recipient=''):
    to = _phone(recipient)
    if not to:
        _fail('SMS : numéro du destinataire manquant ou invalide.')
    sid = config['account_sid']
    _http('POST', f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json',
          form={'To': to, 'From': config['from_number'], 'Body': text[:1500]},
          headers={'Authorization': _basic(sid, config['auth_token'])})
    return f'SMS envoyé au {to}'


@tool('twilio', 'SMS (Twilio)', 'communication', 'smartphone',
      "Envoyez des SMS depuis vos automatisations (rappel de rendez-vous, relance…).",
      [("Créez un compte Twilio et achetez (ou activez) un numéro d'envoi.", 'https://console.twilio.com/'),
       ("Sur l'accueil de la console, copiez l'Account SID et l'Auth Token.", ''),
       ("Indiquez le numéro d'envoi Twilio, puis testez (un SMS part si vous renseignez un numéro de test).", '')],
      [F('account_sid', 'Account SID', placeholder='AC…', pattern=r'AC[0-9a-fA-F]{32}'),
       F('auth_token', 'Auth Token', secret=True),
       F('from_number', "Numéro d'envoi", placeholder='+33 7 …', help="Numéro Twilio au format international, ou identifiant d'expéditeur alphanumérique."),
       F('test_recipient', 'Numéro pour le SMS de test', required=False, placeholder='+33 6 12 34 56 78')],
      uses=[MESSAGE_USE + ' (téléphone du client ou autre numéro)', 'SMS de test'])
def _twilio(config):
    sid = config['account_sid']
    account = _http('GET', f'https://api.twilio.com/2010-04-01/Accounts/{sid}.json', headers={'Authorization': _basic(sid, config['auth_token'])})
    detail = f"Compte « {account.get('friendly_name', sid)} » ({account.get('status', '?')})"
    if config.get('test_recipient'):
        detail += ' · ' + _twilio_send(config, TEST_MESSAGE, config['test_recipient'])
    return detail


SMTP_HINT = "Pour envoyer les emails de Billio par ce service, utilisez aussi le plugin Email avec ses réglages SMTP."


@tool('sendgrid', 'SendGrid', 'communication', 'mail',
      "Vérifiez votre compte SendGrid (Twilio) pour l'envoi d'emails. " + SMTP_HINT,
      [("Dans SendGrid, ouvrez Settings › API Keys › Create API Key.", 'https://app.sendgrid.com/settings/api_keys'),
       ("Copiez la clé (SG.…) ci-dessous.", ''),
       ("Email : plugin Email avec le serveur smtp.sendgrid.net, port 587, identifiant « apikey » et la clé comme mot de passe.", '')],
      [F('api_key', 'Clé API', secret=True, placeholder='SG.…', pattern=r'SG\.\S+')])
def _sendgrid(config):
    scopes = _http('GET', 'https://api.sendgrid.com/v3/scopes', headers=_bearer(config['api_key'])).get('scopes') or []
    return f'Clé valide · {len(scopes)} permission(s)'


@tool('mailgun', 'Mailgun', 'communication', 'mail',
      "Vérifiez votre compte Mailgun et ses domaines d'envoi. " + SMTP_HINT,
      [("Dans Mailgun, ouvrez votre profil › API Security et créez une clé API.", 'https://app.mailgun.com/settings/api_security'),
       ("Choisissez la région de votre compte (US ou EU) puis testez.", '')],
      [F('api_key', 'Clé API', secret=True),
       F('region', 'Région', options=[['eu', 'Europe (api.eu.mailgun.net)'], ['us', 'États-Unis (api.mailgun.net)']])])
def _mailgun(config):
    host = 'api.eu.mailgun.net' if config.get('region') == 'eu' else 'api.mailgun.net'
    data = _http('GET', f'https://{host}/v3/domains', headers={'Authorization': _basic('api', config['api_key'])})
    names = [d.get('name') for d in data.get('items') or [] if d.get('name')]
    return f"{data.get('total_count', len(names))} domaine(s)" + (f" · {', '.join(names[:3])}" if names else '')


@tool('postmark', 'Postmark', 'communication', 'mail-check',
      "Vérifiez votre serveur Postmark pour des emails transactionnels fiables. " + SMTP_HINT,
      [("Dans Postmark, ouvrez votre serveur › API Tokens.", 'https://account.postmarkapp.com/servers'),
       ("Copiez le « Server API token » ci-dessous.", '')],
      [F('server_token', 'Server API token', secret=True)])
def _postmark(config):
    server = _http('GET', 'https://api.postmarkapp.com/server', headers={'Accept': 'application/json', 'X-Postmark-Server-Token': config['server_token']})
    return f"Serveur « {server.get('Name', '?')} »"


@tool('crisp', 'Crisp', 'communication', 'message-circle-more',
      "Reliez le chat Crisp de votre site à Billio.",
      [("Créez un plugin privé sur le Marketplace Crisp et ouvrez l'onglet « Tokens ».", 'https://marketplace.crisp.chat/'),
       ("Copiez l'identifiant et la clé du jeton (production ou développement).", ''),
       ("Dans Crisp, Paramètres › Paramètres du site › Configuration : copiez le « Website ID ».", '')],
      [F('identifier', 'Identifiant du jeton'),
       F('key', 'Clé du jeton', secret=True),
       F('website_id', 'Website ID', placeholder='xxxxxxxx-xxxx-…', pattern=r'[0-9a-fA-F-]{36}')])
def _crisp(config):
    data = _http('GET', f"https://api.crisp.chat/v1/website/{config['website_id']}",
                 headers={'Authorization': _basic(config['identifier'], config['key']), 'X-Crisp-Tier': 'plugin'}).get('data') or {}
    return f"Site « {data.get('name', '?')} »"


# =========================================================================== #
# Productivité & projets
# =========================================================================== #

@tool('trello', 'Trello', 'productivity', 'square-kanban',
      "Reliez vos tableaux Trello à votre compte Billio.",
      [("Ouvrez le portail d'administration des Power-Ups et créez une nouvelle intégration.", 'https://trello.com/power-ups/admin'),
       ("Dans l'onglet « Clé API », copiez la clé puis cliquez le lien « Jeton » pour générer un jeton.", ''),
       ("Collez la clé et le jeton ci-dessous.", '')],
      [F('api_key', 'Clé API', pattern=r'[0-9a-fA-F]{32}'), F('token', 'Jeton', secret=True)])
def _trello(config):
    me = _http('GET', f"https://api.trello.com/1/members/me?fields=fullName,username&key={config['api_key']}&token={config['token']}")
    return f"Compte {me.get('fullName') or me.get('username', '?')}"


@tool('asana', 'Asana', 'productivity', 'list-checks',
      "Reliez votre espace de travail Asana à Billio.",
      [("Ouvrez la console développeur Asana › « Créer un jeton » (jeton d'accès personnel).", 'https://app.asana.com/0/my-apps'),
       ("Copiez le jeton ci-dessous.", '')],
      [F('access_token', "Jeton d'accès personnel", secret=True)])
def _asana(config):
    me = _http('GET', 'https://app.asana.com/api/1.0/users/me', headers=_bearer(config['access_token'])).get('data') or {}
    spaces = ', '.join(w.get('name', '') for w in (me.get('workspaces') or [])[:3])
    return f"Compte {me.get('name', '?')}" + (f' · {spaces}' if spaces else '')


@tool('clickup', 'ClickUp', 'productivity', 'circle-check-big',
      "Reliez votre espace ClickUp à Billio.",
      [("Dans ClickUp, avatar › Paramètres › Apps.", 'https://app.clickup.com/settings/apps'),
       ("Générez le jeton d'API (pk_…) et copiez-le ci-dessous.", '')],
      [F('access_token', "Jeton d'API", secret=True, placeholder='pk_…', pattern=r'pk_\S+')])
def _clickup(config):
    user = _http('GET', 'https://api.clickup.com/api/v2/user', headers={'Authorization': config['access_token']}).get('user') or {}
    return f"Compte {_first(user.get('username'), user.get('email'), '?')}"


@tool('monday', 'monday.com', 'productivity', 'layout-grid',
      "Reliez vos tableaux monday.com à Billio.",
      [("Dans monday.com, avatar › Développeurs › Mes jetons d'accès.", 'https://developer.monday.com/api-reference/docs/authentication'),
       ("Copiez votre jeton d'API personnel ci-dessous.", '')],
      [F('access_token', "Jeton d'API", secret=True)])
def _monday(config):
    data = _http('POST', 'https://api.monday.com/v2', headers={'Authorization': config['access_token']},
                 json_body={'query': '{ me { name email } account { name } }'})
    if data.get('errors') or data.get('error_message'):
        _fail(str((data.get('errors') or [{}])[0].get('message') or data.get('error_message'))[:200])
    me, account = (data.get('data') or {}).get('me') or {}, (data.get('data') or {}).get('account') or {}
    return f"Compte {me.get('name', '?')} · {account.get('name', '')}".rstrip(' ·')


@tool('airtable', 'Airtable', 'productivity', 'table',
      "Reliez vos bases Airtable à Billio.",
      [("Ouvrez le gestionnaire de jetons Airtable › « Create token ».", 'https://airtable.com/create/tokens'),
       ("Ajoutez au moins le scope « user.email:read » et les bases à partager, puis copiez le jeton.", '')],
      [F('access_token', "Jeton d'accès personnel", secret=True, placeholder='pat…', pattern=r'pat\S+')])
def _airtable(config):
    me = _http('GET', 'https://api.airtable.com/v0/meta/whoami', headers=_bearer(config['access_token']))
    return f"Compte {me.get('email') or me.get('id', '?')}"


@tool('linear', 'Linear', 'productivity', 'git-pull-request-arrow',
      "Reliez votre espace Linear à Billio.",
      [("Dans Linear, Paramètres › Sécurité et accès › Clés API personnelles.", 'https://linear.app/settings/account/security'),
       ("Créez une clé (lin_api_…) et copiez-la ci-dessous.", '')],
      [F('api_key', 'Clé API personnelle', secret=True, placeholder='lin_api_…', pattern=r'lin_api_\S+')])
def _linear(config):
    data = _http('POST', 'https://api.linear.app/graphql', headers={'Authorization': config['api_key']},
                 json_body={'query': '{ viewer { name email } organization { name } }'})
    if data.get('errors'):
        _fail(str(data['errors'][0].get('message'))[:200])
    viewer, org = (data.get('data') or {}).get('viewer') or {}, (data.get('data') or {}).get('organization') or {}
    return f"Compte {viewer.get('name', '?')} · {org.get('name', '')}".rstrip(' ·')


@tool('jira', 'Jira', 'productivity', 'kanban',
      "Reliez votre site Jira (Atlassian Cloud) à Billio.",
      [("Créez un jeton d'API depuis votre compte Atlassian.", 'https://id.atlassian.com/manage-profile/security/api-tokens'),
       ("Indiquez l'adresse de votre site (ex. entreprise.atlassian.net), votre email Atlassian et le jeton.", '')],
      [F('host', 'Adresse du site', placeholder='entreprise.atlassian.net', kind=HOST_FIELD, pattern=r'[a-z0-9-]+\.atlassian\.net'),
       F('email', 'Email du compte', placeholder='vous@entreprise.fr'),
       F('api_token', "Jeton d'API", secret=True)])
def _jira(config):
    me = _http('GET', f"https://{config['host']}/rest/api/3/myself", headers={'Authorization': _basic(config['email'], config['api_token']), 'Accept': 'application/json'})
    return f"Compte {me.get('displayName', '?')} sur {config['host']}"


@tool('github', 'GitHub', 'productivity', 'git-branch',
      "Reliez votre compte GitHub à Billio.",
      [("Créez un jeton à granularité fine (Settings › Developer settings › Personal access tokens).", 'https://github.com/settings/personal-access-tokens/new'),
       ("Choisissez les dépôts concernés et copiez le jeton (github_pat_…).", '')],
      [F('access_token', "Jeton d'accès", secret=True, placeholder='github_pat_…')])
def _github(config):
    user = _http('GET', 'https://api.github.com/user', headers={**_bearer(config['access_token']), 'Accept': 'application/vnd.github+json', 'User-Agent': 'Billio'})
    return f"Compte @{user.get('login', '?')}"


@tool('calendly', 'Calendly', 'productivity', 'calendar-clock',
      "Reliez votre compte Calendly à Billio.",
      [("Dans Calendly, Intégrations et applications › API et webhooks.", 'https://calendly.com/integrations/api_webhooks'),
       ("Générez un jeton d'accès personnel et copiez-le ci-dessous.", '')],
      [F('access_token', "Jeton d'accès personnel", secret=True)])
def _calendly(config):
    me = _http('GET', 'https://api.calendly.com/users/me', headers=_bearer(config['access_token'])).get('resource') or {}
    return f"Compte {me.get('name', '?')} ({me.get('email', '')})"


@tool('toggl', 'Toggl Track', 'productivity', 'timer',
      "Reliez votre suivi du temps Toggl Track à Billio.",
      [("Ouvrez votre profil Toggl Track.", 'https://track.toggl.com/profile'),
       ("En bas de la page, copiez le « API Token ».", '')],
      [F('api_token', 'API Token', secret=True)])
def _toggl(config):
    me = _http('GET', 'https://api.track.toggl.com/api/v9/me', headers={'Authorization': _basic(config['api_token'], 'api_token')})
    return f"Compte {_first(me.get('fullname'), me.get('email'), '?')}"


@tool('harvest', 'Harvest', 'productivity', 'clock',
      "Reliez votre compte Harvest (temps et dépenses) à Billio.",
      [("Ouvrez Harvest ID › Developers › « Create new personal access token ».", 'https://id.getharvest.com/developers'),
       ("Copiez le jeton et l'Account ID affichés.", '')],
      [F('access_token', "Jeton d'accès", secret=True), F('account_id', 'Account ID', placeholder='123456', pattern=r'\d+')])
def _harvest(config):
    me = _http('GET', 'https://api.harvestapp.com/v2/users/me', headers={
        **_bearer(config['access_token']), 'Harvest-Account-Id': config['account_id'], 'User-Agent': 'Billio',
    })
    return f"Compte {me.get('first_name', '')} {me.get('last_name', '')}".strip()


@tool('clockify', 'Clockify', 'productivity', 'alarm-clock',
      "Reliez votre suivi du temps Clockify à Billio.",
      [("Dans Clockify, Préférences du profil › Avancé › « Generate » (clé API).", 'https://app.clockify.me/user/preferences#advanced'),
       ("Copiez la clé ci-dessous.", '')],
      [F('api_key', 'Clé API', secret=True)])
def _clockify(config):
    me = _http('GET', 'https://api.clockify.me/api/v1/user', headers={'X-Api-Key': config['api_key']})
    return f"Compte {_first(me.get('name'), me.get('email'), '?')}"


@tool('typeform', 'Typeform', 'productivity', 'clipboard-list',
      "Reliez vos formulaires Typeform à Billio.",
      [("Dans Typeform, Compte › Jetons personnels › « Générer un nouveau jeton ».", 'https://www.typeform.com/developers/get-started/personal-access-token/'),
       ("Copiez le jeton (tfp_…) ci-dessous.", '')],
      [F('access_token', 'Jeton personnel', secret=True, placeholder='tfp_…')])
def _typeform(config):
    me = _http('GET', 'https://api.typeform.com/me', headers=_bearer(config['access_token']))
    return f"Compte {_first(me.get('alias'), me.get('email'), '?')}"


@tool('todoist', 'Todoist', 'productivity', 'square-check-big',
      "Reliez vos listes Todoist à Billio.",
      [("Dans Todoist, Paramètres › Intégrations › Développeur.", 'https://app.todoist.com/app/settings/integrations/developer'),
       ("Copiez le jeton d'API ci-dessous.", '')],
      [F('access_token', "Jeton d'API", secret=True)])
def _todoist(config):
    data = _http('GET', 'https://api.todoist.com/api/v1/projects', headers=_bearer(config['access_token']))
    projects = data.get('results', []) if isinstance(data, dict) else data
    return f'{len(projects)} projet(s) accessible(s)'


@tool('yousign', 'Yousign', 'productivity', 'signature',
      "Signature électronique française : reliez votre compte Yousign à Billio.",
      [("Dans Yousign, Intégrations › API › « Créer une clé API ».", 'https://yousign.app/auth/workspace/api-keys'),
       ("Choisissez l'environnement de la clé (Production ou Sandbox) et copiez-la ci-dessous.", '')],
      [F('api_key', 'Clé API', secret=True), F('environment', 'Environnement', options=ENV_OPTIONS)])
def _yousign(config):
    host = 'api-sandbox.yousign.app' if config.get('environment') == 'sandbox' else 'api.yousign.app'
    users = _http('GET', f'https://{host}/v3/users', headers=_bearer(config['api_key'])).get('data') or []
    return f"Compte vérifié · {len(users)} utilisateur(s)" + (' · sandbox' if 'sandbox' in host else '')


@tool('pandadoc', 'PandaDoc', 'productivity', 'file-signature',
      "Reliez votre compte PandaDoc (propositions et signatures) à Billio.",
      [("Dans PandaDoc, Paramètres › Intégrations › API › « Generate API key ».", 'https://app.pandadoc.com/a/#/settings/integrations/api'),
       ("Copiez la clé (production ou sandbox) ci-dessous.", '')],
      [F('api_key', 'Clé API', secret=True)])
def _pandadoc(config):
    me = _http('GET', 'https://api.pandadoc.com/public/v1/members/current', headers={'Authorization': f"API-Key {config['api_key']}"})
    return f"Compte {me.get('first_name', '')} {me.get('last_name', '')} · {me.get('workspace_name', '')}".strip(' ·')


# =========================================================================== #
# Paiement
# =========================================================================== #

@tool('gocardless', 'GoCardless', 'payment', 'repeat',
      "Prélèvements SEPA : reliez votre compte GoCardless à Billio.",
      [("Dans GoCardless, Développeurs › « Créer » › Jeton d'accès (lecture-écriture).", 'https://manage.gocardless.com/developers/access-tokens/create'),
       ("Copiez le jeton et choisissez l'environnement correspondant.", '')],
      [F('access_token', "Jeton d'accès", secret=True, placeholder='live_… ou sandbox_…'), F('environment', 'Environnement', options=ENV_OPTIONS)])
def _gocardless(config):
    host = 'api-sandbox.gocardless.com' if config.get('environment') == 'sandbox' else 'api.gocardless.com'
    creditors = _http('GET', f'https://{host}/creditors', headers={**_bearer(config['access_token']), 'GoCardless-Version': '2015-07-06'}).get('creditors') or []
    return f"Créancier « {creditors[0].get('name', '?')} »" if creditors else 'Compte vérifié'


@tool('sumup', 'SumUp', 'payment', 'credit-card',
      "Reliez votre compte SumUp (terminal et liens de paiement) à Billio.",
      [("Dans SumUp, Profil › Paramètres › Pour les développeurs › Clés API.", 'https://me.sumup.com/settings/api-keys'),
       ("Créez une clé secrète (sup_sk_…) et copiez-la ci-dessous.", '')],
      [F('api_key', 'Clé secrète', secret=True, placeholder='sup_sk_…')])
def _sumup(config):
    me = _http('GET', 'https://api.sumup.com/v0.1/me', headers=_bearer(config['api_key']))
    profile = me.get('merchant_profile') or {}
    return f"Commerçant « {_first(profile.get('company_name'), profile.get('merchant_code'), (me.get('account') or {}).get('username'), '?')} »"


@tool('mollie', 'Mollie', 'payment', 'wallet-cards',
      "Reliez votre compte Mollie (CB, virement, iDEAL…) à Billio.",
      [("Dans Mollie, Développeurs › Clés API.", 'https://my.mollie.com/dashboard/developers/api-keys'),
       ("Copiez la clé live_… (ou test_… pour essayer) ci-dessous.", '')],
      [F('api_key', 'Clé API', secret=True, placeholder='live_… ou test_…', pattern=r'(live|test)_\w+')])
def _mollie(config):
    methods = (_http('GET', 'https://api.mollie.com/v2/methods', headers=_bearer(config['api_key'])).get('_embedded') or {}).get('methods') or []
    mode = 'test' if config['api_key'].startswith('test_') else 'live'
    return f"Mode {mode} · {len(methods)} moyen(s) de paiement actif(s)"


@tool('payplug', 'PayPlug', 'payment', 'badge-euro',
      "Solution de paiement française : reliez votre compte PayPlug à Billio.",
      [("Dans le portail PayPlug, Paramètres › Clés API.", 'https://portal.payplug.com/'),
       ("Copiez la clé secrète sk_live_… (ou sk_test_…) ci-dessous.", '')],
      [F('secret_key', 'Clé secrète', secret=True, placeholder='sk_live_… ou sk_test_…', pattern=r'sk_(live|test)_\w+')])
def _payplug(config):
    _http('GET', 'https://api.payplug.com/v1/payments?per_page=1', headers={**_bearer(config['secret_key']), 'PayPlug-Version': '2019-08-06'})
    return f"Clé {'test' if '_test_' in config['secret_key'] else 'live'} valide"


# =========================================================================== #
# Banque & comptabilité
# =========================================================================== #

@tool('qonto', 'Qonto', 'accounting', 'landmark',
      "Reliez votre compte pro Qonto à Billio.",
      [("Dans Qonto, Paramètres › Intégrations et partenariats › Clé API (propriétaire ou admin).", 'https://app.qonto.com/'),
       ("Copiez l'identifiant (login) et la clé secrète ci-dessous.", '')],
      [F('login', 'Identifiant', placeholder='mon-entreprise-1234'), F('secret_key', 'Clé secrète', secret=True)])
def _qonto(config):
    org = _http('GET', 'https://thirdparty.qonto.com/v2/organization', headers={'Authorization': f"{config['login']}:{config['secret_key']}"}).get('organization') or {}
    accounts = org.get('bank_accounts') or []
    return f"{_first(org.get('legal_name'), org.get('slug'), '?')} · {len(accounts)} compte(s)"


@tool('wise', 'Wise', 'accounting', 'globe',
      "Reliez votre compte Wise Business (paiements internationaux) à Billio.",
      [("Dans Wise, Paramètres › Jetons d'API › « Ajouter un jeton » (lecture seule suffit).", 'https://wise.com/settings/api-tokens'),
       ("Copiez le jeton et choisissez l'environnement.", '')],
      [F('access_token', "Jeton d'API", secret=True), F('environment', 'Environnement', options=ENV_OPTIONS)])
def _wise(config):
    host = 'api.sandbox.transferwise.tech' if config.get('environment') == 'sandbox' else 'api.transferwise.com'
    profiles = _http('GET', f'https://{host}/v2/profiles', headers=_bearer(config['access_token']))
    profiles = profiles if isinstance(profiles, list) else []
    names = [_first(p.get('fullName'), (p.get('details') or {}).get('name'), p.get('businessName')) for p in profiles]
    return f"{len(profiles)} profil(s)" + (f" · {', '.join(n for n in names if n)}" if any(names) else '')


@tool('pennylane', 'Pennylane', 'accounting', 'calculator',
      "Reliez votre comptabilité Pennylane à Billio.",
      [("Dans Pennylane, Paramètres › Connectivité › Développeurs › « Générer un jeton ».", 'https://app.pennylane.com/'),
       ("Donnez au jeton les droits nécessaires et copiez-le ci-dessous.", '')],
      [F('access_token', "Jeton d'API", secret=True)])
def _pennylane(config):
    me = _http('GET', 'https://app.pennylane.com/api/external/v2/me', headers=_bearer(config['access_token']))
    company = (me.get('company') or {}).get('name')
    user = me.get('user') or {}
    return f"{_first(company, 'Compte vérifié')}" + (f" · {user.get('first_name', '')} {user.get('last_name', '')}".rstrip() if user else '')


# QuickBooks Online : connexion OAuth uniquement (Intuit ne délivre pas de clé personnelle),
# voir oauth.OAUTH['quickbooks'] ; la configuration porte access_token, realm_id et environment.
def qbo_base(config):
    host = 'sandbox-quickbooks.api.intuit.com' if config.get('environment') == 'sandbox' else 'quickbooks.api.intuit.com'
    return f"https://{host}/v3/company/{config['realm_id']}"


def qbo_headers(config):
    return dict(_bearer(config['access_token']), Accept='application/json')


@tool('quickbooks', 'QuickBooks', 'accounting', 'calculator',
      "Envoyez vos clients, factures et paiements dans QuickBooks Online.",
      [("Cliquez « Se connecter avec QuickBooks » et identifiez-vous avec votre compte Intuit.", ''),
       ("Choisissez l'entreprise QuickBooks à relier puis cliquez « Connecter ».", ''),
       ("Si le bouton n'apparaît pas, l'administrateur de Billio doit d'abord activer la connexion QuickBooks.", '')],
      [], uses=['Action « Envoyer vers une app » des automatisations',
                'Facture envoyée → facture QuickBooks, paiement reçu → paiement QuickBooks'])
def _quickbooks(config):
    return f"Entreprise « {qbo_company(config)} »" + (' (sandbox)' if config.get('environment') == 'sandbox' else '')


def qbo_company(config):
    info = _http('GET', f"{qbo_base(config)}/companyinfo/{config['realm_id']}?minorversion=75",
                 headers=qbo_headers(config)).get('CompanyInfo') or {}
    return _first(info.get('CompanyName'), info.get('LegalName'), 'QuickBooks')


# =========================================================================== #
# CRM & support
# =========================================================================== #

@tool('hubspot', 'HubSpot', 'crm', 'contact',
      "Reliez votre CRM HubSpot à Billio.",
      [("Dans HubSpot, Paramètres › Intégrations › Applications privées › « Créer une application privée ».", 'https://app.hubspot.com/'),
       ("Accordez les scopes CRM nécessaires (contacts, entreprises) puis copiez le jeton (pat-…).", '')],
      [F('access_token', "Jeton d'application privée", secret=True, placeholder='pat-…')])
def _hubspot(config):
    details = _http('GET', 'https://api.hubapi.com/account-info/v3/details', headers=_bearer(config['access_token']))
    return f"Portail {details.get('portalId', '?')} · {details.get('companyCurrency', '')}".rstrip(' ·')


@tool('pipedrive', 'Pipedrive', 'crm', 'handshake',
      "Reliez votre pipeline commercial Pipedrive à Billio.",
      [("Dans Pipedrive, avatar › Préférences personnelles › API.", 'https://app.pipedrive.com/settings/api'),
       ("Copiez votre jeton d'API personnel ci-dessous.", '')],
      [F('api_token', "Jeton d'API", secret=True)])
def _pipedrive(config):
    me = _http('GET', f"https://api.pipedrive.com/v1/users/me?api_token={config['api_token']}").get('data') or {}
    return f"Compte {me.get('name', '?')} · {me.get('company_name', '')}".rstrip(' ·')


@tool('attio', 'Attio', 'crm', 'users-round',
      "Reliez votre CRM Attio à Billio.",
      [("Dans Attio, Paramètres de l'espace › Développeurs › « New access token ».", 'https://app.attio.com/'),
       ("Accordez les scopes de lecture nécessaires et copiez le jeton.", '')],
      [F('access_token', "Jeton d'accès", secret=True)])
def _attio(config):
    me = _http('GET', 'https://api.attio.com/v2/self', headers=_bearer(config['access_token']))
    if me.get('active') is False:
        _fail('Jeton inactif.')
    return f"Espace « {me.get('workspace_name', '?')} »"


@tool('sellsy', 'Sellsy', 'crm', 'briefcase-business',
      "CRM français : reliez votre compte Sellsy à Billio.",
      [("Dans Sellsy, Paramètres › Portail développeur › « Créer un accès API » de type privé.", 'https://go.sellsy.com/'),
       ("Copiez le Client ID et le Client secret ci-dessous.", '')],
      [F('client_id', 'Client ID'), F('client_secret', 'Client secret', secret=True)])
def _sellsy(config):
    token = _http('POST', 'https://login.sellsy.com/oauth2/access-tokens', form={
        'grant_type': 'client_credentials', 'client_id': config['client_id'], 'client_secret': config['client_secret'],
    })
    if not token.get('access_token'):
        _fail('Sellsy a refusé ces identifiants.')
    return 'Accès API Sellsy vérifié'


@tool('intercom', 'Intercom', 'crm', 'headset',
      "Reliez votre support client Intercom à Billio.",
      [("Dans l'Intercom Developer Hub, créez une application puis ouvrez Configure › Authentication.", 'https://app.intercom.com/a/apps/_/developer-hub'),
       ("Copiez le jeton d'accès ci-dessous.", '')],
      [F('access_token', "Jeton d'accès", secret=True)])
def _intercom(config):
    me = _http('GET', 'https://api.intercom.io/me', headers={**_bearer(config['access_token']), 'Accept': 'application/json'})
    return f"Espace « {(me.get('app') or {}).get('name', '?')} » · {me.get('name', '')}".rstrip(' ·')


@tool('zendesk', 'Zendesk', 'crm', 'life-buoy',
      "Reliez votre support Zendesk à Billio.",
      [("Dans Zendesk, Centre d'administration › Applications et intégrations › API Zendesk : activez l'accès par jeton.", ''),
       ("Ajoutez un jeton d'API et copiez-le.", ''),
       ("Indiquez l'adresse de votre compte (ex. entreprise.zendesk.com) et l'email d'un agent.", '')],
      [F('host', 'Adresse du compte', placeholder='entreprise.zendesk.com', kind=HOST_FIELD, pattern=r'[a-z0-9-]+\.zendesk\.com'),
       F('email', "Email de l'agent", placeholder='vous@entreprise.fr'),
       F('api_token', "Jeton d'API", secret=True)])
def _zendesk(config):
    user = _http('GET', f"https://{config['host']}/api/v2/users/me.json",
                 headers={'Authorization': _basic(f"{config['email']}/token", config['api_token'])}).get('user') or {}
    if not user.get('id'):
        _fail('Zendesk a refusé ces identifiants (email ou jeton).')
    return f"Compte {user.get('name', '?')} ({user.get('role', '')})"


@tool('freshdesk', 'Freshdesk', 'crm', 'inbox',
      "Reliez votre support Freshdesk à Billio.",
      [("Dans Freshdesk, avatar › Paramètres du profil : copiez votre clé API.", ''),
       ("Indiquez l'adresse de votre compte (ex. entreprise.freshdesk.com).", '')],
      [F('host', 'Adresse du compte', placeholder='entreprise.freshdesk.com', kind=HOST_FIELD, pattern=r'[a-z0-9-]+\.freshdesk\.com'),
       F('api_key', 'Clé API', secret=True)])
def _freshdesk(config):
    me = _http('GET', f"https://{config['host']}/api/v2/agents/me", headers={'Authorization': _basic(config['api_key'], 'X')})
    return f"Agent {(me.get('contact') or {}).get('name', '?')}"


@tool('close', 'Close', 'crm', 'phone-call',
      "Reliez votre CRM Close à Billio.",
      [("Dans Close, Paramètres › Developer › API Keys › « + New API Key ».", 'https://app.close.com/settings/developer/'),
       ("Copiez la clé ci-dessous.", '')],
      [F('api_key', 'Clé API', secret=True, placeholder='api_…')])
def _close(config):
    me = _http('GET', 'https://api.close.com/api/v1/me/', headers={'Authorization': _basic(config['api_key'], '')})
    orgs = ', '.join(o.get('name', '') for o in (me.get('organizations') or [])[:2])
    return f"Compte {me.get('first_name', '')} {me.get('last_name', '')}".strip() + (f' · {orgs}' if orgs else '')


# =========================================================================== #
# Marketing & e-commerce
# =========================================================================== #

@tool('brevo', 'Brevo', 'marketing', 'megaphone',
      "Emailing et SMS français (ex-Sendinblue) : reliez votre compte Brevo. " + SMTP_HINT,
      [("Dans Brevo, menu du compte › SMTP et API › Clés API › « Générer une nouvelle clé ».", 'https://app.brevo.com/settings/keys/api'),
       ("Copiez la clé (xkeysib-…) ci-dessous.", ''),
       ("Email : plugin Email avec smtp-relay.brevo.com, port 587, et l'identifiant / mot de passe de l'onglet SMTP.", '')],
      [F('api_key', 'Clé API', secret=True, placeholder='xkeysib-…', pattern=r'xkeysib-\S+')])
def _brevo(config):
    account = _http('GET', 'https://api.brevo.com/v3/account', headers={'api-key': config['api_key'], 'Accept': 'application/json'})
    return f"Compte « {_first(account.get('companyName'), account.get('email'), '?')} »"


@tool('mailchimp', 'Mailchimp', 'marketing', 'mail-plus',
      "Reliez vos audiences Mailchimp à Billio.",
      [("Dans Mailchimp, Profil › Extras › Clés API › « Create A Key ».", 'https://us1.admin.mailchimp.com/account/api/'),
       ("Copiez la clé complète (elle se termine par -us…).", '')],
      [F('api_key', 'Clé API', secret=True, placeholder='…-us21', pattern=r'[0-9a-f]{32}-us\d{1,3}')])
def _mailchimp(config):
    dc = config['api_key'].rsplit('-', 1)[-1]
    account = _http('GET', f'https://{dc}.api.mailchimp.com/3.0/', headers={'Authorization': _basic('billio', config['api_key'])})
    return f"Compte « {account.get('account_name', '?')} » · {account.get('total_subscribers', 0)} abonné(s)"


@tool('klaviyo', 'Klaviyo', 'marketing', 'chart-no-axes-combined',
      "Reliez votre compte Klaviyo (emailing e-commerce) à Billio.",
      [("Dans Klaviyo, Paramètres › Compte › Clés API › « Create Private API Key ».", 'https://www.klaviyo.com/settings/account/api-keys'),
       ("Accordez au moins l'accès en lecture « Accounts » et copiez la clé (pk_…).", '')],
      [F('api_key', 'Clé API privée', secret=True, placeholder='pk_…', pattern=r'pk_\w+')])
def _klaviyo(config):
    data = _http('GET', 'https://a.klaviyo.com/api/accounts/', headers={
        'Authorization': f"Klaviyo-API-Key {config['api_key']}", 'revision': '2024-10-15', 'Accept': 'application/vnd.api+json',
    }).get('data') or [{}]
    info = ((data[0].get('attributes') or {}).get('contact_information') or {})
    return f"Compte « {_first(info.get('organization_name'), data[0].get('id'), '?')} »"


@tool('activecampaign', 'ActiveCampaign', 'marketing', 'send',
      "Reliez votre marketing automation ActiveCampaign à Billio.",
      [("Dans ActiveCampaign, Paramètres › Développeur.", ''),
       ("Copiez l'URL de l'API (ex. entreprise.api-us1.com) et la clé.", '')],
      [F('host', "URL de l'API", placeholder='entreprise.api-us1.com', kind=HOST_FIELD, pattern=r'[a-z0-9-]+\.(api-us1|activehosted)\.com'),
       F('api_key', 'Clé API', secret=True)])
def _activecampaign(config):
    user = _http('GET', f"https://{config['host']}/api/3/users/me", headers={'Api-Token': config['api_key']}).get('user') or {}
    return f"Compte {_first(user.get('username'), user.get('email'), '?')}"


@tool('mailerlite', 'MailerLite', 'marketing', 'newspaper',
      "Reliez vos newsletters MailerLite à Billio.",
      [("Dans MailerLite, Intégrations › API › « Générer un nouveau jeton ».", 'https://dashboard.mailerlite.com/integrations/api'),
       ("Copiez le jeton ci-dessous.", '')],
      [F('api_key', "Jeton d'API", secret=True)])
def _mailerlite(config):
    groups = _http('GET', 'https://connect.mailerlite.com/api/groups?limit=1', headers={**_bearer(config['api_key']), 'Accept': 'application/json'})
    total = (groups.get('meta') or {}).get('total')
    return 'Compte vérifié' + (f' · {total} groupe(s)' if total is not None else '')


@tool('kit', 'Kit (ConvertKit)', 'marketing', 'mail-open',
      "Reliez votre compte Kit (ex-ConvertKit) à Billio.",
      [("Dans Kit, Paramètres › Développeur › « Ajouter une nouvelle clé » (API v4).", 'https://app.kit.com/account_settings/developer_settings'),
       ("Copiez la clé ci-dessous.", '')],
      [F('api_key', 'Clé API v4', secret=True, placeholder='kit_…')])
def _kit(config):
    data = _http('GET', 'https://api.kit.com/v4/account', headers={'X-Kit-Api-Key': config['api_key'], 'Accept': 'application/json'})
    return f"Compte « {_first((data.get('account') or {}).get('name'), (data.get('user') or {}).get('email'), '?')} »"


@tool('shopify', 'Shopify', 'marketing', 'shopping-bag',
      "Reliez votre boutique Shopify à Billio.",
      [("Dans l'admin Shopify, Paramètres › Applications › Développer des applications › « Créer une application ».", ''),
       ("Accordez les scopes Admin API utiles (read_orders, read_customers), installez l'application.", ''),
       ("Copiez le jeton d'accès Admin API (shpat_…) et l'adresse de la boutique (xxx.myshopify.com).", '')],
      [F('host', 'Adresse de la boutique', placeholder='boutique.myshopify.com', kind=HOST_FIELD, pattern=r'[a-z0-9-]+\.myshopify\.com'),
       F('access_token', "Jeton d'accès Admin API", secret=True, placeholder='shpat_…')])
def _shopify(config):
    shop = _http('GET', f"https://{config['host']}/admin/api/2025-07/shop.json", headers={'X-Shopify-Access-Token': config['access_token']}).get('shop') or {}
    return f"Boutique « {shop.get('name', '?')} » ({shop.get('currency', '')})"


@tool('webflow', 'Webflow', 'marketing', 'app-window',
      "Reliez vos sites Webflow à Billio.",
      [("Dans Webflow, paramètres du site › Applications et intégrations › Jetons d'API › « Générer ».", 'https://webflow.com/dashboard'),
       ("Accordez au moins la lecture « Sites » et copiez le jeton.", '')],
      [F('access_token', "Jeton d'API du site", secret=True)])
def _webflow(config):
    sites = _http('GET', 'https://api.webflow.com/v2/sites', headers=_bearer(config['access_token'])).get('sites') or []
    return f"{len(sites)} site(s)" + (f" · {', '.join(s.get('displayName', '') for s in sites[:3])}" if sites else '')


# =========================================================================== #
# Automatisation
# =========================================================================== #

def _hook_send(config, text, recipient=''):
    _http('POST', config['webhook_url'], raw=True, json_body={'source': 'billio', 'text': text})
    return 'Message envoyé au webhook'


EVENT_USE = "Action « Envoyer vers une app › Envoyer l'événement » : client, montant, numéro et variables en JSON"


@tool('make', 'Make', 'automation', 'workflow',
      "Déclenchez vos scénarios Make depuis les automatisations Billio.",
      [("Dans Make, créez un scénario dont le premier module est « Webhooks › Custom webhook ».", 'https://www.make.com/'),
       ("Ajoutez un webhook et copiez son adresse (hook.eu1.make.com/…).", ''),
       ("Testez : Make reçoit {source, text} et peut déterminer la structure des données.", '')],
      [F('webhook_url', 'URL du webhook', secret=True, placeholder='https://hook.eu1.make.com/…', pattern=r'https://hook\.[\w-]+\.make\.com/\S+')],
      uses=[EVENT_USE, MESSAGE_USE + ' (le texte est envoyé au scénario)', 'Requête de test'])
def _make(config):
    _hook_send(config, TEST_MESSAGE)
    return 'Requête de test reçue par Make'


@tool('n8n', 'n8n', 'automation', 'network',
      "Déclenchez vos workflows n8n Cloud depuis les automatisations Billio.",
      [("Dans n8n, ajoutez un nœud « Webhook » (méthode POST) en tête du workflow.", 'https://app.n8n.cloud/'),
       ("Activez le workflow puis copiez l'URL de production (….app.n8n.cloud/webhook/…).", '')],
      [F('webhook_url', 'URL du webhook', secret=True, placeholder='https://xxx.app.n8n.cloud/webhook/…',
         pattern=r'https://[\w-]+\.app\.n8n\.cloud/webhook(-test)?/\S+',
         help="Seules les instances n8n Cloud sont acceptées (pas d'adresse auto-hébergée).")],
      uses=[EVENT_USE, MESSAGE_USE + ' (le texte est envoyé au workflow)', 'Requête de test'])
def _n8n(config):
    _hook_send(config, TEST_MESSAGE)
    return 'Requête de test reçue par n8n'


def _ifttt_send(config, text, recipient=''):
    _http('POST', f"https://maker.ifttt.com/trigger/{config['event']}/with/key/{config['key']}", raw=True,
          json_body={'value1': text, 'value2': recipient, 'value3': 'billio'})
    return 'Évènement IFTTT déclenché'


@tool('ifttt', 'IFTTT', 'automation', 'zap',
      "Déclenchez vos applets IFTTT depuis les automatisations Billio.",
      [("Créez une applet dont le déclencheur est « Webhooks › Receive a web request » avec un nom d'évènement.", 'https://ifttt.com/maker_webhooks'),
       ("Ouvrez la page Webhooks › Documentation et copiez votre clé.", 'https://ifttt.com/maker_webhooks/settings'),
       ("Le message est transmis dans « Value1 ».", '')],
      [F('key', 'Clé Webhooks', secret=True), F('event', "Nom de l'évènement", placeholder='billio', pattern=r'[\w-]{1,60}')],
      uses=[MESSAGE_USE + ' (le texte est transmis dans Value1)', 'Déclenchement de test'])
def _ifttt(config):
    _ifttt_send(config, TEST_MESSAGE)
    return f"Évènement « {config['event']} » déclenché"


@tool('zapier', 'Zapier', 'automation', 'zap',
      "Déclenchez vos Zaps depuis les automatisations Billio et reliez Billio à plus de 7 000 applications.",
      [("Dans Zapier, créez un Zap dont le déclencheur est « Webhooks by Zapier › Catch Hook ».", 'https://zapier.com/app/zaps'),
       ("Copiez l'adresse du webhook (hooks.zapier.com/hooks/catch/…) et collez-la ci-dessous.", ''),
       ("Testez : Zapier reçoit une requête et peut déterminer la structure des données.", '')],
      [F('webhook_url', 'URL du webhook', secret=True, placeholder='https://hooks.zapier.com/hooks/catch/…',
         pattern=r'https://hooks\.zapier\.com/hooks/catch/\d+/\w+/?')],
      uses=[EVENT_USE, MESSAGE_USE + ' (le texte est envoyé au Zap)', 'Requête de test'])
def _zapier(config):
    _hook_send(config, TEST_MESSAGE)
    return 'Requête de test reçue par Zapier'


SENDERS.update({
    'microsoft-teams': _teams_send, 'discord': _discord_send, 'google-chat': _gchat_send, 'twilio': _twilio_send,
    'make': _hook_send, 'n8n': _hook_send, 'zapier': _hook_send, 'ifttt': _ifttt_send,
})
PHONE_CHANNELS = ('twilio',)
