from django.db import migrations


WELCOME_HEADER = (
    '<h1>Bienvenue chez [Nom de votre entreprise]</h1>'
    '<p style="color:#6b7280;">Document de bienvenue — [Nom du client]</p>'
)
WELCOME_BODY = (
    '<p>Bonjour [Prénom],</p>'
    '<p>Nous sommes ravis de vous compter parmi nos clients. Ce document récapitule '
    'les informations essentielles pour bien démarrer avec nous.</p>'
    '<h3>Prochaines étapes</h3>'
    '<ul><li>Prise de contact avec votre interlocuteur dédié</li>'
    '<li>Validation du planning et des livrables</li>'
    '<li>Accès à votre espace client</li></ul>'
    '<p>N’hésitez pas à nous contacter pour toute question.</p>'
)
WELCOME_FOOTER = '<p>[Nom de votre entreprise] — [email] · [téléphone]</p>'

PROPOSAL_HEADER = '<h1>Proposition commerciale</h1><p style="color:#6b7280;">Réf. [Numéro] — [Nom du client]</p>'
PROPOSAL_BODY = (
    '<h3>Introduction</h3><p>Présentez brièvement votre entreprise et le contexte de la mission.</p>'
    '<h3>Compréhension du besoin &amp; périmètre</h3><p>Décrivez le besoin identifié et le périmètre proposé.</p>'
    '<h3>Conditions</h3><p>Détaillez les modalités (délais, tarifs, conditions de paiement).</p>'
    '<h3>Appel à l’action</h3><p>Invitez le client à valider la proposition.</p>'
)
PROPOSAL_FOOTER = '<p>Proposition valable 30 jours à compter de sa date d’émission.</p>'

CONTRACT_HEADER = '<h1>Contrat de prestation</h1><p style="color:#6b7280;">Entre les soussignés</p>'
CONTRACT_BODY = (
    '<p><strong>Entre :</strong> [Nom de votre entreprise], ci-après « le Prestataire »</p>'
    '<p><strong>Et :</strong> [Nom du client], ci-après « le Client »</p>'
    '<h3>Article 1 — Objet</h3><p>Décrivez l’objet du contrat.</p>'
    '<h3>Article 2 — Durée</h3><p>Le présent contrat est conclu pour une durée de [durée].</p>'
    '<h3>Article 3 — Conditions financières</h3><p>Détaillez les modalités de facturation et de paiement.</p>'
    '<h3>Article 4 — Résiliation</h3><p>Décrivez les conditions de résiliation.</p>'
)
CONTRACT_FOOTER = (
    '<table><tr><td>Pour le Prestataire<br><br><br>[Nom, date]</td>'
    '<td>Pour le Client<br><br><br>[Nom, date]</td></tr></table>'
)

EVENT_HEADER = '<h1 style="text-align:center;">Proposition d’événement</h1>'
EVENT_BODY = (
    '<h3>Résumé de la demande</h3>'
    '<p><strong>Titre de l’événement :</strong> [Titre]</p>'
    '<p><strong>Lieu et horaire :</strong> [Lieu, date et heure]</p>'
    '<p><strong>Proposé par :</strong> [Nom, fonction]</p>'
    '<p><strong>Nom de l’agence :</strong> [Agence, adresse]</p>'
    '<h3>Description de l’événement</h3>'
    '<p>Décrivez le contexte et les objectifs de l’événement.</p>'
    '<h3>Éléments requis</h3>'
    '<ul><li>Lecteur DVD</li><li>Vidéoprojecteur</li><li>Sonorisation</li></ul>'
    '<h3>Programme</h3>'
    '<p><strong>Jour 1 :</strong> Ouverture de l’événement</p>'
    '<p><strong>Jour 2 :</strong> Ateliers et interventions</p>'
    '<p><strong>Jour 3 :</strong> Clôture</p>'
)
EVENT_FOOTER = '<p style="text-align:center;color:#6b7280;">[Nom de votre entreprise]</p>'


def seed_templates(apps, schema_editor):
    DocumentTemplate = apps.get_model('documents', 'DocumentTemplate')

    templates = [
        {
            'name': 'Document vierge',
            'category': 'general',
            'description': 'Page blanche, à construire librement.',
            'header_html': '', 'body_html': '', 'footer_html': '',
            'style_config': {
                'font_family': 'Inter, sans-serif', 'text_color': '#1f2937',
                'page_background_color': '#ffffff', 'background_image': '',
                'border_style': 'none', 'watermark_text': '', 'watermark_opacity': 0.08,
                'show_page_numbers': False,
            },
        },
        {
            'name': 'Document de bienvenue',
            'category': 'welcome',
            'description': 'Message d’accueil et prochaines étapes pour un nouveau client.',
            'header_html': WELCOME_HEADER, 'body_html': WELCOME_BODY, 'footer_html': WELCOME_FOOTER,
            'style_config': {
                'font_family': 'Inter, sans-serif', 'text_color': '#1f2937',
                'page_background_color': '#ffffff', 'background_image': '',
                'border_style': 'none', 'watermark_text': '', 'watermark_opacity': 0.08,
                'show_page_numbers': False,
            },
        },
        {
            'name': 'Proposition commerciale',
            'category': 'proposal',
            'description': 'Structure narrative classique : introduction, besoin, conditions, appel à l’action.',
            'header_html': PROPOSAL_HEADER, 'body_html': PROPOSAL_BODY, 'footer_html': PROPOSAL_FOOTER,
            'style_config': {
                'font_family': 'Georgia, serif', 'text_color': '#1f2937',
                'page_background_color': '#ffffff', 'background_image': '',
                'border_style': 'none', 'watermark_text': '', 'watermark_opacity': 0.08,
                'show_page_numbers': True,
            },
        },
        {
            'name': 'Contrat',
            'category': 'contract',
            'description': 'Trame de contrat de prestation (parties, objet, durée, conditions, signatures).',
            'header_html': CONTRACT_HEADER, 'body_html': CONTRACT_BODY, 'footer_html': CONTRACT_FOOTER,
            'style_config': {
                'font_family': 'Georgia, serif', 'text_color': '#1f2937',
                'page_background_color': '#ffffff', 'background_image': '',
                'border_style': 'none', 'watermark_text': '', 'watermark_opacity': 0.08,
                'show_page_numbers': True,
            },
        },
        {
            'name': 'Proposition événementielle (bordée)',
            'category': 'proposal',
            'description': 'Mise en page encadrée pour une proposition d’événement.',
            'header_html': EVENT_HEADER, 'body_html': EVENT_BODY, 'footer_html': EVENT_FOOTER,
            'style_config': {
                'font_family': 'Georgia, serif', 'text_color': '#1f2937',
                'page_background_color': '#ffffff', 'background_image': '',
                'border_style': 'framed', 'watermark_text': '', 'watermark_opacity': 0.08,
                'show_page_numbers': False,
            },
        },
    ]

    for data in templates:
        DocumentTemplate.objects.get_or_create(organization=None, name=data['name'], defaults=data)


def unseed_templates(apps, schema_editor):
    DocumentTemplate = apps.get_model('documents', 'DocumentTemplate')
    DocumentTemplate.objects.filter(organization__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_templates, unseed_templates),
    ]
