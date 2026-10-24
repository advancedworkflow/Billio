"""Ajoute le connecteur QuickBooks Online (connexion OAuth Intuit)."""
from django.db import migrations


def forwards(apps, schema_editor):
    apps.get_model('integrations', 'Connector').objects.update_or_create(key='quickbooks', defaults={
        'name': 'QuickBooks', 'category': 'accounting', 'icon': 'calculator', 'order': 13, 'requires_oauth': True,
        'is_active': True,
        'description': 'Envoyez vos clients, factures et paiements dans QuickBooks Online.',
    })


def backwards(apps, schema_editor):
    apps.get_model('integrations', 'Connector').objects.filter(key='quickbooks').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0005_zapier_connector'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
