"""
Documents génériques (bienvenue, proposition, contrat...) : éditeur type
Word avec sections header/body/footer, habillage (logo, filigrane, fond,
bordure) et export PDF. Remplace les anciens modules Proposal et Contract.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


DOCUMENT_TYPE_CHOICES = [
    ('welcome', _('Document de bienvenue')),
    ('proposal', _('Proposition')),
    ('contract', _('Contrat')),
    ('inquiry', _('Formulaire de demande')),
    ('general', _('Document')),
]

# (clé, libellé affiché dans le document et l'éditeur, groupe)
DOCUMENT_VARIABLES = [
    ('client.name', 'Nom du client', 'Client'),
    ('client.email', 'Email du client', 'Client'),
    ('client.phone', 'Téléphone du client', 'Client'),
    ('client.address', 'Adresse du client', 'Client'),
    ('organization.name', 'Nom de votre entreprise', 'Votre entreprise'),
    ('organization.email', 'Email de votre entreprise', 'Votre entreprise'),
    ('organization.phone', 'Téléphone de votre entreprise', 'Votre entreprise'),
    ('organization.address', 'Adresse de votre entreprise', 'Votre entreprise'),
    ('document.number', 'Numéro du document', 'Document'),
    ('document.date', 'Date du jour', 'Document'),
    ('document.title', 'Titre du document', 'Document'),
    ('quote.number', 'Numéro du devis', 'Devis du client'),
    ('quote.date', 'Date du devis', 'Devis du client'),
    ('quote.subtotal', 'Montant HT du devis', 'Devis du client'),
    ('quote.total', 'Montant TTC du devis', 'Devis du client'),
    ('invoice.number', 'Numéro de la facture', 'Facture du client'),
    ('invoice.subtotal', 'Montant HT de la facture', 'Facture du client'),
    ('invoice.total', 'Montant TTC de la facture', 'Facture du client'),
    ('invoice.due_date', 'Échéance de la facture', 'Facture du client'),
]
DOCUMENT_VARIABLE_LABELS = {key: label for key, label, _ in DOCUMENT_VARIABLES}


def used_variables(canvas_data):
    """Variables automatiques (hors champs personnalisés) utilisées par un canvas, dans l'ordre de DOCUMENT_VARIABLES."""
    import json
    import re
    found = set(re.findall(r'data-var=\\?"([\w.]+)', json.dumps(canvas_data or {})))
    return [(key, label, group) for key, label, group in DOCUMENT_VARIABLES if key in found]


def clean_overrides(raw):
    """Valeurs imposées aux variables automatiques (ex. depuis une automatisation) : clés connues, texte court."""
    return {
        key: str(value).strip()[:500]
        for key, value in (raw.items() if isinstance(raw, dict) else [])
        if key in DOCUMENT_VARIABLE_LABELS and str(value or '').strip()
    }


def custom_field_values(fields):
    """{'champ.<id>': valeur affichable} pour les champs personnalisés d'un document."""
    from datetime import date
    values = {}
    for field in fields or []:
        if not isinstance(field, dict) or not field.get('id'):
            continue
        value = str(field.get('value') or '')
        if field.get('type') == 'date' and value:
            try:
                value = date.fromisoformat(value).strftime('%d/%m/%Y')
            except ValueError:
                pass
        if field.get('type') in ('money', 'number') and value:
            from .canvas_render import format_number, parse_number
            number = parse_number(value)
            if number is not None:
                value = format_number(number, field['type'])
        values[f"champ.{field['id']}"] = value
    return values


def _source_lines(obj):
    """Lignes d'un devis / d'une facture, déjà formatées pour les colonnes d'un tableau."""
    from .canvas_render import format_number
    rows = []
    for item in obj.items.all().order_by('order', 'id'):
        rows.append({
            'name': item.name or '',
            'description': item.description or '',
            'quantity': format_number(item.quantity, 'number'),
            'unit': '' if item.unit in ('unit', 'unité', '') else item.unit,
            'unit_price': format_number(item.unit_price, 'money'),
            'tax_rate': format_number(item.tax_rate, 'percent'),
            'total': format_number(item.total, 'money'),
            '_rate': float(item.tax_rate or 0),
        })
    return rows


def linked_sources(organization, client, chosen=None):
    """
    Devis et facture utilisés par les tableaux reliés et les variables « Devis / Facture du client » :
    celui choisi dans le document, sinon le plus récent du client.
    {'quote': {'id', 'label', 'rows', 'vars'}, 'invoice': {...}} (clé absente si rien).
    """
    from apps.invoices.models import Invoice, Quote
    from .canvas_render import format_number
    chosen = chosen or {}
    found = {}
    for kind, model, number_attr in (('quote', Quote, 'quote_number'), ('invoice', Invoice, 'invoice_number')):
        qs = model.objects.filter(organization=organization)
        obj = qs.filter(id=chosen[kind]).first() if chosen.get(kind) else None
        if obj is None and client is not None:
            obj = qs.filter(client=client).order_by('-created_at').first()
        if obj is None:
            continue
        date_value = getattr(obj, 'issue_date', None) or obj.created_at
        variables = {
            f'{kind}.number': getattr(obj, number_attr),
            f'{kind}.subtotal': format_number(obj.subtotal, 'money'),
            f'{kind}.total': format_number(obj.total_amount, 'money'),
        }
        if kind == 'quote':
            variables['quote.date'] = date_value.strftime('%d/%m/%Y') if date_value else ''
        else:
            variables['invoice.due_date'] = obj.due_date.strftime('%d/%m/%Y') if getattr(obj, 'due_date', None) else ''
        found[kind] = {
            'id': str(obj.id),
            'label': f"{'Devis' if kind == 'quote' else 'Facture'} {getattr(obj, number_attr)} — {format_number(obj.total_amount, 'money')}",
            'rows': _source_lines(obj),
            'vars': variables,
        }
    return found


def friendly_variable_tokens(html):
    """Affiche le libellé lisible dans chaque jeton (« Nom du client » plutôt que {{ client.name }})."""
    import re
    from django.utils.html import escape

    def _label(match):
        label = DOCUMENT_VARIABLE_LABELS.get(match.group('key'))
        return f"{match.group('open')}{escape(label)}</span>" if label else match.group(0)

    return re.sub(
        r'(?P<open><span[^>]*class="doc-var-token"[^>]*data-var="(?P<key>[\w.]+)"[^>]*>).*?</span>',
        _label, html or '', flags=re.DOTALL,
    )

PAGE_FORMAT_CHOICES = [
    ('A4', 'A4'),
    ('Letter', 'Letter (US)'),
    ('A5', 'A5'),
]
PAGE_ORIENTATION_CHOICES = [
    ('portrait', _('Portrait')),
    ('landscape', _('Paysage')),
]

HEADER_FOOTER_STYLE_CHOICES = [
    ('none', _('Simple')),
    ('line', _('Ligne de séparation')),
    ('double-line', _('Double ligne')),
    ('dotted', _('Ligne pointillée')),
    ('accent-bar', _('Bandeau accent')),
    ('shaded', _('Fond grisé')),
    ('framed', _('Encadré')),
    ('centered', _('Centré')),
    ('minimal-caps', _('Petites capitales')),
]

FONT_FAMILY_CHOICES = [
    ('Inter, sans-serif', 'Inter (moderne)'),
    ("-apple-system, BlinkMacSystemFont, 'SF Pro Text', Helvetica, Arial, sans-serif", 'Apple (SF Pro)'),
    ('Arial, sans-serif', 'Arial'),
    ('Georgia, serif', 'Georgia (élégant)'),
    ("'Times New Roman', serif", 'Times New Roman (classique)'),
    ("'Courier New', monospace", 'Courier New (machine à écrire)'),
]

TABLE_STYLE_CHOICES = [
    ('bordered', _('Bordures fines')),
    ('striped', _('Lignes alternées')),
    ('minimal', _('Minimaliste (sans bordure)')),
]

# Thèmes prêts à l'emploi : appliquent en un clic une combinaison cohérente
# (police, couleurs, styles d'en-tête/pied/tableau) pour un rendu abouti sans
# avoir à régler chaque paramètre séparément.
DOCUMENT_THEMES = {
    'classic': {
        'label': _('Classique'),
        'font_family': 'Inter, sans-serif',
        'text_color': '#1f2937',
        'accent_color': '#6d28d9',
        'header_style': 'line',
        'footer_style': 'minimal-caps',
        'table_style': 'bordered',
    },
    'modern': {
        'label': _('Moderne'),
        'font_family': 'Inter, sans-serif',
        'text_color': '#111827',
        'accent_color': '#0891b2',
        'header_style': 'accent-bar',
        'footer_style': 'none',
        'table_style': 'striped',
    },
    'elegant': {
        'label': _('Élégant'),
        'font_family': 'Georgia, serif',
        'text_color': '#292524',
        'accent_color': '#92400e',
        'header_style': 'minimal-caps',
        'footer_style': 'dotted',
        'table_style': 'minimal',
    },
    'corporate': {
        'label': _('Corporate'),
        'font_family': 'Arial, sans-serif',
        'text_color': '#1e293b',
        'accent_color': '#1e3a8a',
        'header_style': 'shaded',
        'footer_style': 'line',
        'table_style': 'bordered',
    },
}

LAYOUT_MODE_CHOICES = [
    ('flow', _('Texte continu')),
    ('canvas', _('Canvas libre')),
]

# Dimensions des pages en px CSS (96 dpi) : mêmes unités dans l'éditeur canvas et
# dans le rendu WeasyPrint, les éléments positionnés tombent donc au pixel près.
PAGE_SIZES_PX = {
    'A4': (794, 1123),
    'Letter': (816, 1056),
    'A5': (559, 794),
}


def page_size_px(page_format, orientation):
    width, height = PAGE_SIZES_PX.get(page_format, PAGE_SIZES_PX['A4'])
    if orientation == 'landscape':
        return height, width
    return width, height


DEFAULT_STYLE_CONFIG = {
    'font_family': 'Inter, sans-serif',
    'text_color': '#1f2937',
    'accent_color': '#6d28d9',
    'page_background_color': '#ffffff',
    'background_image': '',
    'border_style': 'none',
    'watermark_text': '',
    'watermark_opacity': 0.08,
    'show_page_numbers': False,
    'page_format': 'A4',
    'page_orientation': 'portrait',
    'page_margin': 48,
    'border_spacing': 12,
    'header_style': 'none',
    'footer_style': 'none',
    'table_style': 'bordered',
}


class Document(models.Model):
    """Document libre (header/body/footer éditables) rattaché à une organisation."""

    STATUS_CHOICES = [
        ('draft', _('Brouillon')),
        ('sent', _('Envoyé')),
        ('archived', _('Archivé')),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=50, blank=True)  # unique par organisation (Meta)

    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.CASCADE, related_name='documents'
    )
    client = models.ForeignKey(
        'clients.Client', on_delete=models.SET_NULL, null=True, blank=True, related_name='documents'
    )

    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPE_CHOICES, default='general')
    title = models.CharField(max_length=200, default=_('Nouveau document'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    header_html = models.TextField(blank=True, default='')
    body_html = models.TextField(blank=True, default='')
    footer_html = models.TextField(blank=True, default='')

    style_config = models.JSONField(default=dict, blank=True)
    layout_mode = models.CharField(max_length=10, choices=LAYOUT_MODE_CHOICES, default='canvas')
    # Mode canvas : {'pages': [{'id', 'background', 'elements': [...]}]} — voir canvas_render.
    canvas_data = models.JSONField(default=dict, blank=True)
    logo = models.ImageField(upload_to='documents/logos/', blank=True, null=True)

    is_favorite = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_documents'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Document')
        verbose_name_plural = _('Documents')
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'number'], condition=~models.Q(number=''),
                                    name='uniq_document_number_per_org'),
        ]

    def __str__(self):
        return f"{self.number or self.title}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self._generate_number()
        if not self.style_config:
            self.style_config = dict(DEFAULT_STYLE_CONFIG)
        super().save(*args, **kwargs)

    def _generate_number(self):
        year = timezone.localdate().year
        prefix = f"DOC-{year}-"
        # Basé sur le dernier numéro existant (pas un count()) : un document supprimé
        # ne doit jamais faire retomber la séquence sur un numéro déjà pris.
        last_number = (
            Document.objects.filter(organization=self.organization, number__startswith=prefix)
            .order_by('-number')
            .values_list('number', flat=True)
            .first()
        )
        next_seq = 1
        if last_number:
            try:
                next_seq = int(last_number[len(prefix):]) + 1
            except ValueError:
                next_seq = Document.objects.filter(organization=self.organization).count() + 1
        # Séquence propre à l'organisation mais numéro unique sur toute la base : sans ce
        # saut, le 1er document d'une nouvelle organisation heurtait le DOC-<année>-0001
        # d'une autre (IntegrityError). Même logique que Invoice._generate_invoice_number.
        while Document.objects.filter(organization=self.organization, number=f"{prefix}{next_seq:04d}").exists():
            next_seq += 1
        return f"{prefix}{next_seq:04d}"

    def get_style(self, key):
        return (self.style_config or {}).get(key, DEFAULT_STYLE_CONFIG.get(key))

    def _variable_values(self):
        """Valeurs résolues pour les jetons `{{ variable }}` insérés dans l'éditeur."""
        client = self.client
        client_address = ''
        if client:
            parts = [client.address, client.postal_code, client.city, client.country]
            client_address = ', '.join(p for p in parts if p)
        org = self.organization
        org_address = ', '.join(
            str(p) for p in (getattr(org, f, '') for f in ('address', 'postal_code', 'city', 'country')) if p
        )
        return {
            'client.name': client.name if client else '',
            'client.email': client.email if client else '',
            'client.phone': (client.phone if client else '') or '',
            'client.address': client_address,
            'organization.name': self.organization.name,
            'organization.email': self.organization.email or '',
            'organization.phone': getattr(org, 'phone', '') or '',
            'organization.address': org_address,
            'document.number': self.number,
            'document.date': timezone.localdate().strftime('%d/%m/%Y'),
            'document.title': self.title,
            **{k: v for source in self.table_sources().values() for k, v in source['vars'].items()},
            # Valeurs imposées à la création (automatisations) : priment sur les valeurs automatiques.
            **clean_overrides((self.canvas_data or {}).get('overrides')),
            **custom_field_values((self.canvas_data or {}).get('fields')),
        }

    def table_sources(self):
        """Devis / facture reliés au document (tableaux remplis automatiquement, variables)."""
        if not hasattr(self, '_table_sources'):
            self._table_sources = linked_sources(self.organization, self.client, (self.canvas_data or {}).get('sources'))
        return self._table_sources

    def resolve_variables(self, html):
        """Remplace les jetons `<span class="doc-var-token" data-var="...">{{ ... }}</span>` par leur valeur."""
        import re
        from django.utils.html import escape
        values = self._variable_values()

        def _replace(match):
            key = match.group('key')
            return escape(values[key]) if key in values else match.group(0)

        pattern = re.compile(
            r'<span[^>]*class="doc-var-token"[^>]*data-var="(?P<key>[\w.]+)"[^>]*>.*?</span>',
            re.DOTALL,
        )
        return pattern.sub(_replace, html or '')

    def generate_pdf_html(self):
        """HTML complet (avec @page WeasyPrint) utilisé pour l'export PDF."""
        if self.layout_mode == 'canvas':
            from .canvas_render import render_canvas_html
            return render_canvas_html(
                self.canvas_data,
                page_format=self.get_style('page_format') or 'A4',
                orientation=self.get_style('page_orientation') or 'portrait',
                resolve=self.resolve_variables,
                sources=self.table_sources(),
            )
        logo_url = self.logo.url if self.logo else (
            self.organization.logo.url if getattr(self.organization, 'logo', None) else ''
        )
        border_spacing = self.get_style('border_spacing')
        border_spacing = 12 if border_spacing is None else border_spacing
        border = f'border: 3px solid #1f2937; padding: {border_spacing}px;' if self.get_style('border_style') == 'framed' else ''
        page_margin = self.get_style('page_margin')
        page_margin = 48 if page_margin is None else page_margin
        page_number_rule = (
            "@bottom-center { content: 'Page ' counter(page) ' / ' counter(pages); "
            "font-size: 9px; color: #6b7280; }"
        ) if self.get_style('show_page_numbers') else ''
        watermark_text = self.get_style('watermark_text')
        watermark_html = (
            f'<div class="watermark">{watermark_text}</div>' if watermark_text else ''
        )
        page_size = self.get_style('page_format') or 'A4'
        if self.get_style('page_orientation') == 'landscape':
            page_size = f'{page_size} landscape'
        accent_color = self.get_style('accent_color') or '#6d28d9'
        header_footer_css = {
            'line': 'border-bottom: 2px solid #e5e7eb; padding-bottom: 12px; margin-bottom: 8px;',
            'double-line': 'border-bottom: 3px double #6b7280; padding-bottom: 12px; margin-bottom: 8px;',
            'dotted': 'border-bottom: 1.5px dotted #6b7280; padding-bottom: 12px; margin-bottom: 8px;',
            'accent-bar': f'border-bottom: 3px solid {accent_color}; padding-bottom: 12px; margin-bottom: 8px;',
            'shaded': 'background: #f7f7f5; padding: 12px; border-radius: 8px;',
            'framed': 'border: 1px solid #e5e7eb; padding: 12px; border-radius: 8px;',
            'centered': 'text-align: center;',
            'minimal-caps': 'text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.82em; color: #6b7280; padding-bottom: 6px;',
        }
        header_extra_css = header_footer_css.get(self.get_style('header_style'), '')
        footer_extra_css = header_footer_css.get(self.get_style('footer_style'), '')
        table_style_css = {
            'bordered': 'table td, table th { border: 1px solid #d1d5db; padding: 6px 8px; }',
            'striped': (
                'table td, table th { border: none; padding: 6px 8px; } '
                'table th { border-bottom: 2px solid ' + accent_color + '; } '
                'table tr:nth-child(even) td { background: #f7f7f8; }'
            ),
            'minimal': (
                'table td, table th { border: none; border-bottom: 1px solid #e5e7eb; padding: 6px 8px; } '
                'table th { border-bottom: 2px solid #1f2937; }'
            ),
        }.get(self.get_style('table_style'), 'table td, table th { border: 1px solid #d1d5db; padding: 6px 8px; }')
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
        <meta charset="utf-8">
        <style>
            @page {{ size: {page_size}; margin: {page_margin}px; {page_number_rule} }}
            body {{
                font-family: {self.get_style('font_family')};
                color: {self.get_style('text_color')};
                background-color: {self.get_style('page_background_color')};
                position: relative;
                {border}
            }}
            .watermark {{
                position: fixed; top: 45%; left: 10%; width: 80%;
                font-size: 72px; color: #000; opacity: {self.get_style('watermark_opacity')};
                transform: rotate(-30deg); text-align: center; z-index: -1;
            }}
            table {{ border-collapse: collapse; width: 100%; }}
            {table_style_css}
            h1, h2, h3 {{ color: {self.get_style('text_color')}; }}
            a {{ color: {accent_color}; }}
            .doc-header img {{ max-height: 60px; }}
            .doc-header {{ {header_extra_css} }}
            .doc-footer {{ font-size: 11px; color: #6b7280; margin-top: 24px; {footer_extra_css} }}
        </style>
        </head>
        <body>
            {watermark_html}
            <div class="doc-header">
                {f'<img src="{logo_url}">' if logo_url else ''}
                {self.resolve_variables(self.header_html)}
            </div>
            <div class="doc-body">{self.resolve_variables(self.body_html)}</div>
            <div class="doc-footer">{self.resolve_variables(self.footer_html)}</div>
        </body>
        </html>
        """

    def generate_pdf_bytes(self):
        from apps.invoices.pdf import render_document_to_pdf_bytes
        return render_document_to_pdf_bytes(self)


class DocumentTemplate(models.Model):
    """
    Modèle de document réutilisable. `organization` nul = modèle système
    (galerie par défaut) ; renseigné = modèle personnel de l'organisation
    (« Mes modèles »), créé via « Enregistrer comme modèle ».
    """

    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.CASCADE, null=True, blank=True,
        related_name='document_templates',
    )
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=20, choices=DOCUMENT_TYPE_CHOICES, default='general')
    description = models.CharField(max_length=255, blank=True, default='')

    header_html = models.TextField(blank=True, default='')
    body_html = models.TextField(blank=True, default='')
    footer_html = models.TextField(blank=True, default='')
    style_config = models.JSONField(default=dict, blank=True)
    layout_mode = models.CharField(max_length=10, choices=LAYOUT_MODE_CHOICES, default='canvas')
    canvas_data = models.JSONField(default=dict, blank=True)

    thumbnail = models.ImageField(upload_to='documents/template_thumbnails/', blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Document Template')
        verbose_name_plural = _('Document Templates')
        ordering = ['organization_id', 'name']

    def __str__(self):
        return self.name

    @property
    def is_system(self):
        return self.organization_id is None


class DocumentResponse(models.Model):
    """Réponses d'un client aux champs de formulaire d'un document (sondage, demande…)."""
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='responses')
    client = models.ForeignKey('clients.Client', on_delete=models.SET_NULL, null=True, blank=True, related_name='document_responses')
    answers = models.JSONField(default=dict, blank=True)  # {id du champ: valeur}
    labels = models.JSONField(default=dict, blank=True)   # {id du champ: libellé au moment de la réponse}
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [models.UniqueConstraint(fields=['document', 'client'], name='unique_document_response_per_client')]

    def __str__(self):
        return f"Réponse à {self.document} ({self.client})"

    def rows(self):
        """[(libellé, valeur affichable)] dans l'ordre des champs."""
        import re
        from datetime import date
        out = []
        for field_id, value in (self.answers or {}).items():
            shown = ', '.join(value) if isinstance(value, list) else str(value or '')
            if re.match(r'^\d{4}-\d{2}-\d{2}$', shown):  # date saisie dans un champ « Date »
                try:
                    shown = date.fromisoformat(shown).strftime('%d/%m/%Y')
                except ValueError:
                    pass
            out.append((self.labels.get(field_id) or 'Champ', shown))
        return out
