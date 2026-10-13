from django.db import migrations


INVOICE_RECAP_HEADER = '<h1>Récapitulatif de facturation</h1><p style="color:#6b7280;">[Nom de votre entreprise] — [Numéro]</p>'
INVOICE_RECAP_BODY = (
    '<p>Bonjour [Nom du client],</p>'
    '<p>Veuillez trouver ci-dessous le récapitulatif des prestations réalisées sur la période.</p>'
    '<table><thead><tr><th>Prestation</th><th>Quantité</th><th>Montant</th></tr></thead>'
    '<tbody><tr><td>[Description]</td><td>[Qté]</td><td>[Montant]</td></tr></tbody></table>'
    '<p>Merci de votre confiance.</p>'
)
INVOICE_RECAP_FOOTER = '<p>[Nom de votre entreprise] — [email] · [téléphone] — [IBAN]</p>'

REPORT_HEADER = '<h1 style="text-align:center;">Rapport mensuel</h1><p style="text-align:center;color:#6b7280;">[Mois / Année] — [Nom du client]</p>'
REPORT_BODY = (
    '<h3>Résumé</h3><p>Synthèse des actions menées ce mois-ci.</p>'
    '<h3>Indicateurs clés</h3>'
    '<table><thead><tr><th>Indicateur</th><th>Valeur</th><th>Évolution</th></tr></thead>'
    '<tbody><tr><td>[Indicateur]</td><td>[Valeur]</td><td>[Évolution]</td></tr></tbody></table>'
    '<h3>Prochaines étapes</h3><ul><li>[Étape 1]</li><li>[Étape 2]</li></ul>'
)
REPORT_FOOTER = '<p style="text-align:center;color:#6b7280;">[Nom de votre entreprise] — Rapport confidentiel</p>'


def seed_templates(apps, schema_editor):
    DocumentTemplate = apps.get_model('documents', 'DocumentTemplate')

    templates = [
        {
            'name': 'Récapitulatif de facturation',
            'category': 'general',
            'description': 'En-tête souligné, pied de page grisé avec les coordonnées bancaires.',
            'header_html': INVOICE_RECAP_HEADER, 'body_html': INVOICE_RECAP_BODY, 'footer_html': INVOICE_RECAP_FOOTER,
            'style_config': {
                'font_family': 'Inter, sans-serif', 'text_color': '#1f2937',
                'page_background_color': '#ffffff', 'background_image': '',
                'border_style': 'none', 'watermark_text': '', 'watermark_opacity': 0.08,
                'show_page_numbers': True, 'page_format': 'A4', 'page_orientation': 'portrait',
                'page_margin': 48, 'border_spacing': 12,
                'header_style': 'line', 'footer_style': 'shaded',
            },
        },
        {
            'name': 'Rapport mensuel',
            'category': 'general',
            'description': 'En-tête centré, pied de page discret — mise en page synthétique pour un suivi périodique.',
            'header_html': REPORT_HEADER, 'body_html': REPORT_BODY, 'footer_html': REPORT_FOOTER,
            'style_config': {
                'font_family': 'Inter, sans-serif', 'text_color': '#1f2937',
                'page_background_color': '#ffffff', 'background_image': '',
                'border_style': 'none', 'watermark_text': '', 'watermark_opacity': 0.08,
                'show_page_numbers': True, 'page_format': 'A4', 'page_orientation': 'portrait',
                'page_margin': 48, 'border_spacing': 12,
                'header_style': 'centered', 'footer_style': 'centered',
            },
        },
    ]

    for data in templates:
        DocumentTemplate.objects.get_or_create(organization=None, name=data['name'], defaults=data)


def unseed_templates(apps, schema_editor):
    DocumentTemplate = apps.get_model('documents', 'DocumentTemplate')
    DocumentTemplate.objects.filter(
        organization__isnull=True, name__in=['Récapitulatif de facturation', 'Rapport mensuel']
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0002_seed_system_templates'),
    ]

    operations = [
        migrations.RunPython(seed_templates, unseed_templates),
    ]
