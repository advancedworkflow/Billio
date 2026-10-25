"""
Lien de paiement d'une facture : la page publique /invoices/public/<uuid>/pay/, permanente.

Chaque visite affiche le reste dû recalculé (paiements, avoirs) ; avec le paiement en ligne,
le bouton ouvre une session Stripe Checkout pour ce montant. Le lien sert partout : email
d'envoi, relances, portail client, page de la facture et QR code « Payer en ligne » du PDF.
"""
from django.conf import settings
from django.urls import reverse
from django.utils.safestring import mark_safe

PAYABLE_STATUSES = ('sent', 'viewed', 'overdue')


def payment_url(invoice):
    return f"{settings.SITE_URL}{reverse('invoices:public-invoice-payment', args=[invoice.id])}"


def payable(invoice):
    """Facture de vente émise, pas encore soldée."""
    return (getattr(invoice, 'invoice_type', '') == 'sale' and invoice.status in PAYABLE_STATUSES
            and invoice.amount_due() > 0)


def qr_svg(url, scale=3):
    import segno
    return segno.make(url, error='m', micro=False).svg_inline(scale=scale, border=1, dark='#18181b')


def document_context(invoice):
    """Variables {{ payment_url }} / {{ payment_qr }} des modèles : seulement si le client peut payer en ligne."""
    from .stripe_checkout import online_payments_enabled
    if not invoice.pk or not payable(invoice) or not online_payments_enabled(invoice.organization):
        return {'payment_url': '', 'payment_qr': ''}
    url = payment_url(invoice)
    return {'payment_url': url, 'payment_qr': mark_safe(qr_svg(url))}
