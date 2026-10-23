"""
Fichier des écritures comptables (FEC, art. L47 A et A47 A-1 du LPF) à remettre à
l'administration fiscale en cas de contrôle, ou à transmettre à l'expert-comptable.

Écritures produites pour une organisation et une période (date de pièce) :

- VT (ventes) : facture émise → 411 client au débit (TTC), 706/707 au crédit (HT) et 4457x
  TVA collectée au crédit, ventilés par taux ; un avoir passe les mêmes comptes en sens inverse ;
- AC (achats) : facture d'achat → 6xx et 44566 TVA déductible au débit, 401 fournisseur au crédit ;
- BQ (banque) : paiement reçu → 512 au débit (627 pour les frais Stripe), 411 au crédit ;
  paiement d'une facture d'achat → 401 au débit, 512 au crédit.

Les comptes clients et fournisseurs sont des comptes auxiliaires (CompAuxNum) ; une facture
soldée (payée ou annulée par avoir) est lettrée avec ses règlements quand le tout s'équilibre.
Format : 18 colonnes séparées par des tabulations, montants à virgule, dates AAAAMMJJ,
encodage ISO 8859-15, nom SIRENFECAAAAMMJJ.txt (date de clôture).
"""
import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

COLUMNS = ['JournalCode', 'JournalLib', 'EcritureNum', 'EcritureDate', 'CompteNum', 'CompteLib',
           'CompAuxNum', 'CompAuxLib', 'PieceRef', 'PieceDate', 'EcritureLib', 'Debit', 'Credit',
           'EcritureLet', 'DateLet', 'ValidDate', 'Montantdevise', 'Idevise']
JOURNALS = {'VT': 'Journal des ventes', 'AC': 'Journal des achats', 'BQ': 'Banque'}
SALES_ACCOUNTS = {
    '706000': 'Prestations de services',
    '707000': 'Ventes de marchandises',
}
ACCOUNTS = {
    '411000': 'Clients',
    '401000': 'Fournisseurs',
    '512000': 'Banque',
    '606000': 'Achats non stockés de matières et fournitures',
    '445660': 'TVA déductible sur autres biens et services',
    '445710': 'TVA collectée',
    '627000': 'Services bancaires et assimilés',
    **SALES_ACCOUNTS,
}
# TVA collectée : un sous-compte par taux, comme la plupart des plans de comptes des cabinets.
VAT_ACCOUNTS = {Decimal('20'): '445711', Decimal('10'): '445712', Decimal('5.5'): '445713',
                Decimal('2.1'): '445714', Decimal('8.5'): '445715'}
CENT = Decimal('0.01')
ISSUED_TYPES = ('sale', 'credit_note', 'purchase')


def _money(value):
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def _fmt_amount(value):
    return f'{_money(value):.2f}'.replace('.', ',')


def _fmt_date(value):
    if value is None:
        return ''
    if hasattr(value, 'hour'):
        value = timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return value.strftime('%Y%m%d')


def _text(value):
    """Texte d'une colonne : ni tabulation ni retour à la ligne, caractères ISO 8859-15."""
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    return text.encode('iso-8859-15', 'replace').decode('iso-8859-15')


def siren(organization):
    digits = re.sub(r'\D', '', organization.registration_number or '')
    return digits[:9] if len(digits) >= 9 else ''


def filename(organization, end):
    return f"{siren(organization) or '000000000'}FEC{end:%Y%m%d}.txt"


def vat_account(rate):
    return VAT_ACCOUNTS.get(Decimal(rate).normalize(), '445710') if rate else '445710'


def vat_label(rate):
    return f"TVA collectée {Decimal(rate).normalize():f} %".replace('.', ',') if rate else 'TVA collectée'


def split_by_rate(invoice):
    """[(taux, HT, TVA)] dont la somme vaut exactement le HT et la TVA de la facture.

    Les lignes donnent la répartition par taux (acomptes déduits compris, en lignes négatives) ;
    les totaux de la facture, eux, font foi : remise et arrondis sont répartis au prorata.
    """
    total = _money(invoice.total_amount)
    vat_total = _money(invoice.tax_amount)
    ht_total = total - vat_total
    bases = defaultdict(Decimal)
    for item in invoice.items.all():
        bases[Decimal(item.tax_rate or 0).normalize()] += Decimal(item.quantity) * Decimal(item.unit_price)
    bases = {rate: base for rate, base in bases.items() if base}
    if not bases:
        rate = (vat_total / ht_total * 100).quantize(Decimal('0.1')).normalize() if ht_total else Decimal('0')
        return [(rate, ht_total, vat_total)]
    vat_weights = {rate: base * rate / 100 for rate, base in bases.items()}
    rows = []
    for rate, base in bases.items():
        ht = _money(ht_total * base / sum(bases.values()))
        weight = sum(vat_weights.values())
        vat = _money(vat_total * vat_weights[rate] / weight) if weight else Decimal('0')
        rows.append([rate, ht, vat])
    # Écarts d'arrondi sur la ligne la plus importante.
    biggest = max(rows, key=lambda r: abs(r[1]))
    biggest[1] += ht_total - sum(r[1] for r in rows)
    biggest[2] += vat_total - sum(r[2] for r in rows)
    return [tuple(r) for r in rows if r[1] or r[2]]


class _Entry:
    def __init__(self, journal, date, piece, piece_date, label, valid_date, currency):
        self.journal, self.date, self.piece, self.piece_date = journal, date, piece, piece_date
        self.label, self.valid_date, self.currency = label, valid_date, currency
        self.lines = []

    def add(self, account, debit=Decimal('0'), credit=Decimal('0'), aux=None, letter_key=None, label=''):
        debit, credit = _money(debit), _money(credit)
        if debit < 0 or credit < 0:  # montant négatif (avoir, acompte déduit) : on change de colonne
            debit, credit = max(debit, -credit, Decimal('0')), max(credit, -debit, Decimal('0'))
        if debit or credit:
            self.lines.append({'account': account, 'debit': debit, 'credit': credit, 'aux': aux,
                               'letter_key': letter_key, 'label': label or ACCOUNTS.get(account, '')})


def _client_aux(client, prefix):
    if not client:
        return (f'{prefix}DIVERS', 'Divers')
    return (f'{prefix}{client.pk:05d}', client.company_name or client.name)


def build_entries(organization, start, end, sales_account='706000'):
    """Écritures de la période, dans l'ordre chronologique (liste d'_Entry)."""
    from apps.payments.models import Payment

    from .models import Invoice

    sales_account = sales_account if sales_account in SALES_ACCOUNTS else '706000'
    entries = []
    invoices = (Invoice.objects.filter(organization=organization, invoice_type__in=ISSUED_TYPES,
                                       issue_date__gte=start, issue_date__lte=end)
                .exclude(status='draft').select_related('client').prefetch_related('items'))
    for invoice in invoices:
        purchase = invoice.invoice_type == 'purchase'
        sign = Decimal('-1') if invoice.is_credit_note else Decimal('1')
        total = _money(invoice.total_amount) * sign
        settled_key = _settled_key(invoice)
        entry = _Entry('AC' if purchase else 'VT', invoice.issue_date, invoice.invoice_number, invoice.issue_date,
                       f"{'Avoir' if invoice.is_credit_note else 'Facture'} {invoice.invoice_number}"
                       + (f" {invoice.client.name}" if invoice.client_id else ''),
                       invoice.sent_at or invoice.issue_date, invoice.currency)
        if purchase:
            supplier = _client_aux(invoice.client, 'F')
            for _rate, ht, vat in split_by_rate(invoice):
                entry.add('606000', debit=ht)
                entry.add('445660', debit=vat)
            entry.add('401000', credit=total, aux=supplier, letter_key=settled_key)
        else:
            client = _client_aux(invoice.client, 'C')
            entry.add('411000', debit=total, aux=client, letter_key=settled_key)
            for rate, ht, vat in split_by_rate(invoice):
                entry.add(sales_account, credit=ht * sign)
                entry.add(vat_account(rate), credit=vat * sign, label=vat_label(rate))
        entries.append(entry)

    payments = (Payment.objects.filter(invoice__organization=organization, status='completed')
                .select_related('invoice', 'invoice__client'))
    for payment in payments:
        date = timezone.localtime(payment.payment_date).date() if payment.payment_date else timezone.localtime(payment.created_at).date()
        if not (start <= date <= end):
            continue
        invoice = payment.invoice
        purchase = invoice.invoice_type == 'purchase'
        amount = _money(payment.amount)
        fee = _money(payment.processing_fee) if not purchase else Decimal('0')
        entry = _Entry('BQ', date, (payment.transaction_id or invoice.invoice_number)[:60], date,
                       f"Règlement {invoice.invoice_number}" + (f" {invoice.client.name}" if invoice.client_id else ''),
                       date, payment.currency)
        key = _settled_key(invoice)
        if purchase:
            entry.add('401000', debit=amount, aux=_client_aux(invoice.client, 'F'), letter_key=key)
            entry.add('512000', credit=amount)
        else:
            entry.add('512000', debit=amount - fee)
            entry.add('627000', debit=fee)
            entry.add('411000', credit=amount, aux=_client_aux(invoice.client, 'C'), letter_key=key)
        entries.append(entry)

    entries.sort(key=lambda e: (e.date, {'VT': 0, 'AC': 1, 'BQ': 2}[e.journal], e.piece))
    _letter(entries)
    return entries


def _settled_key(invoice):
    """Clé de lettrage : la facture d'origine, si elle est soldée (payée, ou annulée par avoir)."""
    origin = invoice.credited_invoice if invoice.is_credit_note else invoice
    if origin is None or origin.status not in ('paid', 'cancelled'):
        return None
    return origin.pk


def _letter(entries):
    """Lettre les lignes clients/fournisseurs d'une même facture soldée quand elles s'équilibrent."""
    groups = defaultdict(list)
    for entry in entries:
        for line in entry.lines:
            if line['letter_key']:
                groups[line['letter_key']].append((entry, line))
    counter = 0
    for lines in groups.values():
        if len(lines) < 2 or sum(l['debit'] - l['credit'] for _e, l in lines) != 0:
            continue  # règlement hors période ou écart : laissé non lettré
        code = _letter_code(counter)
        counter += 1
        date_let = max(e.date for e, _l in lines)
        for _entry, line in lines:
            line['letter'], line['date_let'] = code, date_let


def _letter_code(index):
    """AAA, AAB, … : codes de lettrage sur 3 lettres."""
    letters = ''
    for _ in range(3):
        index, rest = divmod(index, 26)
        letters = chr(65 + rest) + letters
    return letters


def render(organization, start, end, sales_account='706000'):
    """Contenu du FEC (octets ISO 8859-15) et nombre d'écritures."""
    entries = build_entries(organization, start, end, sales_account)
    rows = ['\t'.join(COLUMNS)]
    number = 0
    for entry in entries:
        if not entry.lines:
            continue
        number += 1
        foreign = entry.currency and entry.currency != 'EUR'
        for line in entry.lines:
            aux_num, aux_lib = line['aux'] or ('', '')
            rows.append('\t'.join(_text(value) for value in [
                entry.journal, JOURNALS[entry.journal], f'{entry.journal}{number:06d}', _fmt_date(entry.date),
                line['account'], line['label'],
                aux_num, aux_lib, entry.piece, _fmt_date(entry.piece_date), entry.label,
                _fmt_amount(line['debit']), _fmt_amount(line['credit']),
                line.get('letter', ''), _fmt_date(line.get('date_let')), _fmt_date(entry.valid_date),
                _fmt_amount(line['debit'] or line['credit']) if foreign else '', entry.currency if foreign else '',
            ]))
    return ('\r\n'.join(rows) + '\r\n').encode('iso-8859-15', 'replace'), number
