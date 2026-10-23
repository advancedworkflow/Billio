"""
Rapprochement manuel des paiements : relier l'argent reçu sur le compte bancaire aux factures.

1. `parse_statement` lit le relevé CSV de n'importe quelle banque : séparateur, encodage,
   colonnes (date, libellé, montant ou crédit / débit) et formats (1 234,56 · 1,234.56 ·
   31/12/2026 · 2026-12-31 · 31.12.2026) sont détectés ; seules les entrées d'argent comptent.
2. `import_lines` les range en `BankLine` (une empreinte évite les doublons si l'on réimporte).
3. `suggest` propose pour chaque ligne la facture ouverte la plus probable : numéro de facture
   dans le libellé, montant égal au reste dû, nom du client ; « sûre » quand le doute est faible.
4. `match` enregistre le paiement (apps/payments/recording.py) ; `undo` l'annule.
"""
import csv
import hashlib
import io
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction

DATE_HEADERS = ('date operation', 'date d operation', 'date de l operation', 'date', 'booking date', 'transaction date',
                'buchungstag', 'datum', 'fecha', 'value date', 'date valeur')
LABEL_HEADERS = ('libelle', 'label', 'description', 'details', 'detail', 'memo', 'narrative', 'reference', 'payee',
                 'verwendungszweck', 'buchungstext', 'concepto', 'beneficiaire', 'objet', 'intitule')
AMOUNT_HEADERS = ('montant', 'amount', 'betrag', 'importe', 'valeur', 'somme')
CREDIT_HEADERS = ('credit', 'credits', 'haben', 'abono', 'paid in', 'money in', 'entree', 'encaissement')
DEBIT_HEADERS = ('debit', 'debits', 'soll', 'cargo', 'paid out', 'money out', 'sortie')
SURE = 60
POSSIBLE = 25  # ex. nom du client seul sur un paiement partiel : proposé « à vérifier »


class StatementError(ValueError):
    pass


def _norm(text):
    text = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def _find(headers, names):
    """Index de la première colonne dont l'en-tête correspond à l'un des noms (exact, puis contenu)."""
    normalized = [_norm(h) for h in headers]
    for name in names:
        if name in normalized:
            return normalized.index(name)
    for name in names:
        for index, header in enumerate(normalized):
            if name in header.split() or header.startswith(name):
                return index
    return None


def parse_amount(raw):
    """Montant d'une cellule de relevé, signe compris ; None si illisible."""
    text = str(raw or '').strip().replace(' ', ' ').replace(' ', ' ')
    if not text:
        return None
    negative = text.startswith('-') or text.endswith('-') or (text.startswith('(') and text.endswith(')'))
    text = re.sub(r'[^0-9,.\']', '', text.replace(' ', ''))
    if not text:
        return None
    if ',' in text and '.' in text:  # le dernier séparateur est la décimale
        decimal_sep = ',' if text.rfind(',') > text.rfind('.') else '.'
        thousands = '.' if decimal_sep == ',' else ','
        text = text.replace(thousands, '').replace("'", '').replace(decimal_sep, '.')
    elif ',' in text:
        head, _sep, tail = text.rpartition(',')
        text = (head.replace(',', '') + '.' + tail) if len(tail) != 3 or not head else text.replace(',', '')
    text = text.replace("'", '')
    try:
        value = Decimal(text).quantize(Decimal('0.01'))
    except InvalidOperation:
        return None
    return -value if negative else value


def parse_date(raw, month_first=False):
    text = str(raw or '').strip()[:10]
    formats = ['%Y-%m-%d', '%d.%m.%Y', '%d-%m-%Y', '%Y/%m/%d', '%d/%m/%y']
    formats.insert(1, '%m/%d/%Y' if month_first else '%d/%m/%Y')
    formats.append('%d/%m/%Y' if month_first else '%m/%d/%Y')
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _decode(content):
    for encoding in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise StatementError("Fichier illisible : exportez votre relevé au format CSV depuis votre banque.")


def parse_statement(content, month_first=False):
    """(entrées [{'date', 'amount', 'label'}], nombre de sorties d'argent ignorées)."""
    text = _decode(content)
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise StatementError('Le fichier est vide.')
    sample = '\n'.join(lines[:20])
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=';,\t|').delimiter
    except csv.Error:
        delimiter = ';' if sample.count(';') >= sample.count(',') else ','
    rows = list(csv.reader(lines, delimiter=delimiter))

    # Les banques ajoutent souvent quelques lignes d'en-tête (compte, période) : on cherche la ligne des titres.
    header_index = None
    for index, row in enumerate(rows[:15]):
        if _find(row, DATE_HEADERS) is not None and (
                _find(row, AMOUNT_HEADERS) is not None or _find(row, CREDIT_HEADERS) is not None):
            header_index = index
            break
    if header_index is None:
        raise StatementError("Colonnes introuvables : le relevé doit avoir une colonne Date et une colonne Montant "
                             "(ou Crédit / Débit).")
    headers = rows[header_index]
    col_date = _find(headers, DATE_HEADERS)
    col_label = _find(headers, LABEL_HEADERS)
    col_amount = _find(headers, AMOUNT_HEADERS)
    col_credit = _find(headers, CREDIT_HEADERS)
    col_debit = _find(headers, DEBIT_HEADERS)

    def cell(row, index):
        return row[index] if index is not None and index < len(row) else ''

    entries, debits = [], 0
    for row in rows[header_index + 1:]:
        day = parse_date(cell(row, col_date), month_first)
        if day is None:
            continue
        if col_credit is not None and col_amount is None:
            credit, debit = parse_amount(cell(row, col_credit)), parse_amount(cell(row, col_debit))
            amount = abs(credit) if credit else (-abs(debit) if debit else None)
        else:
            amount = parse_amount(cell(row, col_amount))
        if amount is None or amount == 0:
            continue
        if amount < 0:
            debits += 1
            continue
        label = cell(row, col_label) if col_label is not None else ' '.join(
            c for i, c in enumerate(row) if i not in (col_date, col_amount, col_credit, col_debit))
        entries.append({'date': day, 'amount': amount, 'label': ' '.join(label.split())[:500]})
    return entries, debits


def fingerprint(day, amount, label, occurrence=0):
    raw = f'{day.isoformat()}|{amount:.2f}|{_norm(label)}|{occurrence}'
    return hashlib.sha256(raw.encode()).hexdigest()


def import_lines(organization, entries, user=None):
    """Crée les lignes nouvelles. Renvoie (créées, déjà importées)."""
    from .models import BankLine

    created = duplicates = 0
    seen = {}
    for entry in entries:
        key = (entry['date'], entry['amount'], _norm(entry['label']))
        occurrence = seen.get(key, 0)  # deux virements identiques le même jour restent deux lignes
        seen[key] = occurrence + 1
        _line, was_created = BankLine.objects.get_or_create(
            organization=organization, fingerprint=fingerprint(*key, occurrence),
            defaults={'date': entry['date'], 'amount': entry['amount'], 'label': entry['label'], 'imported_by': user},
        )
        created += was_created
        duplicates += not was_created
    return created, duplicates


def add_line(organization, day, amount, label, user=None):
    """Encaissement saisi à la main (chèque déposé, espèces…)."""
    from .models import BankLine
    occurrence = BankLine.objects.filter(organization=organization, date=day, amount=amount).count()
    return BankLine.objects.create(organization=organization, date=day, amount=amount, label=label[:500],
                                   fingerprint=fingerprint(day, amount, f'manuel {label}', occurrence), imported_by=user)


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

def open_invoices(organization):
    """Factures de vente qui attendent un paiement, avec leur reste dû (attribut `remaining`)."""
    from apps.invoices.models import Invoice

    from .cashflow import OPEN_STATUSES
    from .recording import paid_total

    invoices = []
    for invoice in (Invoice.objects.filter(organization=organization, invoice_type='sale', status__in=OPEN_STATUSES)
                    .select_related('client').order_by('due_date')):
        invoice.remaining = invoice.amount_due(paid_total(invoice))
        if invoice.remaining > 0:
            invoices.append(invoice)
    return invoices


def _score(line, invoice):
    label = _norm(line.label)
    compact = label.replace(' ', '')
    score, reasons = 0, []
    number = _norm(invoice.invoice_number).replace(' ', '')
    digits = re.sub(r'\D', '', invoice.invoice_number or '')
    if number and number in compact:
        score += 60
        reasons.append('numéro de facture dans le libellé')
    elif len(digits) >= 3 and re.search(rf'(?<!\d)0*{int(digits)}(?!\d)', label):
        score += 25
        reasons.append('numéro de facture probable')
    if line.amount == invoice.remaining:
        score += 35
        reasons.append('montant exact')
    elif line.amount == invoice.total_amount:
        score += 25
        reasons.append('montant de la facture')
    elif line.amount < invoice.remaining:
        score += 3
    else:
        score -= 40  # plus que le reste dû : impossible sur cette facture
    client = invoice.client
    if client:
        words = [w for w in _norm(f'{client.name} {client.company_name or ""}').split() if len(w) >= 3]
        if words and any(re.search(rf'\b{re.escape(w)}\b', label) for w in words):
            score += 25
            reasons.append('nom du client')
    if line.date < invoice.issue_date:
        score -= 30
    return score, reasons


def suggest(line, invoices):
    """{'invoice', 'score', 'sure', 'reasons'} pour la meilleure facture, ou None."""
    ranked = sorted(((*_score(line, inv), inv) for inv in invoices if line.amount <= inv.remaining + Decimal('0.01')),
                    key=lambda r: r[0], reverse=True)
    if not ranked or ranked[0][0] < POSSIBLE:
        return None
    best_score, reasons, invoice = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else -100
    sure = best_score >= SURE and best_score - runner_up >= 20
    return {'invoice': invoice, 'score': best_score, 'sure': sure, 'reasons': reasons}


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def match(line, invoice, user=None):
    """Enregistre le paiement de cette ligne sur la facture. Renvoie (soldée, reste)."""
    from .recording import record_manual_payment

    if line.status != 'pending':
        raise StatementError('Cette ligne est déjà traitée.')
    with transaction.atomic():
        payment, fully_paid, left = record_manual_payment(
            invoice, line.amount, min(line.date, date.today()), method_type='bank_transfer',
            reference=line.label[:255], notes='Rapprochement bancaire', user=user, source='reconciliation')
        line.payment, line.status = payment, 'matched'
        line.save(update_fields=['payment', 'status'])
    return fully_paid, left


def ignore(line):
    line.status = 'ignored'
    line.save(update_fields=['status'])


def undo(line):
    """Annule un rapprochement (le paiement créé est supprimé) ou une ligne ignorée."""
    from .recording import cancel_manual_payment

    with transaction.atomic():
        if line.status == 'matched' and line.payment_id:
            cancel_manual_payment(line.payment)
        line.payment, line.status = None, 'pending'
        line.save(update_fields=['payment', 'status'])
