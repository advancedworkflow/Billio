"""
Signature électronique de documents PDF (façon DocuSeal).

Un `SignatureRequest` porte le PDF d'origine (envoyé, ou généré depuis un document / un devis
Billio), ses signataires (`Signer`, un lien secret chacun) et les champs placés sur les pages
(`SignatureField`, coordonnées en fraction de la page). Quand tout le monde a signé, les valeurs
sont apposées sur le PDF, suivies d'un certificat (journal `SignatureEvent`, empreintes SHA-256).
"""
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def _original_path(instance, filename):
    return f"signatures/{instance.organization_id}/{uuid.uuid4().hex}.pdf"


def _signed_path(instance, filename):
    return f"signatures/{instance.organization_id}/{uuid.uuid4().hex}-signe.pdf"


def _new_token():
    return secrets.token_urlsafe(32)


class SignatureRequest(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Brouillon'),
        ('sent', 'En attente de signature'),
        ('completed', 'Signé'),
        ('declined', 'Refusé'),
        ('cancelled', 'Annulé'),
        ('expired', 'Expiré'),
    ]
    SOURCE_CHOICES = [('upload', 'PDF importé'), ('document', 'Document Billio'), ('quote', 'Devis')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('organizations.Organization', on_delete=models.CASCADE,
                                     related_name='signature_requests')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='signature_requests')
    client = models.ForeignKey('clients.Client', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='signature_requests')
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='upload')
    document = models.ForeignKey('documents.Document', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='signature_requests')
    quote = models.ForeignKey('invoices.Quote', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='signature_requests')

    original_pdf = models.FileField(upload_to=_original_path)
    original_sha256 = models.CharField(max_length=64)
    pages = models.JSONField(default=list, blank=True)  # [[largeur, hauteur], …] en points PDF
    signed_pdf = models.FileField(upload_to=_signed_path, blank=True)
    signed_sha256 = models.CharField(max_length=64, blank=True, default='', db_index=True)

    in_order = models.BooleanField(default=False)  # les signataires signent l'un après l'autre
    expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Demande de signature'
        verbose_name_plural = 'Demandes de signature'

    def __str__(self):
        return self.title

    @property
    def is_open(self):
        return self.status == 'sent'

    def expire_if_due(self):
        """Passe la demande à « expirée » si sa date limite est dépassée (contrôle à la lecture)."""
        if self.status == 'sent' and self.expires_at and self.expires_at <= timezone.now():
            self.status = 'expired'
            self.save(update_fields=['status', 'updated_at'])
            SignatureEvent.objects.create(request=self, action='expired')
        return self.status == 'expired'

    def signer_progress(self):
        signers = list(self.signers.all())
        return sum(1 for s in signers if s.status == 'signed'), len(signers)


class Signer(models.Model):
    STATUS_CHOICES = [
        ('waiting', 'En attente de son tour'),
        ('invited', 'Invité'),
        ('viewed', 'A ouvert le document'),
        ('signed', 'A signé'),
        ('declined', 'A refusé'),
    ]
    COLORS = ['#2563eb', '#d97706', '#7c3aed', '#059669', '#db2777', '#0891b2']

    request = models.ForeignKey(SignatureRequest, on_delete=models.CASCADE, related_name='signers')
    client = models.ForeignKey('clients.Client', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='signers')
    name = models.CharField(max_length=200)
    email = models.EmailField()
    order = models.PositiveSmallIntegerField(default=0)
    token = models.CharField(max_length=64, unique=True, default=_new_token)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting')

    invited_at = models.DateTimeField(null=True, blank=True)
    viewed_at = models.DateTimeField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.TextField(blank=True, default='')
    last_reminded_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default='')

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.name} <{self.email}>"

    @property
    def color(self):
        return self.COLORS[self.order % len(self.COLORS)]


class SignatureField(models.Model):
    KIND_CHOICES = [
        ('signature', 'Signature'),
        ('initials', 'Initiales'),
        ('name', 'Nom complet'),
        ('date', 'Date de signature'),
        ('text', 'Texte'),
        ('checkbox', 'Case à cocher'),
    ]

    request = models.ForeignKey(SignatureRequest, on_delete=models.CASCADE, related_name='fields')
    signer = models.ForeignKey(Signer, on_delete=models.CASCADE, related_name='fields')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    page = models.PositiveIntegerField(default=0)
    # Position et taille en fraction de la page affichée (0 → 1, origine en haut à gauche).
    x = models.FloatField()
    y = models.FloatField()
    w = models.FloatField()
    h = models.FloatField()
    required = models.BooleanField(default=True)
    label = models.CharField(max_length=100, blank=True, default='')
    value = models.TextField(blank=True, default='')  # image PNG (data URL) pour signature/initiales

    class Meta:
        ordering = ['page', 'y', 'x', 'id']

    def __str__(self):
        return f"{self.get_kind_display()} p.{self.page + 1}"


class SignatureEvent(models.Model):
    ACTION_CHOICES = [
        ('created', 'Demande créée'),
        ('sent', 'Demande envoyée'),
        ('invited', 'Invitation envoyée'),
        ('reminded', 'Relance envoyée'),
        ('viewed', 'Document ouvert'),
        ('signed', 'Document signé'),
        ('declined', 'Signature refusée'),
        ('completed', 'Toutes les signatures recueillies'),
        ('cancelled', 'Demande annulée'),
        ('expired', 'Demande expirée'),
    ]

    request = models.ForeignKey(SignatureRequest, on_delete=models.CASCADE, related_name='events')
    signer = models.ForeignKey(Signer, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    at = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default='')
    detail = models.CharField(max_length=300, blank=True, default='')

    class Meta:
        ordering = ['at', 'id']

    def __str__(self):
        return f"{self.get_action_display()} ({self.at:%d/%m/%Y %H:%M})"
