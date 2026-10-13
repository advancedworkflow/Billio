"""
Organizations app models.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings
import uuid


class Organization(models.Model):
    """
    Organization model representing a business entity.
    """
    ORGANIZATION_TYPES = [
        ('freelancer', _('Indépendant')),
        ('studio', _('Studio')),
        ('small_business', _('TPE / PME')),
        ('agency', _('Agence')),
    ]

    name = models.CharField(max_length=200, help_text=_('Organization name'))
    type = models.CharField(
        max_length=20,
        choices=ORGANIZATION_TYPES,
        default='freelancer'
    )

    # Ownership
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_organizations'
    )

    # Contact information
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    website = models.URLField(blank=True, null=True)

    # Address
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)

    # Business information
    tax_id = models.CharField(max_length=50, blank=True, null=True)
    registration_number = models.CharField(max_length=50, blank=True, null=True)

    # Branding
    logo = models.ImageField(upload_to='organization_logos/', blank=True, null=True)
    primary_color = models.CharField(max_length=7, default='#000000')  # Hex color
    secondary_color = models.CharField(max_length=7, default='#ffffff')  # Hex color

    # Settings
    default_currency = models.CharField(max_length=3, default='EUR')
    default_language = models.CharField(max_length=10, default='fr')
    timezone = models.CharField(max_length=50, default='Europe/Paris')

    # Invoice settings
    invoice_prefix = models.CharField(max_length=10, default='INV')
    next_invoice_number = models.PositiveIntegerField(default=1)
    # Avoirs : séquence distincte des factures (AV-0001, AV-0002…)
    credit_note_prefix = models.CharField(max_length=10, default='AV')
    next_credit_note_number = models.PositiveIntegerField(default=1)
    default_payment_terms = models.IntegerField(default=30)  # days

    # Quote (devis) settings
    quote_prefix = models.CharField(max_length=10, default='DEV')
    next_quote_number = models.PositiveIntegerField(default=1)

    # Paiement (affichage sur factures / mentions légales)
    PAYMENT_METHOD_CHOICES = [
        ('bank_transfer', _('Virement bancaire / SEPA')),
        ('check', _('Chèque')),
        ('cash', _('Espèces')),
        ('card', _('Carte bancaire')),
        ('other', _('Autre')),
    ]

    preferred_payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default='bank_transfer',
        verbose_name=_('Moyen de paiement préféré'),
        help_text=_('Affiché sur les factures et guide les champs à renseigner.'),
    )

    bank_name = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name=_('Nom de la banque'),
    )
    iban = models.CharField(
        max_length=34,
        blank=True,
        default='',
        verbose_name=_('IBAN'),
        help_text=_('Sans espaces de préférence (normalisé à l’enregistrement).'),
    )
    bic_swift = models.CharField(
        max_length=11,
        blank=True,
        default='',
        verbose_name=_('BIC / SWIFT'),
    )
    payment_instructions = models.TextField(
        blank=True,
        default='',
        verbose_name=_('Instructions de paiement'),
        help_text=_('Ex. délai, libellé du virement, autres moyens de paiement.'),
    )
    # Réglages issus du Centre de ressources (TJM, pénalités, franchise de TVA…) :
    # utilisés par l'éditeur de facture et les mentions légales des modèles.
    billing_preferences = models.JSONField(default=dict, blank=True)
    # Notifications envoyées aux clients sur leur portail (et par email pour les
    # changements majeurs) : {clé d'évènement: {'enabled': bool, 'email': bool}}.
    # Vide = réglages par défaut (voir apps.dashboard.client_notifications.CLIENT_EVENTS).
    client_notification_settings = models.JSONField(default=dict, blank=True)
    # Métier (pack appliqué : phases, modèles de projet, mentions) — voir trade_packs.TRADE_PACKS.
    trade = models.CharField(max_length=30, blank=True, default='')
    # Prise de rendez-vous en ligne : {'enabled', 'types': [{'name', 'duration'}], 'days': [1..7], 'start', 'end',
    # 'min_notice_hours', 'max_days_ahead', 'location'} — voir apps.dashboard.booking.booking_config.
    booking_settings = models.JSONField(default=dict, blank=True)
    booking_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    def billing_texts(self):
        """Mentions générées depuis les réglages : {'legal_mentions', 'payment_terms'} (vide si rien n'est réglé)."""
        prefs = self.billing_preferences or {}
        if not prefs:
            return {}
        from decimal import Decimal, InvalidOperation
        raw_days = prefs.get('payment_days')
        days = int(raw_days if raw_days is not None else (self.default_payment_terms or 30))
        try:
            rate = format(Decimal(str(prefs.get('penalty_rate'))).normalize(), 'f').replace('.', ',') if prefs.get('penalty_rate') else ''
        except InvalidOperation:
            rate = ''
        legal = []
        if prefs.get('vat_exempt'):
            legal.append('TVA non applicable, art. 293 B du CGI.')
        if rate:
            legal.append(
                f"En cas de retard de paiement, des pénalités au taux annuel de {rate} % seront exigibles, "
                "ainsi qu'une indemnité forfaitaire de 40 € pour frais de recouvrement."
            )
        else:
            legal.append("En cas de retard de paiement, une indemnité forfaitaire de 40 € pour frais de recouvrement sera exigible.")
        legal.append(prefs.get('early_discount') or "Pas d'escompte pour paiement anticipé.")
        if prefs.get('trade_mentions'):
            legal.append(prefs['trade_mentions'])
        return {
            'legal_mentions': ' '.join(legal),
            'payment_terms': (
                f"Paiement à {days} jours à réception de facture, par virement bancaire." if days
                else "Paiement à réception de facture, par virement bancaire."
            ),
        }

    # Automatisations exécutées par apps.invoices.scheduled (commande run_automations + tableau de bord)
    automation_reminder_j7 = models.BooleanField(
        default=False,
        verbose_name=_('Relance à J+7'),
    )
    automation_reminder_j14 = models.BooleanField(
        default=False,
        verbose_name=_('Relance à J+14'),
    )
    automation_reminder_j30 = models.BooleanField(
        default=False,
        verbose_name=_('Relance à J+30'),
    )
    automation_recurring_invoices = models.BooleanField(
        default=False,
        verbose_name=_('Factures récurrentes'),
    )
    automation_quote_reminders = models.BooleanField(
        default=True,
        verbose_name=_('Relances automatiques devis (J+3, J+7, avant expiration)'),
    )

    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Organization')
        verbose_name_plural = _('Organizations')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"

    def _take_counter(self, field):
        """Réserve le prochain numéro du compteur `field` (verrou de ligne : pas de doublon en concurrence)."""
        from django.db import transaction
        with transaction.atomic():
            locked = type(self).objects.select_for_update().only(field).get(pk=self.pk)
            number = getattr(locked, field)
            type(self).objects.filter(pk=self.pk).update(**{field: number + 1})
        setattr(self, field, number + 1)
        return number

    def get_next_invoice_number(self):
        """Réserve le prochain numéro de facture (séquence continue propre à l'organisation)."""
        return self._take_counter('next_invoice_number')

    def get_next_credit_note_number(self):
        """Réserve le prochain numéro d'avoir."""
        return self._take_counter('next_credit_note_number')

    def get_next_quote_number(self):
        """Réserve le prochain numéro de devis."""
        return self._take_counter('next_quote_number')


class OrganizationMember(models.Model):
    """
    Members of an organization with different roles.
    """
    ROLE_CHOICES = [
        ('owner', _('Propriétaire')),
        ('admin', _('Administrateur')),
        ('member', _('Membre')),
        ('viewer', _('Lecteur')),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='members'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='organization_memberships'
    )
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='member'
    )

    # Permissions
    can_create_invoices = models.BooleanField(default=True)
    can_edit_organization = models.BooleanField(default=False)
    can_manage_members = models.BooleanField(default=False)
    can_view_financials = models.BooleanField(default=True)

    invited_at = models.DateTimeField(auto_now_add=True)
    joined_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = _('Organization Member')
        verbose_name_plural = _('Organization Members')
        unique_together = ['organization', 'user']

    # Droits appliqués par défaut à chaque rôle (modifiables ensuite membre par membre).
    ROLE_PERMISSIONS = {
        'owner': {'can_create_invoices': True, 'can_edit_organization': True,
                  'can_manage_members': True, 'can_view_financials': True},
        'admin': {'can_create_invoices': True, 'can_edit_organization': True,
                  'can_manage_members': True, 'can_view_financials': True},
        'member': {'can_create_invoices': True, 'can_edit_organization': False,
                   'can_manage_members': False, 'can_view_financials': True},
        'viewer': {'can_create_invoices': False, 'can_edit_organization': False,
                   'can_manage_members': False, 'can_view_financials': True},
    }
    PERMISSION_FIELDS = ('can_create_invoices', 'can_edit_organization', 'can_manage_members', 'can_view_financials')

    def __str__(self):
        return f"{self.user.email} - {self.organization.name} ({self.get_role_display()})"

    def apply_role(self, role):
        """Change le rôle et remet les droits par défaut de ce rôle (sans sauvegarder)."""
        self.role = role
        for field, value in self.ROLE_PERMISSIONS.get(role, {}).items():
            setattr(self, field, value)


class OrganizationInvite(models.Model):
    """
    Pending invitation to join an organization, sent by email.
    Accepted via a unique token link — resolves to an existing user
    (immediate join) or prompts account creation first.
    """
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='invites'
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=20,
        choices=OrganizationMember.ROLE_CHOICES,
        default='member'
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='sent_invites'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = _('Organization Invite')
        verbose_name_plural = _('Organization Invites')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.email} -> {self.organization.name}"

    @property
    def is_accepted(self):
        return self.accepted_at is not None

    def accept(self, user):
        """Crée (ou récupère) l'adhésion de `user` à l'organisation et clôt l'invitation."""
        from django.utils import timezone
        member, created = OrganizationMember.objects.get_or_create(
            organization=self.organization,
            user=user,
            defaults={'role': self.role, 'joined_at': timezone.now(),
                      **OrganizationMember.ROLE_PERMISSIONS.get(self.role, {})},
        )
        if not created and not member.joined_at:
            member.joined_at = timezone.now()
            member.save(update_fields=['joined_at'])
        self.accepted_at = timezone.now()
        self.save(update_fields=['accepted_at'])
        return member

