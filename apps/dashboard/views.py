"""
Views for dashboard app.
"""
from rest_framework import viewsets, generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
import calendar
from decimal import Decimal
from datetime import date
from datetime import timedelta
from .models import DashboardMetric, Report, Notification
from .serializers import (
    DashboardMetricSerializer, ReportSerializer, NotificationSerializer
)


class DashboardMetricViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for DashboardMetric model."""
    queryset = DashboardMetric.objects.all()  # Required for DRF router basename detection
    serializer_class = DashboardMetricSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter metrics based on user's organizations."""
        from django.db.models import Q
        return DashboardMetric.objects.filter(
            Q(organization__owner=self.request.user) |
            Q(organization__members__user=self.request.user)
        ).distinct()


class ReportViewSet(viewsets.ModelViewSet):
    """ViewSet for Report model."""
    queryset = Report.objects.all()  # Required for DRF router basename detection
    serializer_class = ReportSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter reports based on user's organizations."""
        from django.db.models import Q
        return Report.objects.filter(
            Q(organization__owner=self.request.user) |
            Q(organization__members__user=self.request.user)
        ).distinct()


class NotificationViewSet(viewsets.ModelViewSet):
    """ViewSet for Notification model."""
    queryset = Notification.objects.all()  # Required for DRF router basename detection
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter notifications for current user."""
        return Notification.objects.filter(user=self.request.user)


class DashboardStatsView(generics.GenericAPIView):
    """Dashboard statistics view."""
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        # Get user's organizations
        organizations = request.user.owned_organizations.all()
        if not organizations:
            organizations = [m.organization for m in request.user.organization_memberships.all()]

        period_days = int(request.GET.get('period', 30))
        start_date = timezone.now().date() - timedelta(days=period_days)

        # Calculate stats
        from apps.invoices.models import Invoice

        invoices = Invoice.objects.filter(
            organization__in=organizations,
            issue_date__gte=start_date
        )

        stats = {
            'total_revenue': float(invoices.filter(status='paid').aggregate(
                total=Sum('total_amount'))['total'] or 0),
            'invoices_sent': invoices.filter(status__in=['sent', 'paid']).count(),
            'invoices_paid': invoices.filter(status='paid').count(),
            'invoices_overdue': invoices.filter(
                status__in=['sent', 'viewed'],
                due_date__lt=timezone.now().date()
            ).count(),
        }

        return Response(stats)


# HTMX Views
@login_required
def dashboard_home(request):
    """Main dashboard view (UI blocs KPI/actions/activités)."""
    # Local imports to avoid unnecessary dependency loading at startup.
    from apps.invoices.models import Invoice
    from apps.payments.models import Payment, Transaction
    from apps.organizations.models import Organization

    MONTHS_FR = [
        "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
        "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"
    ]

    def parse_month(month_param: str, fallback_dt: date) -> tuple[int, int]:
        if not month_param:
            return fallback_dt.year, fallback_dt.month
        # Expected format: YYYY-MM
        try:
            parts = month_param.split("-")
            if len(parts) == 2:
                y = int(parts[0])
                m = int(parts[1])
                if 1 <= m <= 12:
                    return y, m
        except (TypeError, ValueError):
            pass
        return fallback_dt.year, fallback_dt.month

    def format_eur(value) -> str:
        """
        Format simple FR : "1 205 467,06 €".
        (Pas de dépendance Babel pour rester léger.)
        """
        try:
            dec = Decimal(value or 0)
        except Exception:
            dec = Decimal("0")
        dec = dec.quantize(Decimal("0.01"))
        sign = "-" if dec < 0 else ""
        dec = abs(dec)
        s = f"{dec:,.2f}"  # 1,205,467.06
        s = s.replace(",", " ").replace(".", ",")
        return f"{sign}{s} €"

    def build_trend(current_value: Decimal, previous_value: Decimal) -> dict:
        """
        Build a compact trend payload for KPI cards.
        Returns direction (up/down/flat), signed delta and percentage evolution.
        """
        try:
            current = Decimal(current_value or 0)
        except Exception:
            current = Decimal("0")
        try:
            previous = Decimal(previous_value or 0)
        except Exception:
            previous = Decimal("0")

        delta = current - previous
        if delta > 0:
            direction = "up"
            direction_label = "hausse"
        elif delta < 0:
            direction = "down"
            direction_label = "baisse"
        else:
            direction = "flat"
            direction_label = "stable"

        if previous != 0:
            pct = (delta / previous) * Decimal("100")
        else:
            pct = Decimal("100") if current > 0 else Decimal("0")

        pct_abs = abs(pct).quantize(Decimal("0.1"))
        pct_text = str(pct_abs).replace(".", ",")

        return {
            "direction": direction,
            "label": direction_label,
            "delta_formatted": format_eur(delta),
            "pct_text": f"{pct_text}%",
            "is_flat": direction == "flat",
        }

    def user_accessible_org_ids(user) -> list[int]:
        org_ids = list(user.owned_organizations.values_list("id", flat=True))
        if org_ids:
            return org_ids
        # Fallback to membership relation on the user.
        return list(user.organization_memberships.values_list("organization_id", flat=True))

    def build_mini_band_data(org_ids: list[int], end_day: date) -> list[dict]:
        """Build 4-month compact series for mini charts."""
        from apps.invoices.models import Invoice
        months_fr_short = ["Jan", "Fev", "Mar", "Avr", "Mai", "Jun", "Jul", "Aou", "Sep", "Oct", "Nov", "Dec"]
        points = []
        cursor = date(end_day.year, end_day.month, 1)
        # Build oldest -> latest.
        month_starts = []
        for _ in range(4):
            month_starts.append(cursor)
            if cursor.month == 1:
                cursor = date(cursor.year - 1, 12, 1)
            else:
                cursor = date(cursor.year, cursor.month - 1, 1)
        month_starts = list(reversed(month_starts))

        for month_start in month_starts:
            _, month_last_day = calendar.monthrange(month_start.year, month_start.month)
            month_end = date(month_start.year, month_start.month, month_last_day)
            month_sales_qs = Invoice.objects.filter(
                organization_id__in=org_ids,
                invoice_type="sale",
                status="paid",
                issue_date__gte=month_start,
                issue_date__lte=month_end,
            )
            total = month_sales_qs.aggregate(total=Sum("subtotal")).get("total") or Decimal("0")
            points.append({
                "label": months_fr_short[month_start.month - 1],
                "full_label": f"{months_fr_short[month_start.month - 1]} {month_start.year}",
                "amount": float(total),
                "amount_formatted": format_eur(total),
                "count": month_sales_qs.count(),
            })

        max_amount = max([p["amount"] for p in points] or [0.0])
        for p in points:
            p["height_pct"] = int((p["amount"] / max_amount) * 100) if max_amount > 0 else 12
            if p["height_pct"] < 12:
                p["height_pct"] = 12
        return points

    now = timezone.localdate()
    requested_year, requested_month = parse_month(request.GET.get("month"), now)
    month_label = MONTHS_FR[requested_month - 1]
    _, last_day = calendar.monthrange(requested_year, requested_month)
    start_date = date(requested_year, requested_month, 1)
    end_date = date(requested_year, requested_month, last_day)
    if requested_month == 1:
        prev_year, prev_month = requested_year - 1, 12
    else:
        prev_year, prev_month = requested_year, requested_month - 1
    _, prev_last_day = calendar.monthrange(prev_year, prev_month)
    prev_start_date = date(prev_year, prev_month, 1)
    prev_end_date = date(prev_year, prev_month, prev_last_day)

    org_ids = user_accessible_org_ids(request.user)

    from .automation_engine import sweep_overdue_invoices, sweep_expired_quotes, sweep_overdue_tasks, run_pending_waits
    from .automation_calendar import sweep_calendar_triggers
    from apps.invoices.scheduled import run_billing_schedule
    for org in Organization.objects.filter(id__in=org_ids):
        sweep_overdue_invoices(org)
        sweep_expired_quotes(org)
        sweep_overdue_tasks(org)
        sweep_calendar_triggers(org)
        run_billing_schedule(org)
    run_pending_waits()

    greeting_name = (
        request.user.get_full_name().strip()
        if request.user.get_full_name()
        else (request.user.username or request.user.email)
    )
    greeting_name = greeting_name or "Utilisateur"

    # KPI: encaissements / décaissements (approximations via Payment + Transaction).
    encaissements_total = Payment.objects.filter(
        invoice__organization_id__in=org_ids,
        status="completed",
        payment_date__isnull=False,
        payment_date__date__gte=start_date,
        payment_date__date__lte=end_date,
    ).aggregate(total=Sum("amount")).get("total") or Decimal("0")

    decaissements_total = Transaction.objects.filter(
        payment__invoice__organization_id__in=org_ids,
        success=True,
        transaction_type__in=["refund", "fee", "adjustment"],
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    ).aggregate(total=Sum("amount")).get("total") or Decimal("0")

    solde_total = encaissements_total - decaissements_total

    # KPI: facturé / encours (sale vs purchase) sur les factures du mois.
    invoices_month_sale = Invoice.objects.filter(
        organization_id__in=org_ids,
        issue_date__gte=start_date,
        issue_date__lte=end_date,
        invoice_type="sale",
    )
    invoices_month_purchase = Invoice.objects.filter(
        organization_id__in=org_ids,
        issue_date__gte=start_date,
        issue_date__lte=end_date,
        invoice_type="purchase",
    )

    # HT (vente)
    total_facture_total = invoices_month_sale.filter(
        status__in=["sent", "viewed", "paid", "overdue"],
    ).aggregate(total=Sum("subtotal")).get("total") or Decimal("0")

    encours_client_total = invoices_month_sale.exclude(
        status="paid",
    ).aggregate(total=Sum("subtotal")).get("total") or Decimal("0")

    # TTC (achat)
    total_achats_total = invoices_month_purchase.filter(
        status__in=["sent", "viewed", "paid", "overdue"],
    ).aggregate(total=Sum("total_amount")).get("total") or Decimal("0")

    encours_fournisseur_total = invoices_month_purchase.exclude(
        status="paid",
    ).aggregate(total=Sum("total_amount")).get("total") or Decimal("0")

    # Période précédente (mois N-1) pour afficher progression/baisse.
    prev_encaissements_total = Payment.objects.filter(
        invoice__organization_id__in=org_ids,
        status="completed",
        payment_date__isnull=False,
        payment_date__date__gte=prev_start_date,
        payment_date__date__lte=prev_end_date,
    ).aggregate(total=Sum("amount")).get("total") or Decimal("0")

    prev_decaissements_total = Transaction.objects.filter(
        payment__invoice__organization_id__in=org_ids,
        success=True,
        transaction_type__in=["refund", "fee", "adjustment"],
        created_at__date__gte=prev_start_date,
        created_at__date__lte=prev_end_date,
    ).aggregate(total=Sum("amount")).get("total") or Decimal("0")

    prev_solde_total = prev_encaissements_total - prev_decaissements_total

    prev_invoices_month_sale = Invoice.objects.filter(
        organization_id__in=org_ids,
        issue_date__gte=prev_start_date,
        issue_date__lte=prev_end_date,
        invoice_type="sale",
    )
    prev_invoices_month_purchase = Invoice.objects.filter(
        organization_id__in=org_ids,
        issue_date__gte=prev_start_date,
        issue_date__lte=prev_end_date,
        invoice_type="purchase",
    )

    prev_total_facture_total = prev_invoices_month_sale.filter(
        status__in=["sent", "viewed", "paid", "overdue"],
    ).aggregate(total=Sum("subtotal")).get("total") or Decimal("0")

    prev_encours_client_total = prev_invoices_month_sale.exclude(
        status="paid",
    ).aggregate(total=Sum("subtotal")).get("total") or Decimal("0")

    prev_total_achats_total = prev_invoices_month_purchase.filter(
        status__in=["sent", "viewed", "paid", "overdue"],
    ).aggregate(total=Sum("total_amount")).get("total") or Decimal("0")

    prev_encours_fournisseur_total = prev_invoices_month_purchase.exclude(
        status="paid",
    ).aggregate(total=Sum("total_amount")).get("total") or Decimal("0")

    # Actions à faire
    non_justifiees_count = Transaction.objects.filter(
        payment__invoice__organization_id__in=org_ids,
        success=False,
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    ).count()

    overdue_sales_qs = Invoice.objects.filter(
        organization_id__in=org_ids,
        invoice_type="sale",
        status="overdue",
        due_date__lte=now,
    )
    overdue_sales_count = overdue_sales_qs.count()
    overdue_sales_ht_total = overdue_sales_qs.aggregate(total=Sum("subtotal")).get("total") or Decimal("0")

    overdue_purchases_qs = Invoice.objects.filter(
        organization_id__in=org_ids,
        invoice_type="purchase",
        status="overdue",
        due_date__lte=now,
    )
    overdue_purchases_count = overdue_purchases_qs.count()
    overdue_purchases_ht_total = overdue_purchases_qs.aggregate(total=Sum("subtotal")).get("total") or Decimal("0")

    # Activités récentes
    recent_transactions = (
        Transaction.objects.filter(payment__invoice__organization_id__in=org_ids)
        .select_related("payment__invoice__client", "payment__invoice__organization")
        .order_by("-created_at")[:5]
    )
    recent_transactions_data = []
    for t in recent_transactions:
        client_name = t.payment.invoice.client.name if t.payment_id and t.payment and t.payment.invoice_id else ""
        title = (t.description or client_name or t.transaction_type).strip()
        # Make refund/fees appear as outgoing (negative), like in the screenshot.
        amount_signed = t.amount
        if t.transaction_type in ["refund", "fee", "adjustment"]:
            amount_signed = -amount_signed
        if not t.success:
            # Failed transactions are treated as negative impact visually.
            amount_signed = -abs(amount_signed)
        recent_transactions_data.append({
            "title": title,
            "date": t.created_at,
            "amount_signed": amount_signed,
            "amount_formatted": format_eur(amount_signed),
            "is_negative": amount_signed < 0,
        })

    invoice_status_labels = {
        'draft': 'Brouillon', 'sent': 'Envoyée', 'viewed': 'Consultée',
        'paid': 'Payée', 'overdue': 'En retard', 'cancelled': 'Annulée',
    }
    recent_sales_invoices = invoices_month_sale.select_related("client").order_by("-issue_date")[:4]
    recent_sales_invoices_data = []
    for inv in recent_sales_invoices:
        client_name = inv.client.name
        client_initials = client_name.strip()[:2].upper() if client_name else "—"
        recent_sales_invoices_data.append({
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "invoice_type": inv.invoice_type,
            "status": inv.status,
            "status_display": invoice_status_labels.get(inv.status, inv.status),
            "scheduled_send_at": inv.scheduled_send_at,
            "client_initials": client_initials,
            "client_name": client_name,
            "date": inv.issue_date,
            "amount_ht_formatted": format_eur(inv.subtotal),
        })

    # Purchase invoices: show TTC (total_amount).
    recent_purchase_invoices_data = []
    for inv in invoices_month_purchase.select_related("client").order_by("-issue_date")[:4]:
        client_name = inv.client.name
        client_initials = client_name.strip()[:2].upper() if client_name else "—"
        recent_purchase_invoices_data.append({
            "client_initials": client_initials,
            "client_name": client_name,
            "date": inv.issue_date,
            "amount_ttc_formatted": format_eur(inv.total_amount),
        })

    mini_band = build_mini_band_data(org_ids, now)
    sparkline_coords = []
    if mini_band:
        n = len(mini_band)
        for i, p in enumerate(mini_band):
            x = 5 + (i * 90 / max(n - 1, 1))
            y = 22 - (p["height_pct"] * 18 / 100)
            sparkline_coords.append(f"{x:.1f},{y:.1f}")
    sparkline_points = " ".join(sparkline_coords)

    context = {
        "greeting_name": greeting_name,
        "month_label": month_label,
        "soldes_formatted": format_eur(solde_total),
        "encaissements_formatted": format_eur(encaissements_total),
        "decaissements_formatted": format_eur(decaissements_total),
        "total_facture_formatted": format_eur(total_facture_total),
        "encours_client_formatted": format_eur(encours_client_total),
        "total_achats_formatted": format_eur(total_achats_total),
        "encours_fournisseur_formatted": format_eur(encours_fournisseur_total),
        "non_justifiees_count": non_justifiees_count,
        "overdue_sales_count": overdue_sales_count,
        "overdue_sales_ht_formatted": format_eur(overdue_sales_ht_total),
        "overdue_purchases_count": overdue_purchases_count,
        "overdue_purchases_ht_formatted": format_eur(overdue_purchases_ht_total),
        "recent_transactions_data": recent_transactions_data,
        "recent_sales_invoices_data": recent_sales_invoices_data,
        "recent_purchase_invoices_data": recent_purchase_invoices_data,
        "mini_band_data": mini_band,
        "sparkline_points": sparkline_points,
        "soldes_trend": build_trend(solde_total, prev_solde_total),
        "encaissements_trend": build_trend(encaissements_total, prev_encaissements_total),
        "decaissements_trend": build_trend(decaissements_total, prev_decaissements_total),
        "total_facture_trend": build_trend(total_facture_total, prev_total_facture_total),
        "total_achats_trend": build_trend(total_achats_total, prev_total_achats_total),
        "encours_client_trend": build_trend(encours_client_total, prev_encours_client_total),
        "encours_fournisseur_trend": build_trend(encours_fournisseur_total, prev_encours_fournisseur_total),
        "total_facture_numeric": float(total_facture_total),
        "encaissements_numeric": float(encaissements_total),
        "decaissements_numeric": float(decaissements_total),
        "soldes_numeric": float(solde_total),
        "goal_target": Decimal("20000"),
        "goal_current": total_facture_total,
        "goal_percent": min(
            100,
            int((total_facture_total / Decimal("20000")) * 100) if total_facture_total > 0 else 0,
        ),
        "cashflow_profit_formatted": format_eur(solde_total),
    }

    return render(request, "dashboard/index.html", context)


@login_required
def analytics_home(request):
    """
    Analytics page (simple, server-rendered KPIs + breakdowns).

    The goal is to keep it lightweight while reusing the same data model and styling
    conventions as the main dashboard.
    """
    from apps.invoices.models import Invoice

    # Helpers (kept local to avoid changing existing dashboard logic).
    def format_eur(value) -> str:
        """Format simple FR : "1 205 467,06 €"."""
        try:
            dec = Decimal(value or 0)
        except Exception:
            dec = Decimal("0")
        dec = dec.quantize(Decimal("0.01"))
        sign = "-" if dec < 0 else ""
        dec = abs(dec)
        s = f"{dec:,.2f}"  # 1,205,467.06
        s = s.replace(",", " ").replace(".", ",")
        return f"{sign}{s} €"

    def user_accessible_org_ids(user) -> list[int]:
        org_ids = list(user.owned_organizations.values_list("id", flat=True))
        if org_ids:
            return org_ids
        return list(user.organization_memberships.values_list("organization_id", flat=True))

    def build_mini_band_data(org_ids: list[int], end_day: date) -> list[dict]:
        """Build 4-month compact series for analytics header chart."""
        months_fr_short = ["Jan", "Fev", "Mar", "Avr", "Mai", "Jun", "Jul", "Aou", "Sep", "Oct", "Nov", "Dec"]
        points = []
        cursor = date(end_day.year, end_day.month, 1)
        month_starts = []
        for _ in range(4):
            month_starts.append(cursor)
            if cursor.month == 1:
                cursor = date(cursor.year - 1, 12, 1)
            else:
                cursor = date(cursor.year, cursor.month - 1, 1)
        month_starts = list(reversed(month_starts))

        for month_start in month_starts:
            _, month_last_day = calendar.monthrange(month_start.year, month_start.month)
            month_end = date(month_start.year, month_start.month, month_last_day)
            month_sales_qs = Invoice.objects.filter(
                organization_id__in=org_ids,
                invoice_type="sale",
                status="paid",
                issue_date__gte=month_start,
                issue_date__lte=month_end,
            )
            total = month_sales_qs.aggregate(total=Sum("subtotal")).get("total") or Decimal("0")
            points.append({
                "label": months_fr_short[month_start.month - 1],
                "full_label": f"{months_fr_short[month_start.month - 1]} {month_start.year}",
                "amount": float(total),
                "amount_formatted": format_eur(total),
                "count": month_sales_qs.count(),
            })

        max_amount = max([p["amount"] for p in points] or [0.0])
        for p in points:
            p["height_pct"] = int((p["amount"] / max_amount) * 100) if max_amount > 0 else 12
            if p["height_pct"] < 12:
                p["height_pct"] = 12
        return points

    period_days = int(request.GET.get("period", 30))
    if period_days <= 0:
        period_days = 30

    today = timezone.localdate()
    start_date = today - timedelta(days=period_days)

    org_ids = user_accessible_org_ids(request.user)

    # Query base sets.
    sales_qs = Invoice.objects.filter(
        organization_id__in=org_ids,
        invoice_type="sale",
        issue_date__gte=start_date,
    )
    purchases_qs = Invoice.objects.filter(
        organization_id__in=org_ids,
        invoice_type="purchase",
        issue_date__gte=start_date,
    )

    # KPI totals.
    sales_paid_total = sales_qs.filter(status="paid").aggregate(total=Sum("subtotal")).get("total") or Decimal("0")
    purchases_paid_total = purchases_qs.filter(status="paid").aggregate(total=Sum("total_amount")).get("total") or Decimal("0")

    overdue_sales_count = sales_qs.filter(status="overdue").count()
    overdue_purchases_count = purchases_qs.filter(status="overdue").count()
    overdue_total_count = overdue_sales_count + overdue_purchases_count

    # Payment rate (avoid division by zero).
    sales_relevant_total = sales_qs.filter(status__in=["sent", "viewed", "paid", "overdue"]).aggregate(
        total=Sum("subtotal")
    ).get("total") or Decimal("0")
    sales_payment_rate = (sales_paid_total / sales_relevant_total) if sales_relevant_total else Decimal("0")

    purchases_relevant_total = purchases_qs.filter(status__in=["sent", "viewed", "paid", "overdue"]).aggregate(
        total=Sum("total_amount")
    ).get("total") or Decimal("0")
    purchases_payment_rate = (purchases_paid_total / purchases_relevant_total) if purchases_relevant_total else Decimal("0")

    # Status breakdowns.
    status_label_map = {
        "draft": "Brouillon",
        "sent": "Envoyées",
        "viewed": "Consultées",
        "paid": "Payées",
        "overdue": "En retard",
        "cancelled": "Annulées",
    }
    status_order = ["draft", "sent", "viewed", "paid", "overdue", "cancelled"]

    sales_status_counts_qs = sales_qs.values("status").annotate(count=Count("id"))
    purchases_status_counts_qs = purchases_qs.values("status").annotate(count=Count("id"))

    sales_status_counts_map = {row["status"]: row["count"] for row in sales_status_counts_qs}
    purchases_status_counts_map = {row["status"]: row["count"] for row in purchases_status_counts_qs}

    sales_status_breakdown = [
        {"status": st, "label": status_label_map.get(st, st), "count": int(sales_status_counts_map.get(st, 0))}
        for st in status_order
    ]
    purchases_status_breakdown = [
        {"status": st, "label": status_label_map.get(st, st), "count": int(purchases_status_counts_map.get(st, 0))}
        for st in status_order
    ]

    sales_status_max = max([item.get("count", 0) for item in sales_status_breakdown] or [1])
    purchases_status_max = max([item.get("count", 0) for item in purchases_status_breakdown] or [1])

    # Top clients for paid sales in the period.
    top_clients = list(
        sales_qs.filter(status="paid")
        .values("client__id", "client__name")
        .annotate(total=Sum("subtotal"))
        .order_by("-total")[:5]
    )
    top_clients_formatted = [
        {"client_name": row.get("client__name") or "—", "total_formatted": format_eur(row.get("total") or 0)}
        for row in top_clients
    ]

    # Top products for paid sales in the period.
    from apps.invoices.models import InvoiceItem

    top_products = list(
        InvoiceItem.objects.filter(invoice__in=sales_qs.filter(status="paid"))
        .values("name")
        .annotate(total=Sum("total"))
        .order_by("-total")[:5]
    )
    products_max = max([float(row.get("total") or 0) for row in top_products] or [1.0])
    top_products_formatted = [
        {
            "name": row.get("name") or "—",
            "total_formatted": format_eur(row.get("total") or 0),
            "pct": int((float(row.get("total") or 0) / products_max) * 100) if products_max else 0,
        }
        for row in top_products
    ]

    # Profitability: revenus encaissés vs achats payés sur la période.
    margin_total = sales_paid_total - purchases_paid_total
    margin_rate = (margin_total / sales_paid_total * 100) if sales_paid_total else Decimal("0")
    profitability_max = max(float(sales_paid_total), float(purchases_paid_total), 1.0)
    profitability = {
        "revenue_formatted": format_eur(sales_paid_total),
        "costs_formatted": format_eur(purchases_paid_total),
        "margin_formatted": format_eur(margin_total),
        "margin_rate": float(margin_rate),
        "revenue_pct": int((float(sales_paid_total) / profitability_max) * 100),
        "costs_pct": int((float(purchases_paid_total) / profitability_max) * 100),
    }

    context = {
        "period_days": period_days,
        "period_label": f"{period_days} derniers jours" if period_days != 1 else "Dernier jour",
        "sales_paid_formatted": format_eur(sales_paid_total),
        "purchases_paid_formatted": format_eur(purchases_paid_total),
        "overdue_total_count": overdue_total_count,
        "overdue_sales_count": overdue_sales_count,
        "overdue_purchases_count": overdue_purchases_count,
        "sales_payment_rate": float(sales_payment_rate) * 100,
        "purchases_payment_rate": float(purchases_payment_rate) * 100,
        "sales_status_breakdown": sales_status_breakdown,
        "purchases_status_breakdown": purchases_status_breakdown,
        "sales_status_max": sales_status_max,
        "purchases_status_max": purchases_status_max,
        "top_clients_formatted": top_clients_formatted,
        "top_products_formatted": top_products_formatted,
        "profitability": profitability,
        "start_date": start_date,
        "today": today,
        "mini_band_data": build_mini_band_data(org_ids, today),
    }

    return render(request, "analytics/index.html", context)


@login_required
@api_view(['GET'])
def dashboard_stats_api(request):
    """HTMX API endpoint for dashboard stats."""
    view = DashboardStatsView()
    view.request = request
    return view.get(request)


def _first_user_organization(user):
    org = user.owned_organizations.first()
    if org:
        return org
    membership = user.organization_memberships.select_related("organization").first()
    return membership.organization if membership else None


def _user_org_ids(user):
    """Tous les IDs d'organisation accessibles à l'utilisateur (cohérent avec dashboard_home/analytics_home)."""
    org_ids = list(user.owned_organizations.values_list("id", flat=True))
    if org_ids:
        return org_ids
    return list(user.organization_memberships.values_list("organization_id", flat=True))


@login_required
def automation_builder(request):
    """Centre d'automatisation — board de workflow (nœuds reliés) avec un moteur d'exécution réel."""
    from .models import AutomationRule, AutomationRun
    from .automation_graph import CONDITION_FIELDS, CONDITION_OPS
    from apps.documents.models import DocumentTemplate
    from apps.integrations.app_actions import board_catalog
    from apps.integrations.messaging import CHANNELS, PHONE_CHANNELS, connected_channels
    from apps.integrations.models import ConnectionInstance
    from apps.clients.models import Client
    organization = _first_user_organization(request.user)
    rules = list(
        AutomationRule.objects.filter(organization=organization).order_by('-created_at')
        if organization else AutomationRule.objects.none()
    )
    from apps.documents.canvas_render import WEB_CANVAS_CSS, clean_custom_fields
    from apps.documents.models import used_variables
    from apps.documents.views import _with_thumbnail
    document_templates = DocumentTemplate.objects.filter(
        Q(organization__isnull=True) | Q(organization=organization)
    ) if organization else DocumentTemplate.objects.filter(organization__isnull=True)
    # Modèles perso d'abord, puis ceux de Billio ; chacun avec sa vignette.
    document_templates = [
        _with_thumbnail(t) for t in sorted(document_templates, key=lambda t: (t.organization_id is None, t.name.lower()))
    ]
    clients = Client.objects.filter(organization=organization).order_by('name') if organization else Client.objects.none()
    connected = set(connected_channels(organization))

    runs_by_rule = {}
    for run in AutomationRun.objects.filter(rule__in=rules).order_by('-ran_at')[:400]:
        bucket = runs_by_rule.setdefault(run.rule_id, [])
        if len(bucket) < 8:
            bucket.append({
                'ran_at': timezone.localtime(run.ran_at).strftime('%d/%m/%Y %H:%M'),
                'target': f"{run.target_type}",
                'label': run.detail,
                'success': run.success,
                'waiting': not run.executed,
                'log': run.log or [],
            })

    workflows = [{
        'id': rule.id,
        'name': rule.name or str(rule),
        'description': rule.description,
        'is_active': rule.is_active,
        'trigger_key': rule.trigger_key,
        'run_count': rule.run_count,
        'last_triggered_at': timezone.localtime(rule.last_triggered_at).strftime('%d/%m/%Y %H:%M') if rule.last_triggered_at else '',
        'graph': rule.get_graph(),
        'runs': runs_by_rule.get(rule.id, []),
    } for rule in rules]

    return render(request, "dashboard/automation_builder.html", {
        "canvas_css": WEB_CANVAS_CSS,
        "workflows_json": workflows,
        "automation_config_json": {
            "triggers": [{"key": k, "label": str(v)} for k, v in AutomationRule.TRIGGER_CHOICES],
            "actions": [{"key": k, "label": str(v)} for k, v in AutomationRule.ACTION_CHOICES],
            # Champs personnalisés de chaque modèle : remplis depuis les actions du workflow.
            "documentTemplates": [  # champs typés : liste, date, nombre, montant, obligatoires
                {
                    "id": t.id, "name": t.name, "fields": clean_custom_fields((t.canvas_data or {}).get("fields")),
                    # Vignette de la première page pour la fenêtre de choix du modèle.
                    "category": t.get_category_display(), "description": t.description,
                    "variables": [{"key": k, "label": label, "group": group} for k, label, group in used_variables(t.canvas_data)],
                    "system": t.organization_id is None, "pages": t.page_count,
                    "thumb": {"html": t.thumb_html, "scale": t.thumb_scale, "height": t.thumb_height},
                }
                for t in document_templates
            ],
            "clients": [{"id": str(c.id), "name": c.name} for c in clients],
            "conditionFields": CONDITION_FIELDS,
            "conditionOps": {kind: sorted(ops) for kind, ops in CONDITION_OPS.items()},
            "driveConnected": ConnectionInstance.objects.filter(organization=organization, connector__key="google-drive", status="connected").exists() if organization else False,
            "messagingChannels": [
                {"key": key, "label": label, "connected": key in connected,
                 "recipient": "phone" if key in PHONE_CHANNELS else "chat" if key == "telegram" else "none"}
                for key, label in CHANNELS.items()
            ],
            # Action « Envoyer vers une app » : opérations de chaque outil, connecté ou non.
            "appActions": board_catalog(set(
                ConnectionInstance.objects.filter(organization=organization, status="connected").values_list("connector__key", flat=True)
            ) if organization else set()),
            # Déclencheur « Webhook entrant » : adresse = webhookBase + jeton du workflow + '/'.
            "webhookBase": settings.SITE_URL + reverse('dashboard:automation-webhook', args=['TOKEN']).replace('TOKEN/', ''),
            "integrationsUrl": reverse('integrations:integrations-page'),
            "saveUrl": reverse('dashboard:automation-rule-save'),
            "testUrl": reverse('dashboard:automation-rule-test'),
        },
        "workflow_count": len(rules),
        "active_count": sum(1 for r in rules if r.is_active),
    })


def _validated_graph(request, organization):
    """Lit et valide le graphe posté par le board. Retourne (graph, JsonResponse d'erreur | None)."""
    import json
    from .models import AutomationRule
    from .automation_graph import GraphError, validate_graph
    try:
        raw = json.loads(request.POST.get('graph') or '{}')
    except ValueError:
        return None, JsonResponse({'success': False, 'message': 'Workflow illisible.'}, status=400)
    try:
        graph = validate_graph(
            raw, organization=organization,
            valid_triggers={k for k, _ in AutomationRule.TRIGGER_CHOICES},
            valid_actions={k for k, _ in AutomationRule.ACTION_CHOICES},
        )
    except GraphError as exc:
        return None, JsonResponse({'success': False, 'message': str(exc)}, status=400)
    return graph, None


@require_POST
@login_required
def automation_rule_save(request):
    """Crée ou met à jour un workflow construit dans le board."""
    from .models import AutomationRule
    organization = _first_user_organization(request.user)
    if not organization:
        return JsonResponse({'success': False, 'message': 'Aucune organisation trouvée.'}, status=400)

    graph, error = _validated_graph(request, organization)
    if error:
        return error

    trigger = next(n for n in graph['nodes'] if n['type'] == 'trigger')
    first_action = next(n for n in graph['nodes'] if n['type'] == 'action')
    name = (request.POST.get('name') or '').strip()[:200]
    description = (request.POST.get('description') or '').strip()[:255]

    rule_id = request.POST.get('rule_id')
    if rule_id:
        rule = get_object_or_404(AutomationRule, id=rule_id, organization=organization)
    else:
        rule = AutomationRule(organization=organization, created_by=request.user)

    rule.name = name
    rule.description = description
    rule.graph = graph
    # Champs « à plat » conservés pour l'indexation par déclencheur et l'affichage.
    rule.trigger_key = trigger['key']
    rule.action_key = first_action['key']
    rule.condition_key = ''
    rule.condition_value = ''
    rule.wait_amount = None
    rule.wait_unit = ''
    rule.document_template = None
    if 'is_active' in request.POST:
        rule.is_active = request.POST.get('is_active') == 'true'
    from apps.subscriptions.entitlements import require_feature, require_quota
    if rule.trigger_key == 'webhook_received':
        require_feature(organization, 'inbound_webhooks')
    already_active = bool(rule.pk) and AutomationRule.objects.filter(pk=rule.pk, is_active=True).exists()
    if rule.is_active and not already_active:
        require_quota(organization, 'workflows')
    rule.save()
    return JsonResponse({'success': True, 'id': rule.id, 'graph': graph})


@require_POST
@login_required
def automation_rule_test(request):
    """Simule le workflow (aucune action réelle) et renvoie le chemin parcouru, nœud par nœud."""
    from .automation_engine import dry_run
    organization = _first_user_organization(request.user)
    if not organization:
        return JsonResponse({'success': False, 'message': 'Aucune organisation trouvée.'}, status=400)
    graph, error = _validated_graph(request, organization)
    if error:
        return error

    amount = (request.POST.get('amount') or '').replace(',', '.').strip() or None
    if amount is not None:
        try:
            amount = Decimal(amount)
        except Exception:
            return JsonResponse({'success': False, 'message': 'Montant de test invalide.'}, status=400)
    client_id = request.POST.get('client_id') or None
    if client_id:
        from apps.clients.models import Client
        if not Client.objects.filter(id=client_id, organization=organization).exists():
            return JsonResponse({'success': False, 'message': 'Client inconnu.'}, status=400)
    variables = {k: (request.POST.get(k) or '').strip()[:120] for k in ('projet', 'produit', 'formulaire') if request.POST.get(k)}
    log = dry_run(organization, graph, amount=amount, client_id=client_id, variables=variables)
    return JsonResponse({'success': True, 'log': log})


@require_POST
@login_required
def automation_rule_toggle(request, rule_id):
    """Active/désactive une règle."""
    from .models import AutomationRule
    organization = _first_user_organization(request.user)
    rule = get_object_or_404(AutomationRule, id=rule_id, organization=organization)
    if not rule.is_active:
        from apps.subscriptions.entitlements import require_feature, require_quota
        require_quota(organization, 'workflows')
        if rule.trigger_key == 'webhook_received':
            require_feature(organization, 'inbound_webhooks')
    rule.is_active = not rule.is_active
    rule.save(update_fields=['is_active', 'updated_at'])
    return JsonResponse({'success': True, 'is_active': rule.is_active})


@require_POST
@login_required
def automation_rule_delete(request, rule_id):
    """Supprime une règle."""
    from .models import AutomationRule
    organization = _first_user_organization(request.user)
    rule = get_object_or_404(AutomationRule, id=rule_id, organization=organization)
    rule.delete()
    return JsonResponse({'success': True})


@login_required
def resources_center(request):
    """Centre de ressources — calculateurs TJM / TVA / simulateur de revenus, 100% fonctionnels côté client."""
    org_ids = _user_org_ids(request.user)
    default_tax_rate = "20"
    if org_ids:
        from apps.invoices.models import Tax
        default_tax = Tax.objects.filter(organization_id__in=org_ids, is_default=True).first() \
            or Tax.objects.filter(organization_id__in=org_ids).first()
        if default_tax:
            default_tax_rate = str(default_tax.rate)

    # Repères tirés de l'activité réelle (12 derniers mois).
    figures = None
    if org_ids:
        from django.db.models import Avg, Count, Sum
        from apps.invoices.models import Invoice
        since = timezone.localdate() - timedelta(days=365)
        issued = Invoice.objects.filter(organization_id__in=org_ids, invoice_type="sale", issue_date__gte=since).exclude(status__in=("draft", "cancelled"))
        agg = issued.aggregate(total=Sum("subtotal"), count=Count("id"), avg=Avg("subtotal"))
        delays = [
            (timezone.localdate(paid_at) - issue).days
            for issue, paid_at in issued.filter(status="paid", paid_at__isnull=False).values_list("issue_date", "paid_at")
        ]
        figures = {
            "revenue": agg["total"] or 0,
            "count": agg["count"] or 0,
            "average": agg["avg"] or 0,
            "avg_delay": round(sum(delays) / len(delays)) if delays else None,
        }
    organization = _first_user_organization(request.user)
    prefs = dict((organization.billing_preferences or {}) if organization else {})
    prefs.setdefault("payment_days", organization.default_payment_terms if organization else 30)
    return render(request, "dashboard/resources.html", {
        "default_tax_rate": str(default_tax_rate).replace(",", "."),
        "figures": figures,
        "billing_prefs": prefs,
    })


@require_POST
@login_required
def resources_save_billing(request):
    """Enregistre des réglages du Centre de ressources pour les factures (TJM, pénalités, TVA…)."""
    import json
    organization = _first_user_organization(request.user)
    if not organization:
        return JsonResponse({"ok": False, "error": "Aucune organisation."}, status=400)
    try:
        data = json.loads(request.body or "{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "Données illisibles."}, status=400)
    prefs = dict(organization.billing_preferences or {})

    def number(key, low, high, integer=False):
        if key not in data:
            return
        raw = str(data[key]).replace(",", ".").strip()
        if raw == "":
            prefs.pop(key, None)
            return
        try:
            value = Decimal(raw)
        except Exception:
            raise ValueError(key)
        if not (low <= value <= high):
            raise ValueError(key)
        prefs[key] = int(value) if integer else str(value.quantize(Decimal("0.01")))

    try:
        number("tjm", 0, 100000)
        number("hours_per_day", 1, 24, integer=True)
        number("penalty_rate", 0, 100)
        number("payment_days", 0, 60, integer=True)
    except ValueError as exc:
        labels = {"tjm": "TJM", "hours_per_day": "heures par jour", "penalty_rate": "taux de pénalités", "payment_days": "délai de paiement (60 jours maximum)"}
        return JsonResponse({"ok": False, "error": f"Valeur invalide : {labels.get(str(exc), str(exc))}."}, status=400)
    if "vat_exempt" in data:
        prefs["vat_exempt"] = bool(data["vat_exempt"])
    if "early_discount" in data:
        prefs["early_discount"] = str(data["early_discount"] or "").strip()[:300]
    organization.billing_preferences = prefs
    fields = ["billing_preferences", "updated_at"]
    if "payment_days" in prefs:
        organization.default_payment_terms = prefs["payment_days"]
        fields.append("default_payment_terms")
    organization.save(update_fields=fields)
    return JsonResponse({"ok": True, "prefs": prefs, "texts": organization.billing_texts()})


@login_required
def documents_list(request):
    """Vue unifiée des documents : Invoice/Quote/Document réels."""
    org_ids = _user_org_ids(request.user)
    documents = []
    if org_ids:
        from apps.invoices.models import Invoice, Quote
        from apps.documents.models import Document
        for doc in Document.objects.filter(organization_id__in=org_ids).order_by("-created_at")[:20]:
            documents.append({
                "type": "document",
                "type_label": doc.get_document_type_display(),
                "number": doc.number,
                "title": doc.title,
                "client": doc.client.name if doc.client_id else "—",
                "status": doc.status,
                "date": doc.created_at.date(),
                "amount": None,
                "is_favorite": doc.is_favorite,
                "view_url": reverse("documents:document-pdf", args=[doc.id]),
                "edit_url": reverse("documents:document-editor", args=[doc.id]),
                "favorite_url": reverse("documents:document-toggle-favorite", args=[doc.id]),
            })
        for invoice in Invoice.objects.filter(organization_id__in=org_ids).order_by("-created_at")[:20]:
            documents.append({
                "type": "invoice",
                "type_label": "Facture",
                "number": invoice.invoice_number,
                "title": invoice.title or (invoice.client.name if invoice.client_id else ""),
                "client": invoice.client.name if invoice.client_id else "—",
                "status": invoice.status,
                "date": invoice.issue_date,
                "amount": invoice.total_amount,
                "is_favorite": invoice.is_favorite,
                "view_url": reverse("invoices:invoice-preview", args=[invoice.id]),
                "edit_url": reverse("invoices:invoice-edit", args=[invoice.id]),
                "favorite_url": reverse("invoices:invoice-toggle-favorite", args=[invoice.id]),
            })
        for quote in Quote.objects.filter(organization_id__in=org_ids).order_by("-created_at")[:20]:
            documents.append({
                "type": "quote",
                "type_label": "Devis",
                "number": quote.quote_number,
                "title": quote.title or (quote.client.name if quote.client_id else ""),
                "client": quote.client.name if quote.client_id else "—",
                "status": quote.status,
                "date": quote.issue_date,
                "amount": quote.total_amount,
                "is_favorite": quote.is_favorite,
                "view_url": reverse("invoices:quote-preview", args=[quote.id]),
                "edit_url": reverse("invoices:quote-edit", args=[quote.id]),
                "favorite_url": reverse("invoices:quote-toggle-favorite", args=[quote.id]),
            })
    documents.sort(key=lambda d: d["date"] or date.min, reverse=True)
    from apps.documents.views import gallery_context
    context = {"documents": documents, "tab": "modeles" if request.GET.get("tab") == "modeles" else "documents"}
    context.update(gallery_context(request.user))
    context["template_count"] = len(context["system_templates"]) + len(context["my_templates"]) + 1
    return render(request, "dashboard/documents.html", context)


_TIMELINE_ACTION_LABELS = {
    "invoice": "Voir la facture",
    "payment": "Voir la facture",
    "project": "Voir le projet",
    "deliverable": "Voir le livrable",
    "file": "Voir le projet",
}


@login_required
def activity_timeline(request):
    """Timeline unifiée : agrège les événements réels (clients, factures, devis, paiements,
    projets, livrables, fichiers, et intégrations connectées via apps.integrations)."""
    from apps.invoices.models import Invoice, Quote
    from apps.clients.models import Client
    from apps.payments.models import Transaction
    from apps.integrations.models import WebhookLog

    org_ids = _user_org_ids(request.user)
    events = []

    if org_ids:
        for invoice in Invoice.objects.filter(organization_id__in=org_ids).select_related("client")[:200]:
            client_name = invoice.client.name if invoice.client_id else "—"
            events.append({
                "category": "invoice",
                "icon": "receipt-text",
                "title": f"Facture {invoice.invoice_number} créée",
                "subtitle": client_name,
                "actor": client_name,
                "date": invoice.created_at,
                "url": reverse("invoices:invoice-preview", args=[invoice.id]),
            })
            if invoice.sent_at:
                events.append({
                    "category": "invoice",
                    "icon": "send",
                    "title": f"Facture {invoice.invoice_number} envoyée",
                    "subtitle": client_name,
                    "actor": client_name,
                    "date": invoice.sent_at,
                    "url": reverse("invoices:invoice-preview", args=[invoice.id]),
                })
            if invoice.paid_at:
                events.append({
                    "category": "payment",
                    "icon": "circle-check-big",
                    "title": f"Facture {invoice.invoice_number} payée",
                    "subtitle": client_name,
                    "actor": client_name,
                    "description": f"{client_name} a réglé la facture {invoice.invoice_number}.",
                    "date": invoice.paid_at,
                    "url": reverse("invoices:invoice-preview", args=[invoice.id]),
                    "is_milestone": True,
                })

        for quote in Quote.objects.filter(organization_id__in=org_ids).select_related("client")[:200]:
            client_name = quote.client.name if quote.client_id else "—"
            events.append({
                "category": "quote",
                "icon": "file-text",
                "title": f"Devis {quote.quote_number} créé",
                "subtitle": client_name,
                "actor": client_name,
                "date": quote.created_at,
                "url": None,
            })
            if quote.accepted_at:
                events.append({
                    "category": "quote",
                    "icon": "circle-check-big",
                    "title": f"Devis {quote.quote_number} accepté",
                    "subtitle": client_name,
                    "actor": client_name,
                    "description": f"{client_name} a accepté le devis {quote.quote_number}.",
                    "date": quote.accepted_at,
                    "url": None,
                    "is_milestone": True,
                })

        from apps.dashboard.models import Project, Deliverable, ProjectFile, DeliverableFile, CalendarMark

        for project in Project.objects.filter(organization_id__in=org_ids).select_related("client")[:200]:
            client_name = project.client.name if project.client_id else "—"
            events.append({
                "category": "project",
                "icon": "folder-plus",
                "title": f"Projet « {project.name} » créé",
                "subtitle": client_name,
                "actor": client_name,
                "date": project.created_at,
                "url": reverse("dashboard:project-detail", args=[project.id]),
            })

        deliverables = Deliverable.objects.filter(
            project__organization_id__in=org_ids
        ).select_related("project", "project__client")[:200]
        for d in deliverables:
            project_url = reverse("dashboard:project-detail", args=[d.project_id])
            client_name = d.project.client.name if d.project.client_id else d.project.name
            events.append({
                "category": "deliverable",
                "icon": "package",
                "title": f"Livrable « {d.title} » créé",
                "subtitle": client_name,
                "date": d.created_at,
                "url": project_url,
            })
            if d.submitted_at:
                events.append({
                    "category": "deliverable",
                    "icon": "send",
                    "title": f"Livrable « {d.title} » envoyé",
                    "subtitle": client_name,
                    "date": d.submitted_at,
                    "url": project_url,
                })
            if d.approved_at:
                events.append({
                    "category": "deliverable",
                    "icon": "circle-check-big",
                    "title": f"Livrable « {d.title} » approuvé",
                    "subtitle": client_name,
                    "actor": client_name,
                    "description": f"{client_name} a approuvé le livrable « {d.title} ».",
                    "date": d.approved_at,
                    "url": project_url,
                    "is_milestone": True,
                })
            if d.changes_requested_at:
                events.append({
                    "category": "deliverable",
                    "icon": "rotate-ccw",
                    "title": f"Modifications demandées — « {d.title} »",
                    "subtitle": client_name,
                    "actor": client_name,
                    "description": d.change_request_reason or f"{client_name} a demandé des modifications.",
                    "date": d.changes_requested_at,
                    "url": project_url,
                })

        project_files = ProjectFile.objects.filter(
            project__organization_id__in=org_ids
        ).select_related("project")[:200]
        for f in project_files:
            events.append({
                "category": "file",
                "icon": "paperclip",
                "title": f"Fichier « {f.name or f.file.name} » ajouté",
                "subtitle": f.project.name,
                "date": f.uploaded_at,
                "url": reverse("dashboard:project-detail", args=[f.project_id]),
            })

        deliverable_files = DeliverableFile.objects.filter(
            deliverable__project__organization_id__in=org_ids
        ).select_related("deliverable__project")[:200]
        for f in deliverable_files:
            events.append({
                "category": "file",
                "icon": "paperclip",
                "title": f"Fichier « {f.name or f.file.name} » ajouté",
                "subtitle": f.deliverable.project.name,
                "date": f.uploaded_at,
                "url": reverse("dashboard:project-detail", args=[f.deliverable.project_id]),
            })

        for client in Client.objects.filter(organization_id__in=org_ids)[:200]:
            events.append({
                "category": "client",
                "icon": "user-plus",
                "title": f"Nouveau client — {client.name}",
                "subtitle": client.company_name or client.email or "",
                "date": client.created_at,
                "url": None,
            })

        transactions = (
            Transaction.objects.filter(payment__invoice__organization_id__in=org_ids)
            .select_related("payment__invoice__client")
            .order_by("-created_at")[:100]
        )
        for t in transactions:
            client_name = t.payment.invoice.client.name if t.payment_id and t.payment and t.payment.invoice_id else "—"
            events.append({
                "category": "payment",
                "icon": "wallet-cards",
                "title": t.description or f"Transaction {t.get_transaction_type_display()}",
                "subtitle": client_name,
                "date": t.created_at,
                "url": None,
            })

        webhook_logs = WebhookLog.objects.filter(
            connection_instance__organization_id__in=org_ids, success=True
        ).select_related("connection_instance__connector")[:200]
        for log in webhook_logs:
            connector = log.connection_instance.connector
            category = "communication" if connector.category == "communication" else "automation"
            events.append({
                "category": category,
                "icon": connector.icon,
                "title": f"{connector.name} — {log.event_type or 'événement'}",
                "subtitle": connector.name,
                "actor": connector.name,
                "description": f"Webhook reçu via {connector.name}.",
                "date": log.created_at,
                "url": reverse("integrations:integrations-page"),
                "is_automated": True,
            })

    for e in events:
        e.setdefault("is_milestone", False)
        e.setdefault("is_automated", False)
        e.setdefault("description", "")
        e.setdefault("actor", "")
        e["action_label"] = _TIMELINE_ACTION_LABELS.get(e["category"], "Voir le détail") if e.get("url") else ""

    events.sort(key=lambda e: e["date"], reverse=True)

    stats = {
        "total": len(events),
        "invoice": sum(1 for e in events if e["category"] == "invoice"),
        "quote": sum(1 for e in events if e["category"] == "quote"),
        "client": sum(1 for e in events if e["category"] == "client"),
        "payment": sum(1 for e in events if e["category"] == "payment"),
        "project": sum(1 for e in events if e["category"] == "project"),
        "deliverable": sum(1 for e in events if e["category"] == "deliverable"),
        "file": sum(1 for e in events if e["category"] == "file"),
        "communication": sum(1 for e in events if e["category"] == "communication"),
        "automation": sum(1 for e in events if e["category"] == "automation"),
    }

    calendar_events = [
        {
            "date": timezone.localtime(e["date"]).strftime("%Y-%m-%d"),
            "time": timezone.localtime(e["date"]).strftime("%H:%M"),
            "category": e["category"],
            "icon": e["icon"],
            "title": e["title"],
            "subtitle": e["subtitle"],
            "url": e["url"],
            "is_milestone": e["is_milestone"],
        }
        for e in events
    ]
    for e in calendar_events:
        e["kind"] = "activity"
    activity_count = len(calendar_events)

    # --- Échéances de tâches/jalons/réunions : affichées uniquement dans le calendrier
    # (Planning), pas dans le flux "Activity" qui est un historique d'actions passées. ---
    if org_ids:
        from apps.dashboard.models import Task, Milestone, Meeting

        for t in Task.objects.filter(
            project__organization_id__in=org_ids, due_date__isnull=False
        ).select_related("project")[:300]:
            calendar_events.append({
                "date": t.due_date.isoformat(),
                "time": "",
                "category": "task",
                "icon": "check-square",
                "title": f"Tâche « {t.title} »",
                "subtitle": t.project.name,
                "url": reverse("dashboard:project-detail", args=[t.project_id]),
                "is_milestone": False,
            })

        for m in Milestone.objects.filter(
            project__organization_id__in=org_ids, due_date__isnull=False
        ).select_related("project")[:300]:
            calendar_events.append({
                "date": m.due_date.isoformat(),
                "time": "",
                "category": "milestone",
                "icon": "flag",
                "title": f"Jalon « {m.title} »",
                "subtitle": m.project.name,
                "url": reverse("dashboard:project-detail", args=[m.project_id]),
                "is_milestone": True,
            })

        for mt in Meeting.objects.filter(
            project__organization_id__in=org_ids
        ).exclude(status="cancelled").select_related("project")[:300]:
            local_dt = timezone.localtime(mt.scheduled_at)
            calendar_events.append({
                "date": local_dt.strftime("%Y-%m-%d"),
                "time": local_dt.strftime("%H:%M"),
                "category": "meeting",
                "icon": "video",
                "title": f"Réunion « {mt.title} »",
                "subtitle": f"{mt.project.name} · {mt.duration_minutes} min" + (f" · {mt.location}" if mt.location else ""),
                "url": reverse("dashboard:project-detail", args=[mt.project_id]),
                "is_milestone": False,
            })

        # Livrables et factures à échéance : ce qui est attendu, pas ce qui s'est passé.
        for d in Deliverable.objects.filter(
            project__organization_id__in=org_ids, due_date__isnull=False
        ).exclude(status="approved").select_related("project")[:300]:
            calendar_events.append({
                "date": d.due_date.isoformat(), "time": "", "category": "deliverable", "icon": "package",
                "title": f"Livrable « {d.title} »", "subtitle": d.project.name,
                "url": reverse("dashboard:project-detail", args=[d.project_id]), "is_milestone": False,
            })
        for inv in Invoice.objects.filter(
            organization_id__in=org_ids, status__in=("sent", "viewed", "overdue")
        ).select_related("client")[:300]:
            calendar_events.append({
                "date": inv.due_date.isoformat(), "time": "", "category": "invoice", "icon": "receipt-text",
                "title": f"Échéance {inv.invoice_number}", "subtitle": inv.client.name if inv.client_id else "",
                "url": reverse("invoices:invoice-edit", args=[inv.id]), "is_milestone": False,
            })

        # Tout ce qui est ajouté après l'historique d'activité est « planifié ».
        for e in calendar_events[activity_count:]:
            e["kind"] = "plan"

    events = events[:80]

    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    groups = []
    current_label = None
    current_items = None
    for event in events:
        event_day = timezone.localtime(event["date"]).date()
        if event_day == today:
            label = "Aujourd'hui"
        elif event_day == yesterday:
            label = "Hier"
        else:
            label = event_day.strftime("%d/%m/%Y")
        if label != current_label:
            current_items = []
            groups.append({
                "label": label,
                "items": current_items,
                "categories": set(),
                "date_iso": event_day.isoformat(),
            })
            current_label = label
        current_items.append(event)
        groups[-1]["categories"].add(event["category"])

    for group in groups:
        group["categories"] = ",".join(sorted(group["categories"]))

    # --- Projets actifs (résumé) ---
    projects_summary = []
    active_projects = list(
        Project.objects.filter(organization_id__in=org_ids).exclude(status="completed").select_related("client")
    ) if org_ids else []
    for project in active_projects:
        next_deliverable = project.deliverables.filter(
            due_date__isnull=False
        ).exclude(status="approved").order_by("due_date").first()
        projects_summary.append({
            "id": project.id,
            "name": project.name,
            "client_name": project.client.name if project.client_id else "—",
            "status_display": project.status_label,
            "progress_percent": project.progress_percent,
            "next_deliverable": next_deliverable.title if next_deliverable else None,
            "delivery_date": project.delivery_date,
            "url": reverse("dashboard:project-detail", args=[project.id]),
        })

    # --- À venir (section "Schedule" + panneau Upcoming) : livrables et projets pas encore échus ---
    upcoming = []
    if org_ids:
        upcoming_deliverables = Deliverable.objects.filter(
            project__organization_id__in=org_ids, due_date__isnull=False
        ).exclude(status="approved").select_related("project").order_by("due_date")[:30]
        for d in upcoming_deliverables:
            days = (d.due_date - today).days
            upcoming.append({
                "type": "deliverable",
                "title": d.title,
                "project_name": d.project.name,
                "due_date": d.due_date,
                "days": days,
                "days_abs": abs(days),
                "is_late": days < 0,
                "is_soon": 0 <= days <= 3,
                "url": reverse("dashboard:project-detail", args=[d.project_id]),
            })
        for project in Project.objects.filter(
            organization_id__in=org_ids, delivery_date__isnull=False
        ).exclude(status="completed"):
            days = (project.delivery_date - today).days
            upcoming.append({
                "type": "project",
                "title": f"Livraison — {project.name}",
                "project_name": project.name,
                "due_date": project.delivery_date,
                "days": days,
                "days_abs": abs(days),
                "is_late": days < 0,
                "is_soon": 0 <= days <= 3,
                "url": reverse("dashboard:project-detail", args=[project.id]),
            })
        upcoming.sort(key=lambda u: u["due_date"])
        for u in upcoming:
            u["bucket"] = "late" if u["is_late"] else ("week" if u["days"] <= 7 else "later")

    # --- Gantt léger : une barre start_date -> delivery_date par projet actif,
    # avec les vrais milestones du projet comme repères (losange plein si complété) ---
    gantt_projects = []
    for project in active_projects:
        start = project.start_date or project.created_at.date()
        end = project.delivery_date or today
        if end < start:
            end = start
        milestones = [
            {"date": m.due_date.isoformat(), "title": m.title, "completed": m.is_completed}
            for m in project.milestones.filter(due_date__isnull=False)
        ]
        gantt_projects.append({
            "id": project.id,
            "name": project.name,
            "status": project.status_label,
            "phase_color": project.status_color,
            "progress_percent": project.progress_percent,
            "is_late": bool(project.delivery_date and project.delivery_date < today and project.status != "completed"),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "url": reverse("dashboard:project-detail", args=[project.id]),
            "milestones": milestones,
        })

    # --- Repères "Marquer ce jour" (clic droit sur le calendrier) ---
    calendar_marks = []
    if org_ids:
        from apps.dashboard.models import CalendarMark
        calendar_marks = [
            {"id": mk.id, "date": mk.date.isoformat(), "label": mk.label, "color": mk.color}
            for mk in CalendarMark.objects.filter(organization_id__in=org_ids)
        ]

    # --- Données pour la popup de création rapide depuis le calendrier ---
    quick_create_projects = []
    if org_ids:
        from .project_views import _organization_members_data
        organization = _first_user_organization(request.user)
        members = _organization_members_data(organization) if organization else []
        for project in active_projects:
            quick_create_projects.append({
                "id": project.id,
                "name": project.name,
                "milestones": [{"id": m.id, "title": m.title} for m in project.milestones.all()],
                "members": members,
            })

    return render(request, "dashboard/timeline.html", {
        "groups": groups,
        "has_events": bool(events),
        "stats": stats,
        "calendar_events": calendar_events,
        "projects_summary": projects_summary,
        "upcoming": upcoming,
        "upcoming_late_count": sum(1 for u in upcoming if u["is_late"]),
        "timeline_categories": [
            ("client", "Clients"), ("invoice", "Factures"), ("quote", "Devis"), ("payment", "Paiements"),
            ("project", "Projets"), ("deliverable", "Livrables"), ("file", "Fichiers"),
            ("communication", "Communication"), ("automation", "Automatisation"),
        ],
        "gantt_projects": gantt_projects,
        "calendar_marks": calendar_marks,
        "quick_create_projects": quick_create_projects,
    })


@require_POST
@login_required
def calendar_mark_create(request):
    """Crée ou met à jour (upsert) le repère du jour sélectionné sur le calendrier Timeline."""
    from apps.dashboard.models import CalendarMark

    organization = _first_user_organization(request.user)
    if not organization:
        return JsonResponse({"success": False, "message": "Aucune organisation trouvée."}, status=400)

    from datetime import date as date_cls

    raw_date = request.POST.get("date")
    if not raw_date:
        return JsonResponse({"success": False, "message": "Date requise."}, status=400)
    try:
        mark_date = date_cls.fromisoformat(raw_date)
    except ValueError:
        return JsonResponse({"success": False, "message": "Date invalide."}, status=400)

    mark, _created = CalendarMark.objects.update_or_create(
        organization=organization,
        date=mark_date,
        defaults={
            "label": (request.POST.get("label") or "").strip(),
            "color": request.POST.get("color") or "#f59e0b",
            "created_by": request.user,
        },
    )
    return JsonResponse({
        "success": True,
        "mark": {"id": mark.id, "date": mark_date.isoformat(), "label": mark.label, "color": mark.color},
    })


@require_POST
@login_required
def calendar_mark_delete(request, mark_id):
    """Supprime un repère de calendrier."""
    from apps.dashboard.models import CalendarMark

    org_ids = _user_org_ids(request.user)
    mark = get_object_or_404(CalendarMark.objects.filter(organization_id__in=org_ids), id=mark_id)
    mark.delete()
    return JsonResponse({"success": True})


@login_required
def client_portal_preview(request):
    """Aperçu, côté organisation, de l'espace dédié que voit un client (lien à jeton réel)."""
    organization = _first_user_organization(request.user)
    org_ids = _user_org_ids(request.user)
    clients = []
    selected_client = None
    if org_ids:
        from apps.clients.models import Client
        clients = list(Client.objects.filter(organization_id__in=org_ids, is_active=True).order_by("name")[:8])
        selected_id = (request.GET.get("client") or "").strip()
        if selected_id:
            selected_client = next((c for c in clients if str(c.id) == selected_id), None)
        selected_client = selected_client or (clients[0] if clients else None)

    documents = []
    if selected_client:
        for quote in selected_client.quotes.exclude(status="draft").order_by("-issue_date")[:5]:
            documents.append({
                "label": f"Devis {quote.quote_number}", "status": quote.status,
                "status_display": quote.get_status_display(),
            })
        for invoice in selected_client.invoices.exclude(status="draft").order_by("-issue_date")[:5]:
            documents.append({
                "label": f"Facture {invoice.invoice_number}", "status": invoice.status,
                "status_display": invoice.get_status_display(),
            })

    return render(request, "dashboard/client_portal_preview.html", {
        "clients": clients,
        "selected_client": selected_client,
        "documents": documents,
        "organization": organization,
    })