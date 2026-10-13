"""
Views for payments app.
"""
from django.db.models import Q, Sum
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, get_object_or_404
from decimal import Decimal
from rest_framework import viewsets, generics
from rest_framework.permissions import IsAuthenticated
from apps.integrations.providers import org_mail

from .models import Payment, PaymentMethod, Transaction
from .serializers import PaymentSerializer, PaymentMethodSerializer, TransactionSerializer


class PaymentViewSet(viewsets.ModelViewSet):
    """ViewSet for Payment model."""
    queryset = Payment.objects.all()  # Required for DRF router basename detection
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter payments based on user's organizations."""
        from django.db.models import Q, Sum
        return Payment.objects.filter(
            Q(invoice__organization__owner=self.request.user) |
            Q(invoice__organization__members__user=self.request.user)
        ).distinct()


class PaymentMethodViewSet(viewsets.ModelViewSet):
    """ViewSet for PaymentMethod model."""
    queryset = PaymentMethod.objects.all()  # Required for DRF router basename detection
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter payment methods based on user's organizations."""
        from django.db.models import Q, Sum
        return PaymentMethod.objects.filter(
            Q(organization__owner=self.request.user) |
            Q(organization__members__user=self.request.user)
        ).distinct()


@csrf_exempt
@require_POST
def stripe_webhook(request, organization_id):
    """
    Webhook Stripe d'une organisation (URL indiquée sur la page Intégrations).
    Signature vérifiée avec le secret du webhook de l'organisation ; seul
    `checkout.session.completed` (payé) est traité. Idempotent.
    """
    from apps.organizations.models import Organization
    from .stripe_checkout import record_checkout, stripe_instance, verify_webhook

    organization = Organization.objects.filter(id=organization_id).first()
    instance = stripe_instance(organization)
    if not instance:
        return HttpResponse(status=404)
    try:
        event = verify_webhook(request.body, request.META.get('HTTP_STRIPE_SIGNATURE', ''),
                               (instance.config or {}).get('webhook_secret', ''))
    except (ValueError, KeyError):
        return HttpResponse(status=400)
    if event.get('type') in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        record_checkout(organization, (event.get('data') or {}).get('object') or {})
    return HttpResponse(status=200)


def _get_user_primary_organization(user):
    organization = user.owned_organizations.first()
    if organization:
        return organization
    membership = user.organization_memberships.select_related('organization').first()
    return membership.organization if membership else None


def _get_payment_method_for_user(user, method_id):
    return get_object_or_404(
        PaymentMethod.objects.filter(
            Q(organization__owner=user) | Q(organization__members__user=user)
        ).distinct(),
        id=method_id
    )


@login_required
def payments_page(request):
    """Main payments page: payment methods (to get paid) + recent payment history."""
    payment_methods = PaymentMethod.objects.filter(
        Q(organization__owner=request.user) | Q(organization__members__user=request.user)
    ).distinct().order_by('-is_default', 'name')

    recent_payments = Payment.objects.filter(
        Q(invoice__organization__owner=request.user) | Q(invoice__organization__members__user=request.user)
    ).select_related('invoice', 'invoice__client', 'payment_method').distinct().order_by('-created_at')[:20]

    from . import cashflow
    organization = _get_user_primary_organization(request.user)
    flow = cashflow.build(organization) if organization else None
    open_invoices = []
    if flow:
        for bucket in ('overdue', 'week', 'later'):
            open_invoices += flow['queue'][bucket]

    context = {
        'payment_methods': payment_methods,
        'recent_payments': recent_payments,
        'payment_method_types': PaymentMethod.METHOD_CHOICES,
        'flow': flow,
        'queue_buckets': [
            ('overdue', 'En retard', flow['queue']['overdue']),
            ('week', 'À échéance cette semaine', flow['queue']['week']),
            ('later', 'Plus tard', flow['queue']['later']),
        ] if flow else [],
        # Données du formulaire « Enregistrer un paiement » (factures ouvertes + reste dû).
        'open_invoices_data': [
            {
                'id': str(i.id), 'number': i.invoice_number, 'client': i.client.name if i.client_id else '—',
                'remaining': f'{i.remaining:.2f}', 'total': f'{i.total_amount:.2f}',
            }
            for i in open_invoices
        ],
        'today': timezone.localdate().isoformat(),
        'page_title': 'Paiements',
    }
    return render(request, 'payments/list.html', context)


def _get_open_invoice_for_user(user, invoice_id):
    from apps.invoices.models import Invoice
    return get_object_or_404(
        Invoice.objects.distinct(),
        Q(id=invoice_id) & (Q(organization__owner=user) | Q(organization__members__user=user)),
    )


@login_required
@require_POST
def record_payment(request):
    """
    Enregistre un paiement reçu hors ligne (virement, chèque, espèces…), total ou partiel.
    La facture passe à « payée » quand le reste dû est couvert ; chaque paiement déclenche
    les automatisations « Paiement reçu ».
    """
    from datetime import datetime, time
    from decimal import InvalidOperation
    from . import cashflow

    invoice = _get_open_invoice_for_user(request.user, request.POST.get('invoice_id'))
    if invoice.status not in cashflow.OPEN_STATUSES:
        return JsonResponse({'ok': False, 'error': "Cette facture n'attend pas de paiement."}, status=400)

    paid = invoice.payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    remaining = invoice.amount_due(paid)
    try:
        amount = Decimal((request.POST.get('amount') or '').replace(',', '.').replace(' ', '')).quantize(Decimal('0.01'))
    except InvalidOperation:
        return JsonResponse({'ok': False, 'error': 'Montant invalide.'}, status=400)
    if amount <= 0:
        return JsonResponse({'ok': False, 'error': 'Le montant doit être positif.'}, status=400)
    if amount > remaining + Decimal('0.01'):
        return JsonResponse({'ok': False, 'error': f'Le montant dépasse le reste dû ({remaining:.2f} €).'.replace('.', ',', 1)}, status=400)

    try:
        day = datetime.strptime(request.POST.get('date') or '', '%Y-%m-%d').date()
    except ValueError:
        day = timezone.localdate()
    if day > timezone.localdate():
        return JsonResponse({'ok': False, 'error': 'La date ne peut pas être dans le futur.'}, status=400)
    paid_at = timezone.make_aware(datetime.combine(day, time(12, 0)))

    method_type = request.POST.get('method_type') or 'bank_transfer'
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
        status='completed', provider='manual', provider_payment_id=(request.POST.get('reference') or '').strip()[:255] or None,
        payment_date=paid_at, processed_at=timezone.now(),
        notes=(request.POST.get('notes') or '').strip()[:2000], created_by=request.user,
    )

    fully_paid = amount >= remaining - Decimal('0.009')
    if fully_paid:
        invoice.mark_as_paid()
        Invoice = type(invoice)
        Invoice.objects.filter(id=invoice.id).update(paid_at=paid_at)

    from apps.dashboard.automation_engine import run_automations
    run_automations(
        invoice.organization, 'payment_received',
        source='manual',
        target_type='payment', target_id=payment.id, amount=amount, client_id=invoice.client_id,
        variables={'numero': invoice.invoice_number},
        context_label=(
            f"Paiement de {amount:.2f} € reçu pour la facture {invoice.invoice_number}"
            + (" (soldée)." if fully_paid else f" — reste {remaining - amount:.2f} €.")
        ),
    )
    message = 'Facture soldée.' if fully_paid else f'Paiement partiel enregistré — reste {remaining - amount:.2f} €.'.replace('.', ',', 1)
    return JsonResponse({'ok': True, 'fully_paid': fully_paid, 'message': message})


@login_required
@require_POST
def send_payment_reminder(request, invoice_id):
    """Relance le client par email avec le lien de paiement de la facture."""
    from django.conf import settings
    from django.core.mail import send_mail
    from django.urls import reverse
    from . import cashflow

    invoice = _get_open_invoice_for_user(request.user, invoice_id)
    if invoice.status not in cashflow.OPEN_STATUSES:
        return JsonResponse({'ok': False, 'error': "Cette facture n'attend pas de paiement."}, status=400)
    client = invoice.client
    if not client or not client.email:
        return JsonResponse({'ok': False, 'error': "Le client n'a pas d'adresse email."}, status=400)
    if invoice.last_reminder_at and timezone.now() - invoice.last_reminder_at < timezone.timedelta(hours=24):
        return JsonResponse({'ok': False, 'error': 'Une relance a déjà été envoyée il y a moins de 24 h.'}, status=400)

    paid = invoice.payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    remaining = invoice.amount_due(paid)
    link = f"{settings.SITE_URL}{reverse('invoices:public-invoice-payment', args=[invoice.id])}"
    late = (timezone.localdate() - invoice.due_date).days
    due_line = (
        f"Elle est arrivée à échéance le {invoice.due_date:%d/%m/%Y} ({late} jour{'s' if late > 1 else ''} de retard)."
        if late > 0 else f"Elle arrive à échéance le {invoice.due_date:%d/%m/%Y}."
    )
    org = invoice.organization
    send_mail(
        subject=f"Rappel — facture {invoice.invoice_number} ({remaining:.2f} €)".replace('.', ','),
        message=(
            f"Bonjour {client.name},\n\n"
            f"Sauf erreur de notre part, la facture {invoice.invoice_number} d'un montant restant de "
            f"{remaining:.2f} € est toujours en attente de règlement. {due_line}\n\n"
            f"Vous pouvez la consulter et la régler ici : {link}\n\n"
            f"Si le paiement a déjà été effectué, merci de ne pas tenir compte de ce message.\n\n{org.name}"
        ).replace(f"{remaining:.2f} €", f"{remaining:.2f} €".replace('.', ',')),
        from_email=org_mail(org)[1],
        connection=org_mail(org)[0],  # SMTP de l'organisation s'il est connecté
        recipient_list=[client.email],
        fail_silently=False,
    )
    invoice.last_reminder_at = timezone.now()
    invoice.save(update_fields=['last_reminder_at', 'updated_at'])
    return JsonResponse({'ok': True, 'message': f'Relance envoyée à {client.email}.'})


@login_required
@require_POST
def payment_method_quick_create(request):
    """Create a new payment method from modal popup."""
    name = (request.POST.get('name') or '').strip()
    method_type = (request.POST.get('method_type') or 'bank_transfer').strip()
    bank_name = (request.POST.get('bank_name') or '').strip()
    account_holder = (request.POST.get('account_holder') or '').strip()
    iban = (request.POST.get('iban') or '').strip()
    bic = (request.POST.get('bic') or '').strip()
    is_default = request.POST.get('is_default', 'false') == 'true'

    if not name:
        return JsonResponse({'ok': False, 'error': 'Nom requis.'}, status=400)

    if method_type not in dict(PaymentMethod.METHOD_CHOICES):
        return JsonResponse({'ok': False, 'error': 'Type de moyen de paiement invalide.'}, status=400)

    organization = _get_user_primary_organization(request.user)
    if not organization:
        return JsonResponse({'ok': False, 'error': 'Aucune organisation disponible.'}, status=400)

    method = PaymentMethod.objects.create(
        organization=organization,
        name=name,
        method_type=method_type,
        bank_name=bank_name or None,
        account_holder=account_holder or None,
        iban=iban or None,
        bic=bic or None,
        is_default=is_default,
        is_active=True,
    )

    return JsonResponse({'ok': True, 'id': method.id, 'name': method.name})


@login_required
@require_POST
def payment_method_quick_update(request, method_id):
    """Update a payment method from edit modal."""
    method = _get_payment_method_for_user(request.user, method_id)

    name = (request.POST.get('name') or '').strip()
    method_type = (request.POST.get('method_type') or method.method_type).strip()
    bank_name = (request.POST.get('bank_name') or '').strip()
    account_holder = (request.POST.get('account_holder') or '').strip()
    iban = (request.POST.get('iban') or '').strip()
    bic = (request.POST.get('bic') or '').strip()
    is_active = request.POST.get('is_active', 'true') == 'true'

    if not name:
        return JsonResponse({'ok': False, 'error': 'Nom requis.'}, status=400)

    if method_type not in dict(PaymentMethod.METHOD_CHOICES):
        return JsonResponse({'ok': False, 'error': 'Type de moyen de paiement invalide.'}, status=400)

    method.name = name
    method.method_type = method_type
    method.bank_name = bank_name or None
    method.account_holder = account_holder or None
    method.iban = iban or None
    method.bic = bic or None
    method.is_active = is_active
    method.save()

    return JsonResponse({'ok': True})


@login_required
@require_POST
def payment_method_set_default(request, method_id):
    """Mark a payment method as the default one."""
    method = _get_payment_method_for_user(request.user, method_id)
    method.is_default = True
    method.save()  # PaymentMethod.save() unsets other defaults for the org
    return JsonResponse({'ok': True})


@login_required
@require_POST
def payment_method_quick_delete(request, method_id):
    """Delete a payment method."""
    method = _get_payment_method_for_user(request.user, method_id)
    method.delete()
    return JsonResponse({'ok': True})
