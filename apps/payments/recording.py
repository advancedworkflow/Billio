"""
Enregistrer (ou annuler) un paiement reçu hors ligne sur une facture : formulaire « Enregistrer
un paiement » de la page Paiements et rapprochement bancaire (apps/payments/reconciliation.py).
"""
from datetime import datetime, time
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from .models import Payment, PaymentMethod


class PaymentError(ValueError):
    pass


def paid_total(invoice):
    return invoice.payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or Decimal('0')


def record_manual_payment(invoice, amount, day, *, method_type='bank_transfer', reference='', notes='', user=None,
                          source='manual'):
    """Paiement total ou partiel ; la facture passe à « payée » quand le reste dû est couvert.

    Renvoie (paiement, soldée, reste après paiement). Lève PaymentError si le montant ne convient pas.
    """
    from . import cashflow

    if invoice.status not in cashflow.OPEN_STATUSES:
        raise PaymentError("Cette facture n'attend pas de paiement.")
    remaining = invoice.amount_due(paid_total(invoice))
    amount = Decimal(amount).quantize(Decimal('0.01'))
    if amount <= 0:
        raise PaymentError('Le montant doit être positif.')
    if amount > remaining + Decimal('0.01'):
        raise PaymentError(f'Le montant dépasse le reste dû ({remaining:.2f}).'.replace('.', ',', 1))
    if day > timezone.localdate():
        raise PaymentError('La date ne peut pas être dans le futur.')
    paid_at = timezone.make_aware(datetime.combine(day, time(12, 0)))

    if method_type not in dict(PaymentMethod.METHOD_CHOICES):
        method_type = 'bank_transfer'
    payment_method = PaymentMethod.objects.filter(
        organization=invoice.organization, method_type=method_type, is_active=True,
    ).order_by('-is_default').first() or PaymentMethod.objects.create(
        organization=invoice.organization, method_type=method_type, is_active=True,
        name=f"Paiement manuel — {dict(PaymentMethod.METHOD_CHOICES)[method_type]}",
    )
    payment = Payment.objects.create(
        invoice=invoice, payment_method=payment_method, amount=amount, currency=invoice.currency,
        status='completed', provider='manual', provider_payment_id=(reference or '').strip()[:255] or None,
        payment_date=paid_at, processed_at=timezone.now(), notes=(notes or '').strip()[:2000], created_by=user,
    )

    fully_paid = amount >= remaining - Decimal('0.009')
    if fully_paid:
        invoice.mark_as_paid()
        type(invoice).objects.filter(id=invoice.id).update(paid_at=paid_at)

    from apps.dashboard.automation_engine import run_automations
    run_automations(
        invoice.organization, 'payment_received', source=source,
        target_type='payment', target_id=payment.id, amount=amount, client_id=invoice.client_id,
        variables={'numero': invoice.invoice_number},
        context_label=(f"Paiement de {amount:.2f} reçu pour la facture {invoice.invoice_number}"
                       + (" (soldée)." if fully_paid else f" — reste {remaining - amount:.2f}.")),
    )
    return payment, fully_paid, max(remaining - amount, Decimal('0'))


def cancel_manual_payment(payment):
    """Supprime un paiement saisi à la main et rouvre la facture s'il n'est plus soldée."""
    invoice = payment.invoice
    payment.delete()
    if invoice.status == 'paid' and invoice.amount_due(paid_total(invoice)) > Decimal('0.009'):
        invoice.status = 'overdue' if invoice.due_date and invoice.due_date < timezone.localdate() else 'sent'
        invoice.paid_at = None
        invoice.save(update_fields=['status', 'paid_at', 'updated_at'])
