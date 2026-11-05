"""Signature électronique de documents (apps.signatures) : incluse à partir du forfait Starter."""
from django.db import migrations

ESIGN = {'free': False, 'starter': True, 'pro': True, 'business': True, 'agency': True}


def set_esign(apps, schema_editor):
    Plan = apps.get_model('subscriptions', 'Plan')
    for plan in Plan.objects.filter(code__in=ESIGN):
        plan.features = {**(plan.features or {}), 'esign': ESIGN[plan.code]}
        plan.save(update_fields=['features'])


def unset_esign(apps, schema_editor):
    Plan = apps.get_model('subscriptions', 'Plan')
    for plan in Plan.objects.filter(code__in=ESIGN):
        (plan.features or {}).pop('esign', None)
        plan.save(update_fields=['features'])


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0005_payment_fee_percent'),
    ]

    operations = [
        migrations.RunPython(set_esign, unset_esign),
    ]
