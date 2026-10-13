"""Renomme en français les moyens de paiement manuels créés avec les anciens libellés anglais."""
from django.db import migrations

LABELS = {
    'Bank Transfer': 'Virement bancaire',
    'Credit Card': 'Carte bancaire',
    'Check': 'Chèque',
    'Cash': 'Espèces',
}


def forwards(apps, schema_editor):
    PaymentMethod = apps.get_model('payments', 'PaymentMethod')
    for english, french in LABELS.items():
        PaymentMethod.objects.filter(name=f'Paiement manuel — {english}').update(name=f'Paiement manuel — {french}')
        PaymentMethod.objects.filter(name=english).update(name=french)


def backwards(apps, schema_editor):
    PaymentMethod = apps.get_model('payments', 'PaymentMethod')
    for english, french in LABELS.items():
        PaymentMethod.objects.filter(name=f'Paiement manuel — {french}').update(name=f'Paiement manuel — {english}')


class Migration(migrations.Migration):
    dependencies = [('payments', '0002_french_choice_labels')]
    operations = [migrations.RunPython(forwards, backwards)]
