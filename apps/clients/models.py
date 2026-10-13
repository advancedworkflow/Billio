"""
Clients app models.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings
import uuid


class Client(models.Model):
    """
    Client model representing customers who receive invoices.
    """
    # Relationship to organization (not user directly)
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='clients'
    )

    # Basic information
    name = models.CharField(max_length=200, help_text=_('Client name or company name'))
    email = models.EmailField(help_text=_('Primary contact email'))
    phone = models.CharField(max_length=20, blank=True, null=True)

    # Address information
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)

    # Business information
    company_name = models.CharField(max_length=200, blank=True, null=True)
    tax_id = models.CharField(max_length=50, blank=True, null=True)
    registration_number = models.CharField(max_length=50, blank=True, null=True)

    # Contact person (if different from company)
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    contact_phone = models.CharField(max_length=20, blank=True, null=True)

    # Additional information
    notes = models.TextField(blank=True, null=True)

    # Payment terms (can override organization default)
    payment_terms = models.IntegerField(
        blank=True,
        null=True,
        help_text=_('Payment terms in days (overrides organization default)')
    )

    # Portal access (bearer token for the unauthenticated client portal link)
    portal_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)

    # Status and metadata
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Calculated fields
    total_invoiced = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text=_('Total amount invoiced to this client')
    )
    total_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text=_('Total amount paid by this client')
    )
    outstanding_balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text=_('Current outstanding balance')
    )

    class Meta:
        verbose_name = _('Client')
        verbose_name_plural = _('Clients')
        ordering = ['name']
        unique_together = ['organization', 'email']  # Prevent duplicate emails per org

    def __str__(self):
        return f"{self.name} ({self.organization.name})"

    def get_display_name(self):
        """Return the best display name for the client."""
        if self.company_name:
            return self.company_name
        return self.name

    def get_full_address(self):
        """Return formatted full address."""
        address_parts = []
        if self.address:
            address_parts.append(self.address)
        if self.city:
            address_parts.append(self.city)
        if self.postal_code:
            address_parts.append(self.postal_code)
        if self.country:
            address_parts.append(self.country)
        return ', '.join(address_parts)

    def update_financials(self):
        """Update financial totals from related invoices."""
        from django.db.models import Sum, Case, When, DecimalField

        # Calculate totals from invoices
        invoice_totals = self.invoices.aggregate(
            total_invoiced=Sum('total_amount'),
            total_paid=Sum(
                Case(
                    When(status='paid', then='total_amount'),
                    default=0,
                    output_field=DecimalField(max_digits=10, decimal_places=2)
                )
            )
        )

        self.total_invoiced = invoice_totals['total_invoiced'] or 0
        self.total_paid = invoice_totals['total_paid'] or 0
        self.outstanding_balance = self.total_invoiced - self.total_paid
        self.save(update_fields=['total_invoiced', 'total_paid', 'outstanding_balance'])


class ClientContact(models.Model):
    """
    Additional contacts for a client.
    """
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name='contacts'
    )

    name = models.CharField(max_length=100, help_text=_('Contact person name'))
    email = models.EmailField(help_text=_('Contact email'))
    phone = models.CharField(max_length=20, blank=True, null=True)
    position = models.CharField(max_length=100, blank=True, null=True, help_text=_('Job position'))

    is_primary = models.BooleanField(default=False, help_text=_('Primary contact for this client'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Client Contact')
        verbose_name_plural = _('Client Contacts')
        ordering = ['-is_primary', 'name']

    def __str__(self):
        return f"{self.name} - {self.client.name}"

    def save(self, *args, **kwargs):
        # Ensure only one primary contact per client
        if self.is_primary:
            ClientContact.objects.filter(client=self.client).update(is_primary=False)
        super().save(*args, **kwargs)


