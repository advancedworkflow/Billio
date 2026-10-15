"""
Notifications envoyées au client (portail + email).

Chaque évènement de projet est une petite automatisation active par défaut :
- mineur : notification dans la cloche du portail client uniquement ;
- majeur : notification + email au client (avec le lien vers son espace).
L'organisation peut couper un évènement ou son email dans Paramètres → Notifications client.
"""
import logging

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

# (clé, libellé, description, majeur par défaut)
CLIENT_EVENTS = [
    ('phase_changed', "Changement d'étape du projet", "Le projet passe à une nouvelle étape (ex. Tournage → Post-production).", True),
    ('deliverable_submitted', 'Livrable à valider', 'Un livrable est envoyé au client pour validation.', True),
    ('document_shared', 'Document partagé', 'Un document (contrat, formulaire…) est envoyé au client.', True),
    ('meeting_scheduled', 'Réunion planifiée', 'Une réunion est planifiée sur un projet.', True),
    ('meeting_changed', 'Réunion modifiée ou annulée', "La date, le lieu ou le statut d'une réunion change.", True),
    ('milestone_completed', 'Jalon atteint', 'Un jalon du projet est marqué comme atteint.', False),
    ('file_shared', 'Nouveau fichier', 'Un fichier est ajouté au projet ou à un livrable.', False),
    ('comment_added', 'Nouveau commentaire', 'Vous répondez sur un livrable.', False),
]
EVENT_KEYS = {key for key, *_ in CLIENT_EVENTS}


def event_settings(organization):
    """Réglages effectifs : [{key, label, description, major, enabled, email}] (défauts complétés)."""
    saved = (organization.client_notification_settings or {}) if organization else {}
    rows = []
    for key, label, description, major in CLIENT_EVENTS:
        conf = saved.get(key) or {}
        rows.append({
            'key': key, 'label': label, 'description': description, 'major': major,
            'enabled': conf.get('enabled', True),
            'email': conf.get('email', major),
        })
    return rows


def portal_url(client, path=''):
    return f"{settings.SITE_URL}{path or reverse('dashboard:public-portal-overview', args=[client.portal_token])}"


def notify_client(event, client, title, message='', *, project=None, link=''):
    """
    Crée la notification du portail et, si l'évènement est réglé en « email », prévient
    le client par email. Ne lève jamais : une notification ne doit pas casser l'action.
    """
    if not client or event not in EVENT_KEYS:
        return None
    organization = client.organization
    conf = next(row for row in event_settings(organization) if row['key'] == event)
    if not conf['enabled']:
        return None

    from .models import ClientNotification
    if not link and project is not None:
        link = reverse('dashboard:public-portal-project-detail', args=[client.portal_token, project.id])
    notification = ClientNotification.objects.create(
        client=client, project=project, event=event, title=title[:200], message=message,
        link=link, is_major=conf['major'],
    )
    if conf['email'] and client.email:
        try:
            _send_email(notification, organization)
        except Exception:  # SMTP mal réglé, etc. : la notification du portail reste.
            logger.exception('Email de notification client non envoyé (%s)', notification.id)
    return notification


def _send_email(notification, organization):
    from apps.organizations.branded_email import branded_message

    client = notification.client
    url = portal_url(client, notification.link)
    body = (
        f"Bonjour {client.get_display_name()},\n\n"
        f"{notification.title}\n"
        + (f"{notification.message}\n" if notification.message else '')
    )
    branded_message(organization, subject=f"[{organization.name}] {notification.title}", body=body,
                    to=[client.email], button=('Ouvrir mon espace client', url)).send(fail_silently=False)
    notification.emailed_at = timezone.now()
    notification.save(update_fields=['emailed_at'])
