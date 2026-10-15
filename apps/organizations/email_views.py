"""Page « Personnalisation des emails » : apparence (couleur, bannière, signature) et textes par type d'email."""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import branded_email as be

MAX_IMAGE_BYTES = 2 * 1024 * 1024
IMAGE_TYPES = {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}


def _organization(user):
    from apps.accounts.views import list_editable_organizations_for_payment
    orgs = list_editable_organizations_for_payment(user)
    if not orgs:
        raise Http404
    return orgs[0]


def _apply_form(organization, data):
    """Applique les réglages saisis (sans enregistrer) : couleur, signature et textes personnalisés."""
    color = (data.get('email_color') or '').strip()
    organization.email_color = color if be.HEX_RE.match(color) else ''
    organization.email_signature = (data.get('email_signature') or '').strip()[:1000]
    templates = {}
    for kind, (_label, subject, body, _button) in be.EMAIL_KINDS.items():
        custom_subject = (data.get(f'subject_{kind}') or '').strip()[:200]
        custom_body = (data.get(f'body_{kind}') or '').strip()[:5000]
        entry = {}
        if custom_subject and custom_subject != subject:
            entry['subject'] = custom_subject
        if custom_body and custom_body.replace('\r\n', '\n') != body:
            entry['body'] = custom_body.replace('\r\n', '\n')
        if entry:
            templates[kind] = entry
    organization.email_templates = templates


def _image(request, name):
    """Fichier image valide envoyé dans `name`, sinon None (message d'erreur si refusé)."""
    upload = request.FILES.get(name)
    if not upload:
        return None
    if upload.content_type not in IMAGE_TYPES or upload.size > MAX_IMAGE_BYTES:
        messages.error(request, 'Image refusée : PNG, JPG, WEBP ou GIF de 2 Mo maximum.')
        return None
    return upload


@login_required
def email_settings(request):
    organization = _organization(request.user)
    if request.method == 'POST':
        _apply_form(organization, request.POST)
        for field in ('email_banner', 'email_signature_photo'):
            if request.POST.get(f'remove_{field}'):
                getattr(organization, field).delete(save=False)
                setattr(organization, field, None)
            upload = _image(request, field)
            if upload:
                getattr(organization, field).save(upload.name, upload, save=False)
        organization.save(update_fields=['email_color', 'email_signature', 'email_templates',
                                         'email_banner', 'email_signature_photo', 'updated_at'])
        if request.POST.get('form_action') == 'test':
            kind = request.POST.get('test_kind') if request.POST.get('test_kind') in be.EMAIL_KINDS else 'invoice'
            subject, body, button = be.render_kind(organization, kind, be.SAMPLE_VARIABLES)
            try:
                be.branded_message(organization, subject=f"[Test] {subject}", body=body, to=[request.user.email],
                                   button=(button, be.settings.SITE_URL) if button else None).send(fail_silently=False)
                messages.success(request, f"Email de test envoyé à {request.user.email}.")
            except Exception as exc:
                messages.error(request, f"Envoi impossible : {exc}")
        else:
            messages.success(request, 'Personnalisation des emails enregistrée.')
        return redirect(reverse('organizations:email-settings') + f"?kind={request.POST.get('test_kind') or 'invoice'}")

    kinds = []
    for kind, (label, subject, body, _button) in be.EMAIL_KINDS.items():
        current_subject, current_body = be.kind_texts(organization, kind)
        kinds.append({'key': kind, 'label': label, 'subject': current_subject, 'body': current_body,
                      'default_subject': subject, 'default_body': body,
                      'custom': kind in (organization.email_templates or {})})
    return render(request, 'organizations/email_settings.html', {
        'org': organization,
        'kinds': kinds,
        'kinds_json': json.dumps({k['key']: {'subject': k['default_subject'], 'body': k['default_body']} for k in kinds}),
        'variables': be.VARIABLES,
        'color': be.brand_color(organization),
        'current_kind': request.GET.get('kind') if request.GET.get('kind') in be.EMAIL_KINDS else 'invoice',
        'page_title': 'Personnalisation des emails',
    })


@login_required
@require_POST
def email_preview(request):
    """Aperçu HTML avec les valeurs en cours de saisie (rien n'est enregistré)."""
    organization = _organization(request.user)
    _apply_form(organization, request.POST)
    kind = request.POST.get('kind') if request.POST.get('kind') in be.EMAIL_KINDS else 'invoice'
    subject, body, button = be.render_kind(organization, kind, be.SAMPLE_VARIABLES)
    html = be.render_html(organization, subject=subject, body=body, button=(button, '#') if button else None, preview=True)
    return HttpResponse(html)
