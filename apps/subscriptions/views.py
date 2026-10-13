"""
Page « Abonnement » (forfait, consommation, changement de forfait) et webhook Stripe de Billio.
"""
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from . import billing
from .entitlements import plan_for_user, usage_report
from .models import Plan, Subscription
from .serializers import PlanSerializer, SubscriptionSerializer

logger = logging.getLogger(__name__)

# Lignes du comparatif : (libellé, clé, type)
COMPARISON = [
    ('Factures et devis / mois', 'documents_per_month', 'limit'),
    ('Clients actifs', 'clients', 'limit'),
    ('Projets', 'projects', 'limit'),
    ('Utilisateurs', 'users', 'limit'),
    ('Stockage', 'storage_mb', 'storage'),
    ('Intégrations', 'integrations', 'limit'),
    ('Automatisations actives', 'workflows', 'limit'),
    ('Factures récurrentes', 'recurring', 'bool'),
    ('Acomptes et échéanciers', 'deposits', 'bool'),
    ('Paiements manuels', 'manual_payments', 'bool'),
    ('Relances automatiques', 'reminders', 'bool'),
    ('Signature en ligne des devis', 'quote_signature', 'bool'),
    ('Portail client', 'portal', 'level'),
    ('Prise de rendez-vous', 'booking', 'bool'),
    ('Suivi du temps', 'time_tracking', 'level'),
    ('Facturation du temps', 'time_billing', 'bool'),
    ('Factur-X', 'facturx', 'bool'),
    ('API REST', 'api', 'bool'),
    ('Webhooks entrants', 'inbound_webhooks', 'bool'),
    ('Plusieurs organisations', 'multi_org', 'bool'),
]
LEVEL_LABELS = {'none': None, 'basic': 'Basique', 'full': 'Complet'}


def _cell(plan, key, kind):
    if kind in ('limit', 'storage'):
        value = plan.limit(key)
        if value is None:
            return {'text': 'Illimité', 'yes': True}
        if kind == 'storage':
            return {'text': f"{value / 1024:g} Go" if value >= 1024 else f"{value} Mo", 'yes': True}
        return {'text': f"{value:,}".replace(',', ' '), 'yes': True}
    value = plan.feature(key)
    if kind == 'level':
        label = LEVEL_LABELS.get(value)
        return {'text': label, 'yes': bool(label)}
    return {'text': None, 'yes': bool(value)}


def _owned_organization(user):
    from apps.organizations.models import Organization
    return Organization.objects.filter(owner=user).order_by('created_at').first()


def _billing_owner(user):
    """Le compte qui paie : l'utilisateur s'il possède une organisation, sinon le propriétaire de son équipe."""
    if _owned_organization(user):
        return user, _owned_organization(user)
    from apps.organizations.models import OrganizationMember
    membership = OrganizationMember.objects.select_related('organization__owner').filter(user=user).first()
    if membership and membership.organization.owner:
        return membership.organization.owner, membership.organization
    return user, None


@login_required
def billing_page(request):
    owner, organization = _billing_owner(request.user)
    subscription = billing.get_subscription(owner)
    plans = list(Plan.objects.filter(is_active=True).order_by('order', 'price_monthly'))
    current = plan_for_user(owner)
    comparison = [
        {'label': label, 'cells': [{**_cell(plan, key, kind), 'current': plan.pk == current.pk} for plan in plans]}
        for label, key, kind in COMPARISON
    ]
    return render(request, 'subscriptions/billing.html', {
        'subscription': subscription,
        'current_plan': current,
        'plans': plans,
        'comparison': comparison,
        'usage': usage_report(organization) if organization else [],
        'is_owner': owner == request.user,
        'owner': owner,
        'stripe_ready': billing.is_configured(),
        'paid_active': subscription.is_paid and subscription.status in ('active', 'trialing', 'past_due'),
    })


def _back(request, message=None, level='success'):
    if message:
        getattr(messages, level)(request, message)
    return redirect('subscriptions:billing')


def _owner_subscription(request):
    if not _owned_organization(request.user):
        return None
    return billing.get_subscription(request.user)


@login_required
@require_POST
def choose_plan(request, code):
    """Choisir un forfait : Checkout depuis Free, changement au prorata depuis un forfait payant."""
    subscription = _owner_subscription(request)
    if subscription is None:
        return _back(request, "Seul le propriétaire de l'organisation peut changer de forfait.", 'error')
    plan = get_object_or_404(Plan, code=code, is_active=True)
    paid_active = subscription.is_paid and subscription.status in ('active', 'trialing', 'past_due')
    try:
        if plan.is_free:
            if not paid_active:
                return _back(request, 'Vous êtes déjà au forfait Free.', 'info')
            billing.cancel(subscription)
            return _back(request, "Abonnement résilié : vous gardez votre forfait jusqu'à la fin de la période payée, puis passerez au forfait Free.")
        if paid_active:
            if subscription.plan_id == plan.pk and not subscription.cancel_at_period_end:
                return _back(request, f'Vous êtes déjà au forfait {plan.name}.', 'info')
            billing.change_plan(subscription, plan)
            return _back(request, f'Forfait {plan.name} activé. La différence est calculée au prorata sur votre prochaine facture.')
        success = request.build_absolute_uri(reverse('subscriptions:checkout-return')) + '?session_id={CHECKOUT_SESSION_ID}'
        cancel = request.build_absolute_uri(reverse('subscriptions:billing'))
        return redirect(billing.create_checkout(subscription, plan, success_url=success, cancel_url=cancel))
    except billing.BillingError as exc:
        logger.warning('Abonnement : %s', exc)
        return _back(request, f"L'opération n'a pas abouti : {exc}", 'error')


@login_required
def checkout_return(request):
    """Retour de Stripe Checkout : l'abonnement est relu chez Stripe avant d'être activé."""
    try:
        subscription = billing.sync_checkout(request.GET.get('session_id', ''), request.user)
    except billing.BillingError as exc:
        return _back(request, f"Paiement reçu, activation en cours ({exc}). Rechargez la page dans un instant.", 'info')
    if subscription and subscription.grants_plan:
        return _back(request, f'Merci ! Votre forfait {subscription.plan.name} est actif.')
    return _back(request, "Le paiement n'est pas encore confirmé par Stripe : votre forfait s'activera dès réception.", 'info')


@login_required
@require_POST
def cancel_subscription(request):
    subscription = _owner_subscription(request)
    if not subscription or not subscription.is_paid:
        return _back(request, "Aucun abonnement payant à résilier.", 'info')
    try:
        billing.cancel(subscription)
    except billing.BillingError as exc:
        return _back(request, f"La résiliation n'a pas abouti : {exc}", 'error')
    return _back(request, "Abonnement résilié : vous gardez votre forfait jusqu'à la fin de la période payée.")


@login_required
@require_POST
def resume_subscription(request):
    subscription = _owner_subscription(request)
    if not subscription or not subscription.is_paid:
        return _back(request, "Aucun abonnement à reprendre.", 'info')
    try:
        billing.resume(subscription)
    except billing.BillingError as exc:
        return _back(request, f"L'opération n'a pas abouti : {exc}", 'error')
    return _back(request, 'Résiliation annulée : votre abonnement continue.')


@login_required
@require_POST
def billing_portal(request):
    subscription = _owner_subscription(request)
    if subscription is None:
        return _back(request, "Seul le propriétaire de l'organisation gère la facturation.", 'error')
    try:
        return redirect(billing.portal_url(subscription, request.build_absolute_uri(reverse('subscriptions:billing'))))
    except billing.BillingError as exc:
        return _back(request, f"Le portail de paiement n'a pas pu s'ouvrir : {exc}", 'error')


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """Webhook du compte Stripe de Billio (abonnements). Signature vérifiée."""
    from apps.payments.stripe_checkout import verify_webhook
    try:
        event = verify_webhook(request.body, request.headers.get('Stripe-Signature', ''), settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, KeyError):
        return HttpResponse('Signature invalide.', status=400)
    try:
        billing.handle_event(event)
    except billing.BillingError as exc:
        logger.error('Webhook abonnement %s : %s', event.get('id'), exc)
        return HttpResponse('Erreur temporaire.', status=503)  # Stripe réessaiera
    return HttpResponse('ok')


# ---------- API (lecture) ----------

class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Plan.objects.filter(is_active=True)
    serializer_class = PlanSerializer
    permission_classes = [IsAuthenticated]


class SubscriptionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Subscription.objects.filter(user=self.request.user)

