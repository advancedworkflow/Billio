"""
Vérification de l'adresse email des comptes créés par l'inscription.

Le compte est utilisable tout de suite ; seule restriction tant que l'adresse n'est pas
confirmée : aucun email ne part vers les clients par le serveur d'envoi de Billio (factures,
devis, relances, automatisations). Une adresse inventée ne peut donc pas servir à envoyer du
spam au nom de Billio. Une organisation qui a connecté son propre SMTP n'est pas concernée.

Le lien de confirmation (email de bienvenue, ou « Renvoyer » dans le bandeau) est un jeton
signé valable 7 jours, lié à l'adresse : il ne vaut plus rien si l'adresse change.
"""
from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils import timezone

SALT = 'billio.accounts.email-verification'
MAX_AGE = 7 * 24 * 3600
BLOCKED_MESSAGE = "Confirmez votre adresse email pour envoyer des emails à vos clients : cliquez sur le lien reçu à l'inscription ou renvoyez-le depuis le bandeau en haut de page."  # noqa: E501


class UnverifiedSender(Exception):
    pass


def needs_verification(user):
    return bool(user and user.email_verification_required and not user.email_verified_at and not user.is_superuser)


def client_email_blocked(organization):
    """Message d'erreur si les emails de cette organisation vers ses clients sont bloqués, sinon ''."""
    if organization is None or not needs_verification(organization.owner):
        return ''
    from apps.integrations.models import ConnectionInstance
    own_smtp = ConnectionInstance.objects.filter(organization=organization, connector__key='email', status='connected').first()
    if own_smtp and (own_smtp.config or {}).get('host'):
        return ''
    return BLOCKED_MESSAGE


def make_token(user):
    return signing.dumps({'u': user.pk, 'e': user.email.lower()}, salt=SALT, compress=True)


def verification_url(user):
    return f"{settings.SITE_URL}{reverse('accounts:verify-email', args=[make_token(user)])}"


def verify_token(token):
    """Utilisateur confirmé par ce jeton, ou None (jeton invalide, expiré, adresse changée)."""
    from .models import User
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature:  # SignatureExpired en hérite
        return None
    user = User.objects.filter(pk=data.get('u'), is_active=True).first()
    if not user or user.email.lower() != data.get('e'):
        return None
    if not user.email_verified_at:
        user.email_verified_at = timezone.now()
        user.save(update_fields=['email_verified_at', 'updated_at'])
    return user


def send_verification_email(user):
    """Email avec le lien de confirmation. Renvoie False si l'envoi a échoué."""
    import logging

    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string

    support = getattr(settings, 'SUPPORT_EMAIL', '')
    context = {'user': user, 'verify_url': verification_url(user), 'site_url': settings.SITE_URL}
    message = EmailMultiAlternatives(
        subject='Confirmez votre adresse email', body=render_to_string('auth/verify_email.txt', context),
        to=[user.email], reply_to=[support] if support else None)
    message.attach_alternative(render_to_string('auth/verify_email.html', context), 'text/html')
    try:
        message.send()
        return True
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception('Email de confirmation non envoyé à %s', user.email)
        return False
