"""Installe (ou met à jour) les modèles en mise en page libre de la galerie (canvas.CANVAS_TEMPLATES)."""
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.templates_app.canvas import CANVAS_TEMPLATES, template_fields

    MarketplaceTemplate = apps.get_model('templates_app', 'MarketplaceTemplate')
    for spec in CANVAS_TEMPLATES:
        MarketplaceTemplate.objects.update_or_create(slug=spec['slug'], defaults=template_fields(spec))


def backwards(apps, schema_editor):
    from apps.templates_app.canvas import CANVAS_TEMPLATES

    MarketplaceTemplate = apps.get_model('templates_app', 'MarketplaceTemplate')
    MarketplaceTemplate.objects.filter(slug__in=[s['slug'] for s in CANVAS_TEMPLATES]).delete()


class Migration(migrations.Migration):
    dependencies = [('templates_app', '0005_remove_placeholder_templates')]
    operations = [migrations.RunPython(forwards, backwards)]
