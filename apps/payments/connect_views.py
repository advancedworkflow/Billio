"""Activation du paiement en ligne avec Stripe Connect (Paramètres › Paiement) et webhook Connect."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.integrations.providers import ProviderError

from . import stripe_connect


def _settings_url():
    return f"{reverse('accounts:user-settings')}?tab=paiement"


def _organization(user):
    """Même entreprise que la page Paramètres : propriétaire, ou admin avec droit d'édition."""
    from apps.accounts.views import list_editable_organizations_for_payment
    organizations = list_editable_organizations_for_payment(user)
    return organizations[0] if organizations else None


def _onboarding_redirect(request, account):
    url = stripe_connect.onboarding_url(
        account,
        refresh_url=request.build_absolute_uri(reverse('payments:connect-refresh')),
        return_url=request.build_absolute_uri(reverse('payments:connect-return')),
    )
    return redirect(url)


@login_required
@require_POST
def connect_start(request):
    """Crée le compte connecté si besoin puis ouvre l'inscription hébergée par Stripe."""
    organization = _organization(request.user)
    if not organization:
        messages.error(request, "Seul le propriétaire ou un administrateur de l'entreprise peut activer le paiement en ligne.")
        return redirect(_settings_url())
    try:
        account = stripe_connect.create_account(organization, email=request.user.email)
        return _onboarding_redirect(request, account)
    except ProviderError as exc:
        messages.error(request, str(exc))
        return redirect(_settings_url())


@login_required
def connect_refresh(request):
    """Lien d'inscription expiré ou déjà utilisé : Stripe renvoie ici, on en génère un nouveau."""
    organization = _organization(request.user)
    account = stripe_connect.account_for(organization)
    if not account:
        return redirect(_settings_url())
    try:
        return _onboarding_redirect(request, account)
    except ProviderError as exc:
        messages.error(request, str(exc))
        return redirect(_settings_url())


@login_required
def connect_return(request):
    """Retour de l'inscription Stripe : l'état est relu (Stripe peut encore vérifier le dossier)."""
    account = stripe_connect.account_for(_organization(request.user))
    if account:
        try:
            stripe_connect.sync(account)
        except ProviderError:
            pass
        if account.charges_enabled:
            messages.success(request, 'Paiement en ligne activé : vos clients peuvent payer depuis le lien de leurs factures.')
        elif account.details_submitted:
            messages.info(request, 'Inscription envoyée : Stripe vérifie votre dossier, généralement en quelques minutes.')
        else:
            messages.info(request, "Inscription non terminée : reprenez-la quand vous voulez avec « Finaliser l'inscription ».")
    return redirect(_settings_url())


@csrf_exempt
@require_POST
def connect_webhook(request):
    """
    Webhook Connect de la plateforme (un seul pour toutes les organisations), signé avec
    STRIPE_CONNECT_WEBHOOK_SECRET. L'organisation est retrouvée par le champ `account`.
    """
    from apps.staff.platform import get_setting
    from .stripe_checkout import record_checkout, verify_webhook

    try:
        event = verify_webhook(request.body, request.META.get('HTTP_STRIPE_SIGNATURE', ''),
                               get_setting('STRIPE_CONNECT_WEBHOOK_SECRET'))
    except (ValueError, KeyError):
        return HttpResponse(status=400)
    account = stripe_connect.account_for_event(event)
    if not account:
        return HttpResponse(status=200)  # compte inconnu (supprimé, autre environnement) : rien à faire
    obj = (event.get('data') or {}).get('object') or {}
    kind = event.get('type')
    if kind == 'account.updated':
        stripe_connect.sync(account, obj)
    elif kind in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        record_checkout(account.organization, obj)
    elif (kind or '').startswith('payout.'):
        from .payouts import record_payout
        record_payout(account.organization, obj)
    return HttpResponse(status=200)


# ---------------------------------------------------------------------------
# Versements (Paiements › Versements)
# ---------------------------------------------------------------------------

def _payouts_organization(request):
    from django.http import Http404
    from .views import _get_user_primary_organization
    organization = _get_user_primary_organization(request.user)
    if organization is None:
        raise Http404
    return organization


@login_required
def payouts_page(request):
    from . import payouts
    organization = _payouts_organization(request)
    account = stripe_connect.account_for(organization)
    return render(request, 'payments/payouts.html', {
        'page_title': 'Versements',
        'account': account,
        'connect_available': stripe_connect.available(),
        'payouts': payouts.recent(organization) if account else [],
        'upcoming': payouts.upcoming_total(organization) if account else 0,
        'currency': organization.default_currency,
        'payout_settings_url': payouts.STRIPE_PAYOUT_SETTINGS,
        'settings_url': _settings_url(),
    })


@login_required
@require_POST
def payouts_refresh(request):
    from . import payouts
    account = stripe_connect.account_for(_payouts_organization(request))
    if account:
        try:
            stripe_connect.sync(account)
            payouts.refresh(account)
            messages.success(request, 'Versements à jour.')
        except ProviderError as exc:
            messages.error(request, str(exc))
    return redirect('payments:payouts')


@login_required
def payout_detail(request, payout_id):
    from django.shortcuts import get_object_or_404
    from . import payouts
    from .models import StripePayout
    organization = _payouts_organization(request)
    payout = get_object_or_404(StripePayout, pk=payout_id, organization=organization)
    account = stripe_connect.account_for(organization)
    rows, totals, error = [], None, ''
    if account:
        try:
            rows, totals = payouts.breakdown(account, payout)
        except ProviderError as exc:
            error = str(exc)
    return render(request, 'payments/payout_detail.html', {
        'page_title': f'Versement du {payout.arrival_date:%d/%m/%Y}' if payout.arrival_date else 'Versement',
        'payout': payout, 'rows': rows, 'totals': totals, 'error': error,
        'bank_line': payout.bank_lines.first(),
    })
