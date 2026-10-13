"""
Tableaux exportables vers Google Sheets, Notion ou en CSV : factures et paiements.
Chaque tableau : colonnes [(nom, type)] (types : text, money, date) et lignes {nom: valeur}.
"""
import csv
import io
from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

TABLES = {
    'invoices': 'Factures',
    'payments': 'Paiements',
}
STATUS_FR = {'draft': 'Brouillon', 'sent': 'Envoyée', 'viewed': 'Consultée', 'paid': 'Payée', 'overdue': 'En retard', 'cancelled': 'Annulée'}


def table_rows(organization, key):
    from apps.invoices.models import Invoice
    from apps.payments.models import Payment
    zero = Decimal('0')
    if key == 'invoices':
        columns = [('Numéro', 'text'), ('Client', 'text'), ('Émise le', 'date'), ('Échéance', 'date'),
                   ('Statut', 'text'), ('Montant HT', 'money'), ('Montant TTC', 'money'), ('Encaissé', 'money')]
        rows = []
        invoices = (Invoice.objects.filter(organization=organization, invoice_type='sale').select_related('client')
                    .annotate(paid=Coalesce(Sum('payments__amount', filter=Q(payments__status='completed')), zero))
                    .order_by('-issue_date'))
        for inv in invoices:
            paid = inv.total_amount if inv.status == 'paid' else inv.paid
            rows.append({
                'Numéro': inv.invoice_number, 'Client': inv.client.name if inv.client_id else '',
                'Émise le': inv.issue_date.isoformat() if inv.issue_date else '',
                'Échéance': inv.due_date.isoformat() if inv.due_date else '',
                'Statut': STATUS_FR.get(inv.status, inv.status), 'Montant HT': inv.subtotal,
                'Montant TTC': inv.total_amount, 'Encaissé': paid,
            })
        return columns, rows
    if key == 'payments':
        columns = [('Référence', 'text'), ('Date', 'date'), ('Facture', 'text'), ('Client', 'text'), ('Montant', 'money'), ('Moyen', 'text')]
        rows = []
        payments = (Payment.objects.filter(invoice__organization=organization, status='completed')
                    .select_related('invoice__client', 'payment_method').order_by('-created_at'))
        for p in payments:
            when = p.processed_at or p.created_at
            rows.append({
                'Référence': p.transaction_id or str(p.id)[:8].upper(),
                'Date': when.date().isoformat() if when else '',
                'Facture': p.invoice.invoice_number if p.invoice_id else '',
                'Client': p.invoice.client.name if p.invoice_id and p.invoice.client_id else '',
                'Montant': p.amount, 'Moyen': p.payment_method.name if p.payment_method_id else '',
            })
        return columns, rows
    raise ValueError('Tableau inconnu.')


def to_csv(columns, rows, *, for_sheets=False):
    """
    CSV du tableau. Par défaut pour Excel en français (séparateur point-virgule, virgule
    décimale, BOM) ; for_sheets=True : format standard converti en Google Sheets par Drive.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=',' if for_sheets else ';')
    writer.writerow([name for name, _ in columns])
    for row in rows:
        values = []
        for name, kind in columns:
            value = row.get(name, '')
            values.append(str(value).replace('.', ',') if kind == 'money' and not for_sheets else value)
        writer.writerow(values)
    return buffer.getvalue() if for_sheets else '﻿' + buffer.getvalue()
