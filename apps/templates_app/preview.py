"""
Rendu d'aperçu des modèles de facture / devis avec des données d'exemple réalistes :
vignettes de la page Modèles et aperçu en direct de l'éditeur.
"""
import re
from datetime import timedelta
from decimal import Decimal

from django.template import Context, Template
from django.utils import timezone

# Polices proposées en mode simple (« Selon le modèle » = pas de surcharge).
FONT_CHOICES = {
    'Inter': ("'Inter', Arial, sans-serif", 'Inter:wght@400;500;600;700;800'),
    'Roboto': ("'Roboto', Arial, sans-serif", 'Roboto:wght@400;500;700'),
    'Montserrat': ("'Montserrat', Arial, sans-serif", 'Montserrat:wght@400;500;600;700;800'),
    'Lora': ("'Lora', Georgia, serif", 'Lora:wght@400;500;600;700'),
    'Newsreader': ("'Newsreader', Georgia, serif", 'Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600'),
    'Playfair Display': ("'Playfair Display', Georgia, serif", 'Playfair+Display:wght@400;600;700;800'),
    'Cormorant Garamond': ("'Cormorant Garamond', Georgia, serif", 'Cormorant+Garamond:wght@400;500;600;700'),
    'Poppins': ("'Poppins', Arial, sans-serif", 'Poppins:wght@400;500;600;700;800'),
    'Oswald': ("'Oswald', 'Arial Narrow', sans-serif", 'Oswald:wght@400;500;600;700'),
    'Arial': ('Arial, Helvetica, sans-serif', None),
}

# Balises qu'un modèle n'a pas à utiliser (lecture d'autres gabarits, dump du contexte).
_FORBIDDEN_TAGS = re.compile(r'{%\s*(include|extends|ssi|debug|load\s+(?!billio_format\b|static\b))', re.I)


class TemplateSourceError(ValueError):
    pass


def check_template_source(html):
    match = _FORBIDDEN_TAGS.search(html or '')
    if match:
        raise TemplateSourceError(f"Balise non autorisée dans un modèle : « {match.group(0)} ».")


def font_override_css(font_key):
    """CSS qui impose la police choisie en mode simple (vide si « Selon le modèle »)."""
    if font_key not in FONT_CHOICES:
        return ''
    stack, google = FONT_CHOICES[font_key]
    css = f"@import url('https://fonts.googleapis.com/css2?family={google}&display=swap');\n" if google else ''
    return css + f"body, body * {{ font-family: {stack} !important; }}\n"


def sample_context(organization=None, document_type='invoice'):
    """Données fictives cohérentes (lignes, totaux) + vraies infos de l'organisation si connue."""
    today = timezone.localdate()
    is_quote = document_type == 'quote'
    items = [
        {'name': 'Création du site vitrine', 'description': 'Design, intégration et mise en ligne — 5 pages',
         'quantity': Decimal('1'), 'unit_price': '2400.00', 'unit': 'forfait', 'tax_rate': '20', 'total': '2400.00'},
        {'name': 'Rédaction des contenus', 'description': '', 'quantity': Decimal('3'), 'unit_price': '350.00',
         'unit': 'page', 'tax_rate': '20', 'total': '1050.00'},
        {'name': 'Maintenance mensuelle', 'description': 'Mises à jour et sauvegardes', 'quantity': Decimal('1'),
         'unit_price': '90.00', 'unit': 'mois', 'tax_rate': '20', 'total': '90.00'},
    ]
    org = organization
    logo_url = ''
    if org is not None and getattr(org, 'logo', None):
        try:
            logo_url = org.logo.url
        except ValueError:
            logo_url = ''
    name = getattr(org, 'name', '') or 'Votre entreprise'
    return {
        'document_type': 'quote' if is_quote else 'invoice',
        'document_kind': 'Devis' if is_quote else 'Facture',
        'is_paid': not is_quote,  # aperçu : le tampon « Payé » reste visible
        'invoice_number': 'DEV-2026-0012' if is_quote else 'FAC-2026-0042',
        'document_number': 'DEV-2026-0012' if is_quote else 'FAC-2026-0042',
        'issue_date': today.strftime('%d/%m/%Y'),
        'due_date': (today + timedelta(days=30)).strftime('%d/%m/%Y'),
        'currency': getattr(org, 'default_currency', '') or 'USD',
        'subject': 'Refonte du site internet' if is_quote else '',
        'delivery_terms': 'Livraison sous 4 semaines après acceptation.' if is_quote else '',
        'notes': '',
        'items': items,
        'subtotal': '3540.00', 'tax_amount': '708.00', 'discount_amount': '0', 'total_amount': '4248.00',
        'organization_name': name,
        'organization_initial': name[:1].upper(),
        'organization_logo_url': logo_url,
        'organization_address': getattr(org, 'address', '') or '8 avenue de la République',
        'organization_postal_code': getattr(org, 'postal_code', '') or '69002',
        'organization_city': getattr(org, 'city', '') or 'Lyon',
        'organization_email': getattr(org, 'email', '') or 'contact@exemple.fr',
        'organization_phone': getattr(org, 'phone', '') or '',
        'organization_registration_number': getattr(org, 'registration_number', '') or '123 456 789 00012',
        'organization_tax_id': getattr(org, 'tax_id', '') or '',
        'organization_bank_name': getattr(org, 'bank_name', '') or 'Banque Exemple',
        'organization_iban': getattr(org, 'iban', '') or 'FR76 3000 6000 0112 3456 7890 189',
        'organization_bic_swift': getattr(org, 'bic_swift', '') or 'AGRIFRPP',
        'organization_payment_instructions': getattr(org, 'payment_instructions', '') or '',
        'client_name': 'Atelier Lumière SARL',
        'client_address': '12 rue des Arts\n75011 Paris',
        'client_email': 'compta@atelier-lumiere.fr',
        'client_phone': '',
        'client_registration_number': '987 654 321 00021',
        'client_tax_id': '',
    }


def render_preview(html, css, defaults=None, organization=None, document_type='invoice', font=None):
    """Document HTML complet (pour iframe srcdoc ou réponse directe)."""
    check_template_source(html)
    from apps.organizations.currencies import activate
    activate(organization)
    from .models import apply_billing_texts
    context = apply_billing_texts(dict(defaults or {}), organization)
    context.update(sample_context(organization, document_type))
    body = Template(html or '').render(Context(context))
    try:
        rendered_css = Template(css or '').render(Context(dict(defaults or {})))
    except Exception:  # CSS sans balises valides : tel quel
        rendered_css = css or ''
    return (
        '<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<style>{font_override_css(font)}html,body{{margin:0;background:#fff;}}*{{box-sizing:border-box;}}{rendered_css}</style>'
        f'</head><body>{body}</body></html>'
    )


def is_placeholder(template):
    """Modèle vide créé automatiquement (« Invoice / Default template »)."""
    from .models import InvoiceTemplate
    html = (template.html_structure or '').strip()
    return not html or html == InvoiceTemplate._meta.get_field('html_structure').default or 'Default template</p>' in html
