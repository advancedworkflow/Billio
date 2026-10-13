"""
Page « Modèles » (liste) et éditeur de modèle de facture / devis :
mode simple (disposition, couleur, police, logo, textes) et mode développeur (HTML, CSS, variables).
"""
import json
import re

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template import TemplateSyntaxError
from django.views.decorators.http import require_POST

from apps.invoices.models import Invoice, Quote

from .models import InvoiceTemplate, MarketplaceTemplate
from .preview import FONT_CHOICES, TemplateSourceError, is_placeholder, render_preview

# Champs du mode simple (mêmes noms que les variables des modèles pro).
SIMPLE_FIELDS = ('accent_color', 'logo_height', 'payment_terms', 'legal_mentions', 'thank_you')


def _user_templates(user):
    return InvoiceTemplate.objects.filter(
        Q(organization__owner=user) | Q(organization__members__user=user)
    ).distinct()


def _primary_org(user):
    from apps.organizations.models import Organization
    return Organization.objects.filter(Q(owner=user) | Q(members__user=user)).distinct().first()


def _schema(obj):
    layout = obj.layout_config if isinstance(obj.layout_config, dict) else {}
    schema = layout.get('variable_schema') or {}
    return schema if isinstance(schema, dict) else {}


def _defaults(obj):
    style = obj.style_config if isinstance(obj.style_config, dict) else {}
    return dict(style.get('variables_defaults') or {})


def _frame(html):
    response = HttpResponse(html)
    response['X-Frame-Options'] = 'SAMEORIGIN'
    return response


def _safe_render(html, css, defaults, org, document_type='invoice', font=None):
    try:
        return render_preview(html, css, defaults, org, document_type, font)
    except (TemplateSourceError, TemplateSyntaxError) as exc:
        raise ValueError(str(exc))
    except Exception as exc:  # erreur de rendu (filtre, variable…)
        raise ValueError(f"Erreur de rendu : {exc}")


# --------------------------------------------------------------------------- #
# Liste
# --------------------------------------------------------------------------- #

@login_required
def template_list(request):
    from .views import _ensure_system_templates_seeded
    _ensure_system_templates_seeded()
    org = _primary_org(request.user)
    templates = [t for t in _user_templates(request.user).filter(is_active=True).order_by('-is_default', 'name') if not is_placeholder(t)]

    usage = {}
    if org:
        for row in Invoice.objects.filter(organization=org, template__isnull=False).values('template').annotate(n=Count('id'), last=Max('created_at')):
            usage.setdefault(row['template'], {'invoices': 0, 'quotes': 0, 'last': None})
            usage[row['template']].update(invoices=row['n'], last=row['last'])
        for row in Quote.objects.filter(organization=org, template__isnull=False).values('template').annotate(n=Count('id'), last=Max('created_at')):
            entry = usage.setdefault(row['template'], {'invoices': 0, 'quotes': 0, 'last': None})
            entry['quotes'] = row['n']
            if row['last'] and (not entry['last'] or row['last'] > entry['last']):
                entry['last'] = row['last']
    for t in templates:
        u = usage.get(t.id, {'invoices': 0, 'quotes': 0, 'last': None})
        t.usage_invoices, t.usage_quotes, t.last_used = u['invoices'], u['quotes'], u['last']
        t.font_label = (t.style_config or {}).get('font_override') or 'Selon le modèle'
        t.accent = _defaults(t).get('accent_color') or '#111827'

    default = next((t for t in templates if t.is_default), templates[0] if templates else None)
    gallery = list(MarketplaceTemplate.objects.filter(is_active=True, is_approved=True, template_type='system').order_by('title'))
    gallery.sort(key=lambda m: (not (m.slug or '').startswith('pro-'), m.title))
    for m in gallery:
        m.is_pro = (m.slug or '').startswith('pro-')
        m.accent = _defaults(m).get('accent_color') or '#111827'

    return render(request, 'templates_app/list.html', {
        'templates': templates,
        'default_template': default,
        'gallery': gallery,
        'total_documents': sum(t.usage_invoices + t.usage_quotes for t in templates),
        'page_title': 'Modèles de facture',
    })


@login_required
def template_preview_frame(request, template_id):
    template = get_object_or_404(_user_templates(request.user), id=template_id)
    doc_type = 'quote' if request.GET.get('type') == 'quote' else 'invoice'
    try:
        html = render_preview(template.html_structure, template.css_styles, _defaults(template), template.organization,
                              doc_type, (template.style_config or {}).get('font_override'))
    except Exception:
        html = '<p style="font:14px system-ui;color:#b91c1c;padding:16px">Aperçu indisponible : le modèle contient une erreur.</p>'
    return _frame(html)


@login_required
def marketplace_preview_frame(request, pk):
    source = get_object_or_404(MarketplaceTemplate, pk=pk, is_active=True, is_approved=True)
    try:
        html = render_preview(source.html_structure or source.demo_html or '', source.css_styles, _defaults(source),
                              _primary_org(request.user), 'quote' if request.GET.get('type') == 'quote' else 'invoice')
    except Exception:
        html = '<p style="font:14px system-ui;color:#6b7280;padding:16px">Aperçu indisponible</p>'
    return _frame(html)


@login_required
@require_POST
def template_set_default(request, template_id):
    template = get_object_or_404(_user_templates(request.user), id=template_id)
    InvoiceTemplate.objects.filter(organization=template.organization, is_default=True).exclude(id=template.id).update(is_default=False)
    template.is_default = True
    template.save(update_fields=['is_default', 'updated_at'])
    return JsonResponse({'ok': True})


@login_required
def template_new(request):
    """Copie d'un modèle de la galerie (ou d'un modèle perso) puis ouverture dans l'éditeur."""
    org = _primary_org(request.user)
    if not org:
        return redirect('templates_app:template-list')
    source = None
    if request.GET.get('from_personal'):
        source = get_object_or_404(_user_templates(request.user), id=request.GET['from_personal'])
        base, html, css = f"{source.name} (copie)", source.html_structure, source.css_styles
    else:
        qs = MarketplaceTemplate.objects.filter(is_active=True, is_approved=True)
        source = qs.filter(id=request.GET.get('from_marketplace')).first() if request.GET.get('from_marketplace', '').isdigit() else None
        source = source or qs.filter(slug='pro-essentiel').first()
        if not source:
            return redirect('templates_app:template-list')
        base, html, css = source.title, source.html_structure or source.demo_html, source.css_styles
    name = base[:90]
    n = 2
    while InvoiceTemplate.objects.filter(organization=org, name=name).exists():
        name = f"{base[:85]} {n}"
        n += 1
    template = InvoiceTemplate.objects.create(
        organization=org, name=name, html_structure=html or '', css_styles=css or '',
        layout_config={'variable_schema': _schema(source) or {'fields': []},
                       'source': getattr(source, 'slug', '') or ''},
        style_config={'variables_defaults': _defaults(source),
                      **({'font_override': source.style_config.get('font_override')} if isinstance(source.style_config, dict) and source.style_config.get('font_override') else {})},
        is_active=True, is_default=not InvoiceTemplate.objects.filter(organization=org, is_default=True).exists(),
    )
    return redirect('templates_app:template-edit', template_id=template.id)


# --------------------------------------------------------------------------- #
# Éditeur
# --------------------------------------------------------------------------- #

@login_required
def template_editor(request, template_id):
    template = get_object_or_404(_user_templates(request.user), id=template_id)
    layouts = [
        {'id': m.id, 'title': m.title, 'description': m.description or '', 'html': m.html_structure or '', 'css': m.css_styles or ''}
        for m in MarketplaceTemplate.objects.filter(is_active=True, is_approved=True, slug__startswith='pro-').order_by('id')
    ]
    from .views import _PREVIEW_BUILTIN_KEYS
    config = {
        'id': template.id,
        'name': template.name,
        'isDefault': template.is_default,
        'html': template.html_structure or '',
        'css': template.css_styles or '',
        'schema': _schema(template).get('fields') or [],
        'defaults': _defaults(template),
        'font': (template.style_config or {}).get('font_override') or '',
        'fonts': list(FONT_CHOICES.keys()),
        'layouts': layouts,
        'builtins': sorted(k for k in _PREVIEW_BUILTIN_KEYS if not k.startswith(('font_', 'text_', 'accent_', 'doc_'))),
    }
    return render(request, 'templates_app/editor.html', {'template': template, 'config': config, 'page_title': f'Modèle — {template.name}'})


def _payload(request):
    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _clean_schema(fields):
    clean = []
    for f in (fields if isinstance(fields, list) else [])[:40]:
        if not isinstance(f, dict):
            continue
        name = str(f.get('name') or '').strip()
        if not name.replace('_', '').isalnum() or not name[:1].isalpha():
            continue
        ftype = f.get('type') if f.get('type') in ('text', 'textarea', 'color', 'number') else 'text'
        clean.append({'name': name[:40], 'type': ftype, 'label': str(f.get('label') or name)[:80]})
    return clean


_TAG_SPLIT_RE = re.compile(r'(<[^>]+>)')


def _mark_variables(html, names):
    """
    Mode visuel : entoure {{ variable }} d'un <span data-tpl-var> (hors attributs HTML)
    pour pouvoir modifier la valeur en cliquant dessus dans l'aperçu.
    """
    if not names or not html:
        return html
    segments = _TAG_SPLIT_RE.split(html)  # indices pairs = texte, impairs = balises
    for name in names:
        token = re.compile(r'\{\{\s*' + re.escape(name) + r'(?!\w)(\s*\|[^}]*)?\s*\}\}')
        for i in range(0, len(segments), 2):
            segments[i] = token.sub(lambda m, n=name: f'<span data-tpl-var="{n}">{m.group(0)}</span>', segments[i])
    return ''.join(segments)


@login_required
@require_POST
def template_editor_preview(request, template_id):
    template = get_object_or_404(_user_templates(request.user), id=template_id)
    data = _payload(request)
    source = str(data.get('html') or '')
    if data.get('visual'):
        names = [f.get('name') for f in (data.get('schema') or []) if isinstance(f, dict)
                 and f.get('type') in ('text', 'textarea') and re.fullmatch(r'[A-Za-z_]\w*', str(f.get('name') or ''))]
        source = _mark_variables(source, names)
    try:
        html = _safe_render(source, str(data.get('css') or ''), data.get('defaults') or {},
                            template.organization, data.get('document_type') or 'invoice', data.get('font') or None)
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'html': html})


@login_required
@require_POST
def template_editor_save(request, template_id):
    template = get_object_or_404(_user_templates(request.user), id=template_id)
    data = _payload(request)
    name = str(data.get('name') or '').strip()[:100]
    if not name:
        return JsonResponse({'ok': False, 'error': 'Donnez un nom au modèle.'}, status=400)
    if InvoiceTemplate.objects.filter(organization=template.organization, name=name).exclude(id=template.id).exists():
        return JsonResponse({'ok': False, 'error': 'Un autre modèle porte déjà ce nom.'}, status=400)
    html, css = str(data.get('html') or ''), str(data.get('css') or '')
    defaults = {str(k)[:40]: str(v)[:2000] for k, v in (data.get('defaults') or {}).items()} if isinstance(data.get('defaults'), dict) else {}
    try:
        _safe_render(html, css, defaults, template.organization)
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': f"Modèle non enregistré — {exc}"}, status=400)

    layout = dict(template.layout_config) if isinstance(template.layout_config, dict) else {}
    layout['variable_schema'] = {'fields': _clean_schema(data.get('schema'))}
    style = dict(template.style_config) if isinstance(template.style_config, dict) else {}
    style['variables_defaults'] = defaults
    font = data.get('font') if data.get('font') in FONT_CHOICES else ''
    if font:
        style['font_override'] = font
    else:
        style.pop('font_override', None)

    template.name, template.html_structure, template.css_styles = name, html, css
    template.layout_config, template.style_config = layout, style
    if data.get('is_default'):
        InvoiceTemplate.objects.filter(organization=template.organization, is_default=True).exclude(id=template.id).update(is_default=False)
        template.is_default = True
    template.save()
    return JsonResponse({'ok': True})
