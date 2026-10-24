"""
Moyens de paiement en ligne : ce que Stripe Checkout propose au client, selon le pays.

Checkout est appelé sans liste fixe de moyens : Stripe affiche ceux que l'entreprise a activés
dans son tableau de bord (Paramètres › Moyens de paiement), adaptés au pays et à la devise du
client. Billio conseille ceux à activer pour chaque pays et affiche le moyen réellement utilisé.
Les prélèvements (SEPA, ACH, BECS, Bacs, PAD) se confirment après quelques jours : la facture
passe « payée » au webhook `checkout.session.async_payment_succeeded`.

Virement : un QR code EPC (« GiroCode », norme du Conseil européen des paiements) permet au
client de payer une facture en euros en le scannant avec l'application de sa banque.
"""
from decimal import Decimal

STRIPE_SETTINGS_URL = 'https://dashboard.stripe.com/settings/payment_methods'

LABELS = {
    'card': 'Carte bancaire', 'link': 'Link (Stripe)', 'apple_pay': 'Apple Pay', 'google_pay': 'Google Pay',
    'sepa_debit': 'Prélèvement SEPA', 'bancontact': 'Bancontact', 'ideal': 'iDEAL', 'eps': 'EPS',
    'giropay': 'giropay', 'p24': 'Przelewy24', 'blik': 'BLIK', 'klarna': 'Klarna', 'paypal': 'PayPal',
    'us_bank_account': 'Prélèvement bancaire (ACH)', 'bacs_debit': 'Prélèvement Bacs',
    'au_becs_debit': 'Prélèvement BECS', 'acss_debit': 'Prélèvement préautorisé (PAD)',
    'customer_balance': 'Virement bancaire (Stripe)', 'revolut_pay': 'Revolut Pay', 'twint': 'TWINT',
}
# Moyens conseillés en plus de la carte, Apple Pay et Google Pay (toujours utiles).
RECOMMENDED = {
    'FR': ['sepa_debit', 'paypal'], 'BE': ['bancontact', 'sepa_debit'], 'NL': ['ideal', 'sepa_debit'],
    'DE': ['sepa_debit', 'klarna', 'paypal'], 'AT': ['eps', 'sepa_debit'], 'PL': ['blik', 'p24'],
    'ES': ['sepa_debit', 'paypal'], 'IT': ['sepa_debit', 'paypal'], 'LU': ['sepa_debit', 'bancontact'],
    'IE': ['sepa_debit', 'revolut_pay'], 'PT': ['sepa_debit'], 'GB': ['bacs_debit', 'paypal'],
    'US': ['us_bank_account', 'link'], 'CA': ['acss_debit'], 'AU': ['au_becs_debit'], 'NZ': ['link'],
}
DELAYED = {'sepa_debit', 'us_bank_account', 'bacs_debit', 'au_becs_debit', 'acss_debit', 'customer_balance'}


def label(method_type):
    return LABELS.get(method_type, 'Paiement en ligne')


def recommended(country):
    """[(libellé, confirmation différée)] à activer dans Stripe pour ce pays."""
    from apps.organizations.jurisdictions import is_eu
    extra = RECOMMENDED.get(country) or (['sepa_debit'] if is_eu(country) else [])
    return [(LABELS[m], m in DELAYED) for m in ['card', 'apple_pay', 'google_pay', *extra]]


def epc_payload(organization, invoice, amount):
    """Contenu du QR code EPC (virement SEPA) ; '' si la facture n'est pas payable ainsi."""
    iban = ''.join((organization.iban or '').split()).upper()
    if invoice.currency != 'EUR' or not iban or amount is None or Decimal(amount) <= 0 or Decimal(amount) > Decimal('999999999.99'):
        return ''
    name = (organization.name or '')[:70]
    bic = ''.join((organization.bic_swift or '').split()).upper()
    lines = ['BCD', '002', '1', 'SCT', bic, name, iban, f'EUR{Decimal(amount):.2f}', '', '',
             f'Facture {invoice.invoice_number}'[:140]]
    return '\n'.join(lines)


def epc_qr_svg(organization, invoice, amount):
    payload = epc_payload(organization, invoice, amount)
    if not payload:
        return ''
    import segno
    return segno.make(payload, error='m', micro=False).svg_inline(scale=4, border=2, dark='#18181b')
