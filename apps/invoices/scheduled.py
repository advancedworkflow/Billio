"""
Tâches planifiées de la facturation, sans Celery : exécutées par la commande
`manage.py run_automations` (à planifier toutes les 5 à 15 min) et à l'ouverture
du tableau de bord.

- Relances des factures en retard à J+7 / J+14 / J+30 (réglages de l'organisation).
- Factures récurrentes : une copie de la facture modèle est émise et envoyée à chaque échéance.
- Email d'envoi des factures et avoirs (lien de paiement + PDF quand il est disponible).

Chaque traitement est idempotent : relance mémorisée sur la facture, échéance
récurrente avancée dans la même transaction que la création de la copie.
"""
import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

REMINDER_STAGES = (('j30', 30, 'automation_reminder_j30'), ('j14', 14, 'automation_reminder_j14'),
                   ('j7', 7, 'automation_reminder_j7'))
RECURRENCE_STEP = {'monthly': relativedelta(months=1), 'quarterly': relativedelta(months=3), 'yearly': relativedelta(years=1)}


def _payment_url(invoice):
    return f"{settings.SITE_URL}{reverse('invoices:public-invoice-payment', args=[invoice.id])}"


def _send(invoice, subject, body, *, attach_pdf=True):
    from django.core.mail import EmailMessage
    from apps.integrations.providers import org_mail

    if not invoice.client_id or not invoice.client.email:
        return False
    organization = invoice.organization
    connection, from_email = org_mail(organization)
    message = EmailMessage(subject=subject, body=body, from_email=from_email, to=[invoice.client.email],
                           connection=connection, reply_to=[organization.email] if organization.email else None)
    if attach_pdf:
        try:
            message.attach(f"{'Avoir' if invoice.is_credit_note else 'Facture'}-{invoice.invoice_number}.pdf",
                           invoice.ensure_pdf(), 'application/pdf')
        except Exception:  # moteur PDF indisponible : le lien suffit
            logger.warning('PDF non joint pour %s', invoice.invoice_number)
    message.send(fail_silently=False)
    return True


def send_invoice_email(invoice):
    """Email d'envoi d'une facture (ou d'un avoir) au client. Ne lève pas : l'envoi reste valide."""
    org = invoice.organization
    name = invoice.client.get_display_name() if invoice.client_id else ''
    if invoice.is_credit_note:
        subject = f"[{org.name}] Avoir {invoice.invoice_number}"
        body = (f"Bonjour {name},\n\nVeuillez trouver ci-joint l'avoir {invoice.invoice_number} d'un montant de "
                f"{invoice.total_amount:.2f} {invoice.currency}"
                + (f", sur la facture {invoice.credited_invoice.invoice_number}" if invoice.credited_invoice_id else '')
                + f".\n\n— {org.name}")
    else:
        subject = f"[{org.name}] Facture {invoice.invoice_number}"
        body = (f"Bonjour {name},\n\nVeuillez trouver votre facture {invoice.invoice_number} d'un montant de "
                f"{invoice.total_amount:.2f} {invoice.currency}, à régler avant le {invoice.due_date:%d/%m/%Y}.\n\n"
                f"Consulter et payer la facture : {_payment_url(invoice)}\n\n— {org.name}")
    try:
        return _send(invoice, subject, body)
    except Exception:
        logger.exception("Email de la facture %s non envoyé", invoice.invoice_number)
        return False


def send_overdue_reminders(organization, today=None):
    """Relances J+7 / J+14 / J+30 activées : une seule par palier, la plus récente atteinte seulement."""
    from .models import Invoice

    from apps.subscriptions.entitlements import has_feature
    if not has_feature(organization, 'reminders'):
        return 0  # relances automatiques : à partir du forfait Starter
    today = today or timezone.localdate()
    stages = [(key, days) for key, days, flag in REMINDER_STAGES if getattr(organization, flag, False)]
    if not stages:
        return 0
    sent = 0
    invoices = Invoice.objects.filter(organization=organization, invoice_type='sale',
                                      status__in=['sent', 'viewed', 'overdue'], due_date__lt=today).select_related('client')
    for invoice in invoices:
        days_late = (today - invoice.due_date).days
        due_stage = next(((key, days) for key, days in stages if days_late >= days), None)  # palier le plus avancé
        already = set(invoice.reminders_sent or [])
        if not due_stage or due_stage[0] in already:
            continue
        key, days = due_stage
        remaining = invoice.amount_due()
        if remaining <= 0:
            continue
        subject = {'j7': f"Rappel : facture {invoice.invoice_number} en attente de règlement",
                   'j14': f"Second rappel : facture {invoice.invoice_number}",
                   'j30': f"Dernière relance : facture {invoice.invoice_number}"}[key]
        body = (f"Bonjour {invoice.client.get_display_name()},\n\n"
                f"Sauf erreur de notre part, la facture {invoice.invoice_number} arrivée à échéance le "
                f"{invoice.due_date:%d/%m/%Y} reste impayée ({remaining:.2f} {invoice.currency}, {days_late} jours de retard).\n\n"
                f"Vous pouvez la régler ici : {_payment_url(invoice)}\n\n"
                + ("Sans règlement de votre part, des pénalités de retard et l'indemnité forfaitaire de 40 € "
                   "pour frais de recouvrement pourront être appliquées.\n\n" if key == 'j30' else '')
                + f"Si le paiement a déjà été effectué, merci de ne pas tenir compte de ce message.\n\n— {organization.name}")
        try:
            if not _send(invoice, subject, body, attach_pdf=(key == 'j7')):
                continue
        except Exception:
            logger.exception('Relance %s non envoyée pour %s', key, invoice.invoice_number)
            continue
        # Les paliers déjà dépassés sont considérés comme traités (pas de rafale de relances).
        invoice.reminders_sent = sorted(already | {k for k, d in stages if d <= days})
        invoice.save(update_fields=['reminders_sent', 'updated_at'])
        sent += 1
    return sent


def generate_recurring_invoices(organization, today=None):
    """Émet les échéances des factures récurrentes arrivées à date. Retourne les factures créées."""
    from .models import Invoice, InvoiceItem

    if not organization.automation_recurring_invoices:
        return []
    today = today or timezone.localdate()
    created = []
    templates = Invoice.objects.filter(organization=organization, invoice_type='sale', recurrence__in=RECURRENCE_STEP,
                                       recurrence_next_date__lte=today).exclude(status__in=['draft', 'cancelled'])
    for template_id in templates.values_list('id', flat=True):
        with transaction.atomic():
            source = Invoice.objects.select_for_update().get(id=template_id)
            due_date = source.recurrence_next_date
            if not due_date or due_date > today or source.recurrence not in RECURRENCE_STEP:
                continue
            if source.recurrence_end_date and due_date > source.recurrence_end_date:
                source.recurrence = 'none'
                source.save(update_fields=['recurrence', 'updated_at'])
                continue
            term = max((source.due_date - source.issue_date).days, 0) if source.due_date and source.issue_date else 30
            copy = Invoice.objects.create(
                organization=organization, client=source.client, created_by=source.created_by,
                invoice_type='sale', status='draft', title=source.title, description=source.description,
                currency=source.currency, template=source.template, notes=source.notes, footer=source.footer,
                issue_date=due_date, due_date=due_date + timedelta(days=term), recurrence_source=source,
                subtotal=source.subtotal, tax_amount=source.tax_amount, discount_amount=source.discount_amount,
                total_amount=source.total_amount,
            )
            for item in source.items.all():
                InvoiceItem.objects.create(invoice=copy, name=item.name, description=item.description, quantity=item.quantity,
                                           unit_price=item.unit_price, unit=item.unit, tax_rate=item.tax_rate, order=item.order)
            source.recurrence_next_date = due_date + RECURRENCE_STEP[source.recurrence]
            source.save(update_fields=['recurrence_next_date', 'updated_at'])
        ok, _message = copy.send_to_client()  # numéro définitif + email au client
        if ok:
            from apps.dashboard.automation_engine import run_automations
            run_automations(organization, 'invoice_sent', target_type='invoice', target_id=copy.id,
                            amount=copy.total_amount, client_id=copy.client_id,
                            context_label=f"Facture récurrente {copy.invoice_number} émise et envoyée.")
        created.append(copy)
    return created


def run_billing_schedule(organization, today=None):
    generate_recurring_invoices(organization, today)
    send_overdue_reminders(organization, today)
