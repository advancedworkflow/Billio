from django.db import migrations

CONNECTORS = [
    # key, name, category, icon, requires_oauth, order
    ('whatsapp', 'WhatsApp', 'communication', 'message-circle', False, 0),
    ('slack', 'Slack', 'communication', 'slack', True, 1),
    ('email', 'Email', 'communication', 'mail', False, 2),
    ('notion', 'Notion', 'productivity', 'notebook-text', True, 0),
    ('google-drive', 'Google Drive', 'productivity', 'hard-drive', True, 1),
    ('google-calendar', 'Google Calendar', 'productivity', 'calendar', True, 2),
    ('stripe', 'Stripe', 'payment', 'credit-card', False, 0),
    ('paypal', 'PayPal', 'payment', 'wallet', True, 1),
    ('mobile-money', 'Mobile Money', 'payment', 'smartphone', False, 2),
    ('webhooks', 'Webhooks', 'automation', 'webhook', False, 0),
    ('api', 'API', 'automation', 'code-2', False, 1),
    ('zapier', 'Zapier / Make', 'automation', 'zap', False, 2),
]


def seed_connectors(apps, schema_editor):
    Connector = apps.get_model('integrations', 'Connector')
    for key, name, category, icon, requires_oauth, order in CONNECTORS:
        Connector.objects.update_or_create(
            key=key,
            defaults={
                'name': name,
                'category': category,
                'icon': icon,
                'requires_oauth': requires_oauth,
                'order': order,
            },
        )


def remove_connectors(apps, schema_editor):
    Connector = apps.get_model('integrations', 'Connector')
    Connector.objects.filter(key__in=[c[0] for c in CONNECTORS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_connectors, remove_connectors),
    ]
