"""Ajoute le connecteur Telegram (bot) utilisé par l'action d'automatisation « Envoyer un message »."""
from django.db import migrations


def forwards(apps, schema_editor):
    Connector = apps.get_model('integrations', 'Connector')
    Connector.objects.update_or_create(
        key='telegram',
        defaults={
            'name': 'Telegram',
            'category': 'communication',
            'icon': 'send',
            'requires_oauth': False,
            'order': 3,
            'description': "Envoie des messages via un bot Telegram (jeton du bot + identifiant de conversation).",
        },
    )


def backwards(apps, schema_editor):
    apps.get_model('integrations', 'Connector').objects.filter(key='telegram').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0002_seed_connectors'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
