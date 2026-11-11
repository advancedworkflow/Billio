"""Page Contact du site public : formulaire enregistré en base et transmis au support par email.

Anti-spam sans captcha : champ piège invisible (« website ») et 5 envois par IP et par heure.
Destinataire : SUPPORT_EMAIL, sinon LEGAL_EMAIL ; sans adresse, le message reste dans l'admin.
"""
import logging
import os

from django import forms
from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse

from apps.accounts.throttle import client_ip

from .icons import inline_icons_callback
from .models import ContactMessage

logger = logging.getLogger(__name__)

MAX_PER_HOUR = 5


class ContactForm(forms.ModelForm):
    website = forms.CharField(required=False)  # champ piège, caché aux humains

    class Meta:
        model = ContactMessage
        fields = ['name', 'email', 'company', 'subject', 'message']

    def clean_message(self):
        message = self.cleaned_data['message'].strip()
        if len(message) < 10:
            raise forms.ValidationError('Votre message est un peu court : dites-nous en quelques mots ce dont vous avez besoin.')
        return message


def contact_email():
    return getattr(settings, 'SUPPORT_EMAIL', '') or os.getenv('LEGAL_EMAIL', '').strip()


def _notify(msg):
    to = contact_email()
    if not to:
        return
    body = (f'{msg.name} <{msg.email}>' + (f' · {msg.company}' if msg.company else '')
            + f'\nSujet : {msg.get_subject_display()}\n\n{msg.message}\n')
    try:
        EmailMessage(f'[Contact] {msg.get_subject_display()} · {msg.name}', body,
                     to=[to], reply_to=[msg.email]).send()
    except Exception:  # le message est déjà en base : un SMTP en panne ne doit pas faire échouer l'envoi
        logger.exception('Envoi du message de contact %s impossible', msg.pk)


def contact_page(request):
    form = ContactForm(request.POST or None)
    limited = False
    if request.method == 'POST':
        key = f'contact:ip:{client_ip(request)}'
        if cache.get(key, 0) >= MAX_PER_HOUR:
            limited = True
        elif form.is_valid():
            if not form.cleaned_data.get('website'):
                msg = form.save()
                _notify(msg)
            cache.set(key, cache.get(key, 0) + 1, 60 * 60)
            return redirect(reverse('landing:contact') + '?envoye=1#formulaire')
    response = TemplateResponse(request, 'landing/contact.html', {
        'form': form, 'sent': request.GET.get('envoye') == '1', 'limited': limited,
        'contact_email': contact_email(), 'active': 'contact',
    }, status=429 if limited else 200)
    response.add_post_render_callback(inline_icons_callback)
    return response
