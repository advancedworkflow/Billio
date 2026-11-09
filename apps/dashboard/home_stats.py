"""
Chiffres de l'accueil du tableau de bord : CA sur 12 mois, encaissements, créances par
ancienneté, prochaines échéances, meilleurs clients et taux de signature des devis.

Tout est calculé à partir des factures de vente et des paiements confirmés ; aucune donnée
n'est inventée. Les montants de CA sont HT (chiffre d'affaires), les encaissements et les
créances sont TTC (ce que le client paie réellement).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth

from apps.organizations.currencies import format_money

MONTHS_SHORT = ['Janv.', 'Févr.', 'Mars', 'Avr.', 'Mai', 'Juin', 'Juil.', 'Août', 'Sept.', 'Oct.', 'Nov.', 'Déc.']
ISSUED = ('sent', 'viewed', 'paid', 'overdue')
OPEN = ('sent', 'viewed', 'overdue')
AGING_BUCKETS = (
    ('current', 'À échoir', None, 0),
    ('d30', '1 à 30 jours', 1, 30),
    ('d60', '31 à 60 jours', 31, 60),
    ('d60p', 'Plus de 60 jours', 61, None),
)


def month_starts(end_day, count):
    """Premiers jours des `count` derniers mois, du plus ancien au mois de `end_day`."""
    year, month = end_day.year, end_day.month
    starts = []
    for _ in range(count):
        starts.append(date(year, month, 1))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return list(reversed(starts))


def _next_month(start):
    return date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)


def compact_money(value, currency):
    """Libellé court pour les axes : « 12 k€ », « 1,2 k€ », « 850 € »."""
    value = Decimal(value or 0)
    symbol = format_money(0, currency).replace('0', '').replace(',', '').replace('.', '').strip() or currency
    if abs(value) >= 1000:
        thousands = value / 1000
        text = f'{thousands:.0f}' if abs(thousands) >= 10 or thousands == thousands.to_integral() else f'{thousands:.1f}'.replace('.', ',')
        return f'{text} k{symbol}'
    return f'{value:.0f} {symbol}'


def _nice_ceiling(value):
    """Plafond « rond » de l'axe (1, 2, 2,5, 5 × 10^n) pour des graduations lisibles."""
    if value <= 0:
        return Decimal('1000')
    exponent = len(str(int(value))) - 1
    base = Decimal(10) ** exponent
    for step in (1, 2, Decimal('2.5'), 5, 10):
        if value <= base * step:
            return base * Decimal(step)
    return base * 10


def revenue_series(org_ids, end_day, currency, months=12):
    """CA HT facturé et encaissements TTC par mois, prêts pour le graphique."""
    from apps.invoices.models import Invoice
    from apps.payments.models import Payment

    starts = month_starts(end_day, months)
    first = starts[0]
    invoiced = {
        row['m'].date() if hasattr(row['m'], 'date') else row['m']: row
        for row in Invoice.objects.filter(
            organization_id__in=org_ids, invoice_type='sale', status__in=ISSUED, issue_date__gte=first,
        ).annotate(m=TruncMonth('issue_date')).values('m').annotate(total=Sum('subtotal'), n=Count('id'))
    }
    collected = {
        (row['m'].date() if hasattr(row['m'], 'date') else row['m']): row['total']
        for row in Payment.objects.filter(
            invoice__organization_id__in=org_ids, status='completed', payment_date__date__gte=first,
        ).annotate(m=TruncMonth('payment_date')).values('m').annotate(total=Sum('amount'))
    }
    points = []
    for start in starts:
        row = invoiced.get(start) or {}
        total = row.get('total') or Decimal('0')
        cash = collected.get(start) or Decimal('0')
        points.append({
            'key': start.strftime('%Y-%m'),
            'label': MONTHS_SHORT[start.month - 1],
            'full_label': f'{MONTHS_SHORT[start.month - 1]} {start.year}',
            'amount': float(total),
            'amount_formatted': format_money(total, currency),
            'collected': float(cash),
            'collected_formatted': format_money(cash, currency),
            'count': row.get('n') or 0,
        })
    peak = max([Decimal(str(p['amount'])) for p in points] + [Decimal(str(p['collected'])) for p in points] + [Decimal('0')])
    ceiling = _nice_ceiling(peak)
    for p in points:
        p['height_pct'] = round(p['amount'] / float(ceiling) * 100, 2)
        p['collected_pct'] = round(p['collected'] / float(ceiling) * 100, 2)
    ticks = [{'pct': pct, 'label': compact_money(ceiling * pct / 100, currency)} for pct in (100, 75, 50, 25, 0)]
    year_total = sum(Decimal(str(p['amount'])) for p in points)
    return {'points': points, 'ticks': ticks, 'total_formatted': format_money(year_total, currency)}


def sparkline(values, width=120, height=36):
    """Tracé SVG (ligne + aire) d'une petite série ; vide si tout vaut zéro."""
    values = [float(v or 0) for v in values]
    if len(values) < 2 or not any(values):
        return {'line': '', 'area': ''}
    top = max(values)
    low = min(0.0, min(values))
    span = (top - low) or 1.0
    step = width / (len(values) - 1)
    coords = [(i * step, height - 3 - (v - low) / span * (height - 6)) for i, v in enumerate(values)]
    line = 'M' + ' L'.join(f'{x:.1f},{y:.1f}' for x, y in coords)
    area = f'{line} L{width:.1f},{height} L0,{height} Z'
    return {'line': line, 'area': area}


def receivables(org_ids, today, currency, limit=500):
    """Créances ouvertes (reste dû TTC) réparties par ancienneté + prochaines échéances."""
    from apps.invoices.models import Invoice

    invoices = list(
        Invoice.objects.filter(organization_id__in=org_ids, invoice_type='sale', status__in=OPEN)
        .select_related('client')
        .annotate(paid=Sum('payments__amount', filter=Q(payments__status='completed')))
        .order_by('due_date')[:limit]
    )
    buckets = {key: Decimal('0') for key, *_ in AGING_BUCKETS}
    counts = {key: 0 for key, *_ in AGING_BUCKETS}
    upcoming, total, overdue = [], Decimal('0'), Decimal('0')
    for invoice in invoices:
        due = invoice.amount_due(paid=invoice.paid or Decimal('0'))
        if due <= 0:
            continue
        late = (today - invoice.due_date).days if invoice.due_date else 0
        key = 'current'
        for bucket_key, _label, low, high in AGING_BUCKETS[1:]:
            if late >= low and (high is None or late <= high):
                key = bucket_key
        buckets[key] += due
        counts[key] += 1
        total += due
        if late > 0:
            overdue += due
        if len(upcoming) < 5:
            upcoming.append({
                'id': invoice.id,
                'number': invoice.invoice_number,
                'client': invoice.client.name if invoice.client_id else '',
                'due_date': invoice.due_date,
                'days': -late,
                'late_days': late,
                'is_late': late > 0,
                'amount_formatted': format_money(due, currency),
            })
    rows = []
    for key, label, *_ in AGING_BUCKETS:
        share = float(buckets[key] / total * 100) if total else 0
        rows.append({'key': key, 'label': label, 'amount_formatted': format_money(buckets[key], currency),
                     'count': counts[key], 'pct': round(share, 2)})
    # Les factures en retard d'abord, puis les plus proches de l'échéance.
    upcoming.sort(key=lambda row: (not row['is_late'], row['days']))
    return {
        'total': total,
        'total_formatted': format_money(total, currency),
        'overdue': overdue,
        'overdue_formatted': format_money(overdue, currency),
        'buckets': rows,
        'upcoming': upcoming[:4],
    }


def top_clients(org_ids, today, currency, count=5):
    """Clients qui pèsent le plus dans le CA HT des 12 derniers mois."""
    from apps.invoices.models import Invoice

    since = today - timedelta(days=365)
    rows = list(
        Invoice.objects.filter(organization_id__in=org_ids, invoice_type='sale', status__in=ISSUED, issue_date__gte=since)
        .values('client_id', 'client__name').annotate(total=Sum('subtotal'), n=Count('id')).order_by('-total')[:count]
    )
    grand = Invoice.objects.filter(
        organization_id__in=org_ids, invoice_type='sale', status__in=ISSUED, issue_date__gte=since,
    ).aggregate(total=Sum('subtotal'))['total'] or Decimal('0')
    result = []
    for row in rows:
        total = row['total'] or Decimal('0')
        name = row['client__name'] or '—'
        result.append({
            'id': row['client_id'],
            'name': name,
            'initials': ''.join(part[0] for part in name.split()[:2]).upper() or name[:2].upper(),
            'amount_formatted': format_money(total, currency),
            'count': row['n'],
            'share': round(float(total / grand * 100), 1) if grand else 0,
        })
    top = max([r['share'] for r in result] + [0])
    for r in result:
        r['bar'] = round(r['share'] / top * 100, 1) if top else 0
        r['share_text'] = f"{r['share']:.0f} %"
    return result


def quote_conversion(org_ids, today):
    """Part des devis acceptés parmi ceux qui ont reçu une réponse (12 derniers mois)."""
    from apps.invoices.models import Quote

    since = today - timedelta(days=365)
    decided = Quote.objects.filter(organization_id__in=org_ids, status__in=('accepted', 'rejected', 'expired'),
                                   issue_date__gte=since)
    total = decided.count()
    if not total:
        return None
    return round(decided.filter(status='accepted').count() / total * 100)
