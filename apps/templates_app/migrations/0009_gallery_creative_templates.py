"""Ajoute à la galerie les modèles créatifs (bandeaux, vagues, facettes, pages colorées…) et régénère les autres."""
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.templates_app.canvas import CANVAS_TEMPLATES, template_fields

    MarketplaceTemplate = apps.get_model('templates_app', 'MarketplaceTemplate')
    for spec in CANVAS_TEMPLATES:
        MarketplaceTemplate.objects.update_or_create(slug=spec['slug'], defaults=template_fields(spec))


class Migration(migrations.Migration):
    dependencies = [('templates_app', '0008_template_asset')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
