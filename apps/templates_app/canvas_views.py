"""
Éditeur en mise en page libre (glisser-déposer) des modèles de facture / devis.
La mise en page est enregistrée dans layout_config['canvas'] et transformée en HTML/CSS (canvas.build).
"""
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template import Context, Template
from django.views.decorators.http import require_POST

from . import canvas
from .editor_views import _defaults, _primary_org, _schema, _user_templates
from .models import InvoiceTemplate
from .preview import FONT_CHOICES, sample_context

TEXT_FIELDS = ('payment_terms', 'legal_mentions', 'thank_you')


def _payload(request):
    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _context(organization, defaults, document_type):
    from .models import apply_billing_texts
    ctx = apply_billing_texts(dict(defaults or {}), organization)
    ctx.update(sample_context(organization, document_type))
    return ctx


def block_previews(organization, defaults, document_type='invoice'):
    """HTML de chaque type de bloc et du tableau des lignes, avec des données d'exemple."""
    ctx = Context(_context(organization, defaults, document_type))
    render = lambda source: Template('{% load billio_format %}' + source).render(ctx)  # noqa: E731
    previews = {key: render(canvas._fill(spec[3], canvas.PREFIX)) for key, spec in canvas.BLOCKS.items() if spec[3]}
    previews['items'] = render(canvas._fill(canvas.ITEMS, canvas.PREFIX))
    return previews


@login_required
def canvas_editor(request, template_id):
    template = get_object_or_404(_user_templates(request.user), id=template_id)
    layout = template.layout_config if isinstance(template.layout_config, dict) else {}
    if not layout.get('canvas'):
        return redirect('templates_app:template-edit', template_id=template.id)
    defaults = _defaults(template)
    _html, css = canvas.build(canvas.clean(layout['canvas']))
    config = {
        'id': template.id,
        'name': template.name,
        'isDefault': template.is_default,
        'canvas': canvas.clean(layout['canvas']),
        'accent': defaults.get('accent_color') or '#111827',
        'font': (template.style_config or {}).get('font_override') or '',
        'fonts': list(FONT_CHOICES.keys()),
        'fontStacks': {key: value[0] for key, value in FONT_CHOICES.items()},
        'texts': {key: defaults.get(key, '') for key in TEXT_FIELDS},
        'palette': canvas.palette(),
        'previews': block_previews(template.organization, defaults),
        'pageWidth': canvas.PAGE_WIDTH,
        'padding': canvas.PAGE_PADDING,
    }
    return render(request, 'templates_app/canvas_editor.html', {
        'template': template, 'config': config, 'canvas_css': css, 'page_title': f'Modèle — {template.name}',
        'font_families': '&'.join(f'family={g}' for _stack, g in FONT_CHOICES.values() if g),
    })


@login_required
@require_POST
def canvas_previews(request, template_id):
    template = get_object_or_404(_user_templates(request.user), id=template_id)
    data = _payload(request)
    defaults = dict(_defaults(template))
    defaults.update({key: str(value)[:2000] for key, value in (data.get('texts') or {}).items() if key in TEXT_FIELDS})
    document_type = 'quote' if data.get('document_type') == 'quote' else 'invoice'
    return JsonResponse({'ok': True, 'previews': block_previews(template.organization, defaults, document_type)})


@login_required
@require_POST
def canvas_save(request, template_id):
    template = get_object_or_404(_user_templates(request.user), id=template_id)
    data = _payload(request)
    name = str(data.get('name') or '').strip()[:100]
    if not name:
        return JsonResponse({'ok': False, 'error': 'Donnez un nom au modèle.'}, status=400)
    if InvoiceTemplate.objects.filter(organization=template.organization, name=name).exclude(id=template.id).exists():
        return JsonResponse({'ok': False, 'error': 'Un autre modèle porte déjà ce nom.'}, status=400)
    layout_canvas = canvas.clean(data.get('canvas'))
    html_source, css = canvas.build(layout_canvas)

    accent = str(data.get('accent') or '#111827')[:9]
    defaults = dict(_defaults(template))
    defaults['accent_color'] = accent if accent.startswith('#') else '#111827'
    defaults.setdefault('logo_height', '52')
    defaults.update({key: str(value)[:2000] for key, value in (data.get('texts') or {}).items() if key in TEXT_FIELDS})

    layout = dict(template.layout_config) if isinstance(template.layout_config, dict) else {}
    layout['canvas'] = layout_canvas
    layout['variable_schema'] = canvas.schema_and_defaults(defaults['accent_color'])[0]
    style = dict(template.style_config) if isinstance(template.style_config, dict) else {}
    style['variables_defaults'] = defaults
    font = data.get('font') if data.get('font') in FONT_CHOICES else ''
    if font:
        style['font_override'] = font
    else:
        style.pop('font_override', None)

    template.name, template.html_structure, template.css_styles = name, html_source, css
    template.layout_config, template.style_config = layout, style
    if data.get('is_default'):
        InvoiceTemplate.objects.filter(organization=template.organization, is_default=True).exclude(id=template.id).update(is_default=False)
        template.is_default = True
    template.save()
    return JsonResponse({'ok': True})


@login_required
@require_POST
def canvas_convert(request, template_id):
    """Passe un modèle « code » en mise en page libre (point de départ : disposition classique)."""
    template = get_object_or_404(_user_templates(request.user), id=template_id)
    layout = dict(template.layout_config) if isinstance(template.layout_config, dict) else {}
    layout['canvas'] = canvas.default_canvas()
    defaults = _defaults(template)
    html_source, css = canvas.build(layout['canvas'])
    layout['variable_schema'] = canvas.schema_and_defaults(defaults.get('accent_color') or '#111827')[0]
    template.layout_config, template.html_structure, template.css_styles = layout, html_source, css
    style = dict(template.style_config) if isinstance(template.style_config, dict) else {}
    style['variables_defaults'] = dict(canvas.schema_and_defaults(defaults.get('accent_color') or '#111827')[1], **defaults)
    template.style_config = style
    template.save()
    return redirect('templates_app:template-canvas', template_id=template.id)


@login_required
def canvas_blank(request):
    """Nouveau modèle vide : page blanche, à compléter en glissant des blocs (tableau des lignes compris)."""
    org = _primary_org(request.user)
    if not org:
        return redirect('templates_app:template-list')
    name, n = 'Nouveau modèle', 2
    while InvoiceTemplate.objects.filter(organization=org, name=name).exists():
        name, n = f'Nouveau modèle {n}', n + 1
    empty = canvas.clean({'heights': {'header': 260, 'footer': 220}, 'blocks': [], 'items': False})
    html_source, css = canvas.build(empty)
    schema, defaults = canvas.schema_and_defaults('#111827')
    template = InvoiceTemplate.objects.create(
        organization=org, name=name, html_structure=html_source, css_styles=css,
        layout_config={'variable_schema': schema, 'canvas': empty, 'source': 'vide'},
        style_config={'variables_defaults': defaults}, is_active=True,
        is_default=not InvoiceTemplate.objects.filter(organization=org, is_default=True).exists(),
    )
    return redirect('templates_app:template-canvas', template_id=template.id)


__all__ = ['canvas_editor', 'canvas_previews', 'canvas_save', 'canvas_convert', 'canvas_blank', '_schema']
