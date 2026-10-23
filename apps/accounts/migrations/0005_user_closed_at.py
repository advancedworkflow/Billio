from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_user_two_factor'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='closed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
