"""
Quotas vérifiés à la création, quel que soit le chemin (éditeur, duplication, conversion, API…).
Hors requête d'un utilisateur connecté (tâches planifiées, pages publiques), rien n'est bloqué.
"""
from django.db.models.signals import pre_save
from django.dispatch import receiver

from .entitlements import enforcing, require_quota


def _creating(instance):
    return instance._state.adding and enforcing()


@receiver(pre_save, sender='invoices.Invoice')
def invoice_quota(sender, instance, **kwargs):
    if _creating(instance) and instance.invoice_type != 'credit_note':
        require_quota(instance.organization, 'documents_per_month')


@receiver(pre_save, sender='invoices.Quote')
def quote_quota(sender, instance, **kwargs):
    if _creating(instance):
        require_quota(instance.organization, 'documents_per_month')


@receiver(pre_save, sender='clients.Client')
def client_quota(sender, instance, **kwargs):
    if _creating(instance) and instance.is_active:
        require_quota(instance.organization, 'clients')


@receiver(pre_save, sender='dashboard.Project')
def project_quota(sender, instance, **kwargs):
    if _creating(instance):
        require_quota(instance.organization, 'projects')
