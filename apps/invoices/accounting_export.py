"""
Export comptable universel (tous pays) : une archive ZIP de trois CSV, à importer ou à
transmettre au comptable, quel que soit son logiciel (Xero, QuickBooks, Sage, Excel…).

- factures.csv : une ligne par facture, avoir ou facture d'achat émis (montants HT, taxe, TTC,
  payé, reste dû) ;
- lignes.csv : une ligne par ligne de facture (désignation, quantité, prix, taux de taxe) ;
- paiements.csv : les règlements reçus ou versés de la période.

En France, le FEC (apps/invoices/fec.py) reste le format légal ; ce CSV le complète.
Séparateur « ; » et BOM UTF-8 pour Excel ; dates AAAA-MM-JJ ; montants avec un point.
"""
import csv
import io
import zipfile
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

HEADERS = {
    'invoices': {
        'fr': ['Date', 'Numéro', 'Type', 'Statut', 'Client', 'N° de TVA client', 'Pays client', 'Échéance',
               'Total HT', 'Taxe', 'Total TTC', 'Devise', 'Payé', 'Reste dû', 'Facture d\'origine'],
        'en': ['Date', 'Number', 'Type', 'Status', 'Contact', 'Contact tax ID', 'Contact country', 'Due date',
               'Net', 'Tax', 'Gross', 'Currency', 'Paid', 'Amount due', 'Original invoice'],
        'de': ['Datum', 'Nummer', 'Art', 'Status', 'Kunde', 'USt-IdNr. Kunde', 'Land Kunde', 'Fällig',
               'Netto', 'Steuer', 'Brutto', 'Währung', 'Bezahlt', 'Offen', 'Ursprungsrechnung'],
        'es': ['Fecha', 'Número', 'Tipo', 'Estado', 'Cliente', 'NIF cliente', 'País cliente', 'Vencimiento',
               'Base', 'Impuesto', 'Total', 'Moneda', 'Pagado', 'Pendiente', 'Factura original'],
    },
    'lines': {
        'fr': ['Numéro', 'Date', 'Client', 'Désignation', 'Quantité', 'Unité', 'Prix unitaire HT', 'Taux de taxe %', 'Total HT', 'Devise'],
        'en': ['Invoice number', 'Date', 'Contact', 'Description', 'Quantity', 'Unit', 'Unit amount', 'Tax rate %', 'Line amount', 'Currency'],
        'de': ['Rechnungsnummer', 'Datum', 'Kunde', 'Bezeichnung', 'Menge', 'Einheit', 'Einzelpreis netto', 'Steuersatz %', 'Betrag netto', 'Währung'],
        'es': ['Factura', 'Fecha', 'Cliente', 'Concepto', 'Cantidad', 'Unidad', 'Precio unitario', 'Tipo %', 'Importe', 'Moneda'],
    },
    'payments': {
        'fr': ['Date', 'Facture', 'Client', 'Montant', 'Frais', 'Devise', 'Moyen', 'Référence'],
        'en': ['Date', 'Invoice number', 'Contact', 'Amount', 'Fees', 'Currency', 'Method', 'Reference'],
        'de': ['Datum', 'Rechnung', 'Kunde', 'Betrag', 'Gebühren', 'Währung', 'Zahlungsart', 'Referenz'],
        'es': ['Fecha', 'Factura', 'Cliente', 'Importe', 'Comisiones', 'Moneda', 'Medio', 'Referencia'],
    },
}
TYPES = {
    'sale': {'fr': 'Facture', 'en': 'Invoice', 'de': 'Rechnung', 'es': 'Factura'},
    'credit_note': {'fr': 'Avoir', 'en': 'Credit note', 'de': 'Gutschrift', 'es': 'Rectificativa'},
    'purchase': {'fr': 'Achat', 'en': 'Bill', 'de': 'Eingangsrechnung', 'es': 'Compra'},
}
FILES = {'fr': ('factures.csv', 'lignes.csv', 'paiements.csv'), 'en': ('invoices.csv', 'lines.csv', 'payments.csv'),
         'de': ('rechnungen.csv', 'positionen.csv', 'zahlungen.csv'), 'es': ('facturas.csv', 'lineas.csv', 'pagos.csv')}


def _csv(header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=';')
    writer.writerow(header)
    writer.writerows(rows)
    return '﻿' + buffer.getvalue()


def _amount(value):
    return f'{Decimal(value or 0).quantize(Decimal("0.01"))}'


def build(organization, start, end):
    """Octets de l'archive ZIP pour la période (dates de pièce)."""
    from apps.organizations.jurisdictions import profile
    from apps.payments.models import Payment

    from .models import Invoice

    lang = profile(organization)['doc_language']
    lang = lang if lang in FILES else 'en'
    invoices = (Invoice.objects.filter(organization=organization, issue_date__gte=start, issue_date__lte=end,
                                       invoice_type__in=TYPES)
                .exclude(status='draft').select_related('client', 'credited_invoice')
                .prefetch_related('items').order_by('issue_date', 'invoice_number'))
    invoice_rows, line_rows = [], []
    for invoice in invoices:
        sign = Decimal('-1') if invoice.is_credit_note else Decimal('1')
        paid = invoice.payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or Decimal('0')
        client = invoice.client
        invoice_rows.append([
            invoice.issue_date.isoformat(), invoice.invoice_number, TYPES[invoice.invoice_type][lang],
            invoice.get_status_display(), client.name if client else '', (client.tax_id or '') if client else '',
            (client.country or '') if client else '', invoice.due_date.isoformat() if invoice.due_date else '',
            _amount((invoice.total_amount - invoice.tax_amount) * sign), _amount(invoice.tax_amount * sign),
            _amount(invoice.total_amount * sign), invoice.currency, _amount(paid),
            _amount(invoice.amount_due(paid)) if invoice.invoice_type == 'sale' else '',
            invoice.credited_invoice.invoice_number if invoice.credited_invoice_id else '',
        ])
        for item in invoice.items.all():
            line_rows.append([
                invoice.invoice_number, invoice.issue_date.isoformat(), client.name if client else '', item.name,
                f'{item.quantity}', item.unit, _amount(item.unit_price), f'{Decimal(item.tax_rate).normalize():f}',
                _amount(Decimal(item.quantity) * Decimal(item.unit_price) * sign), invoice.currency,
            ])

    payment_rows = []
    payments = (Payment.objects.filter(invoice__organization=organization, status='completed')
                .select_related('invoice', 'invoice__client', 'payment_method'))
    for payment in payments:
        moment = payment.payment_date or payment.created_at
        day = timezone.localtime(moment).date()
        if not (start <= day <= end):
            continue
        invoice = payment.invoice
        payment_rows.append([
            day.isoformat(), invoice.invoice_number, invoice.client.name if invoice.client_id else '',
            _amount(payment.amount), _amount(payment.processing_fee), payment.currency,
            (payment.payment_method.name if payment.payment_method_id else (payment.provider or '')),
            payment.transaction_id or '',
        ])
    payment_rows.sort()

    names = FILES[lang]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(names[0], _csv(HEADERS['invoices'][lang], invoice_rows))
        zf.writestr(names[1], _csv(HEADERS['lines'][lang], line_rows))
        zf.writestr(names[2], _csv(HEADERS['payments'][lang], payment_rows))
    return archive.getvalue()
