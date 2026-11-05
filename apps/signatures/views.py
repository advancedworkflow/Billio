"""Pages Billio de la signature électronique : liste, éditeur de champs, suivi."""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.documents.views import _get_user_primary_organization
from apps.subscriptions.entitlements import require_feature, require_quota

from . import services
from .models import SignatureField, SignatureRequest, Signer

TABS = {
    'all': ('Toutes', None),
    'sent': ('À signer', ('sent',)),
    'completed': ('Signées', ('completed',)),
    'draft': ('Brouillons', ('draft',)),
    'closed': ('Refusées ou annulées', ('declined', 'cancelled', 'expired')),
}


def _organization(request):
    organization = _get_user_primary_organization(request.user)
    if organization is None:
        raise Http404
    return organization


def _request(request, request_id):
    return get_object_or_404(SignatureRequest.objects.select_related('organization'), pk=request_id,
                             organization=_organization(request))


@login_required
def signature_list(request):
    organization = _organization(request)
    tab = request.GET.get('tab') if request.GET.get('tab') in TABS else 'all'
    queryset = SignatureRequest.objects.filter(organization=organization)
    for item in queryset.filter(status='sent', expires_at__isnull=False):
        item.expire_if_due()
    counts = {key: (queryset.filter(status__in=statuses).count() if statuses else queryset.count())
              for key, (_label, statuses) in TABS.items()}
    statuses = TABS[tab][1]
    rows = (queryset.filter(status__in=statuses) if statuses else queryset).prefetch_related('signers')
    from apps.documents.models import Document
    from apps.invoices.models import Quote
    return render(request, 'signatures/list.html', {
        'page_title': 'Signatures',
        'tab': tab,
        'tabs': [(key, label, counts[key]) for key, (label, _s) in TABS.items()],
        'rows': rows[:200],
        'documents': Document.objects.filter(organization=organization).order_by('-updated_at')[:50],
        'quotes': Quote.objects.filter(organization=organization).select_related('client').order_by('-created_at')[:50],
    })


@login_required
@require_POST
def signature_new(request):
    organization = _organization(request)
    require_feature(organization, 'esign')
    source = request.POST.get('source', 'upload')
    try:
        if source == 'document':
            from apps.documents.models import Document
            document = get_object_or_404(Document, pk=request.POST.get('document_id'), organization=organization)
            data = document.generate_pdf_bytes()
            item = services.create_request(organization, request.user, title=document.title, data=data,
                                           source='document', document=document, client=document.client)
        elif source == 'quote':
            from apps.invoices.models import Quote
            from apps.invoices.pdf import render_document_to_pdf_bytes
            quote = get_object_or_404(Quote, pk=request.POST.get('quote_id'), organization=organization)
            data = render_document_to_pdf_bytes(quote)
            item = services.create_request(organization, request.user, title=f"Devis {quote.quote_number}",
                                           data=data, source='quote', quote=quote, client=quote.client)
        else:
            upload = request.FILES.get('pdf')
            if upload is None:
                raise services.SignatureError('Choisissez un fichier PDF.')
            if upload.size > services.MAX_PDF_BYTES:
                raise services.SignatureError('Le PDF dépasse 20 Mo.')
            require_quota(organization, 'storage_mb', upload.size)
            title = (request.POST.get('title') or '').strip() or upload.name.rsplit('.', 1)[0]
            item = services.create_request(organization, request.user, title=title, data=upload.read())
    except services.SignatureError as exc:
        messages.error(request, str(exc))
        return redirect('signatures:requests')
    except Exception:
        import logging
        logging.getLogger(__name__).exception('PDF à signer non généré')
        messages.error(request, "Le PDF n'a pas pu être généré.")
        return redirect('signatures:requests')
    return redirect('signatures:detail', request_id=item.pk)


def _builder_payload(item):
    signers = list(item.signers.all())
    keys = {signer.pk: str(index) for index, signer in enumerate(signers)}
    return {
        'title': item.title, 'message': item.message, 'in_order': item.in_order,
        'valid_days': 30,
        'pages': item.pages,
        'signers': [{'key': keys[s.pk], 'name': s.name, 'email': s.email, 'client_id': s.client_id} for s in signers],
        'fields': [{'signer': keys[f.signer_id], 'kind': f.kind, 'page': f.page, 'x': f.x, 'y': f.y, 'w': f.w,
                    'h': f.h, 'required': f.required, 'label': f.label} for f in item.fields.all()],
    }


@login_required
def signature_detail(request, request_id):
    item = _request(request, request_id)
    item.expire_if_due()
    if item.status == 'draft':
        from apps.clients.models import Client
        clients = Client.objects.filter(organization=item.organization).exclude(email='').order_by('name')[:500]
        return render(request, 'signatures/builder.html', {
            'page_title': item.title, 'req': item,
            'builder_data': _builder_payload(item),
            'clients_data': [{'id': c.pk, 'name': c.name, 'email': c.email} for c in clients],
            'kinds': SignatureField.KIND_CHOICES,
            'colors': Signer.COLORS,
        })
    signers = list(item.signers.all())
    signed, total = item.signer_progress()
    return render(request, 'signatures/detail.html', {
        'page_title': item.title, 'req': item, 'signers': signers, 'signed': signed, 'total': total,
        'events': item.events.select_related('signer'),
        'needs_finalize': item.status == 'completed' and not item.signed_pdf,
    })


@login_required
@require_POST
def signature_save(request, request_id):
    item = _request(request, request_id)
    try:
        payload = json.loads(request.body or b'{}')
        services.save_draft(item, payload)
        if payload.get('send'):
            require_feature(item.organization, 'esign')
            services.send_request(item, request.user)
            messages.success(request, f"« {item.title} » est parti en signature.")
            return JsonResponse({'ok': True, 'next': reverse('signatures:detail', args=[item.pk])})
    except (ValueError, services.SignatureError) as exc:
        message = str(exc) if isinstance(exc, services.SignatureError) else 'Données invalides.'
        return JsonResponse({'ok': False, 'error': message}, status=400)
    return JsonResponse({'ok': True, 'problems': services.draft_problems(item)})


@login_required
@require_POST
def signature_remind(request, request_id, signer_id):
    item = _request(request, request_id)
    signer = get_object_or_404(Signer, pk=signer_id, request=item)
    try:
        services.remind(signer)
        messages.success(request, f"Relance envoyée à {signer.email}.")
    except services.SignatureError as exc:
        messages.error(request, str(exc))
    return redirect('signatures:detail', request_id=item.pk)


@login_required
@require_POST
def signature_cancel(request, request_id):
    item = _request(request, request_id)
    try:
        services.cancel(item, request.user)
        messages.success(request, 'Demande annulée : les liens de signature ne fonctionnent plus.')
    except services.SignatureError as exc:
        messages.error(request, str(exc))
    return redirect('signatures:detail', request_id=item.pk)


@login_required
@require_POST
def signature_delete(request, request_id):
    item = _request(request, request_id)
    if item.status in ('sent', 'completed'):
        messages.error(request, 'Une demande en cours ou signée ne peut pas être supprimée.')
        return redirect('signatures:detail', request_id=item.pk)
    for file in (item.original_pdf, item.signed_pdf):
        if file:
            file.delete(save=False)
    item.delete()
    messages.success(request, 'Demande supprimée.')
    return redirect('signatures:requests')


@login_required
@require_POST
def signature_finalize(request, request_id):
    item = _request(request, request_id)
    if item.status != 'completed':
        raise Http404
    try:
        data = services.finalize(item)
        services.send_completed(item, data)
        messages.success(request, 'Document signé généré et envoyé aux signataires.')
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Document signé non généré (%s)', item.pk)
        messages.error(request, "Le document signé n'a pas pu être généré.")
    return redirect('signatures:detail', request_id=item.pk)


def pdf_response(file, filename, download=False, raw=False):
    if not file:
        raise Http404
    if raw:
        # Données lues par pdf.js : type neutre, que les extensions de téléchargement
        # (qui interceptent les réponses application/pdf) laissent passer.
        from django.http import HttpResponse
        file.open('rb')
        try:
            response = HttpResponse(file.read(), content_type='application/octet-stream')
        finally:
            file.close()
        response['Cache-Control'] = 'private, no-store'
        return response
    file.open('rb')
    response = FileResponse(file, content_type='application/pdf', as_attachment=download, filename=filename)
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex'
    return response


def signed_filename(item):
    return f"{item.title[:80]} - signé.pdf".replace('/', '-')


@login_required
def signature_pdf(request, request_id):
    item = _request(request, request_id)
    if request.GET.get('signed') and item.signed_pdf:
        return pdf_response(item.signed_pdf, signed_filename(item), download=bool(request.GET.get('download')))
    return pdf_response(item.original_pdf, f"{item.title[:80]}.pdf".replace('/', '-'),
                        download=bool(request.GET.get('download')), raw=bool(request.GET.get('raw')))
