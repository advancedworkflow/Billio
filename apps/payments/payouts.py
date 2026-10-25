"""
Versements Stripe des organisations connectées (Stripe Connect, apps/payments/stripe_connect.py).

Stripe regroupe les paiements encaissés, déduit ses frais et la commission Billio, puis verse le
net sur le compte bancaire (ou la carte) de l'organisation, selon le rythme réglé dans son
tableau de bord Stripe. Billio garde l'historique (`StripePayout`, tenu à jour par le webhook
Connect `payout.*`), détaille chaque versement (paiements, frais) et rapproche le virement reçu
sur le relevé bancaire (`BankLine.payout`) : les paiements sont déjà enregistrés facture par
facture, la ligne du relevé est donc rapprochée sans créer de paiement.
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.db import transaction

from apps.integrations.providers import http

from . import stripe_connect

API = stripe_connect.API
STRIPE_PAYOUT_SETTINGS = 'https://dashboard.stripe.com/settings/payouts'
ARRIVAL_WINDOW = (2, 5)  # jours avant / après la date d'arrivée annoncée par Stripe


def _amount(cents):
    return (Decimal(cents or 0) / 100).quantize(Decimal('0.01'))


def _date(timestamp):
    return datetime.fromtimestamp(timestamp, tz=dt_timezone.utc).date() if timestamp else None


def record_payout(organization, obj):
    """Crée ou met à jour un versement depuis l'objet Payout de Stripe. Notifie un échec."""
    from .models import StripePayout
    if not obj.get('id', '').startswith('po_'):
        return None
    status = obj.get('status') if obj.get('status') in dict(StripePayout.STATUS_CHOICES) else 'pending'
    destination = obj.get('destination')
    defaults = {
        'organization': organization,
        'amount': _amount(obj.get('amount')),
        'currency': (obj.get('currency') or 'eur').upper(),
        'status': status,
        'method': obj.get('method') or 'standard',
        'arrival_date': _date(obj.get('arrival_date')),
        'failure_message': (obj.get('failure_message') or '')[:255],
        'created': datetime.fromtimestamp(obj['created'], tz=dt_timezone.utc) if obj.get('created') else None,
    }
    if isinstance(destination, dict):
        defaults['destination'] = stripe_connect.destination_label(destination)
    with transaction.atomic():
        previous = StripePayout.objects.select_for_update().filter(payout_id=obj['id']).first()
        payout, _ = StripePayout.objects.update_or_create(payout_id=obj['id'], defaults=defaults)
    if status == 'failed' and (previous is None or previous.status != 'failed'):
        _notify_failed(payout)
    if status == 'paid':
        match_bank_lines(organization)
    return payout


def _notify_failed(payout):
    from apps.dashboard.models import Notification
    owner = payout.organization.owner
    detail = f' ({payout.failure_message})' if payout.failure_message else ''
    if owner:
        Notification.objects.create(
            user=owner, notification_type='payment_received', priority='high',
            title='Versement Stripe échoué',
            message=f"Le versement de {payout.amount} {payout.currency} n'a pas pu être fait{detail}. Vérifiez votre compte bancaire dans votre tableau de bord Stripe.",  # noqa: E501
        )


def refresh(account, limit=30):
    """Relit les derniers versements chez Stripe (bouton « Actualiser », complément du webhook)."""
    data = http('GET', f'{API}/payouts?limit={limit}&expand[]=data.destination',
                headers=stripe_connect._headers(account.account_id))
    return [record_payout(account.organization, obj) for obj in data.get('data') or []]


def breakdown(account, payout):
    """
    Détail d'un versement : une ligne par mouvement (paiement, remboursement, frais…) avec la
    facture Billio correspondante quand on la retrouve. Lu en direct chez Stripe.
    """
    from .models import Payment
    data = http('GET', f'{API}/balance_transactions?payout={payout.payout_id}&limit=100&expand[]=data.source',
                headers=stripe_connect._headers(account.account_id))
    rows = []
    for tx in data.get('data') or []:
        if tx.get('type') == 'payout':
            continue
        source = tx.get('source') if isinstance(tx.get('source'), dict) else {}
        intent = source.get('payment_intent') or ''
        payment = Payment.objects.select_related('invoice', 'invoice__client').filter(
            transaction_id=intent, invoice__organization=account.organization).first() if intent else None
        rows.append({
            'type': tx.get('type', ''),
            'label': TYPE_LABELS.get(tx.get('type'), tx.get('type', '')),
            'description': tx.get('description') or '',
            'date': _date(tx.get('created')),
            'gross': _amount(tx.get('amount')),
            'fee': _amount(tx.get('fee')),
            'net': _amount(tx.get('net')),
            'invoice': payment.invoice if payment else None,
        })
    totals = {key: sum((r[key] for r in rows), Decimal('0')) for key in ('gross', 'fee', 'net')}
    return rows, totals


TYPE_LABELS = {
    'charge': 'Paiement', 'payment': 'Paiement', 'refund': 'Remboursement', 'payment_refund': 'Remboursement',
    'adjustment': 'Ajustement', 'stripe_fee': 'Frais Stripe', 'application_fee': 'Commission Billio',
    'dispute': 'Litige', 'payment_failure_refund': 'Paiement échoué',
}


def match_bank_lines(organization):
    """
    Rapproche les lignes du relevé qui correspondent à un versement Stripe versé : même montant,
    date proche de l'arrivée annoncée. Renvoie le nombre de lignes rapprochées.
    """
    from .models import BankLine, StripePayout
    matched = 0
    payouts = StripePayout.objects.filter(organization=organization, status='paid', arrival_date__isnull=False,
                                          bank_lines__isnull=True, bank_match_dismissed=False)
    for payout in payouts:
        before, after = ARRIVAL_WINDOW
        line = (BankLine.objects.filter(organization=organization, status='pending', amount=payout.amount,
                                        date__gte=payout.arrival_date - timedelta(days=before),
                                        date__lte=payout.arrival_date + timedelta(days=after))
                .order_by('date').first())
        if line:
            line.status, line.payout = 'matched', payout
            line.save(update_fields=['status', 'payout'])
            matched += 1
    return matched


def recent(organization, limit=50):
    from .models import StripePayout
    return StripePayout.objects.filter(organization=organization).prefetch_related('bank_lines')[:limit]


def upcoming_total(organization):
    """Montant des versements pas encore arrivés (en préparation ou en cours)."""
    from django.db.models import Sum

    from .models import StripePayout
    total = StripePayout.objects.filter(organization=organization, status__in=('pending', 'in_transit')) \
        .aggregate(total=Sum('amount'))['total']
    return total or Decimal('0')
