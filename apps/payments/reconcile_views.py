"""
Pages « Rapprocher mes encaissements » (Paiements) : importer un relevé, valider les
correspondances proposées, ignorer ou annuler. La logique est dans reconciliation.py.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import reconciliation as rec
from .models import BankLine
from .recording import PaymentError
from .views import _get_user_primary_organization

TABS = ('pending', 'matched', 'ignored')


def _plural(count, word):
    return f"{count} {word}{'s' if count > 1 else ''}"


def _organization(request):
    organization = _get_user_primary_organization(request.user)
    if organization is None:
        raise Http404
    return organization


def _line(request, line_id):
    return get_object_or_404(BankLine, pk=line_id, organization=_organization(request))


def _back(tab='pending'):
    return redirect(f"{reverse('payments:reconcile')}?tab={tab}")


@login_required
def reconcile_page(request):
    organization = _organization(request)
    tab = request.GET.get('tab') if request.GET.get('tab') in TABS else 'pending'
    from .payouts import match_bank_lines
    match_bank_lines(organization)  # virements de Stripe : rapprochés avec leur versement
    lines = BankLine.objects.filter(organization=organization)
    counts = {status: lines.filter(status=status).count() for status in TABS}
    invoices = rec.open_invoices(organization)
    rows = [
        {'line': line, 'suggestion': rec.suggest(line, invoices) if tab == 'pending' else None}
        for line in lines.filter(status=tab).select_related('payment__invoice', 'payment__invoice__client', 'payout')[:200]
    ]
    return render(request, 'payments/reconcile.html', {
        'page_title': 'Rapprocher mes encaissements',
        'tab': tab, 'counts': counts, 'rows': rows,
        'sure_count': sum(1 for r in rows if r['suggestion'] and r['suggestion']['sure']),
        'invoice_choices': [
            {'id': str(i.id), 'number': i.invoice_number, 'client': i.client.name if i.client_id else '—',
             'remaining': i.remaining, 'currency': i.currency}
            for i in invoices
        ],
        'today': timezone.localdate().isoformat(),
        'currency': organization.default_currency,
    })


@login_required
@require_POST
def reconcile_import(request):
    from apps.organizations.jurisdictions import profile

    organization = _organization(request)
    upload = request.FILES.get('statement')
    if not upload:
        messages.error(request, 'Choisissez le fichier CSV de votre relevé bancaire.')
        return _back()
    if upload.size > 5 * 1024 * 1024:
        messages.error(request, 'Fichier trop lourd (5 Mo maximum) : exportez une période plus courte.')
        return _back()
    try:
        entries, debits = rec.parse_statement(upload.read(), month_first=profile(organization)['country'] == 'US')
    except rec.StatementError as exc:
        messages.error(request, str(exc))
        return _back()
    created, duplicates = rec.import_lines(organization, entries, user=request.user)
    messages.success(request, f"Encaissements importés : {created} · déjà présents : {duplicates} · "
                              f"sorties d'argent ignorées : {debits}.")
    return _back()


@login_required
@require_POST
def reconcile_add(request):
    organization = _organization(request)
    try:
        day = datetime.strptime(request.POST.get('date') or '', '%Y-%m-%d').date()
        amount = Decimal((request.POST.get('amount') or '').replace(',', '.').replace(' ', '')).quantize(Decimal('0.01'))
    except (ValueError, InvalidOperation):
        messages.error(request, 'Indiquez une date et un montant valides.')
        return _back()
    if amount <= 0 or day > timezone.localdate():
        messages.error(request, 'Le montant doit être positif et la date ne peut pas être dans le futur.')
        return _back()
    rec.add_line(organization, day, amount, (request.POST.get('label') or '').strip(), user=request.user)
    messages.success(request, 'Encaissement ajouté : choisissez la facture correspondante.')
    return _back()


@login_required
@require_POST
def reconcile_match(request, line_id):
    from apps.invoices.models import Invoice

    line = _line(request, line_id)
    invoice = get_object_or_404(Invoice, pk=request.POST.get('invoice_id') or None, organization=line.organization)
    try:
        fully_paid, left = rec.match(line, invoice, user=request.user)
    except (rec.StatementError, PaymentError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Facture {invoice.invoice_number} soldée.' if fully_paid else
                         f'Paiement partiel enregistré sur {invoice.invoice_number} — reste {left:.2f}.')
    return _back()


@login_required
@require_POST
def reconcile_match_sure(request):
    """Valide d'un coup toutes les correspondances sûres."""
    organization = _organization(request)
    done = 0
    for line in BankLine.objects.filter(organization=organization, status='pending').order_by('date'):
        suggestion = rec.suggest(line, rec.open_invoices(organization))
        if suggestion and suggestion['sure']:
            try:
                rec.match(line, suggestion['invoice'], user=request.user)
                done += 1
            except (rec.StatementError, PaymentError):
                continue
    messages.success(request, f'Encaissements rapprochés : {done}.')
    return _back()


@login_required
@require_POST
def reconcile_ignore(request, line_id):
    rec.ignore(_line(request, line_id))
    messages.success(request, "Ligne ignorée : elle n'est pas comptée comme un paiement client.")
    return _back()


@login_required
@require_POST
def reconcile_undo(request, line_id):
    line = _line(request, line_id)
    previous = line.status
    rec.undo(line)
    messages.success(request, 'Annulé : la ligne est de nouveau à rapprocher.' if previous == 'ignored'
                     else 'Rapprochement annulé : le paiement est supprimé et la facture rouverte si besoin.')
    return _back(previous)
