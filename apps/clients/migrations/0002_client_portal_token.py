import uuid
from django.db import migrations, models


def assign_portal_tokens(apps, schema_editor):
    Client = apps.get_model('clients', 'Client')
    for client in Client.objects.all():
        client.portal_token = uuid.uuid4()
        client.save(update_fields=['portal_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='portal_token',
            field=models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=False),
        ),
        migrations.RunPython(assign_portal_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='client',
            name='portal_token',
            field=models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
