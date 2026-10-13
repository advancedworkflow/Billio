"""
Abonnement Billio via Stripe Billing, avec le compte Stripe de Billio (STRIPE_SECRET_KEY),
distinct des comptes Stripe que nos clients connectent pour encaisser leurs propres factures.

Parcours : forfait choisi → client Stripe créé ou retrouvé → Stripe Checkout (mode abonnement)
→ webhook signé → abonnement relu chez Stripe et enregistré → limites appliquées par Billio.
Les droits viennent toujours de l'état enregistré (`Subscription`), jamais d'un simple paiement passé.
"""
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.integrations.providers import ProviderError, http

API = 'https://api.stripe.com/v1'
STRIPE_VERSION = '2024-06-20'


class BillingError(Exception):
    pass


def secret_key():
    key = getattr(settings, 'STRIPE_SECRET_KEY', '') or ''
    return key if key.startswith(('sk_', 'rk_')) and 'your' not in key else ''


def is_configured():
    return bool(secret_key())


def _call(method, path, form=None):
    key = secret_key()
    if not key:
        raise BillingError("Le paiement des abonnements n'est pas encore configuré (clé Stripe de Billio manquante).")
    headers = {'Authorization': f'Bearer {key}', 'Stripe-Version': STRIPE_VERSION}
    try:
        return http(method, f'{API}{path}', form=form, headers=headers)
    except ProviderError as exc:
        raise BillingError(str(exc)) from None


# ---------- Abonnement local ----------

def get_subscription(user):
    """Abonnement du compte, créé au forfait Free s'il n'existe pas encore."""
    from .entitlements import free_plan
    from .models import Subscription
    subscription = Subscription.objects.select_related('plan').filter(user=user).first()
    if subscription:
        return subscription
    plan = free_plan()
    if not plan.pk:
        plan.save()
    return Subscription.objects.create(user=user, plan=plan, status='free')


# ---------- Prix et clients Stripe ----------

def price_lookup_key(plan):
    cents = int(plan.price_monthly * 100)
    return f'billio_{plan.code}_{cents}_eur_month'


def ensure_price(plan):
    """Prix Stripe mensuel du forfait (créé au besoin ; un nouveau prix si le tarif change)."""
    lookup = price_lookup_key(plan)
    found = _call('GET', '/prices?' + urlencode({'active': 'true', 'lookup_keys[0]': lookup}))
    if found.get('data'):
        price_id = found['data'][0]['id']
    else:
        product_id = f'billio_{plan.code}'
        try:
            _call('GET', f'/products/{product_id}')
        except BillingError:
            _call('POST', '/products', {'id': product_id, 'name': f'Billio {plan.name}',
                                        'metadata[plan]': plan.code})
        price = _call('POST', '/prices', {
            'product': product_id, 'currency': 'eur', 'unit_amount': int(plan.price_monthly * 100),
            'recurring[interval]': 'month', 'lookup_key': lookup, 'transfer_lookup_key': 'true',
            'tax_behavior': 'exclusive', 'metadata[plan]': plan.code,
        })
        price_id = price['id']
    if plan.stripe_price_id != price_id:
        plan.stripe_price_id = price_id
        plan.save(update_fields=['stripe_price_id', 'updated_at'])
    return price_id


def ensure_customer(subscription):
    if subscription.stripe_customer_id:
        return subscription.stripe_customer_id
    user = subscription.user
    customer = _call('POST', '/customers', {
        'email': user.email, 'name': user.get_full_name() or user.email,
        'metadata[user_id]': user.pk, 'preferred_locales[0]': 'fr',
    })
    subscription.stripe_customer_id = customer['id']
    subscription.save(update_fields=['stripe_customer_id', 'updated_at'])
    return customer['id']


def _tax_params(prefix):
    """TVA : taux Stripe fixe (STRIPE_TAX_RATE_ID) ou Stripe Tax (STRIPE_AUTOMATIC_TAX=1)."""
    rate = getattr(settings, 'STRIPE_TAX_RATE_ID', '')
    if rate:
        return {f'{prefix}[default_tax_rates][0]': rate}
    return {}


# ---------- Actions ----------

def create_checkout(subscription, plan, *, success_url, cancel_url):
    """Session Checkout pour passer d'un forfait gratuit à un forfait payant ; renvoie l'URL Stripe."""
    if plan.is_free:
        raise BillingError('Le forfait Free ne nécessite pas de paiement.')
    form = {
        'mode': 'subscription',
        'customer': ensure_customer(subscription),
        'line_items[0][price]': ensure_price(plan),
        'line_items[0][quantity]': 1,
        'success_url': success_url,
        'cancel_url': cancel_url,
        'client_reference_id': subscription.user_id,
        'metadata[user_id]': subscription.user_id,
        'metadata[plan]': plan.code,
        'subscription_data[metadata][user_id]': subscription.user_id,
        'subscription_data[metadata][plan]': plan.code,
        'allow_promotion_codes': 'true',
        'billing_address_collection': 'required',
        'tax_id_collection[enabled]': 'true',
        'customer_update[name]': 'auto',
        'customer_update[address]': 'auto',
        'locale': 'fr',
        **_tax_params('subscription_data'),
    }
    if getattr(settings, 'STRIPE_AUTOMATIC_TAX', False):
        form['automatic_tax[enabled]'] = 'true'
    session = _call('POST', '/checkout/sessions', form)
    return session['url']


def change_plan(subscription, plan):
    """Change de forfait payant (au prorata) ; vers Free = résiliation en fin de période."""
    if plan.is_free:
        return cancel(subscription)
    remote = _call('GET', f'/subscriptions/{subscription.stripe_subscription_id}')
    item_id = remote['items']['data'][0]['id']
    updated = _call('POST', f'/subscriptions/{subscription.stripe_subscription_id}', {
        'items[0][id]': item_id, 'items[0][price]': ensure_price(plan),
        'proration_behavior': 'create_prorations', 'cancel_at_period_end': 'false',
        'metadata[plan]': plan.code,
    })
    return sync_subscription(updated, user=subscription.user)


def cancel(subscription):
    """Résiliation en fin de période payée (le forfait reste actif jusque-là)."""
    updated = _call('POST', f'/subscriptions/{subscription.stripe_subscription_id}', {'cancel_at_period_end': 'true'})
    return sync_subscription(updated, user=subscription.user)


def resume(subscription):
    updated = _call('POST', f'/subscriptions/{subscription.stripe_subscription_id}', {'cancel_at_period_end': 'false'})
    return sync_subscription(updated, user=subscription.user)


def portal_url(subscription, return_url):
    """Portail Stripe : moyen de paiement, factures Billio, adresse de facturation."""
    session = _call('POST', '/billing_portal/sessions', {
        'customer': ensure_customer(subscription), 'return_url': return_url, 'locale': 'fr',
    })
    return session['url']


# ---------- Synchronisation depuis Stripe ----------

def _plan_from_remote(remote):
    from .models import Plan
    item = ((remote.get('items') or {}).get('data') or [{}])[0]
    price = item.get('price') or {}
    lookup = price.get('lookup_key') or ''
    if lookup.startswith('billio_'):
        plan = Plan.objects.filter(code=lookup.split('_')[1]).first()
        if plan:
            return plan
    if price.get('id'):
        plan = Plan.objects.filter(stripe_price_id=price['id']).first()
        if plan:
            return plan
    code = (price.get('metadata') or {}).get('plan') or (remote.get('metadata') or {}).get('plan')
    return Plan.objects.filter(code=code).first() if code else None


def _timestamp(value):
    return datetime.fromtimestamp(int(value), tz=dt_timezone.utc) if value else None


def sync_subscription(remote, user=None):
    """Enregistre l'état d'un abonnement Stripe (objet `subscription`). Idempotent."""
    from django.contrib.auth import get_user_model
    from .models import Subscription

    local = Subscription.objects.filter(stripe_subscription_id=remote['id']).first()
    if local is None:
        user_id = (remote.get('metadata') or {}).get('user_id')
        if user is None and user_id:
            user = get_user_model().objects.filter(pk=user_id).first()
        if user is None and remote.get('customer'):
            found = Subscription.objects.filter(stripe_customer_id=remote['customer']).first()
            user = found.user if found else None
        if user is None:
            return None
        local = get_subscription(user)
        if local.stripe_subscription_id and local.stripe_subscription_id != remote['id'] \
                and local.status in ('active', 'trialing', 'past_due') and remote.get('status') in ('canceled', 'incomplete_expired'):
            return local  # ancien abonnement terminé : ne pas écraser l'abonnement en cours

    with transaction.atomic():
        local = Subscription.objects.select_for_update().get(pk=local.pk)
        plan = _plan_from_remote(remote)
        if plan:
            local.plan = plan
        status = remote.get('status') or 'incomplete'
        if status == 'paused':
            status = 'unpaid'
        if status in ('past_due', 'unpaid'):
            local.past_due_since = local.past_due_since or timezone.now()
        else:
            local.past_due_since = None
        local.status = status
        local.stripe_subscription_id = remote['id']
        local.stripe_customer_id = remote.get('customer') or local.stripe_customer_id
        local.current_period_end = _timestamp(remote.get('current_period_end'))
        local.cancel_at_period_end = bool(remote.get('cancel_at_period_end'))
        local.save()
    return local


def sync_checkout(session_id, user):
    """Retour de Checkout : relit la session côté serveur (ne jamais croire le navigateur)."""
    if not str(session_id).startswith('cs_'):
        return None
    session = _call('GET', f'/checkout/sessions/{session_id}')
    if str(session.get('client_reference_id')) != str(user.pk) or not session.get('subscription'):
        return None
    remote = _call('GET', f"/subscriptions/{session['subscription']}")
    return sync_subscription(remote, user=user)


def handle_event(event):
    """Évènement de webhook déjà vérifié. Renvoie l'abonnement local mis à jour (ou None)."""
    kind = event.get('type', '')
    obj = (event.get('data') or {}).get('object') or {}
    subscription_id = None
    user = None
    if kind == 'checkout.session.completed' and obj.get('mode') == 'subscription':
        subscription_id = obj.get('subscription')
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.filter(pk=obj.get('client_reference_id') or 0).first()
    elif kind.startswith('customer.subscription.'):
        subscription_id = obj.get('id')
    elif kind in ('invoice.paid', 'invoice.payment_failed', 'invoice.payment_succeeded'):
        subscription_id = obj.get('subscription')
    if not subscription_id:
        return None
    remote = _call('GET', f'/subscriptions/{subscription_id}')  # état le plus récent, quel que soit l'ordre des évènements
    local = sync_subscription(remote, user=user)
    if local and kind == 'invoice.payment_failed':
        _notify_payment_failed(local)
    return local


def _notify_payment_failed(subscription):
    from apps.dashboard.models import Notification
    ends = subscription.grace_ends_at
    Notification.objects.create(
        user=subscription.user, notification_type='subscription_expiring', priority='high',
        title='Paiement de votre abonnement refusé',
        message=(f"Le prélèvement de votre forfait {subscription.plan.name} a échoué. Mettez à jour votre carte"
                 + (f" avant le {timezone.localtime(ends):%d/%m/%Y}" if ends else '')
                 + " pour garder vos options ; sinon votre compte repassera aux limites du forfait Free."),
    )
