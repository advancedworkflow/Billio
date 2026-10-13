"""
Templates app models for customizable invoice templates.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.core.files.base import ContentFile
from django.template import Template, Context
from django.utils import timezone
import os


class InvoiceTemplate(models.Model):
    """
    Invoice template model - cœur du système de génération dynamique.
    Stocke HTML + CSS + configurations JSON pour génération dynamique.
    """
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='invoice_templates'
    )

    name = models.CharField(max_length=100)

    # Structure HTML de base du template
    html_structure = models.TextField(
        default='<div class="invoice"><h1>Invoice</h1><p>Default template</p></div>',
        help_text=_('HTML template structure with placeholders')
    )

    # Styles CSS du template
    css_styles = models.TextField(
        default='.invoice { font-family: Arial, sans-serif; padding: 20px; }',
        help_text=_('CSS styles for the template')
    )

    # Configuration de layout (disposition des éléments)
    layout_config = models.JSONField(
        default=dict,
        help_text=_('Layout configuration in JSON format')
    )

    # Configuration de style (couleurs, polices, espacement)
    style_config = models.JSONField(
        default=dict,
        help_text=_('Style configuration in JSON format')
    )

    # Métadonnées
    is_default = models.BooleanField(
        default=False,
        help_text=_('Is this the default template for the organization?')
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_('Is this template active and available for use?')
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Invoice Template')
        verbose_name_plural = _('Invoice Templates')
        ordering = ['-is_default', 'name']
        unique_together = ['organization', 'name']

    def __str__(self):
        return f"{self.name} ({self.organization.name})"

    def save(self, *args, **kwargs):
        """Ensure only one default template per organization."""
        if self.is_default:
            InvoiceTemplate.objects.filter(
                organization=self.organization,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    @property
    def is_global(self):
        """Check if this is a global template (no organization)."""
        return self.organization is None

    def render_html(self, document):
        """
        Génère le HTML final du document (facture ou devis) en remplaçant les placeholders.

        Args:
            document: Instance du modèle Invoice ou Quote

        Returns:
            str: HTML rendu avec les données du document
        """
        # Préparer les données de contexte (données document + variables personnalisables)
        context_data = self._prepare_context_data(document)

        # Créer le template Django
        template = Template(self.html_structure)

        # Rendre avec le contexte
        context = Context(context_data)
        rendered_html = template.render(context)

        return rendered_html

    def _flat_document_context(self, document):
        """
        Contexte « plat » (même forme que l'aperçu éditeur) pour variables {{ invoice_number }}, {% for item in items %}, etc.
        Fonctionne pour une Invoice (invoice_number/due_date) comme pour un Quote (quote_number/expiry_date) :
        les clés exposées restent identiques dans les deux cas pour que les gabarits n'aient pas besoin de le savoir.
        """
        org = document.organization
        cl = document.client

        def df(d):
            return d.strftime('%d/%m/%Y') if d else ''

        is_quote = hasattr(document, 'quote_number')
        number = getattr(document, 'invoice_number', None) or getattr(document, 'quote_number', None) or ''
        due_or_expiry = getattr(document, 'due_date', None) or getattr(document, 'expiry_date', None)

        items = []
        qs = document.items.all().order_by('order', 'name') if hasattr(document, 'items') else []
        for i in qs:
            items.append({
                'name': i.name,
                'description': (i.description or '').strip(),
                'quantity': i.quantity,
                'unit_price': str(i.unit_price),
                'unit': i.unit,
                'tax_rate': str(i.tax_rate),
                'total': str(i.total),
            })

        return {
            'invoice_number': number,
            'document_number': number,
            'document_type': 'quote' if is_quote else 'invoice',
            'issue_date': df(document.issue_date),
            'due_date': df(due_or_expiry),
            'currency': document.currency,
            'subtotal': str(document.subtotal),
            'tax_amount': str(document.tax_amount),
            'discount_amount': str(document.discount_amount),
            'total_amount': str(document.total_amount),
            'organization_name': org.name if org else '',
            'organization_address': org.address or '' if org else '',
            'organization_city': org.city or '' if org else '',
            'organization_postal_code': org.postal_code or '' if org else '',
            'organization_phone': org.phone or '' if org else '',
            'organization_email': org.email or '' if org else '',
            'organization_registration_number': org.registration_number or '' if org else '',
            'organization_tax_id': org.tax_id or '' if org else '',
            'organization_initial': (org.name or '?')[:1].upper() if org else '',
            'organization_logo_url': self._logo_file_uri(org),
            'organization_bank_name': (org.bank_name or '') if org else '',
            'organization_iban': (org.iban or '') if org else '',
            'organization_bic_swift': (org.bic_swift or '') if org else '',
            'organization_payment_instructions': (org.payment_instructions or '') if org else '',
            'document_kind': 'Devis' if is_quote else 'Facture',
            **self._quote_text_overrides(document, is_quote),
            'client_name': cl.name if cl else '',
            'client_email': cl.email if cl else '',
            'client_address': cl.address or '' if cl else '',
            'client_phone': cl.phone or '' if cl else '',
            'client_registration_number': cl.registration_number or '' if cl else '',
            'client_tax_id': cl.tax_id or '' if cl else '',
            'notes': document.notes or '',
            'items': items,
        }

    @staticmethod
    def _quote_text_overrides(document, is_quote):
        """
        Textes propres au devis (objet, conditions, délais, mentions, pied) : quand ils sont
        renseignés sur le devis, ils remplacent les valeurs par défaut du modèle.
        """
        if not is_quote:
            return {}
        overrides = {}
        title = (getattr(document, 'title', '') or '').strip()
        project = (getattr(document, 'project_name', '') or '').strip()
        subject = ' — '.join(part for part in (title if title.lower() != 'devis' else '', project) if part)
        if subject:
            overrides['subject'] = subject
        for source, key in (
            ('payment_terms', 'payment_terms'), ('delivery_terms', 'delivery_terms'),
            ('terms_and_conditions', 'legal_mentions'), ('footer', 'thank_you'),
        ):
            value = (getattr(document, source, '') or '').strip()
            if value:
                overrides[key] = value
        return overrides

    @staticmethod
    def _logo_file_uri(org):
        """Logo de l'organisation pour le PDF : WeasyPrint lit le fichier sur disque (pas d'URL HTTP)."""
        logo = getattr(org, 'logo', None) if org else None
        if not logo:
            return ''
        try:
            from pathlib import Path
            path = Path(logo.path)
            return path.as_uri() if path.exists() else ''
        except (ValueError, NotImplementedError):
            return ''

    def render_css(self, document=None):
        """
        Génère le CSS final avec les configurations de style appliquées.

        Args:
            document: Instance du modèle Invoice ou Quote (optionnel)

        Returns:
            str: CSS final
        """
        css = self.css_styles

        # Appliquer les configurations de style (placeholders type {{ colors.primary }})
        if self.style_config:
            css = self._apply_style_config(css, self.style_config)

        # Variables {{ accent_color }}, {{ font_family }}, etc. dans la feuille CSS
        ctx = {}
        if document is not None:
            ctx = self._prepare_context_data(document)
        elif self.style_config:
            ctx = dict(self.style_config.get('variables_defaults') or {})
        try:
            css = Template(css).render(Context(ctx))
        except Exception:
            pass

        # Police imposée depuis le mode simple de l'éditeur (en tête : contient un @import).
        from .preview import font_override_css
        override = font_override_css((self.style_config or {}).get('font_override'))
        return override + css if override else css

    def _prepare_context_data(self, document):
        """
        Prépare les données de contexte pour le rendu du template.

        Args:
            document: Instance du modèle Invoice ou Quote

        Returns:
            dict: Données de contexte
        """
        is_quote = hasattr(document, 'quote_number')

        # Libellé par défaut selon le type de document, remplaçable par variables_defaults du template
        context = {'document_label': 'Devis N°' if is_quote else 'Facture N°'}

        # Valeurs par défaut éditables (couleurs, libellés, textes légaux) — ne peuvent pas écraser les clés métier
        style_cfg = self.style_config or {}
        defaults = apply_billing_texts(dict(style_cfg.get('variables_defaults') or {}), document.organization)
        context.update(defaults)

        context.update({
            'invoice': document,
            'document': document,
            'organization': document.organization,
            'client': document.client,
            'items': document.items.all().order_by('order', 'name') if hasattr(document, 'items') else [],
            'subtotal': document.subtotal,
            'tax_amount': document.tax_amount,
            'discount_amount': document.discount_amount,
            'total': document.total_amount,
            'issue_date': document.issue_date,
            'due_date': getattr(document, 'due_date', None) or getattr(document, 'expiry_date', None),
            'status': document.get_status_display(),
            # Bloc « Tampon » de l'éditeur de modèle : affiché seulement sur une facture réglée.
            'is_paid': getattr(document, 'status', '') == 'paid',
        })
        # Champs plats (aperçu + PDF identiques)
        context.update(self._flat_document_context(document))

        # Sections de layout (visibilité / options)
        if self.layout_config:
            context.update(self._apply_layout_config(self.layout_config))

        return context

    def _apply_style_config(self, css, style_config):
        """
        Applique la configuration de style au CSS.

        Args:
            css: CSS de base
            style_config: Configuration de style

        Returns:
            str: CSS modifié
        """
        # Extraire les configurations
        colors = style_config.get('colors', {})
        fonts = style_config.get('fonts', {})
        spacing = style_config.get('spacing', {})

        # Remplacer les variables CSS
        replacements = {}

        # Couleurs
        replacements.update({
            '{{ colors.primary }}': colors.get('primary', '#2563eb'),
            '{{ colors.secondary }}': colors.get('secondary', '#64748b'),
            '{{ colors.text }}': colors.get('text', '#0f172a'),
            '{{ colors.background }}': colors.get('background', '#ffffff'),
        })

        # Polices
        replacements.update({
            '{{ fonts.family }}': fonts.get('family', 'Arial'),
            '{{ fonts.size_base }}': fonts.get('size_base', '14px'),
            '{{ fonts.size_title }}': fonts.get('size_title', '24px'),
        })

        # Espacement
        replacements.update({
            '{{ spacing.padding }}': spacing.get('padding', '20px'),
            '{{ spacing.section_gap }}': spacing.get('section_gap', '30px'),
        })

        # Appliquer les remplacements
        for placeholder, value in replacements.items():
            css = css.replace(placeholder, value)

        return css

    def _apply_layout_config(self, layout_config):
        """
        Applique la configuration de layout aux données de contexte.

        Args:
            layout_config: Configuration de layout

        Returns:
            dict: Modifications du contexte
        """
        context_updates = {}

        # Configuration des sections
        sections = layout_config.get('sections', {})

        for section_name, section_config in sections.items():
            visible_key = f'{section_name}_visible'
            context_updates[visible_key] = section_config.get('visible', True)

            # Autres propriétés de section
            for prop, value in section_config.items():
                if prop != 'visible':
                    context_updates[f'{section_name}_{prop}'] = value

        return context_updates


class MarketplaceTemplate(models.Model):
    """
    Marketplace template model - templates available for purchase.
    Can be system templates (official) or creator templates (user-submitted).
    """
    TEMPLATE_TYPE_CHOICES = [
        ('system', 'Système'),
        ('creator', 'Créateur')
    ]

    title = models.CharField(max_length=150, verbose_name='Titre')
    slug = models.SlugField(unique=True, verbose_name='Slug')

    description = models.TextField(verbose_name='Description', blank=True)

    # Preview and demo
    preview_image = models.ImageField(
        upload_to='templates/previews/',
        verbose_name='Image de prévisualisation',
        blank=True,
        null=True
    )
    demo_html = models.TextField(
        verbose_name='HTML de démonstration',
        help_text='HTML pour la prévisualisation'
    )

    # Pricing
    price = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
        verbose_name='Prix'
    )
    currency = models.CharField(
        max_length=10,
        default='EUR',
        verbose_name='Devise'
    )

    is_free = models.BooleanField(default=True, verbose_name='Gratuit')
    is_active = models.BooleanField(default=True, verbose_name='Actif')
    is_approved = models.BooleanField(
        default=False,
        verbose_name='Approuvé',
        help_text='Pour les templates créateur - doit être approuvé par un admin'
    )

    template_type = models.CharField(
        max_length=20,
        choices=TEMPLATE_TYPE_CHOICES,
        default='system',
        verbose_name='Type de template'
    )

    # Creator (for creator templates)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name='Créateur'
    )

    # Template content (for system templates)
    html_structure = models.TextField(
        blank=True,
        help_text='HTML template structure (for system templates)'
    )
    css_styles = models.TextField(
        blank=True,
        help_text='CSS styles (for system templates)'
    )
    layout_config = models.JSONField(
        default=dict,
        help_text='Layout configuration (for system templates)'
    )
    style_config = models.JSONField(
        default=dict,
        help_text='Style configuration (for system templates)'
    )

    # Metadata
    tags = models.JSONField(
        default=list,
        verbose_name='Tags',
        help_text='Liste des tags pour le filtrage'
    )
    compatible_types = models.JSONField(
        default=list,
        verbose_name='Types compatibles',
        help_text='["invoice", "quote", "receipt"]'
    )

    # Stats
    download_count = models.PositiveIntegerField(default=0, verbose_name='Téléchargements')
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0, verbose_name='Note')
    review_count = models.PositiveIntegerField(default=0, verbose_name='Avis')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Template Marketplace'
        verbose_name_plural = 'Templates Marketplace'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_template_type_display()})"

    def save(self, *args, **kwargs):
        """Auto-approve system templates, set free status based on price."""
        if self.template_type == 'system':
            self.is_approved = True

        if self.price == 0:
            self.is_free = True
        else:
            self.is_free = False

        super().save(*args, **kwargs)

    @property
    def is_system_template(self):
        return self.template_type == 'system'

    @property
    def is_creator_template(self):
        return self.template_type == 'creator'

    def get_average_rating(self):
        """Calculate average rating from reviews."""
        # This would be implemented with a Review model
        return self.rating

    def increment_download_count(self):
        """Increment download counter."""
        self.download_count += 1
        self.save(update_fields=['download_count'])

    def update_rating(self):
        """Update template rating based on reviews."""
        reviews = self.reviews.all()
        if reviews.exists():
            avg_rating = reviews.aggregate(avg=models.Avg('rating'))['avg']
            self.rating = round(avg_rating, 2)
            self.review_count = reviews.count()
        else:
            self.rating = 0
            self.review_count = 0
        self.save(update_fields=['rating', 'review_count'])


class OrganizationTemplate(models.Model):
    """
    Template instance for an organization - cloned from marketplace template.
    This allows organizations to customize templates without affecting the original.
    """
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='organization_templates'
    )

    # Reference to original marketplace template
    marketplace_template = models.ForeignKey(
        MarketplaceTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='organization_instances'
    )

    name = models.CharField(max_length=100, verbose_name='Nom')

    # Template content (can be modified)
    html_structure = models.TextField(
        help_text='Structure HTML personnalisée'
    )
    css_styles = models.TextField(
        help_text='Styles CSS personnalisés'
    )
    layout_config = models.JSONField(
        default=dict,
        help_text='Configuration de layout'
    )
    style_config = models.JSONField(
        default=dict,
        help_text='Configuration de style'
    )

    # Status
    is_default = models.BooleanField(default=False, verbose_name='Par défaut')
    is_active = models.BooleanField(default=True, verbose_name='Actif')

    # Purchase info
    purchased_at = models.DateTimeField(null=True, blank=True, verbose_name='Acheté le')
    purchase_price = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Prix d\'achat'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Template Organisation'
        verbose_name_plural = 'Templates Organisation'
        ordering = ['-is_default', 'name']
        unique_together = ['organization', 'name']

    def __str__(self):
        return f"{self.name} ({self.organization.name})"

    def save(self, *args, **kwargs):
        """Ensure only one default template per organization."""
        if self.is_default:
            OrganizationTemplate.objects.filter(
                organization=self.organization,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    @classmethod
    def create_from_marketplace(cls, organization, marketplace_template, custom_name=None):
        """
        Create an organization template from a marketplace template.

        Args:
            organization: Organization instance
            marketplace_template: MarketplaceTemplate instance
            custom_name: Optional custom name for the template

        Returns:
            OrganizationTemplate instance
        """
        name = custom_name or marketplace_template.title

        # Ensure unique name within organization
        base_name = name
        counter = 1
        while cls.objects.filter(organization=organization, name=name).exists():
            name = f"{base_name} ({counter})"
            counter += 1

        return cls.objects.create(
            organization=organization,
            marketplace_template=marketplace_template,
            name=name,
            html_structure=marketplace_template.html_structure,
            css_styles=marketplace_template.css_styles,
            layout_config=marketplace_template.layout_config,
            style_config=marketplace_template.style_config,
            purchased_at=timezone.now() if not marketplace_template.is_free else None,
            purchase_price=marketplace_template.price if not marketplace_template.is_free else None
        )


class TemplatePurchase(models.Model):
    """
    Record of template purchases for revenue tracking and access control.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name='Utilisateur'
    )

    template = models.ForeignKey(
        MarketplaceTemplate,
        on_delete=models.CASCADE,
        verbose_name='Template'
    )

    # Purchase details
    price = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        verbose_name='Prix payé'
    )
    currency = models.CharField(
        max_length=10,
        default='EUR',
        verbose_name='Devise'
    )

    # Payment integration
    stripe_payment_intent = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Stripe Payment Intent'
    )
    stripe_session_id = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Stripe Session ID'
    )

    # Status
    is_completed = models.BooleanField(default=False, verbose_name='Achat complété')

    purchased_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Achat de Template'
        verbose_name_plural = 'Achats de Templates'
        ordering = ['-purchased_at']
        unique_together = ['user', 'template']  # One purchase per user per template

    def __str__(self):
        return f"{self.user.email} - {self.template.title} ({self.price} {self.currency})"

    @property
    def can_access_template(self):
        """Check if user can access this template."""
        return self.is_completed


class TemplateReview(models.Model):
    """
    User reviews and ratings for marketplace templates.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name='Utilisateur'
    )

    template = models.ForeignKey(
        MarketplaceTemplate,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name='Template'
    )

    rating = models.PositiveSmallIntegerField(
        choices=[(i, f"{i} étoiles") for i in range(1, 6)],
        verbose_name='Note'
    )

    comment = models.TextField(
        blank=True,
        verbose_name='Commentaire'
    )

    is_verified_purchase = models.BooleanField(
        default=False,
        verbose_name='Achat vérifié'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Avis Template'
        verbose_name_plural = 'Avis Templates'
        ordering = ['-created_at']
        unique_together = ['user', 'template']

    def __str__(self):
        return f"{self.user.email} - {self.template.title} ({self.rating}★)"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update template rating
        self.template.update_rating()


# Note: InvoiceTemplate remains separate for backward compatibility
# Migration to OrganizationTemplate can be done later if needed

def apply_billing_texts(defaults, organization):
    """
    Remplace les textes d'origine des modèles pro (conditions de paiement, mentions légales)
    par ceux générés depuis les réglages de facturation de l'organisation (Centre de ressources).
    Un texte personnalisé dans l'éditeur de modèle est conservé tel quel.
    """
    from .pro_templates import COMMON_DEFAULTS
    texts = organization.billing_texts() if organization is not None and hasattr(organization, 'billing_texts') else {}
    for key, value in texts.items():
        current = (defaults.get(key) or '').strip()
        if not current or current == COMMON_DEFAULTS.get(key, '').strip():
            defaults[key] = value
    return defaults
