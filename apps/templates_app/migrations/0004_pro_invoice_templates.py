"""Installe (ou met à jour) les modèles de facture / devis « pro » de la galerie."""
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.templates_app.pro_templates import PRO_TEMPLATES, template_fields

    MarketplaceTemplate = apps.get_model('templates_app', 'MarketplaceTemplate')
    for spec in PRO_TEMPLATES:
        MarketplaceTemplate.objects.update_or_create(slug=spec['slug'], defaults=template_fields(spec))


def backwards(apps, schema_editor):
    from apps.templates_app.pro_templates import PRO_TEMPLATES

    MarketplaceTemplate = apps.get_model('templates_app', 'MarketplaceTemplate')
    MarketplaceTemplate.objects.filter(slug__in=[s['slug'] for s in PRO_TEMPLATES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('templates_app', '0003_marketplacetemplate_templatereview_templatepurchase_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
