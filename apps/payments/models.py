"""
Payments app models.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from decimal import Decimal
import uuid


class PaymentMethod(models.Model):
    """
    Available payment methods for organizations.
    """
    METHOD_CHOICES = [
        ('bank_transfer', _('Virement bancaire')),
        ('credit_card', _('Carte bancaire')),
        ('paypal', _('PayPal')),
        ('stripe', _('Stripe')),
        ('check', _('Chèque')),
        ('cash', _('Espèces')),
    ]

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='payment_methods'
    )

    name = models.CharField(max_length=100, help_text=_('Payment method name'))
    method_type = models.CharField(
        max_length=20,
        choices=METHOD_CHOICES,
        default='bank_transfer'
    )

    # For bank transfers
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    account_holder = models.CharField(max_length=100, blank=True, null=True)
    iban = models.CharField(max_length=34, blank=True, null=True)
    bic = models.CharField(max_length=11, blank=True, null=True)

    # For online payments (Stripe, PayPal)
    api_key = models.CharField(max_length=255, blank=True, null=True)
    webhook_secret = models.CharField(max_length=255, blank=True, null=True)

    # Settings
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    processing_fee = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text=_('Processing fee as percentage')
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Payment Method')
        verbose_name_plural = _('Payment Methods')
        ordering = ['-is_default', 'name']

    def __str__(self):
        return f"{self.name} ({self.organization.name})"

    def save(self, *args, **kwargs):
        # Ensure only one default payment method per organization
        if self.is_default:
            PaymentMethod.objects.filter(
                organization=self.organization
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class Payment(models.Model):
    """
    Payment record for invoices.
    """
    STATUS_CHOICES = [
        ('pending', _('En attente')),
        ('processing', _('En cours')),
        ('completed', _('Terminé')),
        ('failed', _('Échoué')),
        ('cancelled', _('Annulé')),
        ('refunded', _('Remboursé')),
    ]

    # Unique identifiers
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction_id = models.CharField(max_length=100, blank=True, null=True, unique=True)

    # Relationships
    invoice = models.ForeignKey(
        'invoices.Invoice',
        on_delete=models.CASCADE,
        related_name='payments'
    )
    payment_method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.SET_NULL,
        null=True,
        related_name='payments'
    )

    # Payment details
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='EUR')

    # Status and processing
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )

    # External payment provider data
    provider = models.CharField(max_length=50, blank=True, null=True)  # stripe, paypal, etc.
    provider_payment_id = models.CharField(max_length=255, blank=True, null=True)
    provider_data = models.JSONField(blank=True, null=True)  # Store provider-specific data

    # Processing fees
    processing_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Dates
    payment_date = models.DateTimeField(blank=True, null=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    # Additional information
    notes = models.TextField(blank=True, null=True)

    # Metadata
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='processed_payments'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Payment')
        verbose_name_plural = _('Payments')
        ordering = ['-created_at']

    def __str__(self):
        return f"Payment {self.transaction_id or self.id} - {self.amount} {self.currency}"

    def save(self, *args, **kwargs):
        # Auto-generate transaction ID if not provided
        if not self.transaction_id:
            self.transaction_id = self._generate_transaction_id()

        # Update invoice status if payment is completed
        if self.status == 'completed':
            self._update_invoice_status()

        super().save(*args, **kwargs)

    def _generate_transaction_id(self):
        """Generate unique transaction ID."""
        import uuid
        return f"TXN-{uuid.uuid4().hex[:12].upper()}"

    def _update_invoice_status(self):
        """Update invoice status when payment is completed."""
        total_paid = sum(
            payment.amount for payment in
            self.invoice.payments.filter(status='completed')
        )

        if total_paid >= self.invoice.total_amount:
            self.invoice.status = 'paid'
            self.invoice.paid_at = self.payment_date or self.processed_at
            self.invoice.save()


class Transaction(models.Model):
    """
    Detailed transaction log for auditing and tracking.
    """
    TYPE_CHOICES = [
        ('payment', _('Paiement')),
        ('refund', _('Remboursement')),
        ('fee', _('Frais')),
        ('adjustment', _('Ajustement')),
    ]

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name='transactions'
    )

    transaction_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default='payment'
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)

    # Provider information
    provider_reference = models.CharField(max_length=255, blank=True, null=True)
    provider_data = models.JSONField(blank=True, null=True)

    # Status
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True, null=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Transaction')
        verbose_name_plural = _('Transactions')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transaction_type} - {self.amount} - {'Success' if self.success else 'Failed'}"


class BankLine(models.Model):
    """
    Encaissement lu sur un relevé bancaire (ou saisi à la main), à rapprocher d'une facture
    (apps/payments/reconciliation.py). Une fois validé, il pointe vers le paiement créé.
    """
    STATUS_CHOICES = [
        ('pending', _('À rapprocher')),
        ('matched', _('Rapproché')),
        ('ignored', _('Ignoré')),
    ]

    organization = models.ForeignKey('organizations.Organization', on_delete=models.CASCADE, related_name='bank_lines')
    date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    label = models.CharField(max_length=500, blank=True, default='')
    # Empreinte date + montant + libellé : réimporter le même relevé ne crée pas de doublon.
    fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='bank_lines')
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Ligne de relevé')
        verbose_name_plural = _('Lignes de relevé')
        ordering = ['-date', '-id']
        constraints = [models.UniqueConstraint(fields=['organization', 'fingerprint'], name='uniq_bank_line_per_org')]

    def __str__(self):
        return f'{self.date} {self.amount} {self.label[:40]}'
