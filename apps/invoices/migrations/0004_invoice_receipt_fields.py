from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0003_invoice_invoice_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='receipt_generated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='invoice',
            name='receipt_number',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
