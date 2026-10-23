"""
Fermeture du compte (CGU § 9, RGPD art. 17).

1. `close_account` : l'abonnement Stripe est résilié tout de suite (sans remboursement de la
   période en cours), le compte est désactivé (toutes ses sessions et jetons d'API cessent de
   fonctionner) et ses organisations sont mises en pause : plus de relances ni de factures
   récurrentes envoyées aux clients.
2. Pendant `ACCOUNT_DELETION_GRACE_DAYS` jours (30 par défaut), le support peut rouvrir le
   compte (Administration › Comptes › Réactiver) en cas d'erreur.
3. Ensuite `purge_closed_accounts` (lancé par `run_automations`) efface le compte, les
   organisations dont il est propriétaire avec toutes leurs données, et les fichiers déposés.
   Les CGU promettent un effacement sous 90 jours : le délai doit rester en dessous.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def grace_days():
    return int(getattr(settings, 'ACCOUNT_DELETION_GRACE_DAYS', 30))


def deletion_date(user):
    return user.closed_at + timedelta(days=grace_days()) if user.closed_at else None


def shared_organizations(user):
    """Organisations du compte où d'autres personnes travaillent : elles disparaîtront aussi."""
    from apps.organizations.models import OrganizationMember
    rows = []
    for org in user.owned_organizations.all().order_by('name'):
        others = OrganizationMember.objects.filter(organization=org).exclude(user=user).count()
        if others:
            rows.append({'organization': org, 'members': others})
    return rows


def close_account(user):
    """Ferme le compte. Lève BillingError si l'abonnement Stripe n'a pas pu être résilié."""
    from rest_framework.authtoken.models import Token

    from apps.subscriptions import billing
    from apps.subscriptions.models import Subscription

    subscription = Subscription.objects.filter(user=user).first()
    if subscription and subscription.stripe_subscription_id and subscription.status not in ('canceled', 'incomplete_expired'):
        billing.cancel_now(subscription)
    with transaction.atomic():
        user.is_active = False
        user.closed_at = timezone.now()
        user.save(update_fields=['is_active', 'closed_at', 'updated_at'])
        user.owned_organizations.update(is_active=False)
        Token.objects.filter(user=user).delete()
    _send_closure_email(user)


def reopen_account(user):
    """Annule une fermeture pendant le délai de grâce (le forfait payant n'est pas rétabli)."""
    with transaction.atomic():
        user.is_active = True
        user.closed_at = None
        user.save(update_fields=['is_active', 'closed_at', 'updated_at'])
        user.owned_organizations.update(is_active=True)


def purge_user(user):
    """Efface le compte, ses organisations (avec toutes leurs données) et les fichiers déposés."""
    from django.core.files.storage import default_storage

    from apps.invoices.models import Invoice, Quote

    from .personal_data import owned_querysets, stored_files

    organizations = list(user.owned_organizations.all())
    files = stored_files(owned_querysets(user, organizations))
    with transaction.atomic():
        for org in organizations:
            # Liens PROTECT (avoir → facture, facture de situation → devis, devis → modèle) :
            # on efface dans l'ordre plutôt que de laisser la cascade les refuser.
            Invoice.objects.filter(organization=org, credited_invoice__isnull=False).delete()
            Invoice.objects.filter(organization=org).delete()
            Quote.objects.filter(organization=org).delete()
            org.delete()
        user.delete()
    for name in files:
        try:
            default_storage.delete(name)
        except OSError:
            logger.warning('Fichier %s non supprimé du stockage.', name)


def purge_closed_accounts(now=None):
    """Efface les comptes fermés depuis plus que le délai de grâce. Renvoie le nombre effacé."""
    limit = (now or timezone.now()) - timedelta(days=grace_days())
    count = 0
    for user in get_user_model().objects.filter(closed_at__isnull=False, closed_at__lte=limit, is_active=False):
        try:
            purge_user(user)
            count += 1
        except Exception:  # noqa: BLE001 — un compte en échec ne bloque pas les autres
            logger.exception('Effacement du compte fermé %s en échec.', user.pk)
    return count


def _send_closure_email(user):
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string

    support = getattr(settings, 'SUPPORT_EMAIL', '')
    context = {'user': user, 'deletion_date': deletion_date(user), 'support_email': support, 'site_url': settings.SITE_URL}
    message = EmailMultiAlternatives(
        subject='Votre compte Billio est fermé', body=render_to_string('auth/account_closed_email.txt', context),
        to=[user.email], reply_to=[support] if support else None)
    message.attach_alternative(render_to_string('auth/account_closed_email.html', context), 'text/html')
    try:
        message.send()
    except Exception:  # noqa: BLE001 — SMTP indisponible : la fermeture reste faite
        logger.exception('Email de fermeture non envoyé à %s', user.email)
