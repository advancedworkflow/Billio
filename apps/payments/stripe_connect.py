"""
Paiement en ligne « clé en main » avec Stripe Connect : Billio est la plateforme (compte Stripe
de Billio, STRIPE_SECRET_KEY), chaque organisation a son propre compte Stripe connecté.

- Inscription hébergée par Stripe (identité, entreprise, IBAN) : Billio ne voit ni pièce
  d'identité ni coordonnées bancaires, seulement l'état du compte (StripeConnectAccount).
- Paiements en « direct charges » : la session Checkout est créée sur le compte de l'organisation
  (en-tête Stripe-Account). Elle est le vendeur ; frais Stripe, remboursements et litiges sont les
  siens ; Stripe lui verse l'argent sur son compte bancaire selon son rythme de versement.
- Commission Billio : `payment_fee_percent` dans les limites du forfait (0,5 % Gratuit / Starter /
  Pro, 0 % Business / Agency), prélevée par Stripe sur chaque paiement (application fee).
- Un seul webhook Connect pour toutes les organisations (STRIPE_CONNECT_WEBHOOK_SECRET) :
  `account.updated` tient l'état à jour, les paiements passent par `record_checkout`.

Le mode « mes propres clés » (plugin Stripe des Intégrations) reste possible ; Connect est utilisé
dès que le compte connecté peut encaisser.
"""
from decimal import ROUND_HALF_UP, Decimal

from apps.integrations.providers import ProviderError, http

API = 'https://api.stripe.com/v1'
DASHBOARD_URL = 'https://dashboard.stripe.com/'
DEFAULT_FEE_PERCENT = Decimal('0.5')


def platform_key():
    from apps.subscriptions.billing import secret_key
    return secret_key()


def available():
    """Connect est proposé dès que la clé Stripe de Billio est configurée."""
    return bool(platform_key())


def supported_country(country):
    from apps.organizations.jurisdictions import PACKS
    return country in PACKS


def _headers(account_id=''):
    headers = {'Authorization': f'Bearer {platform_key()}', 'Stripe-Version': '2024-06-20'}
    if account_id:
        headers['Stripe-Account'] = account_id
    return headers


def account_for(organization):
    from .models import StripeConnectAccount
    if not organization or not getattr(organization, 'pk', None):
        return None
    return StripeConnectAccount.objects.filter(organization=organization).first()


def active_account(organization):
    """Compte connecté qui peut encaisser (ou None)."""
    account = account_for(organization)
    return account if account and account.charges_enabled and available() else None


def fee_percent(organization):
    from apps.subscriptions.entitlements import plan_for
    value = plan_for(organization).limit('payment_fee_percent')
    return DEFAULT_FEE_PERCENT if value is None else Decimal(str(value))


def application_fee(organization, cents):
    """Commission Billio en centimes sur un paiement de `cents` centimes."""
    return int((Decimal(cents) * fee_percent(organization) / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _country(organization):
    from apps.organizations.jurisdictions import profile
    return profile(organization)['country']


def create_account(organization, email=''):
    """Crée le compte connecté de l'organisation (une seule fois) et le renvoie."""
    from .models import StripeConnectAccount
    existing = account_for(organization)
    if existing:
        return existing
    if not available():
        raise ProviderError("Le paiement en ligne n'est pas encore activé sur Billio.")
    country = _country(organization)
    if not supported_country(country):
        raise ProviderError("Le paiement en ligne n'est pas disponible dans votre pays. Vous pouvez relier votre propre compte Stripe dans les Intégrations.")
    form = {
        'country': country,
        # Compte avec tableau de bord Stripe complet : l'organisation est le vendeur, paie les frais
        # Stripe, et Stripe collecte lui-même les informations d'inscription.
        'controller[stripe_dashboard][type]': 'full',
        'controller[fees][payer]': 'account',
        'controller[losses][payments]': 'stripe',
        'controller[requirement_collection]': 'stripe',
        'business_profile[name]': organization.name[:255],
        'metadata[organization_id]': organization.id,
    }
    if email:
        form['email'] = email
    data = http('POST', f'{API}/accounts', form=form, headers=_headers())
    account = StripeConnectAccount.objects.create(organization=organization, account_id=data['id'], country=country)
    return sync(account, data)


def onboarding_url(account, refresh_url, return_url):
    """Lien (usage unique, quelques minutes) vers le formulaire d'inscription hébergé par Stripe."""
    link = http('POST', f'{API}/account_links', form={
        'account': account.account_id, 'refresh_url': refresh_url, 'return_url': return_url,
        'type': 'account_onboarding',
    }, headers=_headers())
    return link['url']


def sync(account, data=None):
    """Met à jour l'état du compte depuis Stripe (objet Account déjà reçu, sinon relu). Notifie l'activation."""
    if data is None:
        data = http('GET', f"{API}/accounts/{account.account_id}", headers=_headers())
    was_active = account.charges_enabled
    requirements = data.get('requirements') or {}
    dashboard = (data.get('settings') or {}).get('dashboard') or {}
    account.country = data.get('country') or account.country
    account.default_currency = (data.get('default_currency') or '')[:3]
    account.display_name = (dashboard.get('display_name') or (data.get('business_profile') or {}).get('name') or '')[:255]
    account.details_submitted = bool(data.get('details_submitted'))
    account.charges_enabled = bool(data.get('charges_enabled'))
    account.payouts_enabled = bool(data.get('payouts_enabled'))
    account.requirements = list(requirements.get('currently_due') or [])
    account.disabled_reason = (requirements.get('disabled_reason') or '')[:120]
    account.payout_schedule = schedule_label(((data.get('settings') or {}).get('payouts') or {}).get('schedule'))
    externals = (data.get('external_accounts') or {}).get('data') or []
    account.payout_destination = destination_label(next((e for e in externals if e.get('default_for_currency')),
                                                        externals[0] if externals else None))
    account.save()
    if account.charges_enabled and not was_active:
        _notify_active(account)
    return account


WEEKLY = {'monday': 'Chaque lundi', 'tuesday': 'Chaque mardi', 'wednesday': 'Chaque mercredi', 'thursday': 'Chaque jeudi',
          'friday': 'Chaque vendredi', 'saturday': 'Chaque samedi', 'sunday': 'Chaque dimanche'}


def schedule_label(schedule):
    """Rythme des versements tel que réglé dans Stripe : « Chaque jour », « Chaque lundi »…"""
    if not schedule:
        return ''
    interval = schedule.get('interval')
    if interval == 'daily':
        return 'Chaque jour'
    if interval == 'weekly':
        return WEEKLY.get(schedule.get('weekly_anchor'), 'Chaque semaine')
    if interval == 'monthly':
        return f"Chaque mois, le {schedule.get('monthly_anchor') or 1}"
    return 'À la demande' if interval == 'manual' else ''


def destination_label(external):
    """« BNP PARIBAS •••• 1234 » ou « Carte Visa •••• 4242 » (Billio n'a jamais l'IBAN complet)."""
    if not external:
        return ''
    if external.get('object') == 'card':
        return f"Carte {(external.get('brand') or '').title()} •••• {external.get('last4', '')}".replace('  ', ' ')
    return f"{external.get('bank_name') or 'Compte bancaire'} •••• {external.get('last4', '')}"[:120]


def _notify_active(account):
    from apps.dashboard.models import Notification
    owner = account.organization.owner
    if owner:
        Notification.objects.create(
            user=owner, notification_type='integration_connected', priority='medium',
            title='Paiement en ligne activé',
            message='Vos clients peuvent payer vos factures en ligne. Stripe verse les paiements sur votre compte bancaire.',
        )


def account_for_event(event):
    """Compte connecté visé par un évènement du webhook Connect (champ `account`)."""
    from .models import StripeConnectAccount
    account_id = event.get('account') or ''
    if not account_id:
        return None
    return StripeConnectAccount.objects.select_related('organization').filter(account_id=account_id).first()


def summary(organization):
    """État affiché dans Paramètres › Paiement."""
    account = account_for(organization)
    return {
        'available': available(),
        'supported': supported_country(_country(organization)) if organization else False,
        'account': account,
        'status': account.status if account else 'none',
        'fee_percent': fee_percent(organization) if organization else DEFAULT_FEE_PERCENT,
        'dashboard_url': DASHBOARD_URL,
    }


def fee_label(percent):
    """« 0,5 % » (format français, le middleware de traduction n'y touche pas)."""
    text = f'{Decimal(percent).normalize():f}'.replace('.', ',')
    return f'{text} %'
