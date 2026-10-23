"""
Documents (factures, devis, avoirs) dans la langue et la taxe du pays de l'organisation.

Les modèles impriment leurs libellés fixes en français (« Facture n° », « Total TTC », « TVA »…).
Au rendu, `localize` remplace ces libellés, et eux seuls, par ceux de la langue des documents
(Paramètres › Pays & conformité) et le nom de la taxe du pays : VAT, GST, GST/HST, Sales tax…
Le contenu saisi par l'utilisateur (désignations, notes, adresses) n'est pas traduit : seul un
nœud de texte égal à un libellé connu (ou qui commence par un libellé suivi de « : ») change.
"""
import re

from apps.organizations import jurisdictions as j

# (français, anglais, allemand, espagnol) ; {tax}, {ht}, {ttc} prennent les mots du pays.
LABELS = [
    ('Devis', 'Quote', 'Angebot', 'Presupuesto'),
    ('Facture n°', 'Invoice no.', 'Rechnung Nr.', 'Factura n.º'),
    ('Devis n°', 'Quote no.', 'Angebot Nr.', 'Presupuesto n.º'),
    ('Devis N°', 'Quote no.', 'Angebot Nr.', 'Presupuesto n.º'),
    ('N°', 'No.', 'Nr.', 'N.º'),
    ('N° du document', 'Document no.', 'Dokument-Nr.', 'N.º de documento'),
    ('Date', 'Date', 'Datum', 'Fecha'),
    ('Date :', 'Date:', 'Datum:', 'Fecha:'),
    ('DATE :', 'DATE:', 'DATUM:', 'FECHA:'),
    ("Date d'émission", 'Issue date', 'Rechnungsdatum', 'Fecha de emisión'),
    ("Date d'émission :", 'Issue date:', 'Rechnungsdatum:', 'Fecha de emisión:'),
    ("Date d'échéance :", 'Due date:', 'Fällig am:', 'Vencimiento:'),
    ('Date limite / échéance :', 'Due date:', 'Fällig am:', 'Vencimiento:'),
    ('Échéance', 'Due date', 'Fälligkeit', 'Vencimiento'),
    ("Valable jusqu'au", 'Valid until', 'Gültig bis', 'Válido hasta'),
    ("Valable jusqu'au :", 'Valid until:', 'Gültig bis:', 'Válido hasta:'),
    ('Avant le', 'Due by', 'Fällig bis', 'Antes del'),
    ('Facture pour', 'Invoice for', 'Rechnung für', 'Factura para'),
    ('Devis pour', 'Quote for', 'Angebot für', 'Presupuesto para'),
    ('échéance', 'due', 'fällig', 'vencimiento'),
    ('Client', 'Client', 'Kunde', 'Cliente'),
    ('Destinataire', 'Bill to', 'Rechnungsempfänger', 'Destinatario'),
    ('Facturé à', 'Bill to', 'Rechnung an', 'Facturado a'),
    ('Émetteur', 'From', 'Von', 'Emisor'),
    ('Désignation', 'Description', 'Bezeichnung', 'Concepto'),
    ('Description', 'Description', 'Beschreibung', 'Descripción'),
    ('Qté', 'Qty', 'Menge', 'Cant.'),
    ('Quantité', 'Quantity', 'Menge', 'Cantidad'),
    ('Unité', 'Unit', 'Einheit', 'Unidad'),
    ('Prix', 'Price', 'Preis', 'Precio'),
    ('Prix unitaire', 'Unit price', 'Einzelpreis', 'Precio unitario'),
    ('Prix unitaire {ht}', 'Unit price {ht}', 'Einzelpreis {ht}', 'Precio unitario {ht}'),
    ('{tax}', '{tax}', '{tax}', '{tax}'),
    ('Montant {tax}', '{tax} amount', '{tax}-Betrag', 'Importe {tax}'),
    ('Montant {ht}', 'Amount {ht}', 'Betrag {ht}', 'Importe {ht}'),
    ('Total {ht}', 'Total {ht}', 'Gesamt {ht}', 'Total {ht}'),
    ('TOTAL {HT}', 'TOTAL {HT}', 'GESAMT {HT}', 'TOTAL {HT}'),
    ('Total {ttc}', 'Total {ttc}', 'Gesamt {ttc}', 'Total {ttc}'),
    ('Total', 'Total', 'Gesamt', 'Total'),
    ('Total {tax}', 'Total {tax}', '{tax} gesamt', 'Total {tax}'),
    ('% {tax}', '% {tax}', '% {tax}', '% {tax}'),
    ('&#37; {tax}', '&#37; {tax}', '&#37; {tax}', '&#37; {tax}'),
    ('Montant', 'Amount', 'Betrag', 'Importe'),
    ('P.U. {ht}', 'Unit price {ht}', 'Einzelpreis {ht}', 'P. unit. {ht}'),
    ('PU {ht}', 'Unit price {ht}', 'Einzelpreis {ht}', 'P. unit. {ht}'),
    ('Sous total', 'Subtotal', 'Zwischensumme', 'Subtotal'),
    ('Remise', 'Discount', 'Rabatt', 'Descuento'),
    ('Totaux', 'Totals', 'Summen', 'Totales'),
    ('Net à payer', 'Amount due', 'Zu zahlen', 'Total a pagar'),
    ('Montant à régler', 'Amount due', 'Zu zahlender Betrag', 'Importe a pagar'),
    ('Coordonnées bancaires', 'Bank details', 'Bankverbindung', 'Datos bancarios'),
    ('Règlement', 'Payment', 'Zahlung', 'Pago'),
    ('Règlement et banque', 'Payment and bank details', 'Zahlung und Bank', 'Pago y banco'),
    ('Mode de paiement :', 'Payment method:', 'Zahlungsart:', 'Forma de pago:'),
    ('Modalités :', 'Terms:', 'Bedingungen:', 'Condiciones:'),
    ('Conditions', 'Terms', 'Bedingungen', 'Condiciones'),
    ('Mentions légales', 'Legal notices', 'Rechtliche Hinweise', 'Avisos legales'),
    ('Notes', 'Notes', 'Notizen', 'Notas'),
    ('Objet', 'Subject', 'Betreff', 'Asunto'),
    ('Objet :', 'Subject:', 'Betreff:', 'Asunto:'),
    ('Délais', 'Lead time', 'Lieferzeit', 'Plazos'),
    ('Dates', 'Dates', 'Daten', 'Fechas'),
    ('Adresse', 'Address', 'Adresse', 'Dirección'),
    ('Téléphone', 'Phone', 'Telefon', 'Teléfono'),
    ('E-mail', 'Email', 'E-Mail', 'Correo'),
    ('Bon pour accord', 'Approved', 'Einverstanden', 'Conforme'),
    ('Date, signature et mention « Bon pour accord »', 'Date, signature and “Approved”',
     'Datum, Unterschrift und „Einverstanden“', 'Fecha, firma y «Conforme»'),
    ('Payé', 'Paid', 'Bezahlt', 'Pagado'),
    ('PAYÉ', 'PAID', 'BEZAHLT', 'PAGADO'),
]
LANG_INDEX = {'fr': 0, 'en': 1, 'de': 2, 'es': 3}

# Mot de la taxe imprimé, selon le pays et la langue des documents.
TAX_WORDS = {
    'GB': 'VAT', 'IE': 'VAT', 'AU': 'GST', 'NZ': 'GST', 'US': 'Sales tax',
    'CA': {'fr': 'TPS/TVH', 'default': 'GST/HST'},
}
EXCL = {'fr': ('HT', 'TTC'), 'en': ('excl. {tax}', 'incl. {tax}'), 'de': ('netto', 'brutto'), 'es': ('sin {tax}', 'con {tax}')}
REG_LABELS = {'GB': 'Company no.', 'US': 'EIN', 'CA': 'Business no.', 'AU': 'ACN', 'NZ': 'NZBN',
              'DE': 'Steuernummer', 'AT': 'Steuernummer', 'ES': 'NIF', 'IT': 'Codice fiscale', 'BE': "N° d'entreprise"}
TAX_ID_LABELS = {'GB': 'VAT no.', 'AU': 'ABN', 'NZ': 'GST no.', 'US': 'Tax ID', 'DE': 'USt-IdNr.', 'AT': 'UID-Nr.',
                 'ES': 'NIF-IVA', 'IT': 'Partita IVA', 'CA': {'fr': 'N° TPS/TVH', 'default': 'GST/HST no.'}}


def _pick(table, code, lang, fallback):
    value = table.get(code, fallback)
    if isinstance(value, dict):
        return value.get(lang, value['default'])
    return value


def words(organization):
    """Langue et mots du pays : {'lang', 'tax', 'ht', 'ttc', 'reg', 'tax_id'}."""
    prof = j.profile(organization)
    code, lang = prof['country'], prof['doc_language']
    pack = j.pack_for(code)
    if pack['region'] == 'eu' and code not in TAX_WORDS:
        tax = {'fr': 'TVA', 'de': 'USt.', 'es': 'IVA'}.get(lang, 'VAT')
    elif not pack['supported']:
        tax = {'fr': 'TVA', 'de': 'Steuer', 'es': 'Impuesto'}.get(lang, 'Tax')  # « TVA » : nom courant en Afrique francophone
    else:
        tax = _pick(TAX_WORDS, code, lang, 'Tax')
    ht, ttc = (w.format(tax=tax) for w in EXCL.get(lang, EXCL['en']))
    if lang == 'en' and code == 'US':
        ht, ttc = 'before tax', 'incl. tax'
    reg = _pick(REG_LABELS, code, lang, 'SIRET' if code in ('FR', '') else {'fr': "N° d'immatriculation"}.get(lang, 'Registration no.'))
    tax_id = _pick(TAX_ID_LABELS, code, lang, {'fr': 'N° de TVA', 'de': 'USt-IdNr.', 'es': 'NIF-IVA'}.get(lang, 'VAT no.')
                   if pack['region'] == 'eu' or code == '' else 'Tax ID')
    return {'lang': lang, 'tax': tax, 'ht': ht, 'ttc': ttc, 'reg': reg, 'tax_id': tax_id}


def _table(organization, credit_note):
    w = words(organization)
    index = LANG_INDEX.get(w['lang'], 1)
    french = {'tax': 'TVA', 'ht': 'HT', 'ttc': 'TTC', 'HT': 'HT'}
    local = {'tax': w['tax'], 'ht': w['ht'], 'ttc': w['ttc'], 'HT': w['ht'].upper()}
    table = {}
    for row in LABELS:
        source, target = row[0].format(**french), row[index].format(**local)
        if source != target:
            table[source] = target
    title = j.document_title(organization, credit_note=credit_note)
    for source in ('Facture', 'Facture / Devis'):
        table[source] = title
    table['FACTURE'] = title.upper()
    if w['reg'] != 'SIRET':
        table['SIRET'] = w['reg']
    if w['tax_id'] != 'N° de TVA':
        table['N° de TVA'] = w['tax_id']
    return table, w


_TEXT = re.compile(r'>([^<]+)<')
_RAW = re.compile(r'(<(style|script)\b.*?</\2>)', re.S | re.I)


def needs_localizing(organization):
    w = words(organization)
    return w['lang'] != 'fr' or w['tax'] != 'TVA' or w['reg'] != 'SIRET'


def localize(html, organization, credit_note=False):
    """HTML du document avec les libellés fixes dans la langue et la taxe du pays."""
    if not html or organization is None or not needs_localizing(organization):
        return html
    table, w = _table(organization, credit_note)
    prefixes = sorted((k for k in table if k.endswith((':', '°', '.'))), key=len, reverse=True)
    dated = sorted((k for k in table if k in ('Avant le', "Valable jusqu'au")), key=len, reverse=True)
    inline = [  # libellés au milieu d'une ligne : « Studio · SIRET 123 · TVA FR12… », « · échéance 22/11 »
        (re.compile(r'\bSIRET(?= ?[0-9])'), w['reg']),
        (re.compile(r'\bTVA(?= ?[A-Z]{0,2}[0-9])'), w['tax_id']),
        (re.compile(r'· échéance (?=[0-9])'), f"· {table.get('échéance', 'échéance')} "),
    ]

    def swap(match):
        text = match.group(1)
        core = text.strip()
        if not core:
            return match.group(0)
        lead, trail = text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
        if core in table:
            return f'>{lead}{table[core]}{trail}<'
        changed = core
        for key in prefixes:  # « Facture n° INV-0001 », « Date : 12/03/2026 »
            if core.startswith(key) and len(core) > len(key):
                changed = table[key] + core[len(key):]
                break
        else:
            for key in dated:  # « Avant le 22/11/2026 »
                if re.match(re.escape(key) + r' \d', core):
                    changed = table[key] + core[len(key):]
                    break
        for pattern, replacement in inline:
            changed = pattern.sub(replacement, changed)
        return f'>{lead}{changed}{trail}<' if changed != core else match.group(0)

    parts = _RAW.split(html)
    out = []
    skip = False
    for part in parts:
        if skip:  # nom de balise capturé par le groupe 2
            skip = False
            continue
        if _RAW.fullmatch(part or ''):
            out.append(part)
            skip = True
            continue
        out.append(_TEXT.sub(swap, part))
    return ''.join(out)
