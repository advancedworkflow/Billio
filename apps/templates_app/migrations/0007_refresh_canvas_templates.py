"""Régénère les modèles libres de la galerie : tableau personnalisable, couleurs-variables, adresse du vendeur sur « Studio »."""
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.templates_app.canvas import CANVAS_TEMPLATES, template_fields

    MarketplaceTemplate = apps.get_model('templates_app', 'MarketplaceTemplate')
    for spec in CANVAS_TEMPLATES:
        MarketplaceTemplate.objects.update_or_create(slug=spec['slug'], defaults=template_fields(spec))


class Migration(migrations.Migration):
    dependencies = [('templates_app', '0006_canvas_templates')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
