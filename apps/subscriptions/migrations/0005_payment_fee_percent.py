"""Commission Billio sur les paiements en ligne (Stripe Connect) : 0,5 % Free / Starter / Pro, 0 % Business / Agency."""
from django.db import migrations

FEES = {'free': 0.5, 'starter': 0.5, 'pro': 0.5, 'business': 0, 'agency': 0}


def set_fees(apps, schema_editor):
    Plan = apps.get_model('subscriptions', 'Plan')
    for plan in Plan.objects.filter(code__in=FEES):
        plan.limits = {**(plan.limits or {}), 'payment_fee_percent': FEES[plan.code]}
        plan.save(update_fields=['limits'])


def unset_fees(apps, schema_editor):
    Plan = apps.get_model('subscriptions', 'Plan')
    for plan in Plan.objects.filter(code__in=FEES):
        (plan.limits or {}).pop('payment_fee_percent', None)
        plan.save(update_fields=['limits'])


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0004_seed_plans'),
    ]

    operations = [
        migrations.RunPython(set_fees, unset_fees),
    ]
