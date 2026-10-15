"""
Connexion « Se connecter avec… » (OAuth 2.0) pour les outils qui la proposent.

L'utilisateur clique, s'identifie chez l'outil, autorise Billio et revient connecté : plus de clé à
copier. Le résultat est rangé dans la même configuration que le formulaire manuel (webhook_url,
access_token, api_key…), si bien que les tests de connexion, l'action « Envoyer un message » et
« Envoyer vers une app » fonctionnent sans changement.

Chaque outil n'est proposé que si l'application OAuth de Billio est déclarée sur le serveur
(variables <OUTIL>_CLIENT_ID / <OUTIL>_CLIENT_SECRET, ou TRELLO_API_KEY) ; sinon le formulaire
manuel reste le seul chemin. Google Drive garde son propre flux (plugin_views.google_*).
"""
import base64
import os
import urllib.parse

from django.utils import timezone

from . import providers
from .providers import ProviderError, http

# Domaines appelés pendant l'échange du code (en plus de la liste blanche des services).
providers.ALLOWED_HOSTS.update({'slack.com', 'login.mailchimp.com', 'api.hubapi.com'})


def _env(name):
    return os.getenv(name, '').strip()


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


def exchange(key, code, redirect_uri):
    """Code d'autorisation → configuration à enregistrer (même clés que le formulaire manuel)."""
    return OAUTH[key]['exchange'](OAUTH[key], code, redirect_uri)


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
