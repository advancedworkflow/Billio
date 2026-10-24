"""
Connexion « Se connecter avec… » (OAuth 2.0) pour les outils qui la proposent.

L'utilisateur clique, s'identifie chez l'outil, autorise Billio et revient connecté : plus de clé à
copier. Le résultat est rangé dans la même configuration que le formulaire manuel (webhook_url,
access_token, api_key…), si bien que les tests de connexion, l'action « Envoyer un message » et
« Envoyer vers une app » fonctionnent sans changement.

Chaque outil n'est proposé que si l'application OAuth de Billio est déclarée sur le serveur
(variables <OUTIL>_CLIENT_ID / <OUTIL>_CLIENT_SECRET, ou TRELLO_API_KEY, dans l'environnement ou
saisies dans Administration › Clés des intégrations) ; sinon le formulaire
manuel reste le seul chemin. Google Drive garde son propre flux (plugin_views.google_*).
"""
import base64
import urllib.parse

from django.utils import timezone

from . import providers
from .providers import ProviderError, http

# Domaines appelés pendant l'échange du code (en plus de la liste blanche des services).
providers.ALLOWED_HOSTS.update({'slack.com', 'login.mailchimp.com', 'api.hubapi.com', 'oauth.platform.intuit.com'})


def _env(name):
    # Variable d'environnement, sinon clé saisie dans Administration › Clés des intégrations.
    from apps.staff.platform import get_setting
    return get_setting(name)


def _basic(user, password):
    return 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()


# --------------------------------------------------------------------------- échanges par outil

def _slack_exchange(spec, code, redirect_uri):
    data = http('POST', 'https://slack.com/api/oauth.v2.access', form={
        'client_id': _env('SLACK_CLIENT_ID'), 'client_secret': _env('SLACK_CLIENT_SECRET'),
        'code': code, 'redirect_uri': redirect_uri,
    })
    if not data.get('ok'):
        raise ProviderError(f"Slack a refusé la connexion ({data.get('error', 'erreur inconnue')}).")
    hook = data.get('incoming_webhook') or {}
    if not hook.get('url'):
        raise ProviderError('Slack n’a pas renvoyé de canal : choisissez un canal pendant l’autorisation.')
    return {'webhook_url': hook['url'], 'account': f"{(data.get('team') or {}).get('name', 'Slack')} · {hook.get('channel', '')}"}


def _notion_exchange(spec, code, redirect_uri):
    data = http('POST', 'https://api.notion.com/v1/oauth/token', json_body={
        'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri,
    }, headers={'Authorization': _basic(_env('NOTION_CLIENT_ID'), _env('NOTION_CLIENT_SECRET'))})
    if not data.get('access_token'):
        raise ProviderError('Notion n’a pas renvoyé d’accès.')
    return {'access_token': data['access_token'], 'account': data.get('workspace_name') or 'Notion'}


def _mailchimp_exchange(spec, code, redirect_uri):
    data = http('POST', 'https://login.mailchimp.com/oauth2/token', form={
        'grant_type': 'authorization_code', 'client_id': _env('MAILCHIMP_CLIENT_ID'),
        'client_secret': _env('MAILCHIMP_CLIENT_SECRET'), 'redirect_uri': redirect_uri, 'code': code,
    })
    token = data.get('access_token')
    if not token:
        raise ProviderError('Mailchimp n’a pas renvoyé d’accès.')
    meta = http('GET', 'https://login.mailchimp.com/oauth2/metadata', headers={'Authorization': f'OAuth {token}'})
    dc = meta.get('dc')
    if not dc:
        raise ProviderError('Compte Mailchimp introuvable.')
    # Même format qu'une clé API (« jeton-dc ») : l'appel à l'API reste identique.
    return {'api_key': f'{token}-{dc}', 'account': meta.get('accountname') or meta.get('login', {}).get('email', 'Mailchimp')}


def _hubspot_tokens(form):
    data = http('POST', 'https://api.hubapi.com/oauth/v1/token', form=dict(form, client_id=_env('HUBSPOT_CLIENT_ID'),
                                                                      client_secret=_env('HUBSPOT_CLIENT_SECRET')))
    if not data.get('access_token'):
        raise ProviderError('HubSpot n’a pas renvoyé d’accès.')
    return {'access_token': data['access_token'], 'refresh_token': data.get('refresh_token', ''),
            'token_expiry': int(timezone.now().timestamp()) + int(data.get('expires_in') or 1800) - 60}


def _hubspot_exchange(spec, code, redirect_uri):
    config = _hubspot_tokens({'grant_type': 'authorization_code', 'redirect_uri': redirect_uri, 'code': code})
    info = http('GET', f"https://api.hubapi.com/oauth/v1/access-tokens/{config['access_token']}")
    config['account'] = info.get('hub_domain') or 'HubSpot'
    return config


def _hubspot_refresh(config):
    return _hubspot_tokens({'grant_type': 'refresh_token', 'refresh_token': config['refresh_token']})


QUICKBOOKS_TOKEN_URL = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer'


def _quickbooks_tokens(form):
    data = http('POST', QUICKBOOKS_TOKEN_URL, form=form, headers={
        'Authorization': _basic(_env('QUICKBOOKS_CLIENT_ID'), _env('QUICKBOOKS_CLIENT_SECRET')), 'Accept': 'application/json'})
    if not data.get('access_token'):
        raise ProviderError('QuickBooks n’a pas renvoyé d’accès.')
    # Intuit renouvelle le jeton de rafraîchissement : on garde toujours le dernier reçu.
    return {'access_token': data['access_token'], 'refresh_token': data.get('refresh_token', ''),
            'token_expiry': int(timezone.now().timestamp()) + int(data.get('expires_in') or 3600) - 60}


def _quickbooks_exchange(spec, code, redirect_uri, query):
    realm = (query.get('realmId') or '').strip()
    if not realm.isdigit():
        raise ProviderError('QuickBooks n’a pas indiqué d’entreprise : recommencez en choisissant une entreprise.')
    config = _quickbooks_tokens({'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri})
    config['realm_id'] = realm
    config['environment'] = 'sandbox' if _env('QUICKBOOKS_ENVIRONMENT').lower() == 'sandbox' else 'production'
    from .catalog import qbo_company
    try:
        config['account'] = qbo_company(config)
    except ProviderError:
        config['account'] = 'QuickBooks'
    return config


def _quickbooks_refresh(config):
    return _quickbooks_tokens({'grant_type': 'refresh_token', 'refresh_token': config['refresh_token']})


# --------------------------------------------------------------------------- outils

OAUTH = {
    'slack': {
        'name': 'Slack', 'env': ('SLACK_CLIENT_ID', 'SLACK_CLIENT_SECRET'),
        'authorize': 'https://slack.com/oauth/v2/authorize', 'params': {'scope': 'incoming-webhook'},
        'exchange': _slack_exchange, 'console': 'https://api.slack.com/apps',
        'steps': ['Créez une app « From scratch » sur api.slack.com/apps.',
                  'OAuth & Permissions : ajoutez l’URL de redirection ci-dessous et le scope « incoming-webhook ».',
                  'Basic Information : copiez Client ID et Client Secret.'],
    },
    'notion': {
        'name': 'Notion', 'env': ('NOTION_CLIENT_ID', 'NOTION_CLIENT_SECRET'),
        'authorize': 'https://api.notion.com/v1/oauth/authorize', 'params': {'owner': 'user'},
        'exchange': _notion_exchange, 'console': 'https://www.notion.so/profile/integrations',
        'steps': ['Créez une intégration de type « Public » dans Notion.',
                  'Déclarez l’URL de redirection ci-dessous, avec vos coordonnées et votre politique de confidentialité.',
                  'Copiez « OAuth client ID » et « OAuth client secret ».'],
    },
    'mailchimp': {
        'name': 'Mailchimp', 'env': ('MAILCHIMP_CLIENT_ID', 'MAILCHIMP_CLIENT_SECRET'),
        'authorize': 'https://login.mailchimp.com/oauth2/authorize', 'params': {},
        'exchange': _mailchimp_exchange, 'console': 'https://admin.mailchimp.com/account/oauth2/',
        'steps': ['Dans Mailchimp : Profil › Extras › Applications enregistrées › « Register An App ».',
                  'Indiquez l’URL de redirection ci-dessous.',
                  'Copiez Client ID et Client Secret.'],
    },
    'hubspot': {
        'name': 'HubSpot', 'env': ('HUBSPOT_CLIENT_ID', 'HUBSPOT_CLIENT_SECRET'),
        'authorize': 'https://app.hubspot.com/oauth/authorize',
        'params': {'scope': 'crm.objects.contacts.read crm.objects.contacts.write crm.objects.deals.read crm.objects.deals.write'},
        'exchange': _hubspot_exchange, 'refresh': _hubspot_refresh, 'console': 'https://developers.hubspot.com/',
        'steps': ['Créez un compte développeur HubSpot puis une app publique.',
                  'Onglet Auth : URL de redirection ci-dessous et scopes contacts / transactions (lecture et écriture).',
                  'Copiez Client ID et Client secret.'],
    },
    'quickbooks': {
        'name': 'QuickBooks', 'env': ('QUICKBOOKS_CLIENT_ID', 'QUICKBOOKS_CLIENT_SECRET'),
        'authorize': 'https://appcenter.intuit.com/connect/oauth2', 'params': {'scope': 'com.intuit.quickbooks.accounting'},
        'exchange': _quickbooks_exchange, 'refresh': _quickbooks_refresh, 'query': True,
        'console': 'https://developer.intuit.com/app/developer/dashboard',
        'steps': ['Créez une app « QuickBooks Online and Payments » sur developer.intuit.com (scope Accounting).',
                  'Keys & credentials (Production) : ajoutez l’URL de redirection ci-dessous.',
                  'Copiez Client ID et Client Secret. Avec les clés de développement, ajoutez aussi QUICKBOOKS_ENVIRONMENT=sandbox sur le serveur.'],
    },
    # Trello : flux à jeton (pas de secret) ; le jeton revient dans le fragment de l'URL de retour.
    'trello': {
        'name': 'Trello', 'env': ('TRELLO_API_KEY',), 'console': 'https://trello.com/power-ups/admin',
        'steps': ['Créez une intégration dans le portail des Power-Ups Trello.',
                  'Onglet « Clé API » : ajoutez l’origine autorisée ci-dessous (adresse du site).',
                  'Copiez la clé API.'],
    },
}


def configured(key):
    spec = OAUTH.get(key)
    return bool(spec) and all(_env(name) for name in spec['env'])


def authorize_url(key, state, redirect_uri):
    spec = OAUTH[key]
    if key == 'trello':
        return_url = f"{redirect_uri}?{urllib.parse.urlencode({'state': state})}"
        return 'https://trello.com/1/authorize?' + urllib.parse.urlencode({
            'expiration': 'never', 'name': 'Billio', 'scope': 'read,write', 'response_type': 'token',
            'key': _env('TRELLO_API_KEY'), 'return_url': return_url, 'callback_method': 'fragment',
        })
    params = dict(spec['params'], client_id=_env(spec['env'][0]), redirect_uri=redirect_uri,
                  response_type='code', state=state)
    return f"{spec['authorize']}?{urllib.parse.urlencode(params)}"


def exchange(key, code, redirect_uri, query=None):
    """Code d'autorisation → configuration à enregistrer (même clés que le formulaire manuel).

    `query` : paramètres de l'URL de retour, pour les outils qui y ajoutent une donnée (realmId de QuickBooks).
    """
    spec = OAUTH[key]
    if spec.get('query'):
        return spec['exchange'](spec, code, redirect_uri, query or {})
    return spec['exchange'](spec, code, redirect_uri)


def trello_config(token):
    token = (token or '').strip()
    if not token or not token.isalnum() or len(token) > 100:
        raise ProviderError('Jeton Trello manquant ou invalide.')
    return {'api_key': _env('TRELLO_API_KEY'), 'token': token, 'account': 'Trello'}


def fresh_config(instance):
    """Configuration avec un jeton valide : renouvelle (et enregistre) un jeton OAuth expiré."""
    config = dict(instance.config or {})
    spec = OAUTH.get(instance.connector.key) or {}
    refresh = spec.get('refresh')
    if refresh and config.get('refresh_token') and int(config.get('token_expiry') or 0) <= timezone.now().timestamp():
        config.update(refresh(config))
        instance.config = config
        instance.save(update_fields=['config', 'updated_at'])
    return config


# --------------------------------------------------------------------------- page d'autorisation

# Textes de la page « Autoriser Billio » (avant de partir chez l'outil) : ce que Billio pourra faire,
# ce qui se passe chez l'outil, et ce qu'on peut faire ensuite. En mots simples, sans jargon.
CONSENT = {
    'slack': {
        'can': ['Publier des messages dans le canal que vous choisissez (facture payée, devis signé…).'],
        'at_tool': 'Slack vous demande de choisir un canal : prenez celui où vous voulez recevoir les alertes.',
        'next': 'Créez une automatisation « Envoyer un message » pour être prévenu dans Slack.',
    },
    'notion': {
        'can': ['Créer et mettre à jour des pages dans les pages Notion que vous partagez avec Billio.'],
        'at_tool': 'Notion vous demande quelles pages partager : cochez celles où Billio pourra écrire.',
        'next': 'Exportez vos clients, factures ou projets vers Notion depuis le panneau Notion.',
    },
    'mailchimp': {
        'can': ['Ajouter vos clients à vos listes d’abonnés Mailchimp.'],
        'at_tool': 'Connectez-vous à Mailchimp puis cliquez sur « Allow ».',
        'next': 'Créez une automatisation pour inscrire chaque nouveau client à votre liste.',
    },
    'hubspot': {
        'can': ['Créer et mettre à jour vos contacts et vos transactions HubSpot.'],
        'at_tool': 'Choisissez votre compte HubSpot puis cliquez sur « Connecter l’app ».',
        'next': 'Créez une automatisation pour envoyer vos nouveaux clients et devis dans HubSpot.',
    },
    'quickbooks': {
        'can': ['Créer vos clients, factures et paiements dans l’entreprise QuickBooks que vous choisissez.',
                'Lire le nom de l’entreprise et ses codes de TVA pour remplir les factures correctement.'],
        'at_tool': 'Identifiez-vous chez Intuit, choisissez votre entreprise QuickBooks puis cliquez sur « Connecter ».',
        'next': 'Utilisez les recettes « Facture envoyée → QuickBooks » et « Paiement reçu → QuickBooks ».',
    },
    'trello': {
        'can': ['Créer des cartes dans les tableaux Trello de votre compte.'],
        'at_tool': 'Connectez-vous à Trello puis cliquez sur « Autoriser ».',
        'next': 'Créez une automatisation pour ajouter une carte Trello à chaque nouveau projet.',
    },
    'google-drive': {
        'name': 'Google Drive',
        'can': ['Enregistrer vos factures et devis en PDF dans un dossier « Billio » de votre Drive.',
                'Ouvrir les fichiers que vous choisissez pour les importer dans Billio.'],
        'at_tool': 'Choisissez votre compte Google puis cliquez sur « Continuer ».',
        'next': 'Envoyez une facture vers Drive depuis son aperçu, ou exportez vos tableaux.',
    },
}

# Valable pour tous les outils : ce qui rassure avant de cliquer.
CONSENT_NEVER = [
    'Billio ne voit jamais votre mot de passe : vous vous connectez directement chez l’outil.',
    'Billio n’agit que lorsque vous le demandez ou qu’une de vos automatisations le prévoit.',
    'Vous pouvez déconnecter l’outil à tout moment, depuis Billio ou depuis l’outil.',
]


def consent(key):
    """Textes de la page d'autorisation, ou None si l'outil n'a pas de connexion en un clic."""
    if key not in CONSENT:
        return None
    name = CONSENT[key].get('name') or OAUTH[key]['name']
    return dict(CONSENT[key], key=key, name=name, never=CONSENT_NEVER)
