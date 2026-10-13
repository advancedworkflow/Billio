"""
Views for templates_app.
"""
import re
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from django.http import JsonResponse, HttpResponse
from .models import (
    InvoiceTemplate, MarketplaceTemplate, OrganizationTemplate,
    TemplatePurchase, TemplateReview
)
from .serializers import InvoiceTemplateSerializer
from apps.organizations.models import Organization
from django.db.models import Q, Avg
from django.db import IntegrityError
from django.contrib import messages
from django.template import Template, Context
from django.utils.text import slugify
import json

from .system_marketplace_seeds import SYSTEM_MARKETPLACE_SEEDS


def _ensure_system_templates_seeded():
    """Ensure baseline system templates exist (idempotent)."""
    seeds = [
        {
            'title': 'System Clean Light',
            'description': 'Template systeme clair et professionnel pour factures standards.',
            'demo_html': '<h1>Facture {{ invoice_number }}</h1><p>{{ client_name }}</p><p>Total: {{ total_amount }} {{ currency }}</p>',
            'html_structure': (
                '<div class="sys-invoice"><header class="sys-head">'
                '<h1 style="color: {{ primary_color }};">{{ invoice_title }}</h1>'
                '<p>{{ organization_name }}</p></header><section><p><strong>Client:</strong> {{ client_name }}</p>'
                '<p><strong>Email:</strong> {{ client_email }}</p></section><section class="sys-total">'
                '<span>{{ total_label }}</span><strong>{{ total_amount }} {{ currency }}</strong></section></div>'
            ),
            'css_styles': (
                '.sys-invoice { font-family: Inter, Arial, sans-serif; color: #111827; padding: 24px; }'
                '.sys-head { border-bottom: 1px solid #E5E7EB; margin-bottom: 16px; padding-bottom: 12px; }'
                '.sys-head h1 { margin: 0; font-size: 30px; }'
                '.sys-total { margin-top: 16px; display: flex; justify-content: space-between; font-size: 18px; }'
            ),
            'layout_config': {
                'variable_schema': {
                    'fields': [
                        {'name': 'invoice_title', 'type': 'text', 'label': 'Titre facture'},
                        {'name': 'organization_name', 'type': 'text', 'label': 'Entreprise'},
                        {'name': 'client_name', 'type': 'text', 'label': 'Client'},
                        {'name': 'client_email', 'type': 'text', 'label': 'Email client'},
                        {'name': 'primary_color', 'type': 'color', 'label': 'Couleur primaire'},
                        {'name': 'total_label', 'type': 'text', 'label': 'Label total'},
                        {'name': 'total_amount', 'type': 'text', 'label': 'Montant'},
                        {'name': 'currency', 'type': 'text', 'label': 'Devise'},
                    ]
                }
            },
            'style_config': {
                'variables_defaults': {
                    'invoice_title': 'FACTURE',
                    'organization_name': 'Votre Entreprise',
                    'client_name': 'Nom Client',
                    'client_email': 'client@email.com',
                    'primary_color': '#111827',
                    'total_label': 'TOTAL',
                    'total_amount': '0.00',
                    'currency': 'EUR',
                }
            },
            'tags': ['system', 'clean', 'light'],
            'compatible_types': ['invoice', 'quote'],
        },
        {
            'title': 'System Bold Yellow',
            'description': 'Template systeme impactant avec accent jaune.',
            'demo_html': '<h1>Facture</h1><p>{{ client_name }}</p>',
            'html_structure': (
                '<div class="sys-bold"><div class="band" style="background: {{ accent_color }};"></div>'
                '<h1>{{ invoice_title }}</h1><p>{{ organization_name }}</p>'
                '<p>{{ client_name }} - {{ client_email }}</p><p class="amount">{{ total_amount }} {{ currency }}</p></div>'
            ),
            'css_styles': (
                '.sys-bold { font-family: Inter, Arial, sans-serif; border: 1px solid #E5E7EB; border-radius: 14px; padding: 20px; }'
                '.sys-bold .band { height: 10px; border-radius: 10px; margin-bottom: 14px; }'
                '.sys-bold h1 { margin: 0 0 8px 0; color: #111827; font-size: 28px; }'
                '.sys-bold .amount { margin-top: 12px; font-size: 22px; font-weight: 700; color: #111827; }'
            ),
            'layout_config': {
                'variable_schema': {
                    'fields': [
                        {'name': 'invoice_title', 'type': 'text', 'label': 'Titre facture'},
                        {'name': 'organization_name', 'type': 'text', 'label': 'Entreprise'},
                        {'name': 'client_name', 'type': 'text', 'label': 'Client'},
                        {'name': 'client_email', 'type': 'text', 'label': 'Email client'},
                        {'name': 'accent_color', 'type': 'color', 'label': 'Couleur accent'},
                        {'name': 'total_amount', 'type': 'text', 'label': 'Montant'},
                        {'name': 'currency', 'type': 'text', 'label': 'Devise'},
                    ]
                }
            },
            'style_config': {
                'variables_defaults': {
                    'invoice_title': 'FACTURE PRO',
                    'organization_name': 'Votre Entreprise',
                    'client_name': 'Nom Client',
                    'client_email': 'client@email.com',
                    'accent_color': '#FACC15',
                    'total_amount': '0.00',
                    'currency': 'EUR',
                }
            },
            'tags': ['system', 'yellow', 'bold'],
            'compatible_types': ['invoice', 'quote'],
        },
    ]
    seeds.extend(SYSTEM_MARKETPLACE_SEEDS)

    for seed in seeds:
        MarketplaceTemplate.objects.update_or_create(
            slug=slugify(seed['title']),
            defaults={
                'title': seed['title'],
                'description': seed['description'],
                'template_type': 'system',
                'price': 0,
                'is_free': True,
                'is_active': True,
                'is_approved': True,
                'demo_html': seed['demo_html'],
                'html_structure': seed['html_structure'],
                'css_styles': seed['css_styles'],
                'layout_config': seed['layout_config'],
                'style_config': seed['style_config'],
                'tags': seed['tags'],
                'compatible_types': seed['compatible_types'],
            },
        )


class InvoiceTemplateViewSet(viewsets.ModelViewSet):
    """ViewSet for InvoiceTemplate model."""
    queryset = InvoiceTemplate.objects.all()  # Required for DRF router basename detection
    serializer_class = InvoiceTemplateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter templates based on user's organizations."""
        from django.db.models import Q
        return InvoiceTemplate.objects.filter(
            Q(organization__owner=self.request.user) |
            Q(organization__members__user=self.request.user)
        ).distinct()


def _get_user_primary_organization(user):
    org = Organization.objects.filter(owner=user).first()
    if org:
        return org
    membership = user.organization_memberships.select_related('organization').first()
    return membership.organization if membership else None


def _extract_schema_and_defaults(template_obj):
    """
    Extract variable schema/defaults from a template-like object.
    Priority:
      1) layout_config.variable_schema + style_config.variables_defaults
      2) existing layout/style config directly
    """
    layout = getattr(template_obj, 'layout_config', {}) or {}
    style = getattr(template_obj, 'style_config', {}) or {}
    schema = layout.get('variable_schema') or layout.get('schema') or {}
    defaults = style.get('variables_defaults') or style.get('defaults') or {}
    return schema, defaults


_WYSIWYG_ELIGIBLE_TYPES = {'text', 'textarea'}
_HTML_TAG_SPLIT_RE = re.compile(r'(<[^>]*>)')


def _wrap_editable_schema_fields(html_structure, schema):
    """
    Enveloppe {{ field }} (champs texte/textarea du schéma) d'un marqueur DOM éditable,
    uniquement dans les zones de texte (jamais dans un attribut HTML), pour permettre
    l'édition inline côté client sans changer la sémantique du rendu Django (les filtres
    existants comme |linebreaksbr restent à l'intérieur du marqueur).
    """
    fields = (schema or {}).get('fields', [])
    eligible = [f for f in fields if f.get('name') and f.get('type', 'text') in _WYSIWYG_ELIGIBLE_TYPES]
    if not eligible or not html_structure:
        return html_structure

    segments = _HTML_TAG_SPLIT_RE.split(html_structure)  # indices pairs = texte, impairs = balises

    for field in eligible:
        name = field['name']
        ftype = field.get('type', 'text')
        token_re = re.compile(r'\{\{\s*' + re.escape(name) + r'(?!\w)(?P<filters>\s*\|[^}]*)?\s*\}\}')

        def _wrap(match, _name=name, _ftype=ftype):
            inner_token = '{{ ' + _name + (match.group('filters') or '') + ' }}'
            return (
                f'<span class="wysiwyg-field-wrap" data-field-wrap="{_name}">'
                f'<span class="wysiwyg-field" contenteditable="true" spellcheck="false" '
                f'data-field="{_name}" data-field-type="{_ftype}">{inner_token}</span>'
                f'<button type="button" class="wysiwyg-field-delete" data-field-delete="{_name}" '
                f'contenteditable="false" aria-label="Effacer ce champ">&times;</button>'
                f'</span>'
            )

        for i in range(0, len(segments), 2):
            segments[i] = token_re.sub(_wrap, segments[i])

    return ''.join(segments)


def _resolve_source_for_user(user, source_type, template_id=None, slug=None):
    """
    Resolve template source:
      - personal: InvoiceTemplate owned via org access
      - marketplace: MarketplaceTemplate by id/slug
      - organization: OrganizationTemplate accessible by org membership
    """
    if source_type == 'personal':
        if not template_id:
            return None
        return InvoiceTemplate.objects.filter(
            Q(organization__owner=user) | Q(organization__members__user=user),
            id=template_id
        ).distinct().first()

    if source_type == 'organization':
        if not template_id:
            return None
        return OrganizationTemplate.objects.filter(
            Q(organization__owner=user) | Q(organization__members__user=user),
            id=template_id
        ).distinct().first()

    if source_type == 'marketplace':
        qs = MarketplaceTemplate.objects.filter(is_active=True, is_approved=True)
        if template_id:
            return qs.filter(id=template_id).first()
        if slug:
            return qs.filter(slug=slug).first()
    return None


# Toujours autorisés en prévisualisation facture (Alpine) même si absents du schéma
_PREVIEW_BUILTIN_KEYS = frozenset({
    'items',
    'organization_name', 'organization_address', 'organization_city', 'organization_postal_code',
    'organization_phone', 'organization_email', 'organization_registration_number', 'organization_tax_id',
    'organization_bank_name', 'organization_iban', 'organization_bic_swift', 'organization_payment_instructions',
    'organization_preferred_payment_method', 'organization_payment_method_label',
    'client_name', 'client_email', 'client_address', 'client_phone',
    'client_registration_number', 'client_tax_id',
    'subtotal', 'tax_amount', 'total_amount', 'discount_amount',
    'invoice_number', 'issue_date', 'due_date', 'currency',
    'invoice_title', 'notes',
    'document_kind', 'document_type', 'organization_initial', 'organization_logo_url',
    'subject', 'delivery_terms',
    # Variables « document / devis » (éditeur facture) — toujours autorisées si le schéma filtre le reste
    'document_title', 'font_family', 'text_color', 'accent_color', 'accent_text_color',
    'doc_padding', 'logo_placeholder', 'city_date_prefix', 'legal_form_line',
    'tax_legal_mention', 'offer_valid_text', 'signature_label', 'company_legal_footer',
})


def _build_render_context(schema, defaults, variables):
    """
    Build safe render context from schema fields + provided variables.
    Unknown variables are ignored to reduce injection surface.
    Les clés facture (items, organization_*, client_*, montants) restent disponibles pour l'aperçu.
    """
    merged = dict(defaults or {})
    merged.update(variables or {})  # les variables du formulaire écrasent les défauts

    fields = (schema or {}).get('fields', [])
    allowed_names = set()
    for field in fields:
        name = field.get('name')
        if name:
            allowed_names.add(name)

    if not allowed_names:
        # Backward compatibility: if no schema, allow merged keys.
        return merged
    return {
        k: v for k, v in merged.items()
        if k in allowed_names or k in _PREVIEW_BUILTIN_KEYS
    }


@login_required
@require_POST
def template_live_preview(request):
    """
    Render HTML preview from any template source + variables.
    Intended for HTMX live preview.
    """
    source_type = request.POST.get('source_type', 'personal')
    template_id = request.POST.get('template_id')
    slug = request.POST.get('slug')
    variables_raw = request.POST.get('variables', '{}')

    source = _resolve_source_for_user(
        request.user, source_type=source_type, template_id=template_id, slug=slug
    )
    if not source:
        return JsonResponse({'ok': False, 'error': 'Template source introuvable.'}, status=404)

    try:
        variables = json.loads(variables_raw) if variables_raw else {}
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Variables JSON invalides.'}, status=400)

    schema, defaults = _extract_schema_and_defaults(source)
    from .models import apply_billing_texts
    defaults = apply_billing_texts(dict(defaults or {}), _get_user_primary_organization(request.user))
    render_context = _build_render_context(schema, defaults, variables)

    html_structure = getattr(source, 'html_structure', '') or ''
    html_structure = _wrap_editable_schema_fields(html_structure, schema)
    css_styles = getattr(source, 'css_styles', '') or ''
    try:
        rendered_html = Template(html_structure).render(Context(render_context))
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': f'Render error: {str(exc)}'}, status=400)

    return JsonResponse({
        'ok': True,
        'preview_html': rendered_html,
        'preview_css': css_styles,
        'schema': schema,
        'variables': render_context,
    })


@login_required
@require_POST
def template_preview_raw(request):
    """
    Preview HTML/CSS not yet saved: Django Template render with schema-filtered context.
    POST: html_structure, variable_schema (JSON), variables_defaults (JSON), variables (JSON, optional).
    """
    html_structure = request.POST.get('html_structure', '') or '<p>Aucun HTML</p>'
    css_styles = request.POST.get('css_styles', '') or ''
    schema_raw = request.POST.get('variable_schema', '{}')
    defaults_raw = request.POST.get('variables_defaults', '{}')
    variables_raw = request.POST.get('variables', '{}')
    try:
        schema = json.loads(schema_raw) if schema_raw else {}
        defaults = json.loads(defaults_raw) if defaults_raw else {}
        variables = json.loads(variables_raw) if variables_raw else {}
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'JSON schema / variables invalide.'}, status=400)

    render_context = _build_render_context(schema, defaults, variables)
    try:
        rendered_html = Template(html_structure).render(Context(render_context))
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': f'Erreur rendu: {str(exc)}'}, status=400)

    return JsonResponse({
        'ok': True,
        'preview_html': rendered_html,
        'preview_css': css_styles,
    })


@login_required
@require_POST
def template_save_as_personal(request):
    """
    Clone/Save any source template as a personal InvoiceTemplate in user's organization,
    preserving HTML/CSS/schema + chosen variable defaults.
    """
    source_type = request.POST.get('source_type', 'marketplace')
    template_id = request.POST.get('template_id')
    slug = request.POST.get('slug')
    name = (request.POST.get('name') or '').strip()
    variables_raw = request.POST.get('variables', '{}')
    make_default = request.POST.get('is_default') == 'true'

    if not name:
        return JsonResponse({'ok': False, 'error': 'Le nom du template est requis.'}, status=400)

    source = _resolve_source_for_user(
        request.user, source_type=source_type, template_id=template_id, slug=slug
    )
    if not source:
        return JsonResponse({'ok': False, 'error': 'Template source introuvable.'}, status=404)

    organization = _get_user_primary_organization(request.user)
    if not organization:
        return JsonResponse({'ok': False, 'error': 'Aucune organisation accessible.'}, status=400)

    try:
        variables = json.loads(variables_raw) if variables_raw else {}
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Variables JSON invalides.'}, status=400)

    schema, defaults = _extract_schema_and_defaults(source)
    # Seules les variables du modèle (couleurs, textes…) sont gardées, jamais les données d'un document.
    schema_names = {f.get('name') for f in (schema or {}).get('fields', []) if f.get('name')}
    merged = {**(defaults or {}), **(variables if isinstance(variables, dict) else {})}
    selected_defaults = {k: v for k, v in merged.items() if k in schema_names} if schema_names else _build_render_context(schema, defaults, variables)

    # Keep existing layout/style data while adding architecture keys.
    layout_config = dict(getattr(source, 'layout_config', {}) or {})
    style_config = dict(getattr(source, 'style_config', {}) or {})
    layout_config['variable_schema'] = schema
    style_config['variables_defaults'] = selected_defaults

    base_name = name
    candidate = base_name
    n = 1
    while InvoiceTemplate.objects.filter(organization=organization, name=candidate).exists():
        n += 1
        candidate = f"{base_name} ({n})"

    if make_default:
        InvoiceTemplate.objects.filter(organization=organization, is_default=True).update(is_default=False)
    personal = InvoiceTemplate.objects.create(
        organization=organization,
        name=candidate,
        html_structure=(getattr(source, 'html_structure', '') or ''),
        css_styles=(getattr(source, 'css_styles', '') or ''),
        layout_config=layout_config,
        style_config=style_config,
        is_default=make_default,
        is_active=True,
    )

    from apps.invoices.views import _serialize_templates_for_editor
    return JsonResponse({
        'ok': True,
        'template_id': str(personal.id),
        'template_name': personal.name,
        'template': _serialize_templates_for_editor([personal])[0],  # entrée prête pour l'éditeur
    })


@login_required
@require_POST
def template_delete_personal(request):
    template_id = (request.POST.get('template_id') or '').strip()
    if not template_id:
        return JsonResponse({'ok': False, 'error': 'Template invalide.'}, status=400)

    template = InvoiceTemplate.objects.filter(
        Q(id=template_id),
        Q(organization__owner=request.user) | Q(organization__members__user=request.user),
        is_active=True,
    ).distinct().first()
    if not template:
        return JsonResponse({'ok': False, 'error': 'Template introuvable.'}, status=404)

    template.is_active = False
    template.is_default = False
    template.save(update_fields=['is_active', 'is_default', 'updated_at'])
    return JsonResponse({'ok': True})


def _serialize_personal_template_for_editor(t):
    layout = t.layout_config or {}
    style = t.style_config or {}
    desc = ''
    if isinstance(layout, dict):
        desc = layout.get('description') or ''
    return {
        'id': t.id,
        'name': t.name,
        'description': desc,
        'html_structure': t.html_structure or '',
        'css_styles': t.css_styles or '',
        'variable_schema': layout.get('variable_schema') or {'fields': []},
        'variables_defaults': style.get('variables_defaults') or {},
    }


def _serialize_marketplace_template_for_editor(t):
    layout = t.layout_config or {}
    style = t.style_config or {}
    return {
        'id': t.id,
        'title': t.title,
        'slug': t.slug,
        'description': t.description or '',
        'html_structure': t.html_structure or '',
        'css_styles': t.css_styles or '',
        'variable_schema': layout.get('variable_schema') or {'fields': []},
        'variables_defaults': style.get('variables_defaults') or {},
    }


# Marketplace Views

@login_required
def marketplace_list(request):
    """
    Display marketplace templates with filtering and search.
    """
    _ensure_system_templates_seeded()
    # Get query parameters
    search_query = request.GET.get('q', '')
    price_filter = request.GET.get('price', 'all')  # all, free, paid
    type_filter = request.GET.get('type', 'all')    # all, system, creator
    sort_by = request.GET.get('sort', 'popular')    # popular, rating, newest, price

    # Base queryset
    templates = MarketplaceTemplate.objects.filter(
        is_active=True,
        is_approved=True
    )

    # Apply filters
    if search_query:
        templates = templates.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(tags__icontains=search_query)
        )

    if price_filter == 'free':
        templates = templates.filter(is_free=True)
    elif price_filter == 'paid':
        templates = templates.filter(is_free=False)

    if type_filter == 'system':
        templates = templates.filter(template_type='system')
    elif type_filter == 'creator':
        templates = templates.filter(template_type='creator')

    # Apply sorting
    if sort_by == 'rating':
        templates = templates.order_by('-rating', '-download_count')
    elif sort_by == 'newest':
        templates = templates.order_by('-created_at')
    elif sort_by == 'price':
        templates = templates.order_by('price')
    else:  # popular (default)
        templates = templates.order_by('-download_count', '-rating')

    # Get user's purchases for access control
    user_purchases = set()
    if request.user.is_authenticated:
        user_purchases = set(
            TemplatePurchase.objects.filter(
                user=request.user,
                is_completed=True
            ).values_list('template_id', flat=True)
        )

    context = {
        'templates': templates,
        'search_query': search_query,
        'price_filter': price_filter,
        'type_filter': type_filter,
        'sort_by': sort_by,
        'user_purchases': user_purchases,
    }

    return render(request, 'templates_app/marketplace/list.html', context)


@login_required
def marketplace_detail(request, slug):
    """
    Display detailed view of a marketplace template.
    """
    template = get_object_or_404(
        MarketplaceTemplate,
        slug=slug,
        is_active=True,
        is_approved=True
    )

    # Check if user has purchased this template
    has_purchased = False
    if request.user.is_authenticated:
        has_purchased = TemplatePurchase.objects.filter(
            user=request.user,
            template=template,
            is_completed=True
        ).exists()

    # Get reviews
    reviews = template.reviews.all().order_by('-created_at')[:10]  # Last 10 reviews

    # Get similar templates
    similar_templates = MarketplaceTemplate.objects.filter(
        is_active=True,
        is_approved=True
    ).exclude(id=template.id).order_by('-rating')[:4]

    # Get user's organizations for template cloning
    user_organizations = Organization.objects.filter(
        Q(owner=request.user) | Q(members__user=request.user)
    ).distinct()

    context = {
        'template': template,
        'has_purchased': has_purchased,
        'reviews': reviews,
        'similar_templates': similar_templates,
        'user_organizations': user_organizations,
    }

    return render(request, 'templates_app/marketplace/detail.html', context)


@login_required
def marketplace_purchase(request, slug):
    """
    Handle template purchase flow.
    """
    template = get_object_or_404(
        MarketplaceTemplate,
        slug=slug,
        is_active=True,
        is_approved=True
    )

    # Check if already purchased
    existing_purchase = TemplatePurchase.objects.filter(
        user=request.user,
        template=template,
        is_completed=True
    ).first()

    if existing_purchase:
        messages.info(request, f"Vous avez déjà acheté le template '{template.title}'.")
        return redirect('templates_app:marketplace-detail', slug=slug)

    # Handle free templates
    if template.is_free:
        # Create purchase record
        purchase = TemplatePurchase.objects.create(
            user=request.user,
            template=template,
            price=0,
            currency=template.currency,
            is_completed=True
        )

        messages.success(request, f"Template '{template.title}' ajouté à vos templates !")
        return redirect('templates_app:marketplace-detail', slug=slug)

    # Handle paid templates - redirect to Stripe checkout
    # This will be implemented with Stripe integration
    messages.info(request, f"Le template '{template.title}' coûte {template.price} {template.currency}. L'achat payant sera bientôt disponible.")
    return redirect('templates_app:marketplace-detail', slug=slug)


@login_required
def marketplace_clone(request, slug):
    """
    Clone a marketplace template to user's organization.
    """
    if request.method != 'POST':
        return redirect('templates_app:marketplace-detail', slug=slug)

    template = get_object_or_404(
        MarketplaceTemplate,
        slug=slug,
        is_active=True,
        is_approved=True
    )

    organization_id = request.POST.get('organization_id')
    custom_name = request.POST.get('custom_name', '').strip()

    if not organization_id:
        messages.error(request, "Veuillez sélectionner une organisation.")
        return redirect('templates_app:marketplace-detail', slug=slug)

    # Check if user has access to this organization
    try:
        organization = Organization.objects.get(
            Q(id=organization_id) & (Q(owner=request.user) | Q(members__user=request.user))
        )
    except Organization.DoesNotExist:
        messages.error(request, "Organisation non trouvée ou accès non autorisé.")
        return redirect('templates_app:marketplace-detail', slug=slug)

    # Check if user has purchased this template (if not free)
    if not template.is_free:
        has_purchase = TemplatePurchase.objects.filter(
            user=request.user,
            template=template,
            is_completed=True
        ).exists()

        if not has_purchase:
            messages.error(request, "Vous devez d'abord acheter ce template.")
            return redirect('templates_app:marketplace-detail', slug=slug)

    # Clone the template
    org_template = OrganizationTemplate.create_from_marketplace(
        organization=organization,
        marketplace_template=template,
        custom_name=custom_name if custom_name else None
    )

    # Increment download count
    template.increment_download_count()

    messages.success(request,
        f"Template '{org_template.name}' ajouté à l'organisation '{organization.name}'."
    )

    return redirect('templates_app:template-list')


@login_required
def template_review(request, slug):
    """
    Handle template reviews and ratings.
    """
    if request.method != 'POST':
        return redirect('templates_app:marketplace-detail', slug=slug)

    template = get_object_or_404(
        MarketplaceTemplate,
        slug=slug,
        is_active=True,
        is_approved=True
    )

    rating = request.POST.get('rating')
    comment = request.POST.get('comment', '').strip()

    if not rating or not rating.isdigit() or not (1 <= int(rating) <= 5):
        messages.error(request, "Veuillez sélectionner une note valide (1-5 étoiles).")
        return redirect('templates_app:marketplace-detail', slug=slug)

    # Check if user has purchased this template
    has_purchased = TemplatePurchase.objects.filter(
        user=request.user,
        template=template,
        is_completed=True
    ).exists()

    if not template.is_free and not has_purchased:
        messages.error(request, "Vous devez avoir acheté ce template pour laisser un avis.")
        return redirect('templates_app:marketplace-detail', slug=slug)

    # Create or update review
    review, created = TemplateReview.objects.update_or_create(
        user=request.user,
        template=template,
        defaults={
            'rating': int(rating),
            'comment': comment,
            'is_verified_purchase': has_purchased or template.is_free
        }
    )

    messages.success(request, "Votre avis a été enregistré !" if created else "Votre avis a été mis à jour !")
    return redirect('templates_app:marketplace-detail', slug=slug)
