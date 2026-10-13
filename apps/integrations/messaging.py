"""
Envoi de messages via les connecteurs de messagerie de l'organisation (Slack,
Telegram, WhatsApp, et ceux du catalogue : Teams, Discord, Google Chat, SMS Twilio,
Make, n8n, IFTTT). Utilisé par l'action d'automatisation « Envoyer un message ».

Les hôtes appelés sont fixes (API officielles) ; seule l'URL de webhook Slack vient
de la configuration, et elle est restreinte à hooks.slack.com pour qu'une
automatisation ne puisse pas viser une adresse arbitraire (SSRF). Les canaux du
catalogue passent par providers.http et sa liste d'hôtes autorisés.
"""
import json
import re
import urllib.error
import urllib.request

from . import catalog
from .models import ConnectionInstance

CHANNELS = {
    'slack': 'Slack',
    'telegram': 'Telegram',
    'whatsapp': 'WhatsApp',
    **{key: catalog.META[key][0] for key in catalog.SENDERS},
}
# Canaux dont le destinataire est un numéro de téléphone (sinon : conversation par défaut / chat ID / aucun).
PHONE_CHANNELS = ('whatsapp',) + catalog.PHONE_CHANNELS
TIMEOUT_SECONDS = 8


class MessagingError(Exception):
    pass


def connected_channels(organization):
    """Clés des messageries connectées pour l'organisation (ex. ['slack', 'telegram'])."""
    if not organization:
        return []
    return list(
        ConnectionInstance.objects.filter(
            organization=organization, status='connected', connector__key__in=CHANNELS.keys(),
        ).values_list('connector__key', flat=True)
    )


def _post_json(url, payload, headers=None):
    data = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(url, data=data, method='POST', headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 (hôtes contrôlés)
            return response.status, response.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', 'replace')[:300]
        raise MessagingError(f'Erreur {exc.code} du service : {body}') from exc
    except urllib.error.URLError as exc:
        raise MessagingError(f'Service injoignable : {exc.reason}') from exc


def _digits(phone):
    return re.sub(r'\D', '', phone or '')


def send_message(organization, channel, text, *, recipient=''):
    """
    Envoie `text` sur `channel`. `recipient` : numéro (WhatsApp) ou chat ID (Telegram)
    qui remplace la conversation par défaut du connecteur. Retourne un court détail.
    """
    if channel not in CHANNELS:
        raise MessagingError('Messagerie inconnue.')
    instance = ConnectionInstance.objects.filter(
        organization=organization, connector__key=channel, status='connected',
    ).first()
    if not instance:
        raise MessagingError(f"{CHANNELS[channel]} n'est pas connecté (page Intégrations).")
    config = instance.config or {}
    text = (text or '').strip()[:3500]
    if not text:
        raise MessagingError('Le message est vide.')

    try:
        if channel in catalog.SENDERS:
            from .providers import ProviderError
            try:
                detail = catalog.SENDERS[channel](config, text, recipient)
            except ProviderError as exc:
                raise MessagingError(str(exc)) from None
            except KeyError:
                raise MessagingError(f'{CHANNELS[channel]} : configuration incomplète (page Intégrations).') from None
        elif channel == 'slack':
            url = config.get('webhook_url', '')
            if not url.startswith('https://hooks.slack.com/'):
                raise MessagingError("L'URL du webhook Slack doit commencer par https://hooks.slack.com/.")
            _post_json(url, {'text': text})
            detail = 'Message Slack envoyé'
        elif channel == 'telegram':
            token = config.get('access_token', '')
            chat_id = (recipient or config.get('chat_id', '')).strip()
            if not re.fullmatch(r'\d+:[\w-]+', token):
                raise MessagingError('Jeton de bot Telegram invalide.')
            if not re.fullmatch(r'-?\d+|@\w+', chat_id):
                raise MessagingError('Identifiant de conversation Telegram manquant ou invalide.')
            _post_json(f'https://api.telegram.org/bot{token}/sendMessage', {'chat_id': chat_id, 'text': text})
            detail = 'Message Telegram envoyé'
        else:  # whatsapp
            token = config.get('access_token', '')
            phone_number_id = config.get('phone_number_id', '')
            to = _digits(recipient)
            if not token or not phone_number_id.isdigit():
                raise MessagingError('WhatsApp : jeton ou Phone number ID manquant.')
            if len(to) < 8:
                raise MessagingError('WhatsApp : numéro du destinataire manquant ou invalide.')
            _post_json(
                f'https://graph.facebook.com/v19.0/{phone_number_id}/messages',
                {'messaging_product': 'whatsapp', 'to': to, 'type': 'text', 'text': {'body': text}},
                headers={'Authorization': f'Bearer {token}'},
            )
            detail = f'Message WhatsApp envoyé au +{to}'
    except MessagingError as exc:
        instance.last_error = str(exc)[:500]
        instance.save(update_fields=['last_error', 'updated_at'])
        raise

    if instance.last_error:
        instance.last_error = ''
        instance.save(update_fields=['last_error', 'updated_at'])
    return detail
