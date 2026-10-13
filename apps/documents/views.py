"""
Vues du module Documents : galerie de modèles, éditeur canvas (pages à éléments
libres), enregistrement comme modèle, export PDF.
"""
import json

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.clients.models import Client

from .models import (
    DOCUMENT_TYPE_CHOICES, DOCUMENT_VARIABLES, PAGE_FORMAT_CHOICES, PAGE_ORIENTATION_CHOICES, friendly_variable_tokens,
    Document, DocumentTemplate, page_size_px,
)
from .canvas_render import (
    FONT_FAMILIES, WEB_CANVAS_CSS, clean_canvas_data, clean_custom_fields, flow_to_canvas, format_number, render_canvas_pages,
)

# Largeur des vignettes de la galerie (px) : la première page est réduite à cette largeur.
THUMB_WIDTH = 168


def _get_user_primary_organization(user):
    organization = user.owned_organizations.first()
    if organization:
        return organization
    membership = user.organization_memberships.select_related('organization').first()
    return membership.organization if membership else None


def _user_documents_queryset(user):
    return Document.objects.filter(
        Q(organization__owner=user) | Q(organization__members__user=user)
    ).distinct()


def _user_templates_queryset(organization):
    """Modèles système (organization=None) + modèles perso de l'organisation."""
    return DocumentTemplate.objects.filter(Q(organization__isnull=True) | Q(organization=organization))


def _ensure_canvas(obj):
    """Filet de sécurité : un contenu encore en sections HTML est converti en canvas."""
    if obj.layout_mode != 'canvas':
        style = obj.style_config or {}
        obj.canvas_data = flow_to_canvas(
            obj.header_html, obj.body_html, obj.footer_html, style,
            page_format=style.get('page_format') or 'A4', orientation=style.get('page_orientation') or 'portrait',
        )
        obj.layout_mode = 'canvas'
        obj.save(update_fields=['canvas_data', 'layout_mode'])
    return obj


def _with_thumbnail(template):
    style = template.style_config or {}
    page_format = style.get('page_format') or 'A4'
    orientation = style.get('page_orientation') or 'portrait'
    pages = render_canvas_pages(_ensure_canvas(template).canvas_data, page_format=page_format, orientation=orientation, limit=1)
    first = pages[0]
    scale = THUMB_WIDTH / first['width']
    template.thumb_html = friendly_variable_tokens(first['html'])
    # Chaîne pré-formatée : avec LANGUAGE_CODE fr, un float serait rendu « 0,2972 »,
    # que CSS lit comme scale(0, 2972).
    template.thumb_scale = f'{scale:.4f}'
    template.thumb_height = round(first['height'] * scale)
    template.page_count = len((template.canvas_data or {}).get('pages') or [1])
    # Champs à remplir proposés à la création d'un document depuis ce modèle.
    template.fill_fields_json = json.dumps(clean_custom_fields((template.canvas_data or {}).get('fields')))
    return template


@login_required
def document_gallery(request):
    """Ancienne URL de la galerie : les modèles vivent dans l'onglet « Modèles » du hub Documents."""
    return redirect(f"{reverse('dashboard:documents-list')}?tab=modeles")


def gallery_context(user):
    """Vignettes des modèles (système + perso) pour l'onglet « Modèles » du hub Documents."""
    organization = _get_user_primary_organization(user)
    templates = _user_templates_queryset(organization) if organization else DocumentTemplate.objects.filter(organization__isnull=True)
    # Les 4 modèles phares d'abord, puis le reste par nom.
    featured = ['welcome', 'contract', 'proposal', 'inquiry']
    system = sorted(
        templates.filter(organization__isnull=True).exclude(name='Document vierge'),
        key=lambda t: (featured.index(t.category) if t.category in featured and t.name != 'Proposition événementielle (bordée)' else 99, t.name),
    )
    clients = Client.objects.filter(organization=organization, is_active=True).order_by('name') if organization else []
    return {
        'system_templates': [_with_thumbnail(t) for t in system],
        'my_templates': [_with_thumbnail(t) for t in templates.filter(organization=organization)] if organization else [],
        'canvas_css': WEB_CANVAS_CSS,
        'thumb_width': THUMB_WIDTH,
        'fill_clients': [{'id': str(c.id), 'name': c.name} for c in clients],
    }


@login_required
def document_create(request, template_id=None):
    """Crée un document (canvas vierge ou copie d'un modèle) et ouvre l'éditeur."""
    organization = _get_user_primary_organization(request.user)
    if not organization:
        return redirect('dashboard:documents-list')

    document = Document(organization=organization, created_by=request.user, layout_mode='canvas')

    if template_id:
        template = _ensure_canvas(get_object_or_404(_user_templates_queryset(organization), id=template_id))
        document.document_type = template.category
        document.title = template.name
        document.style_config = dict(template.style_config or {})
        document.canvas_data = dict(template.canvas_data or {})
    else:
        document.canvas_data = clean_canvas_data({})

    # Fenêtre « Nouveau document » : client, titre et champs du modèle remplis d'emblée.
    client_id = request.POST.get('client_id')
    if client_id:
        document.client = Client.objects.filter(id=client_id, organization=organization).first()
    title = (request.POST.get('title') or '').strip()
    if title:
        document.title = title[:200]
    fields = []
    for field in clean_custom_fields(document.canvas_data.get('fields')):
        posted = request.POST.get(f"fv_{field['id']}")
        if posted is not None:
            value = posted.strip()[:500]
            field['value'] = value if field['type'] != 'choice' or value in field['options'] else ''
        fields.append(field)
    document.canvas_data['fields'] = fields

    document.save()
    return redirect('documents:document-editor', document_id=document.id)


def _variable_preview_values(document, clients):
    """Valeurs des variables standard : par client (pour le menu Client) et pour le reste."""
    org = document.organization
    org_address = ', '.join(str(p) for p in (org.address, org.postal_code, org.city, org.country) if p)
    per_client = {}
    for client in clients:
        address = ', '.join(p for p in (client.address, client.postal_code, client.city, client.country) if p)
        per_client[str(client.id)] = {
            'client.name': client.name, 'client.email': client.email or '',
            'client.phone': client.phone or '', 'client.address': address,
        }
    return {
        'clients': per_client,
        'sources': _source_previews(org),
        'common': {
            'organization.name': org.name, 'organization.email': org.email or '',
            'organization.phone': org.phone or '', 'organization.address': org_address,
            'document.number': document.number or '',
            'document.date': timezone.localdate().strftime('%d/%m/%Y'),
        },
    }


def _source_previews(organization):
    """Devis et factures récents par client, pour l'aperçu des tableaux reliés dans l'éditeur."""
    from apps.invoices.models import Invoice, Quote
    from .models import _source_lines
    previews = {}
    for kind, model, number_attr in (('quote', Quote, 'quote_number'), ('invoice', Invoice, 'invoice_number')):
        for obj in model.objects.filter(organization=organization).order_by('-created_at').prefetch_related('items')[:120]:
            per_kind = previews.setdefault(str(obj.client_id), {}).setdefault(kind, [])
            if len(per_kind) >= 6:
                continue
            number = getattr(obj, number_attr)
            variables = {
                f'{kind}.number': number,
                f'{kind}.subtotal': format_number(obj.subtotal, 'money'),
                f'{kind}.total': format_number(obj.total_amount, 'money'),
            }
            if kind == 'quote':
                issued = getattr(obj, 'issue_date', None) or obj.created_at
                variables['quote.date'] = issued.strftime('%d/%m/%Y') if issued else ''
            else:
                variables['invoice.due_date'] = obj.due_date.strftime('%d/%m/%Y') if obj.due_date else ''
            per_kind.append({
                'id': str(obj.id),
                'label': f"{'Devis' if kind == 'quote' else 'Facture'} {number} — {format_number(obj.total_amount, 'money')}",
                'rows': _source_lines(obj),
                'vars': variables,
            })
    return previews


@login_required
def document_editor(request, document_id):
    """Éditeur canvas : pages à éléments libres (texte, formes, images, tableaux)."""
    document = _ensure_canvas(get_object_or_404(_user_documents_queryset(request.user), id=document_id))
    clients = Client.objects.filter(organization=document.organization, is_active=True).order_by('name')
    page_format = document.get_style('page_format') or 'A4'
    page_orientation = document.get_style('page_orientation') or 'portrait'
    page_width, page_height = page_size_px(page_format, page_orientation)
    context = {
        'document': document,
        'clients': clients,
        'document_types': DOCUMENT_TYPE_CHOICES,
        'status_choices': Document.STATUS_CHOICES,
        'page_format_choices': PAGE_FORMAT_CHOICES,
        'page_orientation_choices': PAGE_ORIENTATION_CHOICES,
        'page_format': page_format,
        'page_orientation': page_orientation,
        'canvas_json': {
            'data': clean_canvas_data(document.canvas_data),
            'pageWidth': page_width,
            'pageHeight': page_height,
            'fonts': sorted(FONT_FAMILIES),
            'variables': [{'key': key, 'label': label, 'group': group} for key, label, group in DOCUMENT_VARIABLES],
            # Aperçu des valeurs dans l'éditeur : les jetons affichent la vraie valeur.
            'previewValues': _variable_preview_values(document, clients),
            # Réponses des clients aux champs de formulaire du document.
            'responses': [
                {
                    'client': r.client.name if r.client_id else 'Client supprimé',
                    'date': timezone.localtime(r.updated_at).strftime('%d/%m/%Y %H:%M'),
                    'rows': r.rows(),
                }
                for r in document.responses.select_related('client')[:50]
            ],
            'pageSizes': {
                f'{fmt}:{orient}': page_size_px(fmt, orient)
                for fmt, _ in PAGE_FORMAT_CHOICES for orient, _ in PAGE_ORIENTATION_CHOICES
            },
        },
        'page_title': f"Document — {document.title}",
    }
    return render(request, 'documents/canvas_editor.html', context)


@require_POST
@login_required
def document_save(request):
    """Enregistrement (autosave) : titre, sections, réglages, client, statut."""
    document_id = request.POST.get('document_id')
    document = get_object_or_404(_user_documents_queryset(request.user), id=document_id)

    title = request.POST.get('title')
    if title is not None:
        document.title = title.strip() or document.title

    client_id = request.POST.get('client_id')
    if client_id is not None:
        document.client = get_object_or_404(Client, id=client_id, organization=document.organization) if client_id else None

    previous_status = document.status
    status = request.POST.get('status')
    if status in dict(Document.STATUS_CHOICES):
        document.status = status

    document_type = request.POST.get('document_type')
    if document_type in dict(DOCUMENT_TYPE_CHOICES):
        document.document_type = document_type

    style_config = request.POST.get('style_config')
    if style_config:
        try:
            merged = dict(document.style_config or {})
            merged.update(json.loads(style_config))
            document.style_config = merged
        except (ValueError, TypeError):
            pass

    canvas_data = request.POST.get('canvas_data')
    if canvas_data:
        try:
            document.canvas_data = clean_canvas_data(json.loads(canvas_data))
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'message': 'Données du canvas invalides.'}, status=400)

    if 'logo' in request.FILES:
        document.logo = request.FILES['logo']

    document.save()
    if previous_status == 'draft' and document.status == 'sent' and document.client_id:
        from django.urls import reverse
        from apps.dashboard.client_notifications import notify_client
        client = document.client
        notify_client(
            'document_shared', client, f"Nouveau document : « {document.title} »",
            'Consultez-le (et complétez-le s\'il contient un formulaire) depuis votre espace.',
            link=reverse('dashboard:public-portal-document-view', args=[client.portal_token, document.id]),
        )
    return JsonResponse({'success': True, 'updated_at': document.updated_at.isoformat()})


@require_POST
@login_required
def document_image_upload(request, document_id):
    """Upload d'une image insérée directement dans le corps du document (logo, illustration...)."""
    document = get_object_or_404(_user_documents_queryset(request.user), id=document_id)
    image = request.FILES.get('image')
    if not image:
        return JsonResponse({'success': False, 'message': 'Aucune image reçue.'}, status=400)

    from django.core.files.storage import default_storage
    from apps.subscriptions.entitlements import forget_storage, require_quota
    require_quota(document.organization, 'storage_mb', adding=image.size)
    forget_storage(document.organization)
    path = default_storage.save(f'documents/inline/{document.organization_id}/{image.name}', image)
    return JsonResponse({'success': True, 'url': default_storage.url(path)})


@require_POST
@login_required
def document_delete(request, document_id):
    document = get_object_or_404(_user_documents_queryset(request.user), id=document_id)
    document.delete()
    return JsonResponse({'success': True})


@require_POST
@login_required
def document_duplicate(request, document_id):
    document = get_object_or_404(_user_documents_queryset(request.user), id=document_id)
    document.pk = None
    document.id = None
    document.number = ''
    document.title = f"{document.title} (copie)"
    document.status = 'draft'
    document.is_favorite = False
    document.save()
    return JsonResponse({'success': True, 'id': str(document.id)})


@require_POST
@login_required
def document_toggle_favorite(request, document_id):
    document = get_object_or_404(_user_documents_queryset(request.user), id=document_id)
    document.is_favorite = not document.is_favorite
    document.save(update_fields=['is_favorite', 'updated_at'])
    return JsonResponse({'success': True, 'is_favorite': document.is_favorite})


@require_POST
@login_required
def document_save_as_template(request, document_id):
    """Enregistre le document courant comme modèle personnel (« Mes modèles »)."""
    document = get_object_or_404(_user_documents_queryset(request.user), id=document_id)
    name = (request.POST.get('name') or document.title).strip()
    template = DocumentTemplate.objects.create(
        organization=document.organization,
        name=name,
        category=document.document_type,
        style_config=dict(document.style_config or {}),
        layout_mode=document.layout_mode,
        canvas_data=dict(document.canvas_data or {}),
        created_by=request.user,
    )
    return JsonResponse({'success': True, 'id': template.id, 'name': template.name})


@login_required
def document_pdf(request, document_id):
    document = get_object_or_404(_user_documents_queryset(request.user), id=document_id)
    pdf_bytes = document.generate_pdf_bytes()
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{document.number}.pdf"'
    return response
