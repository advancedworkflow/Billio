"""Pages publiques : le signataire ouvre son lien secret, remplit ses champs et signe."""
import json

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.accounts.throttle import client_ip

from . import services
from .models import SignatureRequest, Signer
from .views import pdf_response, signed_filename


def _signer(token):
    signer = get_object_or_404(Signer.objects.select_related('request__organization'), token=token)
    signer.request.expire_if_due()
    return signer


def _field(field, mine):
    data = {'id': field.pk, 'kind': field.kind, 'page': field.page, 'x': field.x, 'y': field.y,
            'w': field.w, 'h': field.h, 'required': field.required, 'label': field.label or field.get_kind_display()}
    if not mine:
        data['value'] = field.value
    return data


def sign_page(request, token):
    signer = _signer(token)
    req = signer.request
    if services.can_sign(signer):
        services.mark_viewed(signer, client_ip(request), request.META.get('HTTP_USER_AGENT', ''))
        state = 'sign'
    elif signer.status == 'signed':
        state = 'done'
    elif signer.status == 'declined':
        state = 'declined'
    elif req.status == 'sent' and signer.status == 'waiting':
        state = 'waiting'
    else:
        state = 'closed'
    mine = [_field(f, True) for f in signer.fields.all()] if state == 'sign' else []
    others = [_field(f, False) for f in req.fields.exclude(signer=signer).filter(signer__status='signed')]
    response = render(request, 'signatures/sign.html', {
        'signer': signer, 'req': req, 'org': req.organization, 'state': state,
        'sign_data': {'pages': req.pages, 'fields': mine, 'others': others, 'name': signer.name},
        'logo_url': req.organization.logo.url if req.organization.logo else '',
    })
    response['X-Robots-Tag'] = 'noindex, nofollow'
    response['Referrer-Policy'] = 'no-referrer'
    return response


def sign_pdf(request, token):
    signer = _signer(token)
    if signer.request.status in ('cancelled', 'expired'):
        raise Http404
    return pdf_response(signer.request.original_pdf, 'document.pdf', raw=bool(request.GET.get('raw')))


@require_POST
def sign_submit(request, token):
    signer = _signer(token)
    try:
        payload = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'Données invalides.'}, status=400)
    if not payload.get('consent'):
        return JsonResponse({'ok': False, 'error': 'Cochez la case d’accord pour signer électroniquement.'}, status=400)
    try:
        services.sign(signer, payload.get('values'), ip=client_ip(request),
                      user_agent=request.META.get('HTTP_USER_AGENT', ''))
    except services.SignatureError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': True})


@require_POST
def sign_decline(request, token):
    signer = _signer(token)
    try:
        payload = json.loads(request.body or b'{}')
    except ValueError:
        payload = {}
    try:
        services.decline(signer, str(payload.get('reason') or ''), ip=client_ip(request),
                         user_agent=request.META.get('HTTP_USER_AGENT', ''))
    except services.SignatureError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': True})


def sign_download(request, token):
    signer = _signer(token)
    req = signer.request
    if req.status != 'completed' or not req.signed_pdf:
        raise Http404
    return pdf_response(req.signed_pdf, signed_filename(req), download=True)


def verify(request):
    """Vérifie qu'un PDF est bien un document signé avec Billio, sans modification (empreinte SHA-256)."""
    result = None
    error = ''
    if request.method == 'POST':
        upload = request.FILES.get('pdf')
        if upload is None:
            error = 'Choisissez le PDF à vérifier.'
        elif upload.size > services.MAX_PDF_BYTES:
            error = 'Le PDF dépasse 20 Mo.'
        else:
            digest = services.sha256(upload.read())
            match = (SignatureRequest.objects.filter(signed_sha256=digest, status='completed')
                     .select_related('organization').first())
            result = {'digest': digest, 'match': match,
                      'signers': list(match.signers.all()) if match else []}
    response = render(request, 'signatures/verify.html', {'result': result, 'error': error})
    response['X-Robots-Tag'] = 'noindex'
    return response
