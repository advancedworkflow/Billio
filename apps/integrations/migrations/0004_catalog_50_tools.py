"""Ajoute 50 outils au catalogue des intégrations (voir apps/integrations/catalog.py) et 3 catégories."""
from django.db import migrations, models

CONNECTORS = [
    # key, name, category, icon, order, description
    ('microsoft-teams', 'Microsoft Teams', 'communication', 'users', 10, 'Publiez des alertes dans un canal Teams (paiement reçu, devis accepté…).'),
    ('discord', 'Discord', 'communication', 'message-square', 11, 'Publiez les évènements de Billio dans un salon de votre serveur Discord.'),
    ('google-chat', 'Google Chat', 'communication', 'messages-square', 12, 'Publiez des alertes dans un espace Google Chat (compte Google Workspace).'),
    ('twilio', 'SMS (Twilio)', 'communication', 'smartphone', 13, 'Envoyez des SMS depuis vos automatisations (rappel de rendez-vous, relance…).'),
    ('sendgrid', 'SendGrid', 'communication', 'mail', 14, "Vérifiez votre compte SendGrid (Twilio) pour l'envoi d'emails. Pour envoyer les emails de Billio par ce service, utilisez aussi le plugin Email avec ses réglages SMTP."),
    ('mailgun', 'Mailgun', 'communication', 'mail', 15, "Vérifiez votre compte Mailgun et ses domaines d'envoi. Pour envoyer les emails de Billio par ce service, utilisez aussi le plugin Email avec ses réglages SMTP."),
    ('postmark', 'Postmark', 'communication', 'mail-check', 16, 'Vérifiez votre serveur Postmark pour des emails transactionnels fiables. Pour envoyer les emails de Billio par ce service, utilisez aussi le plugin Email avec ses réglages SMTP.'),
    ('crisp', 'Crisp', 'communication', 'message-circle-more', 17, 'Reliez le chat Crisp de votre site à Billio.'),
    ('trello', 'Trello', 'productivity', 'square-kanban', 10, 'Reliez vos tableaux Trello à votre compte Billio.'),
    ('asana', 'Asana', 'productivity', 'list-checks', 11, 'Reliez votre espace de travail Asana à Billio.'),
    ('clickup', 'ClickUp', 'productivity', 'circle-check-big', 12, 'Reliez votre espace ClickUp à Billio.'),
    ('monday', 'monday.com', 'productivity', 'layout-grid', 13, 'Reliez vos tableaux monday.com à Billio.'),
    ('airtable', 'Airtable', 'productivity', 'table', 14, 'Reliez vos bases Airtable à Billio.'),
    ('linear', 'Linear', 'productivity', 'git-pull-request-arrow', 15, 'Reliez votre espace Linear à Billio.'),
    ('jira', 'Jira', 'productivity', 'kanban', 16, 'Reliez votre site Jira (Atlassian Cloud) à Billio.'),
    ('github', 'GitHub', 'productivity', 'git-branch', 17, 'Reliez votre compte GitHub à Billio.'),
    ('calendly', 'Calendly', 'productivity', 'calendar-clock', 18, 'Reliez votre compte Calendly à Billio.'),
    ('toggl', 'Toggl Track', 'productivity', 'timer', 19, 'Reliez votre suivi du temps Toggl Track à Billio.'),
    ('harvest', 'Harvest', 'productivity', 'clock', 20, 'Reliez votre compte Harvest (temps et dépenses) à Billio.'),
    ('clockify', 'Clockify', 'productivity', 'alarm-clock', 21, 'Reliez votre suivi du temps Clockify à Billio.'),
    ('typeform', 'Typeform', 'productivity', 'clipboard-list', 22, 'Reliez vos formulaires Typeform à Billio.'),
    ('todoist', 'Todoist', 'productivity', 'square-check-big', 23, 'Reliez vos listes Todoist à Billio.'),
    ('yousign', 'Yousign', 'productivity', 'signature', 24, 'Signature électronique française : reliez votre compte Yousign à Billio.'),
    ('pandadoc', 'PandaDoc', 'productivity', 'file-signature', 25, 'Reliez votre compte PandaDoc (propositions et signatures) à Billio.'),
    ('gocardless', 'GoCardless', 'payment', 'repeat', 10, 'Prélèvements SEPA : reliez votre compte GoCardless à Billio.'),
    ('sumup', 'SumUp', 'payment', 'credit-card', 11, 'Reliez votre compte SumUp (terminal et liens de paiement) à Billio.'),
    ('mollie', 'Mollie', 'payment', 'wallet-cards', 12, 'Reliez votre compte Mollie (CB, virement, iDEAL…) à Billio.'),
    ('payplug', 'PayPlug', 'payment', 'badge-euro', 13, 'Solution de paiement française : reliez votre compte PayPlug à Billio.'),
    ('qonto', 'Qonto', 'accounting', 'landmark', 10, 'Reliez votre compte pro Qonto à Billio.'),
    ('wise', 'Wise', 'accounting', 'globe', 11, 'Reliez votre compte Wise Business (paiements internationaux) à Billio.'),
    ('pennylane', 'Pennylane', 'accounting', 'calculator', 12, 'Reliez votre comptabilité Pennylane à Billio.'),
    ('hubspot', 'HubSpot', 'crm', 'contact', 10, 'Reliez votre CRM HubSpot à Billio.'),
    ('pipedrive', 'Pipedrive', 'crm', 'handshake', 11, 'Reliez votre pipeline commercial Pipedrive à Billio.'),
    ('attio', 'Attio', 'crm', 'users-round', 12, 'Reliez votre CRM Attio à Billio.'),
    ('sellsy', 'Sellsy', 'crm', 'briefcase-business', 13, 'CRM français : reliez votre compte Sellsy à Billio.'),
    ('intercom', 'Intercom', 'crm', 'headset', 14, 'Reliez votre support client Intercom à Billio.'),
    ('zendesk', 'Zendesk', 'crm', 'life-buoy', 15, 'Reliez votre support Zendesk à Billio.'),
    ('freshdesk', 'Freshdesk', 'crm', 'inbox', 16, 'Reliez votre support Freshdesk à Billio.'),
    ('close', 'Close', 'crm', 'phone-call', 17, 'Reliez votre CRM Close à Billio.'),
    ('brevo', 'Brevo', 'marketing', 'megaphone', 10, 'Emailing et SMS français (ex-Sendinblue) : reliez votre compte Brevo. Pour envoyer les emails de Billio par ce service, utilisez aussi le plugin Email avec ses réglages SMTP.'),
    ('mailchimp', 'Mailchimp', 'marketing', 'mail-plus', 11, 'Reliez vos audiences Mailchimp à Billio.'),
    ('klaviyo', 'Klaviyo', 'marketing', 'chart-no-axes-combined', 12, 'Reliez votre compte Klaviyo (emailing e-commerce) à Billio.'),
    ('activecampaign', 'ActiveCampaign', 'marketing', 'send', 13, 'Reliez votre marketing automation ActiveCampaign à Billio.'),
    ('mailerlite', 'MailerLite', 'marketing', 'newspaper', 14, 'Reliez vos newsletters MailerLite à Billio.'),
    ('kit', 'Kit (ConvertKit)', 'marketing', 'mail-open', 15, 'Reliez votre compte Kit (ex-ConvertKit) à Billio.'),
    ('shopify', 'Shopify', 'marketing', 'shopping-bag', 16, 'Reliez votre boutique Shopify à Billio.'),
    ('webflow', 'Webflow', 'marketing', 'app-window', 17, 'Reliez vos sites Webflow à Billio.'),
    ('make', 'Make', 'automation', 'workflow', 10, 'Déclenchez vos scénarios Make depuis les automatisations Billio.'),
    ('n8n', 'n8n', 'automation', 'network', 11, 'Déclenchez vos workflows n8n Cloud depuis les automatisations Billio.'),
    ('ifttt', 'IFTTT', 'automation', 'zap', 12, 'Déclenchez vos applets IFTTT depuis les automatisations Billio.'),
]


def forwards(apps, schema_editor):
    Connector = apps.get_model('integrations', 'Connector')
    for key, name, category, icon, order, description in CONNECTORS:
        Connector.objects.update_or_create(key=key, defaults={
            'name': name, 'category': category, 'icon': icon, 'order': order,
            'description': description, 'requires_oauth': False, 'is_active': True,
        })


def backwards(apps, schema_editor):
    apps.get_model('integrations', 'Connector').objects.filter(key__in=[c[0] for c in CONNECTORS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0003_telegram_connector'),
    ]

    operations = [
        migrations.AlterField(
            model_name='connector',
            name='category',
            field=models.CharField(choices=[('communication', 'Communication'), ('productivity', 'Productivité'), ('payment', 'Paiement'), ('accounting', 'Banque & comptabilité'), ('crm', 'CRM & support'), ('marketing', 'Marketing & e-commerce'), ('automation', 'Automatisation')], max_length=20),
        ),
        migrations.RunPython(forwards, backwards),
    ]
