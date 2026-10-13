"""
Droits d'un compte selon son forfait : options (`require_feature`) et quotas (`require_quota`).

- Le forfait appliqué est celui de l'abonnement du propriétaire de l'organisation, s'il donne
  accès en ce moment (actif, essai, ou délai de grâce après un paiement échoué) ; sinon Free.
- Les quotas se comptent sur tout le compte (toutes les organisations du propriétaire).
- Passer sous une limite ne supprime jamais rien : seules les nouvelles créations sont bloquées.
- Les créations faites par Billio lui-même (tâches planifiées, pages publiques des clients)
  ne sont pas bloquées : le contrôle ne s'applique que pendant la requête d'un utilisateur
  connecté (voir `EntitlementsMiddleware`).

Clés de limites (Plan.limits, None = illimité) : documents_per_month, clients, projects, users,
storage_mb, integrations, workflows.
Clés d'options (Plan.features) : recurring, deposits, manual_payments, reminders, quote_signature,
portal ('basic' | 'full'), booking, time_tracking ('none' | 'basic' | 'full'), time_billing, api,
inbound_webhooks, facturx, multi_org.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

LIMITS = {
    'documents_per_month': 'factures et devis par mois',
    'clients': 'clients actifs',
    'projects': 'projets',
    'users': 'utilisateurs',
    'storage_mb': 'stockage',
    'integrations': 'intégrations connectées',
    'workflows': 'automatisations actives',
}

FEATURES = {
    'recurring': 'Les factures récurrentes',
    'deposits': 'Les acomptes et échéanciers',
    'manual_payments': 'Les paiements manuels',
    'reminders': 'Les relances automatiques',
    'quote_signature': 'La signature en ligne des devis',
    'portal': 'Le portail client complet',
    'booking': 'La prise de rendez-vous en ligne',
    'time_tracking': 'Le suivi du temps',
    'time_billing': 'La facturation du temps passé',
    'api': "L'API",
    'inbound_webhooks': 'Les webhooks entrants',
    'facturx': 'Le format Factur-X',
    'multi_org': 'La gestion de plusieurs organisations',
}

# Options à niveaux, du plus bas au plus haut.
LEVELS = {
    'portal': ['basic', 'full'],
    'time_tracking': ['none', 'basic', 'full'],
}

_enforced = ContextVar('billio_entitlements_enforced', default=False)


class Locked(Exception):
    """Action réservée à un forfait supérieur. `plan` = forfait conseillé (ou None)."""

    def __init__(self, message, plan=None):
        super().__init__(message)
        self.message = message
        self.plan = plan

    @property
    def upgrade_url(self):
        url = reverse('subscriptions:billing')
        return f'{url}#{self.plan.code}' if self.plan else url


class FeatureLocked(Locked):
    pass


class QuotaExceeded(Locked):
    pass


# ---------- Contexte d'application ----------

def enforcing():
    return _enforced.get()


@contextmanager
def enforce(active=True):
    """Active (ou suspend, avec active=False) le contrôle des quotas dans ce bloc."""
    token = _enforced.set(active)
    try:
        yield
    finally:
        _enforced.reset(token)


# ---------- Forfait applicable ----------

def free_plan():
    from .models import Plan
    plan = Plan.objects.filter(code='free').first()
    return plan or Plan(code='free', name='Free', limits={}, features={})


def subscription_for(user):
    from .models import Subscription
    if not user or not getattr(user, 'pk', None):
        return None
    return Subscription.objects.select_related('plan').filter(user=user).first()


def plan_for_user(user):
    subscription = subscription_for(user)
    if subscription and subscription.grants_plan:
        return subscription.plan
    return free_plan()


def plan_for(organization):
    owner = getattr(organization, 'owner', None)
    return plan_for_user(owner) if owner else free_plan()


def has_feature(organization, key, level=None):
    value = plan_for(organization).feature(key)
    if key in LEVELS:
        order = LEVELS[key]
        need = level or order[1]
        return order.index(value if value in order else order[0]) >= order.index(need)
    return bool(value)


def _plans_upward():
    from .models import Plan
    return list(Plan.objects.filter(is_active=True).order_by('order', 'price_monthly'))


def plan_with_feature(key, level=None):
    for plan in _plans_upward():
        value = plan.feature(key)
        if key in LEVELS:
            order = LEVELS[key]
            if order.index(value if value in order else order[0]) >= order.index(level or order[1]):
                return plan
        elif value:
            return plan
    return None


def plan_with_room(key, needed):
    for plan in _plans_upward():
        limit = plan.limit(key)
        if limit is None or limit >= needed:
            return plan
    return None


# ---------- Consommation ----------

def _owner_org_ids(organization):
    from apps.organizations.models import Organization
    owner_id = getattr(organization, 'owner_id', None)
    if not owner_id:
        return [organization.pk] if getattr(organization, 'pk', None) else []
    return list(Organization.objects.filter(owner_id=owner_id).values_list('id', flat=True))


def storage_bytes(organization):
    """Taille des fichiers déposés (livrables, jalons, projets, devis, images des documents)."""
    from django.core.files.storage import default_storage

    org_ids = _owner_org_ids(organization)
    key = f"billio-storage-{'-'.join(map(str, sorted(org_ids)))}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    from apps.dashboard.models import DeliverableFile, MilestoneFile, ProjectFile
    from apps.invoices.models import QuoteAttachment

    querysets = [
        MilestoneFile.objects.filter(milestone__project__organization_id__in=org_ids),
        DeliverableFile.objects.filter(deliverable__project__organization_id__in=org_ids),
        ProjectFile.objects.filter(project__organization_id__in=org_ids),
        QuoteAttachment.objects.filter(quote__organization_id__in=org_ids),
    ]
    total = 0
    for queryset in querysets:
        for item in queryset.only('file'):
            try:
                total += item.file.size
            except (OSError, ValueError):
                continue
    for org_id in org_ids:
        folder = f'documents/inline/{org_id}'
        try:
            _dirs, files = default_storage.listdir(folder)
        except (OSError, NotImplementedError):
            continue
        for name in files:
            try:
                total += default_storage.size(f'{folder}/{name}')
            except OSError:
                continue
    cache.set(key, total, 300)
    return total


def forget_storage(organization):
    cache.delete(f"billio-storage-{'-'.join(map(str, sorted(_owner_org_ids(organization))))}")


def usage(organization, key):
    """Consommation actuelle du compte pour une limite (stockage en Mo)."""
    org_ids = _owner_org_ids(organization)
    if key == 'documents_per_month':
        from apps.invoices.models import Invoice, Quote
        start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        invoices = Invoice.objects.filter(organization_id__in=org_ids, created_at__gte=start).exclude(invoice_type='credit_note')
        return invoices.count() + Quote.objects.filter(organization_id__in=org_ids, created_at__gte=start).count()
    if key == 'clients':
        from apps.clients.models import Client
        return Client.objects.filter(organization_id__in=org_ids, is_active=True).count()
    if key == 'projects':
        from apps.dashboard.models import Project
        return Project.objects.filter(organization_id__in=org_ids).count()
    if key == 'users':
        from apps.organizations.models import OrganizationInvite, OrganizationMember
        members = set(OrganizationMember.objects.filter(organization_id__in=org_ids).values_list('user_id', flat=True))
        if getattr(organization, 'owner_id', None):
            members.add(organization.owner_id)
        pending = OrganizationInvite.objects.filter(organization_id__in=org_ids, accepted_at__isnull=True).count()
        return len(members) + pending
    if key == 'storage_mb':
        return round(storage_bytes(organization) / (1024 * 1024), 1)
    if key == 'integrations':
        from apps.integrations.models import ConnectionInstance
        from apps.integrations.views import INTERNAL_CONNECTORS  # Stripe : brique interne, hors quota
        return ConnectionInstance.objects.filter(organization_id__in=org_ids, status='connected')             .exclude(connector__key__in=INTERNAL_CONNECTORS).count()
    if key == 'workflows':
        from apps.dashboard.models import AutomationRule
        return AutomationRule.objects.filter(organization_id__in=org_ids, is_active=True).count()
    raise KeyError(key)


def _mb(value):
    text = f"{value / 1024:.1f} Go" if value >= 1024 else f"{value:g} Mo"
    return text.replace('.', ',')


def usage_report(organization):
    """[{key, label, used, limit, percent}] pour la page Abonnement."""
    plan = plan_for(organization)
    rows = []
    for key, label in LIMITS.items():
        limit = plan.limit(key)
        used = usage(organization, key)
        if key == 'storage_mb':
            display = f"{_mb(used)} / {_mb(limit)}" if limit is not None else f"{_mb(used)} · illimité"
        else:
            display = f"{used} / {limit}" if limit is not None else f"{used} · illimité"
        rows.append({
            'key': key, 'label': label, 'used': used, 'limit': limit, 'display': display,
            'percent': min(100, round(used / limit * 100)) if limit else 0,
            'full': limit is not None and used >= limit,
        })
    return rows


# ---------- Contrôles ----------

def require_feature(organization, key, level=None):
    """Lève FeatureLocked si l'option n'est pas dans le forfait (seulement pendant une requête utilisateur)."""
    if not enforcing() or organization is None or has_feature(organization, key, level):
        return
    plan = plan_with_feature(key, level)
    label = FEATURES.get(key, key)
    suffix = f" à partir du forfait {plan.name}" if plan else " dans un forfait supérieur"
    raise FeatureLocked(f"{label} est disponible{suffix}.", plan)


def require_quota(organization, key, adding=1):
    """Lève QuotaExceeded si la création dépasse la limite du forfait. Stockage : `adding` en octets."""
    if not enforcing() or organization is None:
        return
    plan = plan_for(organization)
    limit = plan.limit(key)
    if limit is None:
        return
    if key == 'storage_mb':
        used_bytes = storage_bytes(organization)
        if used_bytes + adding <= limit * 1024 * 1024:
            return
        needed = (used_bytes + adding) / (1024 * 1024)
        current = f"{limit / 1024:g} Go" if limit >= 1024 else f"{limit} Mo"
        message = f"Espace de stockage plein : votre forfait {plan.name} inclut {current}."
    else:
        used = usage(organization, key)
        if used + adding <= limit:
            return
        needed = used + adding
        message = f"Limite atteinte : votre forfait {plan.name} inclut {limit} {LIMITS[key]}."
    upgrade = plan_with_room(key, needed)
    if upgrade and upgrade.code != plan.code:
        message += f" Passez au forfait {upgrade.name} pour continuer."
    raise QuotaExceeded(message, upgrade if upgrade and upgrade.code != plan.code else None)
