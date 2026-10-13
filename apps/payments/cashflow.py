"""
Calculs de trésorerie de la page Paiements : encaissé, reste à encaisser, retards,
délai moyen, série mensuelle (historique + projection) et file « À encaisser ».

Sources : factures de vente (hors brouillons / annulées), paiements « completed »,
échéanciers de devis acceptés et jalons de projet facturables.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

ZERO = Decimal('0.00')
OPEN_STATUSES = ('sent', 'viewed', 'overdue')
MONTHS_FR = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']


def add_months(day, n):
    years, month = divmod(day.month - 1 + n, 12)
    return date(day.year + years, month + 1, 1)


def _aware(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def open_invoices(organization):
    """Factures envoyées non soldées, avec le montant déjà réglé et le reste dû."""
    from apps.invoices.models import Invoice
    invoices = (
        Invoice.objects.filter(organization=organization, invoice_type='sale', status__in=OPEN_STATUSES)
        .select_related('client')
        .annotate(paid_sum=Coalesce(Sum('payments__amount', filter=Q(payments__status='completed')), ZERO))
    )
    rows = []
    for invoice in invoices:
        remaining = invoice.amount_due(invoice.paid_sum)
        if remaining <= Decimal('0.009'):
            continue
        invoice.remaining = remaining
        invoice.is_partial = invoice.paid_sum > 0
        rows.append(invoice)
    return rows


def collected_between(organization, start, end):
    """Encaissé sur [start, end[ : paiements complétés + factures payées sans paiement enregistré."""
    from apps.invoices.models import Invoice
    from apps.payments.models import Payment
    payments = (
        Payment.objects.filter(invoice__organization=organization, status='completed')
        .annotate(day=Coalesce('payment_date', 'created_at'))
        .filter(day__gte=_aware(start), day__lt=_aware(end))
        .aggregate(total=Sum('amount'))['total'] or ZERO
    )
    # Factures réglées hors module Paiements (anciennes données, page publique de démo).
    unrecorded = (
        Invoice.objects.filter(organization=organization, status='paid', paid_at__gte=_aware(start), paid_at__lt=_aware(end))
        .exclude(payments__status='completed')
        .aggregate(total=Sum('total_amount'))['total'] or ZERO
    )
    return payments + unrecorded


def _trend(current, previous):
    if not previous:
        return {'direction': 'up' if current else 'flat', 'pct_text': '—' if not current else 'nouveau'}
    pct = (current - previous) / previous * 100
    direction = 'up' if pct > 0.5 else ('down' if pct < -0.5 else 'flat')
    return {'direction': direction, 'pct_text': f"{abs(pct):.0f} %".replace('.', ',')}


def upcoming_milestones(organization, limit=8):
    """Échéances prévues mais pas encore facturées (échéanciers de devis, jalons de projet)."""
    from apps.dashboard.models import Milestone
    from apps.invoices.models import QuotePaymentMilestone
    items = []
    for m in QuotePaymentMilestone.objects.filter(
        quote__organization=organization, quote__status='accepted', status='pending', generated_invoice__isnull=True,
    ).select_related('quote', 'quote__client'):
        items.append({
            'kind': 'Échéancier', 'label': m.label, 'client': m.quote.client.name if m.quote.client_id else '—',
            'source': f"Devis {m.quote.quote_number}", 'amount': m.amount, 'due_date': m.due_date,
            'url': reverse('invoices:quote-edit', args=[m.quote_id]),
        })
    for m in Milestone.objects.filter(
        project__organization=organization, amount__gt=0, is_paid=False,
    ).select_related('project', 'project__client'):
        items.append({
            'kind': 'Jalon', 'label': m.title, 'client': m.project.client.name if m.project.client_id else '—',
            'source': m.project.name, 'amount': m.amount, 'due_date': m.due_date,
            'url': reverse('dashboard:project-detail', args=[m.project_id]),
        })
    items.sort(key=lambda i: (i['due_date'] is None, i['due_date'] or date.max))
    return items[:limit], items


def build(organization, today=None):
    from apps.invoices.models import Invoice
    today = today or timezone.localdate()
    month = today.replace(day=1)

    invoices = open_invoices(organization)
    week_end = today + timedelta(days=7)
    queue = {'overdue': [], 'week': [], 'later': []}
    for invoice in sorted(invoices, key=lambda i: i.due_date):
        invoice.days_late = (today - invoice.due_date).days
        bucket = 'overdue' if invoice.due_date < today else ('week' if invoice.due_date <= week_end else 'later')
        queue[bucket].append(invoice)

    to_collect = sum((i.remaining for i in invoices), ZERO)
    late = sum((i.remaining for i in queue['overdue']), ZERO)
    collected = collected_between(organization, month, add_months(month, 1))
    collected_prev = collected_between(organization, add_months(month, -1), month)

    paid = Invoice.objects.filter(
        organization=organization, status='paid', paid_at__gte=_aware(today - timedelta(days=365)),
    ).values_list('issue_date', 'paid_at')
    delays = [max(0, (timezone.localdate(paid_at) - issued).days) for issued, paid_at in paid if issued and paid_at]
    avg_delay = round(sum(delays) / len(delays)) if delays else None

    upcoming, all_upcoming = upcoming_milestones(organization)

    # Série : 6 mois d'historique + 3 mois de projection (reste dû par échéance + échéances prévues).
    series = []
    for offset in range(-5, 4):
        start = add_months(month, offset)
        end = add_months(month, offset + 1)
        point = {'label': f"{MONTHS_FR[start.month - 1]}", 'is_current': offset == 0, 'is_future': offset > 0,
                 'collected': ZERO, 'expected': ZERO}
        if offset <= 0:
            point['collected'] = collected_between(organization, start, end)
        if offset >= 0:
            for invoice in invoices:
                due = max(invoice.due_date, today)  # un retard est attendu « maintenant »
                if start <= due < end:
                    point['expected'] += invoice.remaining
            for item in all_upcoming:
                if item['due_date'] and start <= max(item['due_date'], today) < end:
                    point['expected'] += item['amount']
        series.append(point)
    peak = max([p['collected'] + p['expected'] for p in series] + [Decimal('1')])
    for point in series:
        point['collected_pct'] = f"{point['collected'] / peak * 100:.1f}"
        point['expected_pct'] = f"{point['expected'] / peak * 100:.1f}"
    expected_3m = sum((p['expected'] for p in series), ZERO)

    return {
        'kpis': {
            'collected': collected, 'collected_trend': _trend(collected, collected_prev),
            'to_collect': to_collect, 'open_count': len(invoices),
            'late': late, 'late_count': len(queue['overdue']),
            'avg_delay': avg_delay, 'paid_count': len(delays),
        },
        'queue': queue,
        'upcoming': upcoming,
        'series': series,
        'expected_3m': expected_3m,
    }
