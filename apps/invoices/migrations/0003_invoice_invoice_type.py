from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('invoices', '0002_invoice_template'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='invoice_type',
            field=models.CharField(db_index=True, default='sale', max_length=20, choices=[('sale', 'Sale / Facture de vente'), ('purchase', "Purchase / Facture d'achat")]),
            preserve_default=False,
        ),
    ]

