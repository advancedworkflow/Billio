"""
Facture électronique Factur-X (profil EN 16931, syntaxe UN/CEFACT CII D16B).

- `readiness(invoice)` liste ce qui manque pour une facture électronique conforme
  (SIREN, TVA intracommunautaire, adresses…), en distinguant client professionnel
  (facture électronique obligatoire : réception depuis le 1er sept. 2026, émission
  pour les PME/micro-entreprises au 1er sept. 2027) et particulier (e-reporting).
- `build_cii_xml(invoice)` produit le XML structuré (factur-x.xml).
- `facturx_pdf(invoice)` intègre ce XML dans le PDF de la facture (PDF/A-3, pièce
  jointe « factur-x.xml », métadonnées XMP Factur-X) : WeasyPrint + bibliothèque factur-x.
- `validate(xml)` contrôle le XML (XSD Factur-X EN 16931 + règles métier schematron).

Le dépôt sur une plateforme agréée (PA) se fait avec ce XML ou ce PDF : chaque PA
a sa propre API, à brancher une fois la plateforme choisie.
"""
import re
from collections import OrderedDict
from decimal import Decimal
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

NS = {
    'rsm': 'urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100',
    'ram': 'urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100',
    'udt': 'urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100',
    'qdt': 'urn:un:unece:uncefact:data:standard:QualifiedDataType:100',
}
for _prefix, _uri in NS.items():
    register_namespace(_prefix, _uri)
PROFILE_ID = 'urn:cen.eu:en16931:2017'
UNIT_CODES = {  # unités Billio → codes UN/ECE Recommandation 20
    'heure': 'HUR', 'h': 'HUR', 'hour': 'HUR', 'jour': 'DAY', 'day': 'DAY', 'demi-journée': 'DAY',
    'm²': 'MTK', 'm2': 'MTK', 'ml': 'MTR', 'm': 'MTR', 'kg': 'KGM', 'forfait': 'LS', 'situation': 'LS',
    'mois': 'MON', 'u': 'C62', 'unit': 'C62', 'unité': 'C62', 'lot': 'C62', 'séance': 'C62', 'photo': 'C62',
}
COUNTRIES = {'france': 'FR', 'belgique': 'BE', 'suisse': 'CH', 'luxembourg': 'LU', 'canada': 'CA',
             'allemagne': 'DE', 'espagne': 'ES', 'italie': 'IT', 'maroc': 'MA', 'sénégal': 'SN'}
EXEMPTION_293B = 'TVA non applicable, art. 293 B du CGI'


def _q(prefix, tag):
    return f'{{{NS[prefix]}}}{tag}'


def _sub(parent, tag, text=None, **attrs):
    prefix, name = tag.split(':')
    element = SubElement(parent, _q(prefix, name), {k: str(v) for k, v in attrs.items()})
    if text is not None:
        element.text = str(text)
    return element


def _amount(value):
    return f"{Decimal(value or 0).quantize(Decimal('0.01'))}"


def _digits(value):
    return re.sub(r'\D', '', value or '')


def _country(value):
    raw = (value or '').strip()
    if len(raw) == 2 and raw.isalpha():
        return raw.upper()
    return COUNTRIES.get(raw.lower(), 'FR')


def _vat_exempt(invoice):
    return bool((invoice.organization.billing_preferences or {}).get('vat_exempt'))


def is_business_client(client):
    return bool(client and (client.company_name or client.registration_number or client.tax_id))


def readiness(invoice):
    """{'b2b': bool, 'missing': [libellés], 'ready': bool} pour une facture électronique conforme."""
    org, client = invoice.organization, invoice.client
    missing = []
    if len(_digits(org.registration_number)) not in (9, 14):
        missing.append('SIREN ou SIRET de votre entreprise (Identité & mentions)')
    if not _vat_exempt(invoice) and not (org.tax_id or '').strip():
        missing.append('N° de TVA intracommunautaire de votre entreprise')
    if not (org.address and org.postal_code and org.city):
        missing.append('Adresse complète de votre entreprise')
    b2b = is_business_client(client)
    if b2b:
        if _country(client.country) == 'FR' and len(_digits(client.registration_number)) not in (9, 14):
            missing.append(f'SIREN du client « {client.get_display_name()} »')
        if not (client.address and client.postal_code and client.city):
            missing.append(f'Adresse complète du client « {client.get_display_name()} »')
    if not invoice.items.exists():
        missing.append('Au moins une ligne de facture')
    return {'b2b': b2b, 'missing': missing, 'ready': not missing}


def _party(parent, tag, *, name, siren='', vat='', address='', postal='', city='', country='FR', email=''):
    party = _sub(parent, tag)
    _sub(party, 'ram:Name', name)
    if siren:
        legal = _sub(party, 'ram:SpecifiedLegalOrganization')
        _sub(legal, 'ram:ID', siren[:9], schemeID='0002')
    addr = _sub(party, 'ram:PostalTradeAddress')
    if postal:
        _sub(addr, 'ram:PostcodeCode', postal)
    if address:
        lines = [line.strip() for line in str(address).splitlines() if line.strip()]
        if lines:
            _sub(addr, 'ram:LineOne', lines[0][:100])
        if len(lines) > 1:
            _sub(addr, 'ram:LineTwo', ' '.join(lines[1:])[:100])
    if city:
        _sub(addr, 'ram:CityName', city)
    _sub(addr, 'ram:CountryID', country)
    if email:
        uri = _sub(party, 'ram:URIUniversalCommunication')
        _sub(uri, 'ram:URIID', email, schemeID='EM')
    if vat:
        reg = _sub(party, 'ram:SpecifiedTaxRegistration')
        _sub(reg, 'ram:ID', vat.replace(' ', ''), schemeID='VA')
    return party


def build_cii_xml(invoice):
    """XML Factur-X (EN 16931) de la facture ou de l'avoir. Retourne des bytes UTF-8."""
    org, client = invoice.organization, invoice.client
    exempt = _vat_exempt(invoice)
    items = list(invoice.items.order_by('order', 'id'))

    root = Element(_q('rsm', 'CrossIndustryInvoice'))
    context = _sub(root, 'rsm:ExchangedDocumentContext')
    _sub(_sub(context, 'ram:GuidelineSpecifiedDocumentContextParameter'), 'ram:ID', PROFILE_ID)

    document = _sub(root, 'rsm:ExchangedDocument')
    _sub(document, 'ram:ID', invoice.invoice_number)
    _sub(document, 'ram:TypeCode', '381' if invoice.is_credit_note else '380')
    _sub(_sub(document, 'ram:IssueDateTime'), 'udt:DateTimeString', invoice.issue_date.strftime('%Y%m%d'), format='102')
    notes = [invoice.notes or '']
    mentions = (org.billing_texts() or {}).get('legal_mentions')
    if mentions:
        notes.append(mentions)
    for text in filter(None, (n.strip() for n in notes)):
        _sub(_sub(document, 'ram:IncludedNote'), 'ram:Content', text[:1000])

    transaction = _sub(root, 'rsm:SupplyChainTradeTransaction')
    taxes = OrderedDict()
    line_total = Decimal('0')
    for index, item in enumerate(items, start=1):
        rate = Decimal('0') if exempt else Decimal(item.tax_rate or 0)
        net = Decimal(item.total if item.total is not None else item.quantity * item.unit_price).quantize(Decimal('0.01'))
        line_total += net
        category = 'E' if exempt else ('S' if rate > 0 else 'Z')
        taxes.setdefault((category, rate), Decimal('0'))
        taxes[(category, rate)] += net
        line = _sub(transaction, 'ram:IncludedSupplyChainTradeLineItem')
        _sub(_sub(line, 'ram:AssociatedDocumentLineDocument'), 'ram:LineID', index)
        product = _sub(line, 'ram:SpecifiedTradeProduct')
        _sub(product, 'ram:Name', (item.name or 'Prestation')[:250])
        if item.description:
            _sub(product, 'ram:Description', item.description[:1000])
        agreement = _sub(line, 'ram:SpecifiedLineTradeAgreement')
        _sub(_sub(agreement, 'ram:NetPriceProductTradePrice'), 'ram:ChargeAmount', _amount(item.unit_price))
        delivery = _sub(line, 'ram:SpecifiedLineTradeDelivery')
        _sub(delivery, 'ram:BilledQuantity', f"{Decimal(item.quantity):.2f}",
             unitCode=UNIT_CODES.get((item.unit or '').strip().lower(), 'C62'))
        settlement = _sub(line, 'ram:SpecifiedLineTradeSettlement')
        tax = _sub(settlement, 'ram:ApplicableTradeTax')
        _sub(tax, 'ram:TypeCode', 'VAT')
        _sub(tax, 'ram:CategoryCode', category)
        _sub(tax, 'ram:RateApplicablePercent', f"{rate:.2f}")
        _sub(_sub(settlement, 'ram:SpecifiedTradeSettlementLineMonetarySummation'), 'ram:LineTotalAmount', _amount(net))

    agreement = _sub(transaction, 'ram:ApplicableHeaderTradeAgreement')
    _party(agreement, 'ram:SellerTradeParty', name=org.name, siren=_digits(org.registration_number),
           vat='' if exempt else (org.tax_id or ''), address=org.address, postal=org.postal_code or '',
           city=org.city or '', country=_country(org.country), email=org.email or '')
    _party(agreement, 'ram:BuyerTradeParty', name=client.get_display_name() if client else 'Client',
           siren=_digits(client.registration_number) if client else '', vat=(client.tax_id or '') if client else '',
           address=client.address if client else '', postal=(client.postal_code or '') if client else '',
           city=(client.city or '') if client else '', country=_country(client.country if client else ''),
           email=(client.email or '') if client else '')
    _sub(transaction, 'ram:ApplicableHeaderTradeDelivery')

    settlement = _sub(transaction, 'ram:ApplicableHeaderTradeSettlement')
    _sub(settlement, 'ram:InvoiceCurrencyCode', invoice.currency or 'EUR')
    if org.iban and not invoice.is_credit_note:
        means = _sub(settlement, 'ram:SpecifiedTradeSettlementPaymentMeans')
        _sub(means, 'ram:TypeCode', '58')  # virement SEPA
        _sub(_sub(means, 'ram:PayeePartyCreditorFinancialAccount'), 'ram:IBANID', org.iban.replace(' ', ''))
    allowance = Decimal(invoice.discount_amount or 0).quantize(Decimal('0.01'))
    main_key = max(taxes, key=taxes.get) if taxes else ('S', Decimal('20'))
    if allowance and taxes:
        taxes[main_key] -= allowance
    tax_total = Decimal('0')
    for (category, rate), basis in taxes.items():
        amount = (basis * rate / 100).quantize(Decimal('0.01'))
        tax_total += amount
        tax = _sub(settlement, 'ram:ApplicableTradeTax')
        _sub(tax, 'ram:CalculatedAmount', _amount(amount))
        _sub(tax, 'ram:TypeCode', 'VAT')
        if category == 'E':
            _sub(tax, 'ram:ExemptionReason', EXEMPTION_293B)
        _sub(tax, 'ram:BasisAmount', _amount(basis))
        _sub(tax, 'ram:CategoryCode', category)
        if category == 'E':
            _sub(tax, 'ram:ExemptionReasonCode', 'VATEX-FR-FRANCHISE')
        _sub(tax, 'ram:RateApplicablePercent', f"{rate:.2f}")
    if allowance:
        charge = _sub(settlement, 'ram:SpecifiedTradeAllowanceCharge')
        _sub(_sub(charge, 'ram:ChargeIndicator'), 'udt:Indicator', 'false')
        _sub(charge, 'ram:ActualAmount', _amount(allowance))
        _sub(charge, 'ram:Reason', 'Remise')
        category_tax = _sub(charge, 'ram:CategoryTradeTax')
        _sub(category_tax, 'ram:TypeCode', 'VAT')
        _sub(category_tax, 'ram:CategoryCode', main_key[0])
        _sub(category_tax, 'ram:RateApplicablePercent', f"{main_key[1]:.2f}")
    if invoice.due_date and not invoice.is_credit_note:
        terms = _sub(settlement, 'ram:SpecifiedTradePaymentTerms')
        _sub(_sub(terms, 'ram:DueDateDateTime'), 'udt:DateTimeString', invoice.due_date.strftime('%Y%m%d'), format='102')

    from django.db.models import Sum
    prepaid = Decimal('0') if invoice.is_credit_note else \
        (invoice.payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or Decimal('0'))
    basis_total = line_total - allowance
    grand = basis_total + tax_total
    summary = _sub(settlement, 'ram:SpecifiedTradeSettlementHeaderMonetarySummation')
    _sub(summary, 'ram:LineTotalAmount', _amount(line_total))
    if allowance:
        _sub(summary, 'ram:AllowanceTotalAmount', _amount(allowance))
    _sub(summary, 'ram:TaxBasisTotalAmount', _amount(basis_total))
    _sub(summary, 'ram:TaxTotalAmount', _amount(tax_total), currencyID=invoice.currency or 'EUR')
    _sub(summary, 'ram:GrandTotalAmount', _amount(grand))
    if prepaid:
        _sub(summary, 'ram:TotalPrepaidAmount', _amount(prepaid))
    _sub(summary, 'ram:DuePayableAmount', _amount(max(grand - prepaid, Decimal('0'))))
    if invoice.is_credit_note and invoice.credited_invoice_id:
        ref = _sub(settlement, 'ram:InvoiceReferencedDocument')
        _sub(ref, 'ram:IssuerAssignedID', invoice.credited_invoice.invoice_number)
        _sub(_sub(ref, 'ram:FormattedIssueDateTime'), 'qdt:DateTimeString',
             invoice.credited_invoice.issue_date.strftime('%Y%m%d'), format='102')

    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding='utf-8', xml_declaration=False)


# --------------------------------------------------------------------------- #
# PDF/A-3 avec XML embarqué
# --------------------------------------------------------------------------- #

def facturx_pdf(invoice):
    """PDF/A-3 de la facture avec factur-x.xml embarqué (bibliothèque factur-x : XMP et relation conformes)."""
    import weasyprint
    from facturx import generate_from_binary

    html = f"<style>{invoice.render_css()}</style>{invoice.render_html()}"
    pdf = weasyprint.HTML(string=html).write_pdf(pdf_variant='pdf/a-3b')
    return generate_from_binary(pdf, build_cii_xml(invoice), flavor='factur-x', level='en16931', check_xsd=True, afrelationship='alternative',
                                lang='fr-FR')


def validate(xml):
    """Liste des erreurs XSD / schematron EN 16931 (vide si conforme)."""
    from facturx import xml_check_schematron, xml_check_xsd
    errors = []
    try:
        xml_check_xsd(xml, flavor='factur-x', level='en16931')
    except Exception as exc:
        errors.append(f'XSD : {exc}')
    # Les règles métier (schematron) demandent un serveur Saxon : contrôlées seulement s'il est configuré.
    from django.conf import settings
    server = getattr(settings, 'FACTURX_SAXON_SERVER', '')
    if server:
        try:
            xml_check_schematron(xml, flavor='factur-x', level='en16931', saxon_server_url=server,
                                 saxon_server_raise_if_http_error=True)
        except Exception as exc:
            errors.append(f'Règles EN 16931 : {exc}')
    return errors
