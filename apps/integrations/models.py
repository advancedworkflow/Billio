"""
Integrations app models.
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Connector(models.Model):
    """
    Catalog entry for a connectable third-party service (WhatsApp, Slack,
    Stripe, ...). Shared across organizations, seeded via a data migration.
    """
    CATEGORY_CHOICES = [
        ('communication', _('Communication')),
        ('productivity', _('Productivité')),
        ('payment', _('Paiement')),
        ('accounting', _('Banque & comptabilité')),
        ('crm', _('CRM & support')),
        ('marketing', _('Marketing & e-commerce')),
        ('automation', _('Automatisation')),
    ]

    key = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    description = models.TextField(blank=True, default='')
    icon = models.CharField(max_length=50, default='plug', help_text=_('Lucide icon name'))
    is_active = models.BooleanField(default=True)
    requires_oauth = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Connector')
        verbose_name_plural = _('Connectors')
        ordering = ['category', 'order', 'name']

    def __str__(self):
        return self.name


class ConnectionInstance(models.Model):
    """
    A connector activated for a given organization.
    """
    STATUS_CHOICES = [
        ('not_connected', _('Non connecté')),
        ('connected', _('Connecté')),
        ('error', _('Erreur')),
    ]

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='connection_instances'
    )
    connector = models.ForeignKey(
        Connector,
        on_delete=models.CASCADE,
        related_name='instances'
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_connected')
    config = models.JSONField(blank=True, null=True, help_text=_('Provider-specific settings (API key, webhook URL, ...)'))

    connected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='connected_integrations'
    )
    connected_at = models.DateTimeField(blank=True, null=True)
    disconnected_at = models.DateTimeField(blank=True, null=True)
    last_error = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Connection')
        verbose_name_plural = _('Connections')
        unique_together = ['organization', 'connector']
        ordering = ['connector__category', 'connector__order']

    def __str__(self):
        return f"{self.connector.name} - {self.organization.name} ({self.status})"


class WebhookLog(models.Model):
    """
    Immutable audit trail of webhook events received for a connection.
    """
    connection_instance = models.ForeignKey(
        ConnectionInstance,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='webhook_logs'
    )

    event_type = models.CharField(max_length=100, blank=True, default='')
    payload = models.JSONField(blank=True, null=True)

    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Webhook Log')
        verbose_name_plural = _('Webhook Logs')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.event_type} - {'OK' if self.success else 'Failed'}"
