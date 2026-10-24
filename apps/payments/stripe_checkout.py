"""
Paiement en ligne par Stripe Checkout, avec le compte Stripe de l'organisation
(plugin « Stripe » de la page Intégrations : clé secrète + secret du webhook).

Le paiement n'est jamais validé sur simple clic : une facture ou un jalon passe
« payé » seulement quand Stripe le confirme, soit au retour du client (session
relue côté serveur avec la clé secrète), soit par le webhook signé. Les deux
chemins appellent `record_checkout`, idempotent par identifiant de session.
"""
import hashlib
import hmac
import json
import time
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.integrations.providers import ProviderError, http

API = 'https://api.stripe.com/v1'
SIGNATURE_TOLERANCE = 300  # secondes


def stripe_instance(organization):
    """Connexion Stripe active de l'organisation (ou None)."""
    from apps.integrations.models import ConnectionInstance
    if not organization:
        return None
    instance = ConnectionInstance.objects.filter(
        organization=organization, connector__key='stripe', status='connected',
    ).first()
    return instance if instance and (instance.config or {}).get('secret_key') else None


def _headers(secret_key):
    return {'Authorization': f'Bearer {secret_key}', 'Stripe-Version': '2024-06-20'}


def account_label(secret_key):
    """Test de connexion : nom du compte Stripe et mode (test / production)."""
    account = http('GET', f'{API}/account', headers=_headers(secret_key))
    name = (account.get('settings') or {}).get('dashboard', {}).get('display_name') or account.get('email') or account.get('id', '?')
    mode = 'mode test' if secret_key.startswith(('sk_test_', 'rk_test_')) else 'mode production'
    return f'Compte Stripe « {name} » ({mode})'


def create_checkout(organization, *, amount, currency, label, metadata, success_url, cancel_url, customer_email=''):
    """Crée une session Checkout et renvoie son URL de paiement."""
    instance = stripe_instance(organization)
    if not instance:
        raise ProviderError("Le paiement par carte n'est pas activé pour cette entreprise.")
    cents = int((Decimal(amount) * 100).quantize(Decimal('1')))
    if cents < 50:
        raise ProviderError('Montant trop faible pour un paiement par carte.')
    form = {
        'mode': 'payment',
        'success_url': success_url,
        'cancel_url': cancel_url,
        'line_items[0][quantity]': 1,
        'line_items[0][price_data][currency]': (currency or 'EUR').lower(),
        'line_items[0][price_data][unit_amount]': cents,
        'line_items[0][price_data][product_data][name]': label[:250],
        'payment_intent_data[description]': label[:250],
    }
    for key, value in metadata.items():
        form[f'metadata[{key}]'] = str(value)
        form[f'payment_intent_data[metadata][{key}]'] = str(value)
    if customer_email:
        form['customer_email'] = customer_email
    session = http('POST', f'{API}/checkout/sessions', form=form, headers=_headers(instance.config['secret_key']))
    return session['url']


def retrieve_session(organization, session_id):
    instance = stripe_instance(organization)
    if not instance or not str(session_id).startswith('cs_'):
        return None
    return http('GET', f'{API}/checkout/sessions/{session_id}', headers=_headers(instance.config['secret_key']))


def verify_webhook(payload, signature_header, secret):
    """Vérifie l'en-tête Stripe-Signature (HMAC-SHA256) et renvoie l'évènement JSON."""
    if not secret or not signature_header:
        raise ValueError('Signature absente.')
    parts = dict(item.split('=', 1) for item in signature_header.split(',') if '=' in item)
    timestamp = parts.get('t', '')
    signatures = [value for key, value in (item.split('=', 1) for item in signature_header.split(',') if '=' in item) if key == 'v1']
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > SIGNATURE_TOLERANCE:
        raise ValueError('Signature expirée.')
    expected = hmac.new(secret.encode(), f'{timestamp}.'.encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in signatures):
        raise ValueError('Signature invalide.')
    return json.loads(payload)


def record_checkout(organization, session):
    """
    Enregistre un paiement confirmé par Stripe (session « paid »). Idempotent.
    Retourne ('invoice' | 'milestone', objet) ou None si la session ne concerne rien de connu.
    """
    if not session or session.get('payment_status') != 'paid':
        return None
    metadata = session.get('metadata') or {}
    if str(metadata.get('organization_id')) != str(organization.id):
        return None
    amount = Decimal(session.get('amount_total') or 0) / 100
    reference = session['id']

    if metadata.get('invoice_id'):
        return 'invoice', _record_invoice_payment(organization, metadata['invoice_id'], amount, reference, session)
    if metadata.get('milestone_id'):
        return 'milestone', _record_milestone_payment(organization, metadata['milestone_id'], reference)
    return None


def used_method(organization, session):
    """Type du moyen de paiement utilisé (card, sepa_debit, bancontact…), ou '' si Stripe ne le dit pas."""
    intent_id = session.get('payment_intent')
    instance = stripe_instance(organization)
    if not intent_id or not instance:
        return ''
    try:
        intent = http('GET', f'{API}/payment_intents/{intent_id}?expand[]=payment_method',
                      headers=_headers(instance.config['secret_key']))
    except ProviderError:
        return ''
    method = intent.get('payment_method') or {}
    wallet = ((method.get('card') or {}).get('wallet') or {}).get('type') if isinstance(method, dict) else None
    return wallet or (method.get('type', '') if isinstance(method, dict) else '')


def _record_invoice_payment(organization, invoice_id, amount, reference, session):
    from django.db.models import Sum
    from apps.invoices.models import Invoice
    from .models import Payment, PaymentMethod

    with transaction.atomic():
        invoice = Invoice.objects.select_for_update().filter(id=invoice_id, organization=organization).first()
        if not invoice or Payment.objects.filter(provider='stripe', provider_payment_id=reference).exists():
            return invoice
        from .local_methods import label as method_label
        used = used_method(organization, session)
        method = PaymentMethod.objects.filter(organization=organization, method_type='stripe', is_active=True).first() \
            or PaymentMethod.objects.create(organization=organization, method_type='stripe', is_active=True, name='Paiement en ligne (Stripe)')
        payment = Payment.objects.create(
            invoice=invoice, payment_method=method, amount=amount, currency=invoice.currency,
            status='completed', provider='stripe', provider_payment_id=reference,
            transaction_id=session.get('payment_intent') or None,
            payment_date=timezone.now(), processed_at=timezone.now(),
            notes=f"Paiement en ligne : {method_label(used)} (Stripe Checkout)." if used else 'Paiement en ligne (Stripe Checkout).',
            provider_data={'method': used} if used else None,
        )
        paid = invoice.payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or Decimal('0')
        fully_paid = invoice.amount_due(paid) <= Decimal('0.009')
        if fully_paid:
            invoice.mark_as_paid()

    from apps.dashboard.automation_engine import run_automations
    run_automations(
        organization, 'payment_received', source='invoice_online',
        target_type='payment', target_id=payment.id, amount=amount, client_id=invoice.client_id,
        variables={'numero': invoice.invoice_number},
        context_label=f"Paiement en ligne de {amount:.2f} € pour la facture {invoice.invoice_number}"
                      + (' (soldée).' if fully_paid else '.'),
    )
    return invoice


def _record_milestone_payment(organization, milestone_id, reference):
    from apps.dashboard.models import Milestone, Notification

    with transaction.atomic():
        milestone = Milestone.objects.select_for_update().select_related('project', 'project__client') \
            .filter(id=milestone_id, project__organization=organization).first()
        if not milestone or milestone.is_paid:
            return milestone
        milestone.is_paid = True
        milestone.paid_at = timezone.now()
        milestone.save(update_fields=['is_paid', 'paid_at', 'updated_at'])

    project = milestone.project
    client_name = project.client.get_display_name() if project.client_id else 'Le client'
    if organization.owner:
        Notification.objects.create(
            user=organization.owner, notification_type='payment_received', priority='medium',
            title=f"Jalon payé : « {milestone.title} »",
            message=f"{client_name} a réglé {milestone.amount} € par carte pour le projet « {project.name} ».",
        )
    from apps.dashboard.automation_engine import run_automations
    run_automations(
        organization, 'payment_received', source='milestone',
        target_type='milestone', target_id=milestone.id, amount=milestone.amount,
        client_id=project.client_id, project_id=project.id,
        variables={'projet': project.name, 'jalon': milestone.title},
        context_label=f"Jalon « {milestone.title} » payé par carte ({project.name}). Réf. Stripe {reference}.",
    )
    return milestone
