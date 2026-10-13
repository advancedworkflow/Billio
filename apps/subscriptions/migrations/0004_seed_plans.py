"""
Grille tarifaire de lancement (validée le 12/10/2026). Ensuite, prix, limites et options
se modifient dans l'admin (Forfaits) ; les clés sont décrites dans apps/subscriptions/entitlements.py.
"""
from decimal import Decimal

from django.db import migrations

GO = 1024  # Mo

PLANS = [
    {
        'code': 'free', 'name': 'Free', 'price_monthly': Decimal('0'), 'order': 0,
        'tagline': "Pour démarrer et envoyer ses premières factures.",
        'limits': {'documents_per_month': 10, 'clients': 15, 'projects': 3, 'users': 1,
                   'storage_mb': 500, 'integrations': 2, 'workflows': 1},
        'features': {'recurring': True, 'deposits': True, 'manual_payments': True, 'reminders': False,
                     'quote_signature': False, 'portal': 'basic', 'booking': False, 'time_tracking': 'none',
                     'time_billing': False, 'api': False, 'inbound_webhooks': False, 'facturx': False,
                     'multi_org': False},
    },
    {
        'code': 'starter', 'name': 'Starter', 'price_monthly': Decimal('9'), 'order': 1,
        'tagline': "Pour travailler au quotidien : relances, signature, portail.",
        'limits': {'documents_per_month': 50, 'clients': 100, 'projects': 10, 'users': 1,
                   'storage_mb': 5 * GO, 'integrations': 5, 'workflows': 5},
        'features': {'recurring': True, 'deposits': True, 'manual_payments': True, 'reminders': True,
                     'quote_signature': True, 'portal': 'full', 'booking': True, 'time_tracking': 'basic',
                     'time_billing': False, 'api': False, 'inbound_webhooks': False, 'facturx': False,
                     'multi_org': False},
    },
    {
        'code': 'pro', 'name': 'Pro', 'price_monthly': Decimal('19'), 'order': 2, 'is_popular': True,
        'tagline': "Le forfait complet du freelance : temps passé, Factur-X, automatisations.",
        'limits': {'documents_per_month': None, 'clients': 300, 'projects': 30, 'users': 1,
                   'storage_mb': 20 * GO, 'integrations': 10, 'workflows': 15},
        'features': {'recurring': True, 'deposits': True, 'manual_payments': True, 'reminders': True,
                     'quote_signature': True, 'portal': 'full', 'booking': True, 'time_tracking': 'full',
                     'time_billing': True, 'api': False, 'inbound_webhooks': False, 'facturx': True,
                     'multi_org': False},
    },
    {
        'code': 'business', 'name': 'Business', 'price_monthly': Decimal('39'), 'order': 3,
        'tagline': "Pour les petites équipes : collaboration, rôles, API et webhooks.",
        'limits': {'documents_per_month': None, 'clients': 1000, 'projects': 100, 'users': 5,
                   'storage_mb': 100 * GO, 'integrations': 25, 'workflows': 50},
        'features': {'recurring': True, 'deposits': True, 'manual_payments': True, 'reminders': True,
                     'quote_signature': True, 'portal': 'full', 'booking': True, 'time_tracking': 'full',
                     'time_billing': True, 'api': True, 'inbound_webhooks': True, 'facturx': True,
                     'multi_org': False},
    },
    {
        'code': 'agency', 'name': 'Agency', 'price_monthly': Decimal('79'), 'order': 4,
        'tagline': "Pour les agences : plusieurs organisations et gros volumes.",
        'limits': {'documents_per_month': None, 'clients': None, 'projects': None, 'users': 15,
                   'storage_mb': 250 * GO, 'integrations': 50, 'workflows': 150},
        'features': {'recurring': True, 'deposits': True, 'manual_payments': True, 'reminders': True,
                     'quote_signature': True, 'portal': 'full', 'booking': True, 'time_tracking': 'full',
                     'time_billing': True, 'api': True, 'inbound_webhooks': True, 'facturx': True,
                     'multi_org': True},
    },
]


def seed(apps, schema_editor):
    Plan = apps.get_model('subscriptions', 'Plan')
    for data in PLANS:
        Plan.objects.update_or_create(code=data['code'], defaults={k: v for k, v in data.items() if k != 'code'})


def unseed(apps, schema_editor):
    apps.get_model('subscriptions', 'Plan').objects.filter(code__in=[p['code'] for p in PLANS]).delete()


class Migration(migrations.Migration):
    dependencies = [('subscriptions', '0003_plans_and_subscriptions')]
    operations = [migrations.RunPython(seed, unseed)]
