"""
Celery tasks for the invoices app: automatic quote reminders (J+3/J+7/avant
expiration) and misc file cleanup, referenced by config/celery.py's beat_schedule.
"""
from celery import shared_task
from django.utils import timezone


@shared_task
def send_quote_reminders():
    """
    Tâche quotidienne : fait passer en 'expired' les devis dont la date de
    validité est dépassée, puis envoie les relances J+3/J+7/avant expiration
    aux devis actifs des organisations qui ont activé cette automatisation.
    """
    from .models import Quote

    today = timezone.now().date()

    Quote.objects.filter(
        status__in=['sent', 'viewed'], expiry_date__lt=today
    ).update(status='expired')

    quotes = Quote.objects.filter(
        status__in=['sent', 'viewed'],
        organization__automation_quote_reminders=True,
    ).select_related('client', 'organization')

    sent_count = 0
    for quote in quotes:
        if not quote.sent_at or not quote.client_id or not quote.client.email:
            continue
        days_since_sent = (today - quote.sent_at.date()).days
        days_to_expiry = (quote.expiry_date - today).days

        if days_since_sent == 3:
            _send_quote_reminder_email(quote, 'j3')
            sent_count += 1
        elif days_since_sent == 7:
            _send_quote_reminder_email(quote, 'j7')
            sent_count += 1
        elif days_to_expiry == 3:
            _send_quote_reminder_email(quote, 'before_expiry')
            sent_count += 1

    return sent_count


def _send_quote_reminder_email(quote, kind):
    from django.core.mail import send_mail
    from django.conf import settings

    subjects = {
        'j3': f"Avez-vous bien reçu notre devis {quote.quote_number} ?",
        'j7': f"Avez-vous eu l'occasion de consulter notre proposition {quote.quote_number} ?",
        'before_expiry': f"Le devis {quote.quote_number} arrive bientôt à expiration",
    }
    bodies = {
        'j3': "Nous voulions nous assurer que vous avez bien reçu notre devis.",
        'j7': "Avez-vous eu l'occasion de consulter notre proposition ?",
        'before_expiry': "Votre devis arrive bientôt à expiration.",
    }
    from apps.integrations.providers import org_mail
    connection, from_email = org_mail(quote.organization)
    send_mail(
        subject=subjects[kind],
        message=bodies[kind],
        from_email=from_email,
        connection=connection,
        recipient_list=[quote.client.email],
        fail_silently=True,
    )


@shared_task
def send_scheduled_invoices():
    """
    Tâche fréquente : envoie automatiquement les factures brouillon dont la
    date d'envoi programmée (`scheduled_send_at`) est atteinte.
    """
    from .models import Invoice

    now = timezone.now()
    due = Invoice.objects.filter(
        status='draft', scheduled_send_at__isnull=False, scheduled_send_at__lte=now,
    )

    sent_count = 0
    for invoice in due:
        success, _message = invoice.send_to_client()
        if success:
            invoice.scheduled_send_at = None
            invoice.save(update_fields=['scheduled_send_at', 'updated_at'])
            sent_count += 1

    return sent_count


@shared_task
def cleanup_old_files():
    """
    Tâche quotidienne : nettoie les fichiers PDF des devis/factures annulés
    ou refusés de longue date, pour ne pas accumuler du stockage inutilement.
    """
    from datetime import timedelta
    from .models import Quote, Invoice

    cutoff = timezone.now() - timedelta(days=90)
    removed = 0

    for quote in Quote.objects.filter(status='rejected', updated_at__lt=cutoff, pdf_file__isnull=False).exclude(pdf_file=''):
        quote.pdf_file.delete(save=True)
        removed += 1

    for invoice in Invoice.objects.filter(status='cancelled', updated_at__lt=cutoff, pdf_file__isnull=False).exclude(pdf_file=''):
        invoice.pdf_file.delete(save=True)
        removed += 1

    return removed
