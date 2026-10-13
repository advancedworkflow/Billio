import uuid

from django.db import migrations, models


def fill_tokens(apps, schema_editor):
    Organization = apps.get_model('organizations', 'Organization')
    for organization in Organization.objects.all():
        organization.booking_token = uuid.uuid4()
        organization.save(update_fields=['booking_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0010_trade_packs'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='booking_settings',
            field=models.JSONField(blank=True, default=dict),
        ),
        # Jeton unique par organisation : ajouté vide, rempli ligne par ligne, puis rendu unique.
        migrations.AddField(
            model_name='organization',
            name='booking_token',
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(fill_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='organization',
            name='booking_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
