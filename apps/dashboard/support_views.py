"""
Support : tickets des utilisateurs vers l'équipe Billio.

- Un utilisateur voit ses tickets, en ouvre, répond et marque « résolu ».
- L'équipe Billio (comptes staff) voit tous les tickets, filtre par statut, répond et change le statut.
- E-mails : nouveau ticket / réponse client → adresse SUPPORT_EMAIL (si définie) ;
  réponse de l'équipe → e-mail et notification à l'utilisateur.
"""
import logging
import os
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Notification, SupportMessage, SupportTicket
from .views import _first_user_organization

logger = logging.getLogger(__name__)

MAX_ATTACHMENT = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.pdf', '.txt', '.csv')


def _is_staff(user):
    return user.is_staff or user.is_superuser


def _tickets_for(user):
    return SupportTicket.objects.all() if _is_staff(user) else SupportTicket.objects.filter(user=user)


def _clean_attachment(request):
    """Fichier joint valide ou None ; un fichier refusé ajoute un message d'erreur."""
    upload = request.FILES.get('attachment')
    if not upload:
        return None
    name = (upload.name or '').lower()
    if upload.size > MAX_ATTACHMENT or not name.endswith(ALLOWED_EXTENSIONS):
        messages.error(request, 'Pièce jointe refusée : image, PDF, TXT ou CSV de 5 Mo maximum.')
        return False
    # Nom aléatoire : l'adresse du fichier ne se devine pas ; il n'est servi qu'aux personnes du ticket.
    upload.name = f'{uuid.uuid4().hex}{os.path.splitext(name)[1]}'
    return upload


def _notify_support(ticket, message, request, *, new):
    to = getattr(settings, 'SUPPORT_EMAIL', '')
    if not to:
        return
    url = request.build_absolute_uri(reverse('dashboard:support-ticket', args=[ticket.id]))
    subject = f"[Support #{ticket.id}] {'Nouveau ticket' if new else 'Nouvelle réponse'} : {ticket.subject}"
    body = (f"De : {ticket.user.get_full_name() or ticket.user.email} <{ticket.user.email}>\n"
            f"Organisation : {ticket.organization.name if ticket.organization else '—'}\n"
            f"Catégorie : {ticket.get_category_display()} · Priorité : {ticket.get_priority_display()}\n\n"
            f"{message.body}\n\n{url}")
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
    except Exception:  # un SMTP indisponible ne doit pas bloquer le ticket
        logger.exception('E-mail au support non envoyé (ticket %s)', ticket.id)


def _notify_user(ticket, message, request):
    Notification.objects.create(
        user=ticket.user, notification_type='support_reply',
        title=f"Réponse du support : {ticket.subject}"[:200],
        message=message.body[:500], priority='medium',
    )
    url = request.build_absolute_uri(reverse('dashboard:support-ticket', args=[ticket.id]))
    try:
        send_mail(f"Réponse à votre demande : {ticket.subject}",
                  f"Bonjour,\n\nL'équipe Billio a répondu à votre demande :\n\n{message.body}\n\nRépondre ou consulter le fil : {url}",
                  settings.DEFAULT_FROM_EMAIL, [ticket.user.email], fail_silently=False)
    except Exception:
        logger.exception('E-mail de réponse non envoyé (ticket %s)', ticket.id)


@login_required
def support_list(request):
    tickets = _tickets_for(request.user).select_related('user', 'organization').prefetch_related('messages')
    status = request.GET.get('status', '')
    if status in dict(SupportTicket.STATUS_CHOICES):
        tickets = tickets.filter(status=status)
    if request.method == 'POST':
        subject = (request.POST.get('subject') or '').strip()[:160]
        body = (request.POST.get('body') or '').strip()[:10000]
        if not subject or not body:
            messages.error(request, 'Indiquez un sujet et décrivez votre demande.')
            return redirect('dashboard:support')
        attachment = _clean_attachment(request)
        if attachment is False:
            return redirect('dashboard:support')
        ticket = SupportTicket.objects.create(
            user=request.user, organization=_first_user_organization(request.user), subject=subject,
            category=request.POST.get('category') if request.POST.get('category') in dict(SupportTicket.CATEGORY_CHOICES) else 'question',
            priority='urgent' if request.POST.get('priority') == 'urgent' else 'normal',
            page_url=(request.POST.get('page_url') or '')[:300],
        )
        message = SupportMessage.objects.create(ticket=ticket, author=request.user, body=body, attachment=attachment or '')
        _notify_support(ticket, message, request, new=True)
        messages.success(request, 'Demande envoyée : nous vous répondons ici et par e-mail.')
        return redirect('dashboard:support-ticket', ticket_id=ticket.id)
    counts = {key: _tickets_for(request.user).filter(status=key).count() for key, _ in SupportTicket.STATUS_CHOICES}
    return render(request, 'dashboard/support.html', {
        'page_title': 'Support', 'tickets': tickets, 'status': status, 'counts': counts,
        'is_staff': _is_staff(request.user),
        'categories': SupportTicket.CATEGORY_CHOICES, 'statuses': SupportTicket.STATUS_CHOICES,
        'prefill_subject': request.GET.get('subject', '')[:160],
    })


@login_required
def support_ticket(request, ticket_id):
    ticket = get_object_or_404(_tickets_for(request.user).select_related('user', 'organization'), id=ticket_id)
    staff = _is_staff(request.user)
    if request.method == 'POST':
        body = (request.POST.get('body') or '').strip()[:10000]
        attachment = _clean_attachment(request)
        if attachment is False:
            return redirect('dashboard:support-ticket', ticket_id=ticket.id)
        if body or attachment:
            message = SupportMessage.objects.create(ticket=ticket, author=request.user, from_staff=staff and request.user != ticket.user,
                                                    body=body or '(pièce jointe)', attachment=attachment or '')
            if message.from_staff:
                ticket.status = 'answered'
                _notify_user(ticket, message, request)
            else:
                ticket.status = 'open'
                _notify_support(ticket, message, request, new=False)
            ticket.save(update_fields=['status', 'updated_at'])
            messages.success(request, 'Réponse envoyée.')
        return redirect('dashboard:support-ticket', ticket_id=ticket.id)
    return render(request, 'dashboard/support_ticket.html', {
        'page_title': f'Support #{ticket.id}', 'ticket': ticket, 'thread': ticket.messages.select_related('author'),
        'is_staff': staff, 'statuses': SupportTicket.STATUS_CHOICES,
    })


@login_required
@require_POST
def support_ticket_status(request, ticket_id):
    ticket = get_object_or_404(_tickets_for(request.user), id=ticket_id)
    status = request.POST.get('status')
    # L'utilisateur peut clore ou rouvrir sa demande ; l'équipe choisit n'importe quel statut.
    allowed = dict(SupportTicket.STATUS_CHOICES) if _is_staff(request.user) else {'resolved': 1, 'open': 1}
    if status not in allowed:
        raise Http404
    ticket.status = status
    ticket.save(update_fields=['status', 'updated_at'])
    return redirect('dashboard:support-ticket', ticket_id=ticket.id)


@login_required
def support_attachment(request, message_id):
    """Pièce jointe d'un message, servie seulement à l'auteur du ticket et à l'équipe Billio."""
    message = get_object_or_404(SupportMessage.objects.select_related('ticket'), id=message_id)
    if not message.attachment or not _tickets_for(request.user).filter(id=message.ticket_id).exists():
        raise Http404
    return FileResponse(message.attachment.open('rb'), as_attachment=False, filename=os.path.basename(message.attachment.name))
