"""
Emails aux couleurs de l'organisation : logo, couleur, bannière, bouton d'action, signature.

- `branded_message(...)` : EmailMultiAlternatives (texte + HTML) envoyé par le SMTP de
  l'organisation s'il est connecté. Utilisé par tous les emails envoyés aux clients.
- `render_kind(...)` : sujet et texte d'un email type (facture, avoir, devis, relances),
  personnalisables dans « Personnalisation des emails » ; {{variables}} remplacées.

Les images sont des liens absolus vers les fichiers publiés (/media/ ou S3) : rien n'est
joint au message, les clients mail les chargent à l'ouverture.
"""
import re

from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import escape, linebreaks, urlize
from django.utils.safestring import mark_safe

DEFAULT_COLOR = '#6d28d9'
HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

# Variables proposées dans l'éditeur (toutes ne s'appliquent pas à tous les emails).
VARIABLES = [
    ('client', 'Client'), ('numero', 'N° du document'), ('montant', 'Montant'), ('echeance', "Date d'échéance"),
    ('jours_retard', 'Jours de retard'), ('entreprise', 'Votre entreprise'),
]

# type → (libellé, sujet par défaut, texte par défaut, bouton)
EMAIL_KINDS = {
    'invoice': ("Envoi d'une facture", '[{{entreprise}}] Facture {{numero}}',
                "Bonjour {{client}},\n\nVeuillez trouver votre facture {{numero}} d'un montant de {{montant}}, "
                "à régler avant le {{echeance}}.\n\nMerci pour votre confiance.",
                'Consulter et payer la facture'),
    'credit_note': ("Envoi d'un avoir", '[{{entreprise}}] Avoir {{numero}}',
                    "Bonjour {{client}},\n\nVeuillez trouver ci-joint l'avoir {{numero}} d'un montant de {{montant}}.",
                    ''),
    'quote': ("Envoi d'un devis", '[{{entreprise}}] Devis {{numero}}',
              "Bonjour {{client}},\n\nVoici notre devis {{numero}} d'un montant de {{montant}}, valable jusqu'au "
              "{{echeance}}.\n\nVous pouvez le consulter et l'accepter en ligne.",
              'Consulter le devis'),
    'reminder_j7': ('Relance J+7', 'Rappel : facture {{numero}} en attente de règlement',
                    "Bonjour {{client}},\n\nSauf erreur de notre part, la facture {{numero}} arrivée à échéance le "
                    "{{echeance}} reste impayée ({{montant}}, {{jours_retard}} jours de retard).\n\n"
                    "Si le paiement a déjà été effectué, merci de ne pas tenir compte de ce message.",
                    'Régler la facture'),
    'reminder_j14': ('Relance J+14', 'Second rappel : facture {{numero}}',
                     "Bonjour {{client}},\n\nSauf erreur de notre part, la facture {{numero}} arrivée à échéance le "
                     "{{echeance}} reste impayée ({{montant}}, {{jours_retard}} jours de retard).\n\n"
                     "Si le paiement a déjà été effectué, merci de ne pas tenir compte de ce message.",
                     'Régler la facture'),
    'reminder_j30': ('Relance J+30', 'Dernière relance : facture {{numero}}',
                     "Bonjour {{client}},\n\nSauf erreur de notre part, la facture {{numero}} arrivée à échéance le "
                     "{{echeance}} reste impayée ({{montant}}, {{jours_retard}} jours de retard).\n\n"
                     "Sans règlement de votre part, des pénalités de retard et l'indemnité forfaitaire de 40 € pour "
                     "frais de recouvrement pourront être appliquées.\n\n"
                     "Si le paiement a déjà été effectué, merci de ne pas tenir compte de ce message.",
                     'Régler la facture'),
}

SAMPLE_VARIABLES = {
    'client': 'Mme Durand', 'numero': 'INV-0042', 'montant': '1 440,00 EUR', 'echeance': '30/11/2026',
    'jours_retard': '7',
}


def money(amount, currency):
    return f"{amount:.2f} {currency}"


def fill(text, variables):
    for key, value in variables.items():
        text = text.replace('{{' + key + '}}', str(value)).replace('{{ ' + key + ' }}', str(value))
    return text


def kind_texts(organization, kind):
    """(sujet, texte) personnalisés de l'organisation, ou ceux par défaut."""
    _label, subject, body, _button = EMAIL_KINDS[kind]
    custom = (organization.email_templates or {}).get(kind) or {}
    return (custom.get('subject') or '').strip() or subject, (custom.get('body') or '').strip() or body


def render_kind(organization, kind, variables):
    """(sujet, texte, libellé du bouton) d'un email type, variables remplacées."""
    subject, body = kind_texts(organization, kind)
    values = dict(variables, entreprise=organization.name)
    return fill(subject, values), fill(body, values), EMAIL_KINDS[kind][3]


def brand_color(organization):
    for value in (organization.email_color, organization.primary_color):
        if value and HEX_RE.match(value) and value.lower() not in ('#ffffff', '#000000'):
            return value
    return DEFAULT_COLOR


def _absolute(file_field):
    if not file_field:
        return ''
    try:
        url = file_field.url
    except ValueError:
        return ''
    return url if url.startswith('http') else f"{settings.SITE_URL}{url}"


def signature_text(organization):
    return (organization.email_signature or '').strip() or f"— {organization.name}"


def render_html(organization, *, subject, body, button=None, preview=False):
    """HTML de l'email (tableaux et styles en ligne, compatibles avec les clients mail)."""
    color = brand_color(organization)
    address = ', '.join(p for p in (organization.address, ' '.join(x for x in (organization.postal_code, organization.city) if x)) if p)
    footer = ' · '.join(p for p in (organization.name, address, organization.email,
                                    f"SIRET {organization.registration_number}" if organization.registration_number else '') if p)
    return render_to_string('emails/branded.html', {
        'subject': subject,
        'color': color,
        'logo_url': _absolute(organization.logo),
        'banner_url': _absolute(organization.email_banner),
        'photo_url': _absolute(organization.email_signature_photo),
        'org_name': organization.name,
        'body_html': mark_safe(linebreaks(urlize(escape(body), nofollow=True))),
        'signature_html': mark_safe('<br>'.join(escape(line) for line in signature_text(organization).splitlines())),
        'button': button,
        'footer': footer,
        'preview': preview,
    })


def branded_message(organization, *, subject, body, to, button=None, reply_to=None, connection=None, from_email=None):
    """Email texte + HTML aux couleurs de l'organisation. `button` : (libellé, url) facultatif."""
    from django.core.mail import EmailMultiAlternatives
    from apps.integrations.providers import org_mail

    if connection is None and from_email is None:
        connection, from_email = org_mail(organization)
    text = body.rstrip()
    if button and button[1]:
        text += f"\n\n{button[0]} : {button[1]}"
    text += f"\n\n{signature_text(organization)}"
    if reply_to is None and organization.email:
        reply_to = [organization.email]
    message = EmailMultiAlternatives(subject=subject, body=text, from_email=from_email, to=list(to),
                                     connection=connection, reply_to=reply_to)
    message.attach_alternative(render_html(organization, subject=subject, body=body,
                                           button=button if button and button[1] else None), 'text/html')
    return message
