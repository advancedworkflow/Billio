"""
Invoices app models.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
from dateutil.relativedelta import relativedelta
import uuid

DRAFT_PREFIX = 'BROUILLON-'


class Tax(models.Model):
    """
    Tax model for different tax rates.
    """
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='taxes'
    )

    name = models.CharField(max_length=100, help_text=_('Tax name (e.g., TVA 20%)'))
    rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text=_('Tax rate as percentage (e.g., 20.00 for 20%)')
    )

    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Tax')
        verbose_name_plural = _('Taxes')
        ordering = ['-is_default', 'name']
        unique_together = ['organization', 'name']

    def __str__(self):
        return f"{self.name} ({self.rate}%)"


class Product(models.Model):
    """
    Reusable product/service catalog entry, org-scoped.
    """
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='products'
    )

    name = models.CharField(max_length=200, help_text=_('Product or service name'))
    description = models.TextField(blank=True, null=True)

    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=50, default='unit', help_text=_('Unit of measurement'))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    KIND_CHOICES = [('service', 'Prestation'), ('product', 'Produit')]
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default='service')
    reference = models.CharField(max_length=60, blank=True, default='', help_text=_('Référence / SKU interne'))
    category = models.CharField(max_length=80, blank=True, default='')
    # Coût de revient (temps, achat, sous-traitance) : sert au calcul de marge, jamais affiché au client.
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Product')
        verbose_name_plural = _('Products')
        ordering = ['name']

    def __str__(self):
        return self.name


class Invoice(models.Model):
    """
    Main Invoice model.
    """
    INVOICE_TYPE_CHOICES = [
        ('sale', _('Facture de vente')),
        ('purchase', _("Facture d'achat")),
        ('credit_note', _('Avoir')),
    ]

    STATUS_CHOICES = [
        ('draft', _('Brouillon')),
        ('sent', _('Envoyée')),
        ('viewed', _('Consultée')),
        ('paid', _('Payée')),
        ('overdue', _('En retard')),
        ('cancelled', _('Annulée')),
    ]

    # Unique identifiers
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Unique par organisation (contrainte en Meta). Un brouillon porte un numéro provisoire
    # « BROUILLON-… » : le numéro définitif est attribué à l'émission, sans trou dans la séquence.
    invoice_number = models.CharField(max_length=50)
    # Facture de situation (BTP) : avancement cumulé d'un marché (devis accepté).
    situation_quote = models.ForeignKey('invoices.Quote', on_delete=models.PROTECT, null=True, blank=True,
                                        related_name='situations')
    situation_number = models.PositiveIntegerField(null=True, blank=True)
    situation_progress = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True,
                                             help_text=_('Avancement cumulé du marché, en %.'))
    # Retenue de garantie (loi n° 71-584 du 16 juillet 1971) : déduite du net à payer jusqu'à sa libération.
    retention_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    retention_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    retention_released_at = models.DateTimeField(null=True, blank=True)
    # Relances déjà envoyées (« j7 », « j14 », « j30 ») : jamais deux fois la même.
    reminders_sent = models.JSONField(default=list, blank=True)
    # Facture récurrente : cette facture sert de modèle, une copie est émise à chaque échéance.
    RECURRENCE_CHOICES = [('none', _('Aucune')), ('monthly', _('Tous les mois')),
                          ('quarterly', _('Tous les trimestres')), ('yearly', _('Tous les ans'))]
    recurrence = models.CharField(max_length=10, choices=RECURRENCE_CHOICES, default='none')
    recurrence_next_date = models.DateField(blank=True, null=True)
    recurrence_end_date = models.DateField(blank=True, null=True)
    recurrence_source = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='recurrences',
        help_text=_('Facture modèle dont celle-ci est une échéance.'),
    )
    credited_invoice = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True, related_name='credit_notes',
        help_text=_("Facture corrigée par cet avoir."),
    )

    # Relationships
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='invoices'
    )
    client = models.ForeignKey(
        'clients.Client',
        on_delete=models.CASCADE,
        related_name='invoices'
    )
    template = models.ForeignKey(
        'templates_app.InvoiceTemplate',
        on_delete=models.PROTECT,
        related_name='invoices',
        help_text=_('Template used to generate this invoice'),
        null=True,
        blank=True
    )

    # Invoice details
    title = models.CharField(max_length=200, default=_('Invoice'))
    description = models.TextField(blank=True, null=True)

    # Dates
    issue_date = models.DateField(help_text=_('Date when invoice was issued'))
    due_date = models.DateField(help_text=_('Payment due date'))

    # Financial information
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)

    # Currency and localization
    currency = models.CharField(max_length=3, default='EUR')

    # Type (sale vs purchase)
    invoice_type = models.CharField(
        max_length=20,
        choices=INVOICE_TYPE_CHOICES,
        default='sale',
        db_index=True,
    )

    # Status and tracking
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft'
    )

    # Payment information
    payment_terms = models.IntegerField(default=30, help_text=_('Payment terms in days'))

    # Additional fields
    notes = models.TextField(blank=True, null=True)
    # Logo propre à ce document (bibliothèque d'images des modèles) ; vide = logo de l'entreprise.
    logo_asset = models.ForeignKey('templates_app.TemplateAsset', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    footer = models.TextField(blank=True, null=True)

    # PDF and file storage
    pdf_file = models.FileField(upload_to='invoices/', blank=True, null=True)

    # Metadata
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_invoices'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    scheduled_send_at = models.DateTimeField(
        blank=True, null=True,
        help_text=_('Si renseigné, la facture (encore en brouillon) sera envoyée automatiquement à cette date.')
    )
    paid_at = models.DateTimeField(blank=True, null=True)
    # Dernière relance de paiement envoyée depuis la page Paiements (évite les doublons).
    last_reminder_at = models.DateTimeField(blank=True, null=True)
    receipt_number = models.CharField(max_length=64, blank=True, null=True)
    receipt_generated_at = models.DateTimeField(blank=True, null=True)
    is_favorite = models.BooleanField(default=False)

    class Meta:
        verbose_name = _('Invoice')
        verbose_name_plural = _('Invoices')
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'invoice_number'], name='uniq_invoice_number_per_org'),
        ]

    def __str__(self):
        return f"{self.invoice_number} - {self.client.name}"

    def save(self, *args, **kwargs):
        # Numéro définitif à l'émission seulement : un brouillon supprimé ne laisse pas de trou.
        if self.status == 'draft' and not self.invoice_number:
            self.invoice_number = f"{DRAFT_PREFIX}{uuid.uuid4().hex[:8].upper()}"
        elif self.status != 'draft' and (not self.invoice_number or self.is_provisional_number):
            self.invoice_number = self._generate_invoice_number()
            if kwargs.get('update_fields') is not None:  # ex. save(update_fields=['status']) à l'envoi
                kwargs['update_fields'] = {*kwargs['update_fields'], 'invoice_number'}
            if self.is_credit_note:
                self._pending_credit_application = True

        # Set default template if not provided
        if not hasattr(self, 'template') or not self.template:
            self.template = self.get_default_template()

        # Calculate total if not set
        if not self.total_amount:
            self.total_amount = self.subtotal + self.tax_amount - self.discount_amount

        super().save(*args, **kwargs)
        if getattr(self, '_pending_credit_application', False):
            self._pending_credit_application = False
            self._apply_credit_note()

    @property
    def is_locked(self):
        """Facture de vente ou avoir émis : contenu figé (obligation légale), on corrige par un avoir."""
        return self.invoice_type in ('sale', 'credit_note') and self.status != 'draft'

    @property
    def is_credit_note(self):
        return self.invoice_type == 'credit_note'

    @property
    def credited_total(self):
        """Montant des avoirs émis sur cette facture."""
        from django.db.models import Sum
        if not self.pk or self.is_credit_note:
            return Decimal('0')
        return self.credit_notes.exclude(status='draft').aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

    def amount_due(self, paid=None):
        """Reste à payer : total − paiements reçus − avoirs émis (jamais négatif)."""
        from django.db.models import Sum
        if paid is None:
            paid = self.payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or Decimal('0')
        retained = self.retention_amount if self.retention_amount and not self.retention_released_at else Decimal('0')
        return max(self.total_amount - retained - paid - self.credited_total, Decimal('0'))

    def create_credit_note(self, *, user=None, amount=None, reason=''):
        """
        Avoir (brouillon) sur cette facture émise : reprend toutes les lignes, ou une
        seule ligne « Avoir partiel » si `amount` (TTC) est donné. À émettre ensuite.
        """
        if self.invoice_type != 'sale' or self.status == 'draft':
            raise ValueError("Un avoir se crée sur une facture de vente émise.")
        today = timezone.localdate()
        credit = Invoice.objects.create(
            organization=self.organization, client=self.client, created_by=user,
            invoice_type='credit_note', credited_invoice=self, status='draft',
            title='Avoir', currency=self.currency, template=self.template,
            issue_date=today, due_date=today, total_amount=Decimal('0'),
            notes=(f"Avoir sur la facture {self.invoice_number} du {self.issue_date:%d/%m/%Y}."
                   + (f"\nMotif : {reason}" if reason else '')),
        )
        if amount is None:
            for item in self.items.all():
                InvoiceItem.objects.create(
                    invoice=credit, name=item.name, description=item.description, quantity=item.quantity,
                    unit_price=item.unit_price, unit=item.unit, tax_rate=item.tax_rate, order=item.order,
                )
            credit.subtotal, credit.tax_amount = self.subtotal, self.tax_amount
            credit.discount_amount, credit.total_amount = self.discount_amount, self.total_amount
        else:
            amount = min(Decimal(amount), self.total_amount)
            # Avoir partiel au taux de TVA dominant de la facture
            rate = (self.tax_amount / self.subtotal * 100).quantize(Decimal('0.01')) if self.subtotal else Decimal('0')
            ht = (amount / (1 + rate / 100)).quantize(Decimal('0.01'))
            InvoiceItem.objects.create(invoice=credit, name=reason or 'Avoir partiel', quantity=1, unit_price=ht, tax_rate=rate)
            credit.subtotal, credit.tax_amount, credit.total_amount = ht, amount - ht, amount
        credit.save(update_fields=['subtotal', 'tax_amount', 'discount_amount', 'total_amount'])
        return credit

    def _apply_credit_note(self):
        """À l'émission d'un avoir : solde ou annule la facture d'origine selon le reste dû."""
        original = self.credited_invoice
        if not original or original.status in ('paid', 'cancelled', 'draft'):
            return
        if original.amount_due() <= Decimal('0.009'):
            from django.db.models import Sum
            paid = original.payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or Decimal('0')
            # Rien d'encaissé : la facture est annulée par l'avoir ; sinon elle est soldée.
            if paid <= 0:
                original.status = 'cancelled'
                original.save(update_fields=['status', 'updated_at'])
            else:
                original.mark_as_paid()

    @property
    def is_provisional_number(self):
        return (self.invoice_number or '').startswith(DRAFT_PREFIX)

    def _generate_invoice_number(self):
        """Prochain numéro de la séquence de l'organisation (continue, sans trou)."""
        credit = self.is_credit_note
        prefix = self.organization.credit_note_prefix if credit else self.organization.invoice_prefix
        take = self.organization.get_next_credit_note_number if credit else self.organization.get_next_invoice_number
        while True:  # saute seulement un numéro déjà saisi à la main dans cette organisation
            number = f"{prefix}-{take():04d}"
            if not Invoice.objects.filter(organization=self.organization, invoice_number=number).exists():
                return number

    def get_default_template(self):
        """Get the default template for this organization."""
        from apps.templates_app.models import InvoiceTemplate

        # Try to get organization's default template
        default_template = InvoiceTemplate.objects.filter(
            organization=self.organization,
            is_default=True,
            is_active=True
        ).first()

        if default_template:
            return default_template

        # Fallback to any active template from the organization
        org_template = InvoiceTemplate.objects.filter(
            organization=self.organization,
            is_active=True
        ).first()

        if org_template:
            return org_template

        # Last resort: create a basic default template
        return self._create_default_template()

    def _create_default_template(self):
        """Modèle par défaut de l'organisation : une copie du modèle pro « Essentiel » si possible."""
        from apps.templates_app.models import InvoiceTemplate, MarketplaceTemplate

        pro = MarketplaceTemplate.objects.filter(slug='pro-essentiel', is_active=True).first()
        if pro:
            template, _created = InvoiceTemplate.objects.get_or_create(
                organization=self.organization, name=(pro.title or 'Essentiel')[:100],
                defaults={
                    'html_structure': pro.html_structure or '', 'css_styles': pro.css_styles or '',
                    'layout_config': pro.layout_config if isinstance(pro.layout_config, dict) else {},
                    'style_config': pro.style_config if isinstance(pro.style_config, dict) else {},
                    'is_default': not InvoiceTemplate.objects.filter(organization=self.organization, is_default=True).exists(),
                    'is_active': True,
                },
            )
            return template

        template = InvoiceTemplate.objects.create(
            organization=self.organization,
            name='Default Template',
            html_structure=self._get_default_html_structure(),
            css_styles=self._get_default_css_styles(),
            layout_config=self._get_default_layout_config(),
            style_config=self._get_default_style_config(),
            is_default=True,
            is_active=True
        )
        return template

    def render_html(self):
        """
        Génère le HTML final de la facture en utilisant son template.

        Returns:
            str: HTML rendu de la facture
        """
        self.template = usable_template(self.organization, self.template)

        return self.template.render_html(self)

    def render_css(self):
        """
        Génère le CSS final de la facture en utilisant son template.

        Returns:
            str: CSS de la facture
        """
        self.template = usable_template(self.organization, self.template)

        return self.template.render_css(self)

    def generate_pdf_html(self):
        """
        Génère le HTML complet (avec CSS inline) pour la génération PDF.

        Returns:
            str: HTML complet prêt pour PDF
        """
        html = self.render_html()
        css = self.render_css()

        # Injecter le CSS dans le HTML
        html_with_css = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
            {css}
            </style>
        </head>
        <body>
            {html}
        </body>
        </html>
        """

        return html_with_css

    def generate_pdf_bytes(self):
        from .pdf import render_document_to_pdf_bytes
        return render_document_to_pdf_bytes(self)

    def _pdf_cache_name(self):
        # Change si la facture OU son modèle (contenu, style) a été modifié.
        template = usable_template(self.organization, self.template)
        stamp = max(self.updated_at or timezone.now(), template.updated_at or timezone.now()).strftime('%Y%m%d%H%M%S%f')
        return f"invoice_{self.invoice_number}_t{template.pk}_{stamp}.pdf"

    def ensure_pdf(self):
        """
        PDF de la facture, mis en cache dans `pdf_file` : régénéré seulement si la facture
        a changé depuis (le nom du fichier porte la date de dernière modification).
        Retourne le contenu (bytes).
        """
        from django.core.files.base import ContentFile
        name = self._pdf_cache_name()
        if self.pdf_file and self.pdf_file.name.endswith(name):
            try:
                with self.pdf_file.open('rb') as handle:
                    content = handle.read()
                if content.startswith(b'%PDF'):
                    return content
            except (FileNotFoundError, OSError):
                pass
        content = self.generate_pdf_bytes()
        old = self.pdf_file.name if self.pdf_file else None
        self.pdf_file.save(name, ContentFile(content), save=False)
        # update() : ne touche pas updated_at, sinon le cache serait aussitôt périmé.
        type(self).objects.filter(pk=self.pk).update(pdf_file=self.pdf_file.name)
        if old and old != self.pdf_file.name:
            self.pdf_file.storage.delete(old)
        return content

    def _get_default_html_structure(self):
        """Get default HTML structure."""
        return """
<div class="invoice">
    <header class="invoice-header">
        <h1>Invoice</h1>
        <div class="invoice-meta">
            <p>Invoice #: {{ invoice.invoice_number }}</p>
            <p>Date: {{ invoice.issue_date }}</p>
            <p>Due: {{ invoice.due_date }}</p>
        </div>
    </header>

    <section class="client-info">
        <h3>Bill To:</h3>
        <p>{{ client.name }}</p>
        <p>{{ client.email }}</p>
        {% if client.address %}
        <p>{{ client.address }}</p>
        {% endif %}
    </section>

    <table class="items-table">
        <thead>
            <tr>
                <th>Description</th>
                <th>Qty</th>
                <th>Unit Price</th>
                <th>Total</th>
            </tr>
        </thead>
        <tbody>
            {% for item in items %}
            <tr>
                <td>{{ item.description }}</td>
                <td>{{ item.quantity }}</td>
                <td>{{ item.unit_price }}</td>
                <td>{{ item.total }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <section class="totals">
        <div class="total-row">
            <span>Subtotal:</span>
            <span>{{ invoice.subtotal }}</span>
        </div>
        <div class="total-row">
            <span>Tax:</span>
            <span>{{ invoice.tax_amount }}</span>
        </div>
        <div class="total-row total">
            <span>Total:</span>
            <span>{{ invoice.total_amount }}</span>
        </div>
    </section>
</div>
        """.strip()

    def _get_default_css_styles(self):
        """Get default CSS styles."""
        return """
.invoice {
    font-family: Arial, sans-serif;
    max-width: 800px;
    margin: 0 auto;
    padding: 20px;
}

.invoice-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 30px;
}

.invoice-header h1 {
    color: #2563eb;
    font-size: 36px;
    margin: 0;
}

.invoice-meta p {
    margin: 5px 0;
    color: #666;
}

.client-info {
    margin-bottom: 30px;
}

.client-info h3 {
    color: #2563eb;
    margin-bottom: 10px;
}

.items-table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 30px;
}

.items-table th,
.items-table td {
    padding: 10px;
    text-align: left;
    border-bottom: 1px solid #ddd;
}

.items-table th {
    background-color: #f8f9fa;
    font-weight: bold;
}

.totals {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    max-width: 300px;
    margin-left: auto;
}

.total-row {
    display: flex;
    justify-content: space-between;
    width: 100%;
    padding: 5px 0;
}

.total-row.total {
    font-weight: bold;
    font-size: 18px;
    border-top: 2px solid #2563eb;
    margin-top: 10px;
    padding-top: 15px;
}
        """.strip()

    def _get_default_layout_config(self):
        """Get default layout configuration."""
        return {
            "sections": {
                "header": {
                    "visible": True,
                    "alignment": "space-between"
                },
                "invoice_info": {
                    "position": "right"
                },
                "client_info": {
                    "position": "left"
                },
                "items_table": {
                    "columns": ["description", "quantity", "unit_price", "total"]
                },
                "totals": {
                    "alignment": "right"
                },
                "footer": {
                    "visible": False
                }
            }
        }

    def _get_default_style_config(self):
        """Get default style configuration."""
        return {
            "colors": {
                "primary": "#2563eb",
                "secondary": "#64748b",
                "text": "#0f172a",
                "background": "#ffffff"
            },
            "fonts": {
                "family": "Arial",
                "size_base": "14px",
                "size_title": "24px"
            },
            "spacing": {
                "padding": "20px",
                "section_gap": "30px"
            }
        }

    def send_to_client(self):
        """
        Envoie la facture au client selon le workflow SENT.
        Génère PDF, crée Payment Intent Stripe, envoie email.

        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            from django.core.files.base import ContentFile
            from django.utils import timezone
            import uuid

            # 1. Le PDF n'est plus pré-généré ici (c'était un fichier factice) : il est
            #    produit à la demande et mis en cache par ensure_pdf() (page publique, téléchargement).

            # 2. Créer le Payment Intent Stripe (si configuré)
            stripe_payment_intent_id = None if self.is_credit_note else self._create_stripe_payment_intent()
            if stripe_payment_intent_id:
                self.stripe_payment_intent_id = stripe_payment_intent_id

            # 3. Marquer comme envoyé
            self.status = 'sent'
            self.sent_at = timezone.now()
            self.save()

            # 4. Email au client (lien de paiement + PDF si disponible)
            from .scheduled import send_invoice_email
            send_invoice_email(self)

            return True, f"Facture #{self.invoice_number} envoyée avec succès"

        except Exception as e:
            return False, f"Erreur lors de l'envoi: {str(e)}"

    def _create_stripe_payment_intent(self):
        """
        Crée un Payment Intent Stripe pour cette facture.

        Returns:
            str: ID du Payment Intent ou None si échec
        """
        try:
            # TODO: Implémenter l'intégration Stripe
            # Pour l'instant, retourner None (pas d'erreur)
            return None
        except Exception as e:
            # Log l'erreur mais ne pas bloquer l'envoi
            print(f"Erreur Stripe: {e}")
            return None

    def mark_as_paid(self):
        """
        Marque la facture comme payée.
        Normalement appelé par webhook Stripe ou confirmation manuelle.
        """
        from django.utils import timezone

        if self.status in ['sent', 'viewed', 'overdue']:
            self.status = 'paid'
            self.paid_at = timezone.now()
            if not self.receipt_number:
                self.receipt_number = self._generate_receipt_number()
                self.receipt_generated_at = timezone.now()
            self.save()
            self._notify_payment_received()

    def _notify_payment_received(self):
        """Crée une notification pour le(s) responsable(s) de l'organisation."""
        from apps.dashboard.models import Notification

        recipients = {self.organization.owner}
        if self.created_by_id:
            recipients.add(self.created_by)
        client_label = self.client.name if self.client_id else "un client"
        for user in recipients:
            if not user:
                continue
            Notification.objects.create(
                user=user,
                notification_type='payment_received',
                title=f"Facture {self.invoice_number} payée",
                message=f"Paiement reçu de {client_label} — {self.total_amount} {self.currency}.",
                priority='medium',
                related_invoice=self,
            )

    def _generate_receipt_number(self):
        """Generate receipt number once invoice is paid."""
        return f"RCPT-{self.invoice_number}"

    def mark_as_overdue(self):
        """
        Marque la facture comme en retard.
        """
        from django.utils import timezone

        if self.status in ['sent', 'viewed'] and timezone.now().date() > self.due_date:
            self.status = 'overdue'
            self.save()

    @property
    def is_overdue(self):
        """Check if invoice is overdue."""
        from django.utils import timezone
        return (
            self.status in ['sent', 'viewed'] and
            timezone.now().date() > self.due_date
        )

    def get_status_display(self):
        """Get human-readable status."""
        return dict(self.STATUS_CHOICES)[self.status]

    def mark_as_sent(self):
        """
        Marque la facture comme envoyée.
        Utilise send_to_client() pour le workflow complet.
        """
        success, message = self.send_to_client()
        if not success:
            raise Exception(message)


class InvoiceItem(models.Model):
    """
    Individual items on an invoice.
    """
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='items'
    )

    # Item details
    name = models.CharField(max_length=200, help_text=_('Item name or description'))
    description = models.TextField(blank=True, null=True)

    # Quantity and pricing
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=50, default='unit', help_text=_('Unit of measurement'))

    # Tax
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # Calculated fields
    total = models.DecimalField(max_digits=10, decimal_places=2, editable=False)

    # Ordering
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _('Invoice Item')
        verbose_name_plural = _('Invoice Items')
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.name} - {self.invoice.invoice_number}"

    def save(self, *args, **kwargs):
        # Calculate total
        self.total = self.quantity * self.unit_price
        super().save(*args, **kwargs)


class Quote(models.Model):
    """
    Quote/Devis model, similar to Invoice but for estimates.
    """
    STATUS_CHOICES = [
        ('draft', _('Brouillon')),
        ('sent', _('Envoyé')),
        ('viewed', _('Consulté')),
        ('accepted', _('Accepté')),
        ('rejected', _('Refusé')),
        ('expired', _('Expiré')),
    ]

    RECURRENCE_INTERVAL_CHOICES = [
        ('weekly', _('Hebdomadaire')),
        ('monthly', _('Mensuelle')),
        ('quarterly', _('Trimestrielle')),
        ('yearly', _('Annuelle')),
    ]

    # Similar fields to Invoice
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quote_number = models.CharField(max_length=50)  # unique par organisation (Meta)

    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='quotes'
    )
    client = models.ForeignKey(
        'clients.Client',
        on_delete=models.CASCADE,
        related_name='quotes'
    )
    template = models.ForeignKey(
        'templates_app.InvoiceTemplate',
        on_delete=models.PROTECT,
        related_name='quotes',
        help_text=_('Template used to generate this quote'),
        null=True,
        blank=True
    )

    title = models.CharField(max_length=200, default=_('Quote'))
    description = models.TextField(blank=True, null=True)

    # Project reference (section 3 du spec)
    project_reference = models.CharField(max_length=200, blank=True, default='')
    project_name = models.CharField(max_length=200, blank=True, default='')
    project_location = models.CharField(max_length=200, blank=True, default='')
    project_start_date = models.DateField(blank=True, null=True)
    project_delivery_date = models.DateField(blank=True, null=True)

    issue_date = models.DateField()
    expiry_date = models.DateField(help_text=_('Quote expiry date'))

    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)

    currency = models.CharField(max_length=3, default='EUR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    # Conditions commerciales (section 7, 9, 10 du spec)
    notes = models.TextField(blank=True, null=True)
    # Logo propre à ce document (bibliothèque d'images des modèles) ; vide = logo de l'entreprise.
    logo_asset = models.ForeignKey('templates_app.TemplateAsset', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    payment_terms = models.TextField(blank=True, default='')
    delivery_terms = models.TextField(blank=True, default='')
    terms_and_conditions = models.TextField(blank=True, default='')
    footer = models.TextField(blank=True, null=True)

    # PDF
    pdf_file = models.FileField(upload_to='quotes/', blank=True, null=True)

    # Workflow / acceptation électronique (section 11, 15 du spec)
    sent_at = models.DateTimeField(blank=True, null=True)
    viewed_at = models.DateTimeField(blank=True, null=True)
    accepted_at = models.DateTimeField(blank=True, null=True)
    accepted_by_name = models.CharField(max_length=200, blank=True, default='')
    accepted_by_email = models.EmailField(blank=True, default='')
    signature_data = models.TextField(blank=True, default='')
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, default='')
    rejected_at = models.DateTimeField(blank=True, null=True)
    rejection_reason = models.TextField(blank=True, default='')

    # Devis récurrent / abonnement (section 21 du spec)
    is_recurring = models.BooleanField(default=False)
    recurrence_interval = models.CharField(
        max_length=20, choices=RECURRENCE_INTERVAL_CHOICES, blank=True, default=''
    )
    recurrence_count = models.PositiveIntegerField(blank=True, null=True)
    recurrence_start_date = models.DateField(blank=True, null=True)

    # Conversion devis -> facture (section 20 du spec)
    converted_to_invoice = models.OneToOneField(
        'Invoice', on_delete=models.SET_NULL, null=True, blank=True, related_name='source_quote'
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_quotes'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_favorite = models.BooleanField(default=False)

    class Meta:
        verbose_name = _('Quote')
        verbose_name_plural = _('Quotes')
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'quote_number'], name='uniq_quote_number_per_org'),
        ]

    def __str__(self):
        return f"{self.quote_number} - {self.client.name}"

    def save(self, *args, **kwargs):
        if not self.quote_number:
            self.quote_number = self._generate_quote_number()

        self.template = usable_template(self.organization, self.template)

        if not self.total_amount:
            self.total_amount = self.subtotal + self.tax_amount - self.discount_amount

        super().save(*args, **kwargs)

    def _generate_quote_number(self):
        """Generate unique quote number using the organization's atomic counter."""
        prefix = self.organization.quote_prefix
        while True:  # séquence propre à l'organisation
            number = f"{prefix}-{self.organization.get_next_quote_number():04d}"
            if not Quote.objects.filter(organization=self.organization, quote_number=number).exists():
                return number

    def get_default_template(self):
        """Get the default template for this organization (shared with invoices)."""
        from apps.templates_app.models import InvoiceTemplate

        default_template = InvoiceTemplate.objects.filter(
            organization=self.organization,
            is_default=True,
            is_active=True
        ).first()

        if default_template:
            return default_template

        org_template = InvoiceTemplate.objects.filter(
            organization=self.organization,
            is_active=True
        ).first()

        if org_template:
            return org_template

        return Invoice(organization=self.organization)._create_default_template()

    def render_html(self):
        """Génère le HTML final du devis en utilisant son template."""
        self.template = usable_template(self.organization, self.template)
        return self.template.render_html(self)

    def render_css(self):
        """Génère le CSS final du devis en utilisant son template."""
        self.template = usable_template(self.organization, self.template)
        return self.template.render_css(self)

    def generate_pdf_html(self):
        """Génère le HTML complet (avec CSS inline) pour la génération PDF."""
        html = self.render_html()
        css = self.render_css()

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
            {css}
            </style>
        </head>
        <body>
            {html}
        </body>
        </html>
        """

    def generate_pdf_bytes(self):
        """Génère le contenu binaire du PDF via WeasyPrint."""
        from .pdf import render_document_to_pdf_bytes
        return render_document_to_pdf_bytes(self)

    def send_to_client(self):
        """
        Envoie le devis au client : génère le PDF, marque comme envoyé.

        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            from django.core.files.base import ContentFile

            pdf_filename = f"quote_{self.quote_number}_{uuid.uuid4().hex[:8]}.pdf"
            pdf_content = self.generate_pdf_bytes()
            self.pdf_file.save(pdf_filename, ContentFile(pdf_content), save=False)

            self.status = 'sent'
            self.sent_at = timezone.now()
            self.save()
            self._email_client(pdf_content)

            from apps.dashboard.automation_engine import run_automations
            run_automations(
                self.organization, 'quote_sent',
                target_type='quote', target_id=self.id,
                amount=self.total_amount, client_id=self.client_id,
                context_label=f"Devis {self.quote_number} envoyé.",
            )

            return True, f"Devis #{self.quote_number} envoyé avec succès"
        except Exception as e:
            return False, f"Erreur lors de l'envoi: {str(e)}"

    def _email_client(self, pdf_content=None):
        """Email du devis au client (lien d'acceptation en ligne + PDF). N'empêche jamais l'envoi."""
        import logging
        from django.conf import settings
        from django.urls import reverse
        from apps.organizations.branded_email import branded_message, money, render_kind

        if not self.client_id or not self.client.email:
            return False
        try:
            subject, body, button_label = render_kind(self.organization, 'quote', {
                'client': self.client.get_display_name(), 'numero': self.quote_number,
                'montant': money(self.total_amount, self.currency),
                'echeance': f"{self.expiry_date:%d/%m/%Y}" if self.expiry_date else '', 'jours_retard': '',
            })
            url = f"{settings.SITE_URL}{reverse('invoices:public-quote-view', args=[self.id])}"
            message = branded_message(self.organization, subject=subject, body=body, to=[self.client.email],
                                      button=(button_label, url))
            if pdf_content:
                message.attach(f"Devis-{self.quote_number}.pdf", pdf_content, 'application/pdf')
            message.send(fail_silently=False)
            return True
        except Exception:
            logging.getLogger(__name__).exception('Email du devis %s non envoyé', self.quote_number)
            return False

    def mark_as_viewed(self):
        """Marque le devis comme vu par le client (idempotent)."""
        if self.status == 'sent':
            self.status = 'viewed'
            self.viewed_at = timezone.now()
            self.save(update_fields=['status', 'viewed_at', 'updated_at'])

    def mark_as_accepted(self, *, name='', email='', signature_data='', ip=None, user_agent=''):
        """Marque le devis comme accepté par le client et enregistre les preuves d'acceptation."""
        self.status = 'accepted'
        self.accepted_at = timezone.now()
        self.accepted_by_name = name
        self.accepted_by_email = email
        self.signature_data = signature_data
        self.ip_address = ip
        self.user_agent = user_agent
        self.save()
        self._notify(
            'quote_accepted',
            f"Devis {self.quote_number} accepté",
            f"{name or self.client.name} a accepté le devis {self.quote_number}.",
        )
        from apps.dashboard.automation_engine import run_automations
        run_automations(
            self.organization, 'quote_accepted',
            target_type='quote', target_id=self.id,
            amount=self.total_amount, client_id=self.client_id,
            context_label=f"Devis {self.quote_number} accepté par {name or self.client.name}.",
        )

    def mark_as_rejected(self, *, reason=''):
        """Marque le devis comme refusé par le client."""
        self.status = 'rejected'
        self.rejected_at = timezone.now()
        self.rejection_reason = reason
        self.save()
        self._notify(
            'quote_rejected',
            f"Devis {self.quote_number} refusé",
            f"Le devis {self.quote_number} a été refusé par {self.client.name}.",
        )
        from apps.dashboard.automation_engine import run_automations
        run_automations(
            self.organization, 'quote_rejected',
            target_type='quote', target_id=self.id,
            amount=self.total_amount, client_id=self.client_id,
            context_label=f"Devis {self.quote_number} refusé.",
        )

    def mark_as_expired(self):
        """Marque le devis comme expiré si la date de validité est dépassée."""
        if self.status in ('sent', 'viewed') and timezone.now().date() > self.expiry_date:
            self.status = 'expired'
            self.save(update_fields=['status', 'updated_at'])

    @property
    def is_expired(self):
        """Check if quote is past its expiry date."""
        return (
            self.status in ('sent', 'viewed') and
            timezone.now().date() > self.expiry_date
        )

    def _notify(self, notification_type, title, message, priority='medium'):
        """Crée une notification pour le(s) responsable(s) de l'organisation."""
        from apps.dashboard.models import Notification

        recipients = {self.organization.owner}
        if self.created_by_id:
            recipients.add(self.created_by)
        for user in recipients:
            if not user:
                continue
            Notification.objects.create(
                user=user,
                notification_type=notification_type,
                title=title,
                message=message,
                priority=priority,
                related_quote=self,
            )

    def create_situation_invoice(self, progress, *, retention_rate=Decimal('5'), user=None):
        """
        Facture de situation (brouillon) : `progress` = avancement cumulé du marché en %.
        Facture la différence avec la situation précédente, ligne par ligne du devis,
        et applique la retenue de garantie sur le TTC.
        """
        progress = Decimal(str(progress)).quantize(Decimal('0.01'))
        if self.status != 'accepted':
            raise ValueError('Une facture de situation se crée sur un devis accepté.')
        previous = self.situations.exclude(status='cancelled').order_by('-situation_number')
        if previous.filter(status='draft').exists():
            raise ValueError('Une situation est encore en brouillon : émettez-la ou supprimez-la avant la suivante.')
        last = previous.first()
        done = last.situation_progress if last else Decimal('0')
        if not (done < progress <= 100):
            raise ValueError(f"L'avancement cumulé doit être compris entre {done:.0f} % (situation précédente) et 100 %.")
        delta = progress - done
        number = (last.situation_number if last else 0) + 1
        today = timezone.localdate()
        invoice = Invoice.objects.create(
            organization=self.organization, client=self.client, created_by=user, status='draft',
            title=f"Situation n° {number}", currency=self.currency, issue_date=today,
            due_date=today + timedelta(days=self.organization.default_payment_terms or 30),
            situation_quote=self, situation_number=number, situation_progress=progress,
            retention_rate=Decimal(str(retention_rate or 0)), total_amount=Decimal('0'),
        )
        subtotal = tax = Decimal('0')
        for order, item in enumerate(self.items.all()):
            amount = (item.total * delta / 100).quantize(Decimal('0.01'))
            if not amount:
                continue
            InvoiceItem.objects.create(invoice=invoice, name=f"{item.name} — {delta:.2f} % (cumul {progress:.2f} %)".replace('.', ','),
                                       description=item.description, quantity=1, unit='situation',
                                       unit_price=amount, tax_rate=item.tax_rate, order=order)
            subtotal += amount
            tax += (amount * item.tax_rate / 100).quantize(Decimal('0.01'))
        invoice.subtotal, invoice.tax_amount, invoice.total_amount = subtotal, tax, subtotal + tax
        invoice.retention_amount = (invoice.total_amount * invoice.retention_rate / 100).quantize(Decimal('0.01'))
        market = sum((i.total for i in self.items.all()), Decimal('0'))
        lines = [f"Situation n° {number} sur le devis {self.quote_number} (marché {market:.2f} € HT).",
                 f"Avancement cumulé : {progress:.2f} % — déjà facturé : {done:.2f} % — présente situation : {delta:.2f} %."]
        if invoice.retention_amount:
            lines.append(f"Retenue de garantie {invoice.retention_rate:.2f} % : {invoice.retention_amount:.2f} € "
                         f"(loi n° 71-584 du 16 juillet 1971), libérable un an après la réception des travaux. "
                         f"Net à payer : {invoice.total_amount - invoice.retention_amount:.2f} €.")
        invoice.notes = '\n'.join(lines)
        invoice.save(update_fields=['subtotal', 'tax_amount', 'total_amount', 'retention_amount', 'notes'])
        return invoice

    def convert_to_invoice(self, user):
        """Crée une Invoice (+ InvoiceItems) à partir de ce devis, sans ressaisie."""
        invoice = Invoice.objects.create(
            organization=self.organization,
            client=self.client,
            title=self.title,
            description=self.description,
            issue_date=timezone.now().date(),
            due_date=timezone.now().date() + timedelta(days=self.organization.default_payment_terms),
            subtotal=self.subtotal,
            tax_amount=self.tax_amount,
            discount_amount=self.discount_amount,
            total_amount=self.total_amount,
            currency=self.currency,
            status='draft',
            payment_terms=self.organization.default_payment_terms,
            notes=self.notes,
            footer=self.footer,
            created_by=user,
        )
        # Une ligne de facture n'a pas de remise propre : la remise de ligne du devis est
        # intégrée au prix unitaire (et signalée dans la description) pour que le total de
        # chaque ligne, et donc celui de la facture, reste celui du devis.
        subtotal = Decimal('0')
        tax_amount = Decimal('0')
        for item in self.items.all():
            unit_price = item.unit_price
            description = item.description or ''
            discount = item.discount_percent or Decimal('0')
            if discount:
                unit_price = (item.unit_price * (Decimal('100') - discount) / Decimal('100')).quantize(Decimal('0.01'))
                note = f"Remise de {discount.normalize():f} % incluse"
                description = f"{description} — {note}" if description else note
            line = InvoiceItem.objects.create(
                invoice=invoice,
                name=item.name,
                description=description,
                quantity=item.quantity,
                unit_price=unit_price,
                unit=item.unit,
                tax_rate=item.tax_rate,
                order=item.order,
            )
            subtotal += line.total
            tax_amount += (line.total * (item.tax_rate or Decimal('0')) / Decimal('100')).quantize(Decimal('0.01'))
        # Acomptes / échéances déjà facturés sur ce devis : déduits ligne à ligne (même HT et même
        # taux de TVA que la facture d'acompte), sinon le client paierait deux fois.
        order = self.items.count()
        deposits = Invoice.objects.filter(source_milestone__quote=self).exclude(status='cancelled').exclude(pk=invoice.pk).distinct()
        for deposit in deposits.prefetch_related('items').order_by('issue_date', 'created_at'):
            label = deposit.invoice_number if deposit.status != 'draft' else 'brouillon'
            for item in deposit.items.all():
                order += 1
                line = InvoiceItem.objects.create(
                    invoice=invoice, name=f"À déduire : {item.name} (facture {label})", quantity=1,
                    unit='forfait', unit_price=-item.total, tax_rate=item.tax_rate, order=order,
                )
                subtotal += line.total
                tax_amount += (line.total * (item.tax_rate or Decimal('0')) / Decimal('100')).quantize(Decimal('0.01'))
        invoice.subtotal = subtotal
        invoice.tax_amount = tax_amount
        invoice.total_amount = subtotal + tax_amount - (self.discount_amount or Decimal('0'))
        invoice.template = self.template
        invoice.save(update_fields=['subtotal', 'tax_amount', 'total_amount', 'template', 'updated_at'])
        self.converted_to_invoice = invoice
        self.save(update_fields=['converted_to_invoice', 'updated_at'])

        if self.project_name:
            from apps.dashboard.models import Project
            # Projet déjà ouvert pour ce client (ex. créé avant le devis) : on le rattache
            # au devis plutôt que d'en créer un doublon.
            existing = Project.objects.filter(
                organization=self.organization, client=self.client, name__iexact=self.project_name,
                source_quote__isnull=True,
            ).order_by('-created_at').first()
            if existing:
                existing.source_quote = self
                existing.save(update_fields=['source_quote', 'updated_at'])
                return invoice
            from apps.subscriptions.entitlements import QuotaExceeded
            try:
                Project.objects.create(
                    organization=self.organization,
                    client=self.client,
                    name=self.project_name,
                    reference=self.project_reference,
                    description=f"Projet créé automatiquement depuis le devis {self.quote_number}.",
                    status='discovery',
                    source_quote=self,
                    start_date=self.project_start_date,
                    delivery_date=self.project_delivery_date,
                    created_by=user,
                )
            except QuotaExceeded:
                pass  # limite de projets du forfait atteinte : la facture est créée, sans projet automatique

        return invoice

    def generate_recurrence_milestones(self):
        """Génère les échéances (QuotePaymentMilestone) d'un devis récurrent."""
        if not (self.is_recurring and self.recurrence_interval and self.recurrence_count):
            return []

        self.payment_milestones.filter(status='pending').delete()

        start = self.recurrence_start_date or self.issue_date
        step_map = {
            'weekly': timedelta(weeks=1),
            'monthly': relativedelta(months=1),
            'quarterly': relativedelta(months=3),
            'yearly': relativedelta(years=1),
        }
        step = step_map[self.recurrence_interval]
        per_cycle = (self.total_amount / self.recurrence_count).quantize(Decimal('0.01'))

        milestones = []
        running_total = Decimal('0')
        for i in range(self.recurrence_count):
            due = start + step * i
            amount = per_cycle if i < self.recurrence_count - 1 else self.total_amount - running_total
            running_total += amount
            milestones.append(QuotePaymentMilestone(
                quote=self,
                label=f"Échéance {i + 1}/{self.recurrence_count}",
                due_date=due,
                amount=amount,
                order=i,
            ))
        return QuotePaymentMilestone.objects.bulk_create(milestones)

    def vat_split(self, amount_ttc):
        """
        Ventile un montant TTC (acompte, échéance) entre les taux de TVA du devis, au prorata
        du TTC de chaque taux : [(taux, HT, TVA)], la somme HT + TVA retombant exactement sur
        le montant. Devis sans lignes : taux par défaut de l'organisation (0 % en franchise).
        """
        bases = {}
        for item in self.items.all():
            rate = item.tax_rate or Decimal('0')
            bases[rate] = bases.get(rate, Decimal('0')) + item.total
        bases = {rate: base for rate, base in bases.items() if base}
        if not bases:
            prefs = self.organization.billing_preferences or {}
            bases = {Decimal('0') if prefs.get('vat_exempt') else Decimal('20'): Decimal('1')}
        weights = {rate: base * (100 + rate) / 100 for rate, base in bases.items()}
        total_weight = sum(weights.values())
        rates = sorted(weights)
        split, remaining = [], amount_ttc
        for index, rate in enumerate(rates):
            ttc = remaining if index == len(rates) - 1 else (amount_ttc * weights[rate] / total_weight).quantize(Decimal('0.01'))
            remaining -= ttc
            ht = (ttc * 100 / (100 + rate)).quantize(Decimal('0.01'))
            split.append((rate, ht, ttc - ht))
        return split

    def generate_invoice_for_milestone(self, milestone, user):
        """
        Facture d'acompte / d'échéance (brouillon) : le montant TTC de l'échéance est ventilé
        en HT + TVA selon les taux du devis (une ligne par taux), avec la référence du devis.
        """
        ref = f"devis {self.quote_number}" + (f" du {self.issue_date:%d/%m/%Y}" if self.issue_date else '')
        invoice = Invoice.objects.create(
            organization=self.organization,
            client=self.client,
            title=f"{self.title} — {milestone.label}",
            issue_date=timezone.now().date(),
            due_date=milestone.due_date or timezone.now().date(),
            total_amount=milestone.amount,
            currency=self.currency,
            status='draft',
            created_by=user,
            template=self.template,
            notes=f"{milestone.label} sur le {ref} — montant total du devis : {self.total_amount:.2f} € TTC.",
        )
        subtotal = tax = Decimal('0')
        split = self.vat_split(milestone.amount)
        for order, (rate, ht, vat) in enumerate(split):
            suffix = f" (TVA {rate.normalize():f} %)" if len(split) > 1 else ''
            InvoiceItem.objects.create(
                invoice=invoice, name=f"{milestone.label} — {ref}{suffix}", quantity=1,
                unit='forfait', unit_price=ht, tax_rate=rate, order=order,
            )
            subtotal += ht
            tax += vat
        invoice.subtotal, invoice.tax_amount, invoice.total_amount = subtotal, tax, subtotal + tax
        invoice.save(update_fields=['subtotal', 'tax_amount', 'total_amount'])
        milestone.generated_invoice = invoice
        milestone.status = 'invoiced'
        milestone.save(update_fields=['generated_invoice', 'status'])
        return invoice

    def get_status_display(self):
        """Get human-readable status."""
        return dict(self.STATUS_CHOICES)[self.status]


class QuoteItem(models.Model):
    """
    Individual items on a quote (mirrors InvoiceItem, plus catalog traceability and per-line discount).
    """
    quote = models.ForeignKey(
        Quote,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        'Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quote_items'
    )

    name = models.CharField(max_length=200, help_text=_('Item name or description'))
    description = models.TextField(blank=True, null=True)

    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=50, default='unit', help_text=_('Unit of measurement'))

    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    total = models.DecimalField(max_digits=10, decimal_places=2, editable=False)

    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _('Quote Item')
        verbose_name_plural = _('Quote Items')
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.name} - {self.quote.quote_number}"

    def save(self, *args, **kwargs):
        gross = self.quantity * self.unit_price
        self.total = gross - (gross * self.discount_percent / Decimal('100'))
        super().save(*args, **kwargs)


class QuotePaymentMilestone(models.Model):
    """
    Payment schedule line for a quote (échéancier de paiement), also used to
    materialize the installments of a recurring quote.
    """
    STATUS_CHOICES = [
        ('pending', _('En attente')),
        ('invoiced', _('Facturé')),
        ('paid', _('Payé')),
        ('cancelled', _('Annulé')),
    ]

    quote = models.ForeignKey(
        Quote,
        on_delete=models.CASCADE,
        related_name='payment_milestones'
    )
    label = models.CharField(max_length=200)
    due_date = models.DateField(null=True, blank=True)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text=_('Montant TTC dû'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    order = models.PositiveIntegerField(default=0)
    generated_invoice = models.ForeignKey(
        'Invoice', on_delete=models.SET_NULL, null=True, blank=True, related_name='source_milestone'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Quote Payment Milestone')
        verbose_name_plural = _('Quote Payment Milestones')
        ordering = ['order', 'due_date']

    def __str__(self):
        return f"{self.label} - {self.quote.quote_number}"


class QuoteAttachment(models.Model):
    """
    File attached to a quote (cahier des charges, plans, CGV, contrats...).
    """
    quote = models.ForeignKey(
        Quote,
        on_delete=models.CASCADE,
        related_name='attachments'
    )
    file = models.FileField(upload_to='quotes/attachments/')
    name = models.CharField(max_length=255, blank=True, default='')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='+'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Quote Attachment')
        verbose_name_plural = _('Quote Attachments')
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.name or self.file.name


def _is_placeholder_template(template):
    """Modèle vide créé automatiquement (« Invoice / Default template ») : inutilisable tel quel."""
    from apps.templates_app.models import InvoiceTemplate
    html = (template.html_structure or '').strip()
    default = InvoiceTemplate._meta.get_field('html_structure').default
    return not html or html == default or html == Invoice._get_default_html_structure(None).strip()


def usable_template(organization, current=None):
    """
    Modèle réellement exploitable pour rendre une facture / un devis : le modèle choisi s'il
    a un contenu, sinon un modèle de l'organisation, sinon une copie du modèle pro « Essentiel ».
    """
    from apps.templates_app.models import InvoiceTemplate, MarketplaceTemplate
    if current is not None and not _is_placeholder_template(current):
        return current
    for candidate in InvoiceTemplate.objects.filter(organization=organization, is_active=True).order_by('-is_default', 'name'):
        if not _is_placeholder_template(candidate):
            return candidate
    pro = MarketplaceTemplate.objects.filter(slug='pro-essentiel', is_active=True).first()
    if pro:
        copy, _created = InvoiceTemplate.objects.get_or_create(
            organization=organization, name=(pro.title or 'Essentiel')[:100],
            defaults={
                'html_structure': pro.html_structure or '', 'css_styles': pro.css_styles or '',
                'layout_config': pro.layout_config if isinstance(pro.layout_config, dict) else {},
                'style_config': pro.style_config if isinstance(pro.style_config, dict) else {},
                'is_active': True, 'is_default': False,
            },
        )
        return copy
    return current or Invoice(organization=organization)._create_default_template()
