"""Ajoute le connecteur Zapier (webhook « Catch Hook ») utilisé par les automatisations."""
from django.db import migrations


def forwards(apps, schema_editor):
    apps.get_model('integrations', 'Connector').objects.update_or_create(key='zapier', defaults={
        'name': 'Zapier', 'category': 'automation', 'icon': 'zap', 'order': 9, 'requires_oauth': False, 'is_active': True,
        'description': 'Déclenchez vos Zaps depuis les automatisations Billio et reliez Billio à plus de 7 000 applications.',
    })


def backwards(apps, schema_editor):
    apps.get_model('integrations', 'Connector').objects.filter(key='zapier').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0004_catalog_50_tools'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
