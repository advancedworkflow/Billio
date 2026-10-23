"""
Views for payments app.
"""
import re
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
    from datetime import datetime
    from decimal import InvalidOperation
    from .recording import PaymentError, record_manual_payment

    invoice = _get_open_invoice_for_user(request.user, request.POST.get('invoice_id'))
    try:
        amount = Decimal((request.POST.get('amount') or '').replace(',', '.').replace(' ', '')).quantize(Decimal('0.01'))
    except InvalidOperation:
        return JsonResponse({'ok': False, 'error': 'Montant invalide.'}, status=400)
    try:
        day = datetime.strptime(request.POST.get('date') or '', '%Y-%m-%d').date()
    except ValueError:
        day = timezone.localdate()
    try:
        _payment, fully_paid, left = record_manual_payment(
            invoice, amount, day, method_type=request.POST.get('method_type') or 'bank_transfer',
            reference=request.POST.get('reference') or '', notes=request.POST.get('notes') or '', user=request.user)
    except PaymentError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    message = 'Facture soldée.' if fully_paid else f'Paiement partiel enregistré — reste {left:.2f} €.'.replace('.', ',', 1)
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
    from apps.accounts.email_verification import client_email_blocked
    blocked = client_email_blocked(invoice.organization)
    if blocked:
        return JsonResponse({'ok': False, 'error': blocked}, status=400)
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


def _clean_method_fields(method_type, bank_name, account_holder, iban, bic):
    """Garde seulement les champs du type choisi et les vérifie. Renvoie (champs, erreur)."""
    empty = {'bank_name': None, 'account_holder': None, 'iban': None, 'bic': None}
    if method_type == 'bank_transfer':
        iban = re.sub(r'\s+', '', iban).upper()
        bic = re.sub(r'\s+', '', bic).upper()
        if not account_holder:
            return None, 'Indiquez le titulaire du compte.'
        if not _iban_is_valid(iban):
            return None, 'IBAN invalide : vérifiez les caractères saisis.'
        if bic and not re.fullmatch(r'[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?', bic):
            return None, 'BIC invalide (8 ou 11 caractères).'
        return dict(empty, bank_name=bank_name[:100] or None, account_holder=account_holder[:100], iban=iban, bic=bic or None), None
    if method_type == 'check':
        if not account_holder:
            return None, "Indiquez l'ordre des chèques."
        return dict(empty, account_holder=account_holder[:100]), None
    if method_type == 'paypal':
        address = account_holder.strip()
        if not (re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', address)
                or re.fullmatch(r'(https?://)?(www\.)?paypal\.me/[\w.-]+/?', address, re.I)):
            return None, 'Adresse PayPal invalide : email ou lien paypal.me/…'
        return dict(empty, account_holder=address[:100]), None
    return empty, None  # carte / Stripe / espèces : rien à saisir


def _iban_is_valid(iban):
    if not re.fullmatch(r'[A-Z]{2}\d{2}[A-Z0-9]{10,30}', iban or ''):
        return False
    digits = ''.join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    return int(digits) % 97 == 1


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
    fields, error = _clean_method_fields(method_type, bank_name, account_holder, iban, bic)
    if error:
        return JsonResponse({'ok': False, 'error': error}, status=400)

    organization = _get_user_primary_organization(request.user)
    if not organization:
        return JsonResponse({'ok': False, 'error': 'Aucune organisation disponible.'}, status=400)

    method = PaymentMethod.objects.create(
        organization=organization,
        name=name,
        method_type=method_type,
        is_default=is_default,
        **fields,
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
    fields, error = _clean_method_fields(method_type, bank_name, account_holder, iban, bic)
    if error:
        return JsonResponse({'ok': False, 'error': error}, status=400)

    method.name = name
    method.method_type = method_type
    for field, value in fields.items():
        setattr(method, field, value)
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
