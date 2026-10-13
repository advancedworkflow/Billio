"""
Abonnement des comptes Billio (le SaaS lui-même, distinct des factures que nos clients émettent).

Trois notions séparées, pour pouvoir changer prix et limites sans toucher au code métier :
- `Plan` : le forfait (prix, limites chiffrées, options), modifiable dans l'admin ;
- `Subscription` : l'état de l'abonnement du compte, tenu à jour par Stripe (webhook) ;
- les quotas : calculés à la volée sur les données (voir `entitlements.py`).
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Jours d'accès conservés après un paiement échoué, avant de repasser aux limites du forfait gratuit.
GRACE_DAYS = 7


class Plan(models.Model):
    """Forfait : prix mensuel HT, limites (`None` = illimité) et options."""

    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=60)
    tagline = models.CharField(max_length=200, blank=True, default='')
    price_monthly = models.DecimalField(max_digits=8, decimal_places=2, default=0, help_text=_('Prix mensuel HT, en euros.'))
    limits = models.JSONField(default=dict, blank=True, help_text=_('Limites chiffrées ; null = illimité.'))
    features = models.JSONField(default=dict, blank=True, help_text=_('Options incluses (vrai/faux ou niveau).'))
    stripe_price_id = models.CharField(max_length=100, blank=True, default='')
    is_active = models.BooleanField(default=True)
    is_popular = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Forfait')
        verbose_name_plural = _('Forfaits')
        ordering = ['order', 'price_monthly']

    def __str__(self):
        return f"{self.name} ({self.price_monthly} € HT/mois)"

    @property
    def is_free(self):
        return not self.price_monthly

    def limit(self, key):
        """Limite chiffrée (None = illimité). Une clé absente compte comme illimitée."""
        return (self.limits or {}).get(key)

    def feature(self, key):
        return (self.features or {}).get(key, False)


class Subscription(models.Model):
    """Abonnement d'un compte (le propriétaire des organisations). Une ligne par compte."""

    STATUS_CHOICES = [
        ('free', _('Gratuit')),
        ('active', _('Actif')),
        ('trialing', _("En période d'essai")),
        ('past_due', _('Paiement en retard')),
        ('unpaid', _('Impayé')),
        ('canceled', _('Résilié')),
        ('incomplete', _('Paiement à finaliser')),
        ('incomplete_expired', _('Paiement expiré')),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='subscription')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='free')
    stripe_customer_id = models.CharField(max_length=100, blank=True, default='')
    stripe_subscription_id = models.CharField(max_length=100, blank=True, default='', db_index=True)
    current_period_end = models.DateTimeField(blank=True, null=True)
    cancel_at_period_end = models.BooleanField(default=False)
    past_due_since = models.DateTimeField(blank=True, null=True)
    comped = models.BooleanField(default=False, help_text=_('Forfait offert, attribué à la main (sans Stripe).'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Abonnement')
        verbose_name_plural = _('Abonnements')

    def __str__(self):
        return f"{self.user.email} — {self.plan.name} ({self.get_status_display()})"

    @property
    def in_grace_period(self):
        return self.status == 'past_due' and self.past_due_since is not None \
            and timezone.now() < self.past_due_since + timedelta(days=GRACE_DAYS)

    @property
    def grace_ends_at(self):
        return self.past_due_since + timedelta(days=GRACE_DAYS) if self.past_due_since else None

    @property
    def grants_plan(self):
        """L'abonnement donne-t-il accès à son forfait en ce moment ?"""
        if self.comped:
            return True
        return self.status in ('active', 'trialing') or self.in_grace_period

    @property
    def is_paid(self):
        return bool(self.stripe_subscription_id) and self.status not in ('canceled', 'incomplete_expired')
