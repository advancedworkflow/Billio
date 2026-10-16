"""
Accounts app models.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """
    Custom user model extending Django's AbstractUser.
    """
    ROLE_CHOICES = [
        ('freelancer', _('Indépendant')),
        ('merchant', _('Commerçant')),
        ('creator', _('Créateur')),
    ]

    email = models.EmailField(_('email address'), unique=True)
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='freelancer',
        help_text=_('User role in the system')
    )
    phone = models.CharField(max_length=20, blank=True, null=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)

    # Social login fields
    google_id = models.CharField(max_length=100, blank=True, null=True, unique=True)

    # Preferences
    language = models.CharField(max_length=10, default='fr')
    timezone = models.CharField(max_length=50, default='Europe/Paris')
    currency = models.CharField(max_length=3, default='EUR')

    # Acceptation des CGU, de la politique de confidentialité et des cookies (case cochée à l'inscription)
    terms_accepted_at = models.DateTimeField(blank=True, null=True)

    # Double authentification (apps/accounts/two_factor.py) : active si totp_enabled_at est renseigné
    totp_secret = models.CharField(max_length=64, blank=True, default='')
    totp_enabled_at = models.DateTimeField(blank=True, null=True)
    totp_last_step = models.BigIntegerField(default=0)
    totp_recovery_codes = models.JSONField(default=list, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        verbose_name = _('User')
        verbose_name_plural = _('Users')

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"


class UserProfile(models.Model):
    """
    Extended user profile information.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    company_name = models.CharField(max_length=100, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    tax_id = models.CharField(max_length=50, blank=True, null=True)

    # Business information
    business_type = models.CharField(max_length=50, blank=True, null=True)
    industry = models.CharField(max_length=100, blank=True, null=True)

    # Preferences
    invoice_prefix = models.CharField(max_length=10, default='INV')
    default_payment_terms = models.IntegerField(default=30)  # days

    class Meta:
        verbose_name = _('User Profile')
        verbose_name_plural = _('User Profiles')

    def __str__(self):
        return f"Profile for {self.user.email}"


