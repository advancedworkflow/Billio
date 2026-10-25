from django.contrib import messages
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponse
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
from decimal import Decimal, InvalidOperation
from rest_framework import viewsets, generics
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from .models import Invoice, InvoiceItem, Tax, Quote, Product
from .serializers import InvoiceSerializer, QuoteSerializer, TaxSerializer, PublicInvoiceSerializer
from apps.templates_app.models import InvoiceTemplate, MarketplaceTemplate
from apps.clients.models import Client
from apps.organizations.models import Organization
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q
from django.urls import reverse
import json
import uuid
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


def format_eur(value) -> str:
    """Format simple FR : "1 205 467,06 €"."""
    try:
        dec = Decimal(value or 0)
    except Exception:
        dec = Decimal("0")
    dec = dec.quantize(Decimal("0.01"))
    sign = "-" if dec < 0 else ""
    dec = abs(dec)
    s = f"{dec:,.2f}"
    s = s.replace(",", " ").replace(".", ",")
    return f"{sign}{s} €"


def _serialize_templates_for_editor(templates):
    payload = []
    for template in templates:
        layout = template.layout_config or {}
        style = template.style_config or {}
        payload.append({
            'id': str(template.id),
            'source': 'personal',
            'name': template.name,
            'preview_url': reverse('templates_app:template-preview-frame', args=[template.id]),
            'html_structure': template.html_structure or '',
            'css_styles': template.css_styles or '',
            'variable_schema': layout.get('variable_schema') or layout.get('schema') or {'fields': []},
            'variables_defaults': style.get('variables_defaults') or style.get('defaults') or {},
        })
    return payload


def _serialize_marketplace_for_invoice_carousel(qs):
    """Templates système / marketplace pour le carrousel de création facture."""
    payload = []
    for mt in qs:
        layout = mt.layout_config or {}
        style = mt.style_config or {}
        payload.append({
            'id': f'm-{mt.id}',
            'source': 'marketplace',
            'name': mt.title,
            'preview_url': reverse('templates_app:marketplace-preview-frame', args=[mt.id]),
            'html_structure': mt.html_structure or '',
            'css_styles': mt.css_styles or '',
            'variable_schema': layout.get('variable_schema') or layout.get('schema') or {'fields': []},
            'variables_defaults': style.get('variables_defaults') or style.get('defaults') or {},
        })
    return payload


def _editor_products(organization):
    """Catalogue produits pour l'autocomplétion des lignes dans l'éditeur."""
    return list(Product.objects.filter(organization=organization, is_active=True).order_by('name').values(
        'id', 'name', 'description', 'unit_price', 'unit', 'tax_rate', 'reference',
    )[:500])


def build_invoice_editor_templates_library(organization):
    """Mes templates org d’abord (défaut en tête), puis modèles marketplace disponibles."""
    personal_qs = InvoiceTemplate.objects.filter(
        organization=organization,
        is_active=True,
    ).order_by('-is_default', 'name')
    # Les modèles vides créés automatiquement (HTML par défaut du champ) n'ont aucun intérêt
    # dans le sélecteur : on les masque.
    placeholder_html = InvoiceTemplate._meta.get_field('html_structure').default
    personal_qs = [t for t in personal_qs if (t.html_structure or '').strip() not in ('', placeholder_html)]
    personal = _serialize_templates_for_editor(personal_qs)
    from apps.templates_app.pro_templates import PRO_TEMPLATES
    from apps.templates_app.canvas import CANVAS_TEMPLATES
    pro_order = {spec['slug']: index for index, spec in enumerate(PRO_TEMPLATES + CANVAS_TEMPLATES)}
    mp_qs = sorted(
        MarketplaceTemplate.objects.filter(is_active=True, is_approved=True).order_by('-created_at')[:30],
        key=lambda mt: pro_order.get(mt.slug, len(pro_order)),  # modèles « pro » en tête, dans l'ordre défini
    )
    marketplace = _serialize_marketplace_for_invoice_carousel(mp_qs)
    # Conditions de paiement / mentions légales issues des réglages du Centre de ressources.
    from apps.templates_app.models import apply_billing_texts
    for entry in personal + marketplace:
        entry['variables_defaults'] = apply_billing_texts(dict(entry['variables_defaults'] or {}), organization)
    return personal + marketplace


def billing_editor_data(organization):
    """Réglages de facturation (Centre de ressources) utilisés par l'éditeur."""
    prefs = (organization.billing_preferences or {}) if organization else {}
    return {
        'tjm': prefs.get('tjm') or '',
        'hours_per_day': prefs.get('hours_per_day') or 7,
        'payment_days': int(prefs.get('payment_days') or getattr(organization, 'default_payment_terms', 30) or 30),
        'vat_exempt': bool(prefs.get('vat_exempt')),
    }


def apply_document_logo(document, organization, raw_id):
    """Logo propre au document : une image de la bibliothèque de l'organisation, ou rien (logo de l'entreprise)."""
    from apps.templates_app.models import TemplateAsset
    try:
        asset_id = int(raw_id or 0)
    except (TypeError, ValueError):
        asset_id = 0
    document.logo_asset = TemplateAsset.objects.filter(organization=organization, id=asset_id).first() if asset_id else None


def build_invoice_editor_bootstrap(invoice, *, preselected_client_id='', invoice_type='sale', page_title='Créer une facture'):
    """
    État initial pour l’éditeur facture (évite d’injecter du texte brut dans du JS = erreurs de syntaxe / Alpine cassé).
    """
    if invoice is not None:
        lines = list(invoice.items.all())
        # Factures enregistrées avant la TVA par ligne : TVA à 0 sur les lignes mais 20 %
        # appliqués au total. On les présente à 20 % pour ne pas changer leur montant.
        legacy_flat_vat = bool(lines) and all(not item.tax_rate for item in lines) and (invoice.tax_amount or 0) > 0
        items = []
        for item in lines:
            items.append({
                'name': item.name or '',
                'description': item.description or '',
                'quantity': float(item.quantity or 0),
                'unit_price': float(item.unit_price or 0),
                'unit': item.unit or 'unité',
                'tax_rate': 20.0 if legacy_flat_vat else float(item.tax_rate or 0),
            })
        client_id_val = str(invoice.client_id) if invoice.client_id else ''
        pcid = (preselected_client_id or '').strip()
        if pcid:
            client_id_val = str(pcid)
        return {
            'page_title': page_title,
            'selected_template': str(invoice.template_id) if getattr(invoice, 'template_id', None) else '',
            'invoice_data': {
                'client_id': client_id_val,
                'invoice_number': invoice.invoice_number or 'AUTO-001',
                'issue_date': invoice.issue_date.isoformat() if getattr(invoice, 'issue_date', None) else '',
                'due_date': invoice.due_date.isoformat() if getattr(invoice, 'due_date', None) else '',
                'currency': invoice.currency or 'EUR',
                'invoice_type': invoice.invoice_type or 'sale',
                'notes': invoice.notes or '',
                'discount_amount': float(invoice.discount_amount or 0),
                'logo_asset_id': invoice.logo_asset_id or '',
                'items': items,
            },
        }
    return {
        'page_title': page_title,
        'selected_template': '',
        'invoice_data': {
            'client_id': str(preselected_client_id or ''),
            'invoice_number': 'AUTO-001',
            'issue_date': '',
            'due_date': '',
            'currency': 'EUR',
            'invoice_type': invoice_type if invoice_type in ('sale', 'purchase') else 'sale',
            'notes': '',
            'discount_amount': 0,
            'items': [],
        },
    }


def resolve_invoice_template_selection(organization, template_ref):
    """
    Id perso (UUID/int) ou préfixe m-<id> marketplace → instance InvoiceTemplate pour la facture.
    Pour un modèle marketplace, réutilise un template org du même nom s’il existe, sinon copie.
    """
    if not template_ref:
        return None
    ref = str(template_ref).strip()
    if ref.startswith('m-'):
        pk = ref[2:].strip()
        if not pk.isdigit():
            return None
        mt = MarketplaceTemplate.objects.filter(
            id=int(pk), is_active=True, is_approved=True
        ).first()
        if not mt:
            return None
        base_name = (mt.title or 'Modèle').strip()[:100] or 'Modèle'
        existing = InvoiceTemplate.objects.filter(
            organization=organization, name=base_name
        ).first()
        if existing:
            # Les modèles « pro » de la galerie évoluent : leur copie reste alignée sur la source.
            if (mt.slug or '').startswith('pro-') and existing.html_structure != mt.html_structure:
                existing.html_structure = mt.html_structure or ''
                existing.css_styles = mt.css_styles or ''
                existing.layout_config = mt.layout_config if isinstance(mt.layout_config, dict) else {}
                existing.style_config = mt.style_config if isinstance(mt.style_config, dict) else {}
                existing.save(update_fields=['html_structure', 'css_styles', 'layout_config', 'style_config', 'updated_at'])
            return existing
        return InvoiceTemplate.objects.create(
            organization=organization,
            name=base_name,
            html_structure=mt.html_structure or '',
            css_styles=mt.css_styles or '',
            layout_config=mt.layout_config if isinstance(mt.layout_config, dict) else {},
            style_config=mt.style_config if isinstance(mt.style_config, dict) else {},
            is_active=True,
            is_default=False,
        )
    try:
        return InvoiceTemplate.objects.get(
            id=ref, organization=organization, is_active=True
        )
    except (InvoiceTemplate.DoesNotExist, ValueError):
        return None


INVOICE_LOCKED_MESSAGE = "Facture émise : elle ne peut plus être modifiée ni supprimée. Pour la corriger, créez un avoir."


class InvoiceViewSet(viewsets.ModelViewSet):
    """ViewSet for Invoice model."""
    queryset = Invoice.objects.all()  # Required for DRF router basename detection
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter invoices based on user's organizations."""
        from django.db.models import Q
        return Invoice.objects.filter(
            Q(organization__owner=self.request.user) |
            Q(organization__members__user=self.request.user)
        ).distinct()

    def update(self, request, *args, **kwargs):
        if self.get_object().is_locked:
            return Response({'error': INVOICE_LOCKED_MESSAGE}, status=400)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if self.get_object().is_locked:
            return Response({'error': INVOICE_LOCKED_MESSAGE}, status=400)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        """Send invoice to client."""
        invoice = self.get_object()
        invoice.mark_as_sent()
        from apps.dashboard.automation_engine import run_automations
        run_automations(
            invoice.organization, 'invoice_sent',
            target_type='invoice', target_id=invoice.id,
            amount=invoice.total_amount, client_id=invoice.client_id,
            context_label=f"Facture {invoice.invoice_number} envoyée.",
        )
        return Response({'message': 'Invoice sent successfully'})

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        """Mark invoice as paid."""
        invoice = self.get_object()
        invoice.mark_as_paid()
        from apps.dashboard.automation_engine import run_automations
        run_automations(
            invoice.organization, 'payment_received',
            source='manual',
            target_type='payment', target_id=invoice.id,
            amount=invoice.total_amount, client_id=invoice.client_id,
            context_label=f"Paiement reçu pour la facture {invoice.invoice_number}.",
        )
        return Response({'message': 'Invoice marked as paid'})


class QuoteViewSet(viewsets.ModelViewSet):
    """ViewSet for Quote model."""
    queryset = Quote.objects.all()  # Required for DRF router basename detection
    serializer_class = QuoteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter quotes based on user's organizations."""
        from django.db.models import Q
        return Quote.objects.filter(
            Q(organization__owner=self.request.user) |
            Q(organization__members__user=self.request.user)
        ).distinct()


class TaxViewSet(viewsets.ModelViewSet):
    """ViewSet for Tax model."""
    queryset = Tax.objects.all()  # Required for DRF router basename detection
    serializer_class = TaxSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter taxes based on user's organizations."""
        from django.db.models import Q
        return Tax.objects.filter(
            Q(organization__owner=self.request.user) |
            Q(organization__members__user=self.request.user)
        ).distinct()


class PublicInvoiceView(generics.RetrieveAPIView):
    """Public view for invoices (no authentication required)."""
    serializer_class = PublicInvoiceSerializer
    permission_classes = [AllowAny]

    def get_object(self):
        invoice_id = self.kwargs['invoice_id']
        return get_object_or_404(Invoice, id=invoice_id)


# HTMX Views
def invoice_list(request):
    """Main invoice list view."""
    from apps.organizations.models import Organization
    from django.db.models import Q
    from django.urls import reverse

    selected_organization = None
    org_param = (request.GET.get('organization') or '').strip()
    if org_param:
        selected_organization = Organization.objects.filter(
            Q(id=org_param) &
            (Q(owner=request.user) | Q(members__user=request.user))
        ).distinct().first()

    calendar_invoices = []
    if request.user.is_authenticated:
        invoices_qs = Invoice.objects.filter(
            Q(organization__owner=request.user) | Q(organization__members__user=request.user)
        ).select_related('client').order_by('due_date').distinct()[:300]
        for inv in invoices_qs:
            calendar_invoices.append({
                'id': str(inv.id),
                'number': inv.invoice_number,
                'client_name': inv.client.name if inv.client_id else '—',
                'due_date': inv.due_date.isoformat(),
                'status': inv.status,
                'status_label': inv.get_status_display(),
                'amount_formatted': format_eur(inv.total_amount),
                'preview_url': reverse('invoices:invoice-preview', args=[inv.id]),
            })

    invoices_total_count = 0
    if request.user.is_authenticated:
        invoices_total_count = Invoice.objects.filter(
            Q(organization__owner=request.user) | Q(organization__members__user=request.user)
        ).distinct().count()

    context = {
        'selected_organization': selected_organization,
        'selected_organization_id': str(selected_organization.id) if selected_organization else '',
        'calendar_invoices': calendar_invoices,
        'invoices_total_count': invoices_total_count,
    }
    return render(request, 'invoices/list.html', context)


@api_view(['POST'])
def invoice_create_api(request):
    """HTMX API endpoint for creating invoices."""
    if request.method == 'POST':
        # Basic validation and creation logic here
        # This is a placeholder - implement according to your needs
        return JsonResponse({'success': True, 'message': 'Invoice created'})


@login_required
def invoice_list_api(request):
    """HTMX API endpoint for invoice list."""
    # Check if user is authenticated (double check since @login_required should handle this)
    if not request.user.is_authenticated:
        from django.http import JsonResponse
        return JsonResponse({'error': 'Authentication required'}, status=401)

    try:
        # Base queryset - filter by user's accessible organizations
        from django.db.models import Q
        invoices = Invoice.objects.filter(
            Q(organization__owner=request.user) |
            Q(organization__members__user=request.user)
        )

        # Apply filters
        search = request.GET.get('search', '')
        status = request.GET.get('status', '')
        date_range = request.GET.get('date_range', '')
        invoice_type = request.GET.get('invoice_type', '')
        limit = request.GET.get('limit', '')
        organization_id = (request.GET.get('organization') or '').strip()

        if search:
            invoices = invoices.filter(
                Q(invoice_number__icontains=search) |
                Q(client__name__icontains=search) |
                Q(title__icontains=search)
            )

        if status:
            invoices = invoices.filter(status=status)

        if invoice_type in ['sale', 'purchase']:
            invoices = invoices.filter(invoice_type=invoice_type)

        if organization_id:
            invoices = invoices.filter(organization_id=organization_id)

        if date_range:
            from django.utils import timezone
            from datetime import timedelta
            try:
                days = int(date_range)
                start_date = timezone.now().date() - timedelta(days=days)
                invoices = invoices.filter(issue_date__gte=start_date)
            except (ValueError, TypeError):
                pass

        # Order by creation date
        invoices = invoices.order_by('-created_at')

        # Handle limit parameter (for dashboard recent invoices)
        if limit:
            try:
                limit_int = int(limit)
                limited_invoices = list(invoices[:limit_int])

                # Create a mock page object for limited results
                class MockPage:
                    def __init__(self, object_list):
                        self.object_list = object_list
                        self.start_index = 1
                        self.end_index = len(object_list)
                        self.has_other_pages = False
                        self.has_previous = False
                        self.has_next = False

                context = {
                    'invoices': limited_invoices,  # Pass the list directly
                    'is_paginated': False,
                    'page_obj': None,
                    'paginator': None,
                    'is_limited': True,
                }
            except (ValueError, TypeError):
                # If limit is invalid, fall back to pagination
                paginator = Paginator(invoices, 20)
                page_number = request.GET.get('page')
                page_obj = paginator.get_page(page_number)
                context = {
                    'invoices': page_obj,
                    'is_paginated': page_obj.has_other_pages(),
                    'page_obj': page_obj,
                    'paginator': paginator,
                    'is_limited': False,
                }
        else:
            # Normal pagination
            paginator = Paginator(invoices, 20)
            page_number = request.GET.get('page')
            page_obj = paginator.get_page(page_number)
            context = {
                'invoices': page_obj,
                'is_paginated': page_obj.has_other_pages(),
                'page_obj': page_obj,
                'paginator': paginator,
                'is_limited': False,
            }

        return render(request, 'invoices/_invoice_list.html', context)
    except Exception as e:
        print(f"Exception in invoice_list_api: {e}")
        import traceback
        traceback.print_exc()
        return render(request, 'invoices/_invoice_list.html', {
            'invoices': [],
            'is_paginated': False,
            'page_obj': None,
            'paginator': None,
            'is_limited': False,
        })


@login_required
def invoice_create(request):
    """Page de création d'une nouvelle facture."""
    # Récupérer l'organisation de l'utilisateur
    organizations = request.user.owned_organizations.all()
    if not organizations.exists():
        organizations = [m.organization for m in request.user.organization_memberships.all()]

    # Si pas d'organisation, créer une organisation de test temporairement
    if not organizations:
        from apps.organizations.models import Organization
        test_org, created = Organization.objects.get_or_create(
            name=f"Organisation de {request.user.username}",
            defaults={
                'owner': request.user,
                'address': '123 Rue de Test\n75001 Paris',
                'phone': '+33123456789',
                'email': f"{request.user.username}@test.com",
            }
        )
        organizations = [test_org]

    organization = organizations[0]

    # Plus de modèle vide créé d'office : l'éditeur propose directement les modèles de la galerie.

    # Récupérer les templates disponibles (affichage Django optionnel)
    templates = InvoiceTemplate.objects.filter(
        organization=organization,
        is_active=True
    ).order_by('-is_default', 'name')

    # Créer un client de test si aucun n'existe
    clients = Client.objects.filter(organization=organization)
    if not clients.exists():
        Client.objects.create(
            organization=organization,
            name='Client Test',
            email='client@test.com',
            address='123 Rue de Test\n75001 Paris',
            phone='+33123456789'
        )
        clients = Client.objects.filter(organization=organization)

    # Convertir les clients en liste sérialisable pour JavaScript
    clients_data = list(clients.values(
        'id', 'name', 'email', 'address', 'phone', 'registration_number', 'tax_id'
    ))
    organization_data = {
        'name': organization.name,
        'logo_url': organization.logo.url if organization.logo else '',
        'address': organization.address or '',
        'city': organization.city or '',
        'postal_code': organization.postal_code or '',
        'phone': organization.phone or '',
        'email': organization.email or '',
        'registration_number': organization.registration_number or '',
        'tax_id': organization.tax_id or '',
        'bank_name': organization.bank_name or '',
        'iban': organization.iban or '',
        'bic_swift': organization.bic_swift or '',
        'payment_instructions': organization.payment_instructions or '',
        'preferred_payment_method': getattr(organization, 'preferred_payment_method', None) or 'bank_transfer',
        'payment_method_label': organization.get_preferred_payment_method_display()
        if hasattr(organization, 'get_preferred_payment_method_display') else '',
        'billing': billing_editor_data(organization),
    }

    invoice_type = request.GET.get('invoice_type', 'sale')
    if invoice_type not in ['sale', 'purchase']:
        invoice_type = 'sale'

    preselected_client_id = request.GET.get('client', '')
    context = {
        'organization': organization,
        'templates': templates,
        'templates_data_obj': build_invoice_editor_templates_library(organization),
        'clients': clients,  # QuerySet pour les boucles Django
        'clients_data': clients_data,
        'organization_data': organization_data,
        'products_data': _editor_products(organization),
        'page_title': 'Créer une facture',
        'invoice_type': invoice_type,
        'preselected_client_id': preselected_client_id,
        'is_demo': False,
        'is_edit_mode': False,
        'invoice_editor_bootstrap': build_invoice_editor_bootstrap(
            None,
            preselected_client_id=preselected_client_id,
            invoice_type=invoice_type,
            page_title='Créer une facture',
        ),
    }
    from apps.organizations.currencies import editor_context
    context.update(editor_context(organization, context['invoice_editor_bootstrap'], new=True))

    return render(request, 'invoices/create.html', context)


@login_required
def save_invoice(request, invoice_id=None):
    """Sauvegarder une facture (création ou mise à jour)."""
    # Récupérer l'organisation
    organizations = request.user.owned_organizations.all()
    if not organizations.exists():
        organizations = [m.organization for m in request.user.organization_memberships.all()]

    if not organizations:
        return JsonResponse({'error': 'Aucune organisation trouvée'}, status=400)

    organization = organizations[0]

    if request.method == 'POST':
        try:
            data = request.POST.copy()
            items_data = json.loads(data.get('items', '[]'))

            if invoice_id:
                # Mise à jour
                invoice = get_object_or_404(
                    Invoice,
                    id=invoice_id,
                    organization=organization
                )
                if invoice.is_locked:
                    return JsonResponse({'error': INVOICE_LOCKED_MESSAGE}, status=400)
            else:
                # Création
                invoice = Invoice(organization=organization, created_by=request.user)

            # Mettre à jour les champs de base
            # create.html envoie `client_id` (et pas `client`).
            raw_client_id = (data.get('client_id') or data.get('client') or '').strip()
            if not raw_client_id:
                return JsonResponse({'error': 'Veuillez sélectionner un client.'}, status=400)
            client = Client.objects.filter(id=raw_client_id, organization=organization).first()
            if not client:
                return JsonResponse({'error': 'Client introuvable pour votre organisation.'}, status=400)
            invoice.client = client
            invoice.title = data.get('title', 'Facture')
            issue_date_raw = data.get('issue_date')
            due_date_raw = data.get('due_date')
            invoice.issue_date = issue_date_raw or timezone.now().date()
            invoice.due_date = due_date_raw or (timezone.now().date() + timedelta(days=30))
            invoice.currency = data.get('currency', 'EUR')
            invoice.notes = data.get('notes', '')
            if not invoice.is_credit_note:
                invoice.invoice_type = data.get('invoice_type', 'sale') or 'sale'

            # Template (perso ou marketplace via préfixe m-)
            template_ref = data.get('template')
            if template_ref:
                template = resolve_invoice_template_selection(organization, template_ref)
                if template:
                    invoice.template = template

            apply_document_logo(invoice, organization, data.get('logo_asset_id'))

            invoice.save()

            # Supprimer les anciens items
            invoice.items.all().delete()

            # Ajouter les nouveaux items — TVA par ligne (20 % par défaut si non précisée)
            subtotal = Decimal('0')
            tax_amount = Decimal('0')
            for idx, item_data in enumerate(items_data):
                try:
                    rate = Decimal(str(item_data.get('tax_rate', 20) if item_data.get('tax_rate') not in (None, '') else 20))
                except InvalidOperation:
                    rate = Decimal('20')
                line = InvoiceItem.objects.create(
                    invoice=invoice,
                    name=item_data.get('name', ''),
                    description=item_data.get('description', '') or '',
                    quantity=Decimal(str(item_data.get('quantity') or 0)),
                    unit_price=Decimal(str(item_data.get('unit_price') or 0)),
                    tax_rate=rate,
                    unit=(item_data.get('unit') or 'unit')[:50],
                    order=idx,
                )
                subtotal += line.total
                tax_amount += (line.total * rate / Decimal('100')).quantize(Decimal('0.01'))

            try:
                discount = max(Decimal('0'), Decimal(str(data.get('discount_amount') or '0')))
            except InvalidOperation:
                discount = Decimal('0')
            invoice.subtotal = subtotal
            invoice.tax_amount = tax_amount
            invoice.discount_amount = discount
            invoice.total_amount = subtotal + tax_amount - discount
            invoice.save()

            return JsonResponse({
                'success': True,
                'invoice_id': str(invoice.id),
                'message': 'Facture sauvegardée avec succès'
            })

        except Exception as e:
            return JsonResponse({
                'error': str(e)
            }, status=400)

    return JsonResponse({'error': 'Méthode non autorisée'}, status=405)


@require_POST
def send_invoice(request, invoice_id):
    """
    HTMX endpoint to send invoice.
    Implémente le workflow SENT: génération HTML/PDF, création Payment Intent Stripe, envoi email.
    """
    try:
        from django.db.models import Q
        invoice = get_object_or_404(
            Invoice.objects.distinct(),
            Q(id=invoice_id) & (
                Q(organization__owner=request.user) |
                Q(organization__members__user=request.user)
            )
        )

        # Vérifier que la facture est en DRAFT
        if invoice.status != 'draft':
            return JsonResponse({
                'success': False,
                'message': f'Impossible d\'envoyer une facture avec le statut "{invoice.get_status_display()}"'
            }, status=400)

        from apps.accounts.email_verification import client_email_blocked
        blocked = client_email_blocked(invoice.organization) if invoice.client_id and invoice.client.email else ''
        if blocked:
            if not (request.headers.get('HX-Request') or 'application/json' in request.headers.get('Accept', '')):
                messages.error(request, blocked)
                return redirect('invoices:invoice-preview', invoice_id=invoice.id)
            return JsonResponse({'success': False, 'message': blocked}, status=400)

        # Générer le PDF et créer le Payment Intent Stripe
        success, message = invoice.send_to_client()

        if success and not invoice.is_credit_note:
            from apps.dashboard.automation_engine import run_automations
            run_automations(
                invoice.organization, 'invoice_sent',
                target_type='invoice', target_id=invoice.id,
                amount=invoice.total_amount, client_id=invoice.client_id,
                context_label=f"Facture {invoice.invoice_number} envoyée à {invoice.client.name if invoice.client_id else ''}.",
            )
        if success and invoice.is_credit_note:
            message = f"Avoir {invoice.invoice_number} émis."
        # Formulaire classique (bouton de l'aperçu) : retour sur l'aperçu avec un message, pas du JSON brut.
        wants_json = request.headers.get('HX-Request') or 'application/json' in request.headers.get('Accept', '')
        if not wants_json:
            (messages.success if success else messages.error)(request, message)
            return redirect('invoices:invoice-preview', invoice_id=invoice.id)
        if success:
            return JsonResponse({'success': True, 'message': message})
        return JsonResponse({'success': False, 'message': message}, status=400)

    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)


@require_POST
def schedule_invoice_send(request, invoice_id):
    """Programme (ou annule) l'envoi automatique d'une facture brouillon à une date future."""
    from django.db.models import Q
    from django.utils.dateparse import parse_datetime

    invoice = get_object_or_404(
        Invoice.objects.distinct(),
        Q(id=invoice_id) & (
            Q(organization__owner=request.user) |
            Q(organization__members__user=request.user)
        )
    )

    if invoice.status != 'draft':
        return JsonResponse({
            'success': False,
            'message': f'Impossible de programmer l\'envoi d\'une facture avec le statut "{invoice.get_status_display()}"',
        }, status=400)

    raw = (request.POST.get('scheduled_send_at') or '').strip()
    if not raw:
        invoice.scheduled_send_at = None
        invoice.save(update_fields=['scheduled_send_at', 'updated_at'])
        return JsonResponse({'success': True, 'message': 'Envoi programmé annulé.'})

    scheduled_at = parse_datetime(raw)
    if scheduled_at is None:
        return JsonResponse({'success': False, 'message': 'Date invalide.'}, status=400)
    if timezone.is_naive(scheduled_at):
        scheduled_at = timezone.make_aware(scheduled_at)
    if scheduled_at <= timezone.now():
        return JsonResponse({'success': False, 'message': 'La date doit être dans le futur.'}, status=400)

    invoice.scheduled_send_at = scheduled_at
    invoice.save(update_fields=['scheduled_send_at', 'updated_at'])
    return JsonResponse({
        'success': True,
        'message': f"Envoi programmé pour le {timezone.localtime(scheduled_at).strftime('%d/%m/%Y à %H:%M')}.",
    })


@login_required
@require_POST
def invoice_toggle_favorite(request, invoice_id):
    """Bascule le statut favori d'une facture."""
    from django.db.models import Q
    invoice = get_object_or_404(
        Invoice.objects.distinct(),
        Q(id=invoice_id) & (
            Q(organization__owner=request.user) |
            Q(organization__members__user=request.user)
        )
    )
    invoice.is_favorite = not invoice.is_favorite
    invoice.save(update_fields=['is_favorite', 'updated_at'])
    return JsonResponse({'success': True, 'is_favorite': invoice.is_favorite})


@login_required
@require_POST
def mark_invoice_paid(request, invoice_id):
    """
    Marque manuellement une facture comme payée lorsque le client a réglé par
    un autre moyen que le lien de paiement en ligne (virement bancaire, espèces,
    chèque...). Enregistre un Payment 'completed' pour garder une trace du moyen utilisé.
    """
    from django.db.models import Q
    from apps.payments.models import Payment, PaymentMethod

    invoice = get_object_or_404(
        Invoice.objects.distinct(),
        Q(id=invoice_id) & (
            Q(organization__owner=request.user) |
            Q(organization__members__user=request.user)
        )
    )

    if invoice.status == 'paid':
        return JsonResponse({'success': False, 'message': 'Cette facture est déjà marquée comme payée.'}, status=400)
    if invoice.status not in ('sent', 'viewed', 'overdue'):
        return JsonResponse({
            'success': False,
            'message': f'Impossible de marquer comme payée une facture avec le statut "{invoice.get_status_display()}".',
        }, status=400)

    method_type = request.POST.get('payment_method') or 'bank_transfer'
    valid_methods = {value for value, _label in PaymentMethod.METHOD_CHOICES}
    if method_type not in valid_methods:
        method_type = 'bank_transfer'
    notes = (request.POST.get('notes') or '').strip()

    payment_method, _created = PaymentMethod.objects.get_or_create(
        organization=invoice.organization,
        method_type=method_type,
        name=f"Paiement manuel — {dict(PaymentMethod.METHOD_CHOICES)[method_type]}",
        defaults={'is_active': True},
    )

    from django.db.models import Sum
    already_paid = invoice.payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or 0
    Payment.objects.create(
        invoice=invoice,
        payment_method=payment_method,
        amount=invoice.amount_due(already_paid),  # le solde, après acomptes et avoirs
        currency=invoice.currency,
        status='completed',
        provider='manual',
        payment_date=timezone.now(),
        processed_at=timezone.now(),
        notes=notes,
        created_by=request.user,
    )

    invoice.mark_as_paid()

    from apps.dashboard.automation_engine import run_automations
    run_automations(
        invoice.organization, 'payment_received',
        source='manual',
        target_type='payment', target_id=invoice.id,
        amount=invoice.total_amount, client_id=invoice.client_id,
        context_label=f"Paiement manuel enregistré pour la facture {invoice.invoice_number}.",
    )

    return JsonResponse({'success': True, 'message': 'Facture marquée comme payée.'})


@require_POST
def duplicate_invoice(request, invoice_id):
    """HTMX endpoint to duplicate invoice."""
    try:
        from django.db.models import Q
        original_invoice = get_object_or_404(
            Invoice.objects.distinct(),
            Q(id=invoice_id) & (
                Q(organization__owner=request.user) |
                Q(organization__members__user=request.user)
            )
        )

        # Create duplicate
        duplicate = Invoice.objects.create(
            organization=original_invoice.organization,
            client=original_invoice.client,
            title=f"Copie de {original_invoice.title}",
            description=original_invoice.description,
            issue_date=original_invoice.issue_date,
            due_date=original_invoice.due_date,
            subtotal=original_invoice.subtotal,
            tax_amount=original_invoice.tax_amount,
            discount_amount=original_invoice.discount_amount,
            total_amount=original_invoice.total_amount,
            currency=original_invoice.currency,
            status='draft',
            payment_terms=original_invoice.payment_terms,
            notes=original_invoice.notes,
            footer=original_invoice.footer,
            created_by=request.user
        )

        # Duplicate items
        for item in original_invoice.items.all():
            InvoiceItem.objects.create(
                invoice=duplicate,
                name=item.name,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                unit=item.unit,
                tax_rate=item.tax_rate,
                order=item.order
            )

        return JsonResponse({'success': True, 'message': 'Facture dupliquée avec succès'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)


@login_required
def invoice_edit(request, invoice_id):
    """Page d'édition d'une facture existante."""
    # Récupérer la facture
    from django.db.models import Q
    invoice = get_object_or_404(
        Invoice.objects.distinct(),
        Q(id=invoice_id) & (
            Q(organization__owner=request.user) |
            Q(organization__members__user=request.user)
        )
    )
    if invoice.is_locked:
        messages.info(request, INVOICE_LOCKED_MESSAGE)
        return redirect('invoices:invoice-preview', invoice_id=invoice.id)

    # Récupérer les templates disponibles (org)
    templates = InvoiceTemplate.objects.filter(
        organization=invoice.organization,
        is_active=True
    ).order_by('-is_default', 'name')

    # Récupérer les clients
    clients = Client.objects.filter(organization=invoice.organization)
    clients_data = list(clients.values(
        'id', 'name', 'email', 'address', 'phone', 'registration_number', 'tax_id'
    ))
    org = invoice.organization
    organization_data = {
        'name': org.name,
        'logo_url': org.logo.url if org.logo else '',
        'address': org.address or '',
        'city': org.city or '',
        'postal_code': org.postal_code or '',
        'phone': org.phone or '',
        'email': org.email or '',
        'registration_number': org.registration_number or '',
        'tax_id': org.tax_id or '',
        'bank_name': org.bank_name or '',
        'iban': org.iban or '',
        'bic_swift': org.bic_swift or '',
        'payment_instructions': org.payment_instructions or '',
        'preferred_payment_method': getattr(org, 'preferred_payment_method', None) or 'bank_transfer',
        'payment_method_label': org.get_preferred_payment_method_display()
        if hasattr(org, 'get_preferred_payment_method_display') else '',
        'billing': billing_editor_data(org),
    }

    page_title = f'Éditer la facture #{invoice.invoice_number}'
    preselected_from_qs = (request.GET.get('client') or '').strip()
    preselected_client_id = preselected_from_qs or (
        str(invoice.client_id) if invoice.client_id else ''
    )
    context = {
        'invoice': invoice,
        'organization': invoice.organization,
        'templates': templates,
        'templates_data_obj': build_invoice_editor_templates_library(invoice.organization),
        'clients': clients,
        'clients_data': clients_data,
        'organization_data': organization_data,
        'products_data': _editor_products(invoice.organization),
        # Needed because the template uses: invoice.invoice_type|default:invoice_type|default:"sale"
        # Django resolves the fallback variable eagerly, so it must exist in the context.
        'invoice_type': invoice.invoice_type,
        'page_title': page_title,
        'is_demo': False,
        'is_edit_mode': False,
        # Même clé que invoice_create (create.html / options client « selected »).
        'preselected_client_id': preselected_client_id,
        'invoice_editor_bootstrap': build_invoice_editor_bootstrap(
            invoice,
            preselected_client_id=preselected_from_qs,
            invoice_type=invoice.invoice_type,
            page_title=page_title,
        ),
    }
    from apps.organizations.currencies import editor_context
    context.update(editor_context(invoice.organization, context['invoice_editor_bootstrap'], new=False))

    return render(request, 'invoices/create.html', context)


def _seller_country(invoice):
    from apps.organizations.jurisdictions import profile
    return profile(invoice.organization)['country']


def _payment_link_context(invoice):
    """Panneau « Lien de paiement » de l'aperçu : facture émise et pas encore soldée."""
    from apps.payments import payment_links
    from apps.payments.stripe_checkout import online_payments_enabled
    if not payment_links.payable(invoice):
        return {'payment_link': ''}
    url = payment_links.payment_url(invoice)
    return {'payment_link': url, 'payment_qr': payment_links.qr_svg(url, scale=4),
            'online_payments': online_payments_enabled(invoice.organization)}


@login_required
def invoice_preview(request, invoice_id):
    """
    Prévisualisation HTML d'une facture.
    """
    invoice = get_object_or_404(
        Invoice.objects.distinct(),
        Q(organization__owner=request.user) | Q(organization__members__user=request.user),
        id=invoice_id
    )

    try:
        html_content = invoice.render_html()
        css_content = invoice.render_css()
    except Exception as e:
        html_content = f"<div class='error'>Erreur lors de la génération: {str(e)}</div>"
        css_content = "body { color: red; }"

    context = {
        'invoice': invoice,
        'html_content': html_content,
        'css_content': css_content,
        'page_title': f"{'Avoir' if invoice.is_credit_note else 'Facture'} {invoice.invoice_number}",
        'credit_notes': list(invoice.credit_notes.order_by('created_at')) if not invoice.is_credit_note else [],
        'amount_due': invoice.amount_due() if invoice.invoice_type == 'sale' and invoice.status != 'draft' else None,
        **_payment_link_context(invoice),
        'recurrence_choices': Invoice.RECURRENCE_CHOICES,
        'einvoice': __import__('apps.invoices.facturx', fromlist=['readiness']).readiness(invoice)
                    if invoice.invoice_type in ('sale', 'credit_note') and _seller_country(invoice) == 'FR' else None,
        'compliance_checks': __import__('apps.organizations.jurisdictions', fromlist=['invoice_checks']).invoice_checks(invoice)
                             if invoice.invoice_type in ('sale', 'credit_note') else [],
    }

    return render(request, 'invoices/preview.html', context)


@login_required
@require_POST
def invoice_recurrence_update(request, invoice_id):
    """Rend une facture de vente récurrente (elle sert de modèle) ou arrête la récurrence."""
    from datetime import datetime
    from .scheduled import RECURRENCE_STEP
    invoice = get_object_or_404(
        Invoice.objects.distinct(),
        Q(organization__owner=request.user) | Q(organization__members__user=request.user),
        id=invoice_id, invoice_type='sale',
    )
    recurrence = request.POST.get('recurrence', 'none')
    if recurrence not in dict(Invoice.RECURRENCE_CHOICES):
        recurrence = 'none'

    def parse(value):
        try:
            return datetime.strptime(value or '', '%Y-%m-%d').date()
        except ValueError:
            return None

    invoice.recurrence = recurrence
    if recurrence == 'none':
        invoice.recurrence_next_date = None
        messages.success(request, 'Récurrence arrêtée.')
    else:
        start = parse(request.POST.get('next_date')) or ((invoice.issue_date or timezone.localdate()) + RECURRENCE_STEP[recurrence])
        invoice.recurrence_next_date = max(start, timezone.localdate())
        invoice.recurrence_end_date = parse(request.POST.get('end_date'))
        note = '' if invoice.organization.automation_recurring_invoices else \
            " Activez « Factures récurrentes » dans Réglages de relances pour qu'elles partent automatiquement."
        messages.success(request, f"Prochaine facture le {invoice.recurrence_next_date:%d/%m/%Y}, envoyée automatiquement au client.{note}")
    # Champs de planification seulement : le contenu d'une facture émise reste figé.
    invoice.save(update_fields=['recurrence', 'recurrence_next_date', 'recurrence_end_date', 'updated_at'])
    return redirect('invoices:invoice-preview', invoice_id=invoice.id)


@login_required
def invoice_facturx(request, invoice_id, fmt):
    """Facture électronique Factur-X : XML CII (EN 16931) ou PDF/A-3 avec le XML embarqué."""
    from . import facturx
    invoice = get_object_or_404(
        Invoice.objects.distinct(),
        Q(organization__owner=request.user) | Q(organization__members__user=request.user),
        id=invoice_id, invoice_type__in=('sale', 'credit_note'),
    )
    from apps.subscriptions.entitlements import require_feature
    require_feature(invoice.organization, 'facturx')
    if invoice.status == 'draft':
        messages.error(request, "Émettez d'abord la facture : une facture électronique porte son numéro définitif.")
        return redirect('invoices:invoice-preview', invoice_id=invoice.id)
    xml = facturx.build_cii_xml(invoice)
    errors = facturx.validate(xml)
    if errors:
        messages.error(request, 'Facture électronique non conforme : ' + ' '.join(errors)[:400])
        return redirect('invoices:invoice-preview', invoice_id=invoice.id)
    if fmt == 'xml':
        response = HttpResponse(xml, content_type='application/xml')
        response['Content-Disposition'] = f'attachment; filename="factur-x-{invoice.invoice_number}.xml"'
        return response
    try:
        content = facturx.facturx_pdf(invoice)
    except Exception:
        logger.exception('PDF Factur-X impossible pour %s', invoice.invoice_number)
        messages.error(request, "Le PDF Factur-X n'a pas pu être généré (moteur PDF indisponible). Le XML reste téléchargeable.")
        return redirect('invoices:invoice-preview', invoice_id=invoice.id)
    response = HttpResponse(content, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Facture-{invoice.invoice_number}-facturx.pdf"'
    return response


@login_required
@require_POST
def invoice_retention_release(request, invoice_id):
    """Libère la retenue de garantie : elle redevient due par le client."""
    invoice = get_object_or_404(
        Invoice.objects.distinct(),
        Q(organization__owner=request.user) | Q(organization__members__user=request.user),
        id=invoice_id,
    )
    if invoice.retention_amount and not invoice.retention_released_at and invoice.status != 'draft':
        invoice.retention_released_at = timezone.now()
        # La facture était soldée hors retenue : elle redevient à encaisser.
        if invoice.status == 'paid' and invoice.amount_due() > 0:
            invoice.status = 'sent'
        invoice.save(update_fields=['retention_released_at', 'status', 'updated_at'])
        messages.success(request, f"Retenue de garantie de {invoice.retention_amount} € libérée : elle est maintenant due par le client.")
    return redirect('invoices:invoice-preview', invoice_id=invoice.id)


@login_required
@require_POST
def invoice_credit_note_create(request, invoice_id):
    """Crée un avoir (brouillon) sur une facture émise : total, ou partiel (montant TTC + motif)."""
    invoice = get_object_or_404(
        Invoice.objects.distinct(),
        Q(organization__owner=request.user) | Q(organization__members__user=request.user),
        id=invoice_id,
    )
    raw = (request.POST.get('amount') or '').replace(',', '.').replace(' ', '').strip()
    amount = None
    if request.POST.get('mode') == 'partial':
        try:
            amount = Decimal(raw).quantize(Decimal('0.01'))
        except InvalidOperation:
            amount = Decimal('0')
        if amount <= 0 or amount > invoice.total_amount:
            messages.error(request, "Montant d'avoir invalide.")
            return redirect('invoices:invoice-preview', invoice_id=invoice.id)
    try:
        credit = invoice.create_credit_note(user=request.user, amount=amount, reason=(request.POST.get('reason') or '').strip()[:200])
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('invoices:invoice-preview', invoice_id=invoice.id)
    messages.success(request, "Avoir créé en brouillon : vérifiez-le puis émettez-le.")
    return redirect('invoices:invoice-preview', invoice_id=credit.id)


def public_invoice_payment(request, invoice_id):
    """Public payment page shared with clients."""
    from apps.payments.stripe_checkout import online_payments_enabled
    invoice = get_object_or_404(Invoice, id=invoice_id, invoice_type='sale')

    if invoice.status == 'draft':
        return HttpResponse("Facture non envoyee.", status=400)

    if invoice.status == 'sent':
        invoice.status = 'viewed'
        invoice.save(update_fields=['status', 'updated_at'])

        from apps.dashboard.automation_engine import run_automations
        run_automations(
            invoice.organization, 'invoice_viewed',
            target_type='invoice', target_id=invoice.id,
            amount=invoice.total_amount, client_id=invoice.client_id,
            variables={'numero': invoice.invoice_number},
            context_label=f"Facture {invoice.invoice_number} consultée par le client.",
        )

        from apps.dashboard.models import Notification
        recipients = {invoice.organization.owner}
        if invoice.created_by_id:
            recipients.add(invoice.created_by)
        client_label = invoice.client.name if invoice.client_id else "Un client"
        for user in recipients:
            if not user:
                continue
            Notification.objects.create(
                user=user,
                notification_type='invoice_viewed',
                title=f"Facture {invoice.invoice_number} consultée",
                message=f"{client_label} a consulté la facture.",
                priority='low',
                related_invoice=invoice,
            )

    from django.db.models import Sum
    from decimal import Decimal as D
    paid = invoice.payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or D('0')
    remaining = D('0') if invoice.status == 'paid' else invoice.amount_due(paid)
    items = list(invoice.items.order_by('order', 'id'))
    tax_groups = {}
    for item in items:
        rate = item.tax_rate or D('0')
        tax_groups[rate] = tax_groups.get(rate, D('0')) + (item.total * rate / D('100'))
    days_left = (invoice.due_date - timezone.localdate()).days if invoice.due_date else None
    context = {
        'invoice': invoice,
        'organization': invoice.organization,
        'items': items,
        'tax_lines': [(rate, amount.quantize(D('0.01'))) for rate, amount in sorted(tax_groups.items()) if rate],
        'paid_amount': paid,
        'remaining': remaining,
        'payments': invoice.payments.filter(status='completed').select_related('payment_method').order_by('payment_date'),
        'days_left': days_left,
        'days_late': -days_left if days_left is not None and days_left < 0 else 0,
        'page_title': f'Facture {invoice.invoice_number} — {invoice.organization.name}',
        'card_payment': online_payments_enabled(invoice.organization),
        'transfer_qr': __import__('apps.payments.local_methods', fromlist=['epc_qr_svg']).epc_qr_svg(
            invoice.organization, invoice, remaining) if invoice.status != 'paid' else '',
        'payment_cancelled': request.GET.get('paiement') == 'annule',
    }
    return render(request, 'invoices/public_payment.html', context)


def public_invoice_pdf(request, invoice_id):
    """PDF de la facture ou de l'avoir pour le client (lien public). ?download=1 force le téléchargement."""
    invoice = get_object_or_404(Invoice, id=invoice_id, invoice_type__in=('sale', 'credit_note'))
    if invoice.status == 'draft':
        return HttpResponse("Facture non envoyée.", status=404)
    try:
        content = invoice.ensure_pdf()
    except Exception:  # runtime WeasyPrint absent ou rendu impossible
        logger.exception("PDF de la facture %s impossible à générer", invoice.invoice_number)
        return HttpResponse("Le PDF n'est pas disponible pour le moment. Réessayez dans quelques instants.", status=503)
    response = HttpResponse(content, content_type='application/pdf')
    disposition = 'attachment' if request.GET.get('download') else 'inline'
    response['Content-Disposition'] = f'{disposition}; filename="Facture-{invoice.invoice_number}.pdf"'
    response['X-Frame-Options'] = 'SAMEORIGIN'
    return response


@require_POST
def public_invoice_pay(request, invoice_id):
    """
    Le client clique « Payer en ligne » : on ouvre une session Stripe Checkout pour le
    reste dû. La facture n'est marquée payée qu'après confirmation de Stripe
    (retour `public_invoice_pay_return` ou webhook), jamais sur ce simple clic.
    """
    from apps.integrations.providers import ProviderError
    from apps.payments.stripe_checkout import create_checkout

    invoice = get_object_or_404(Invoice, id=invoice_id, invoice_type='sale')
    payment_page = reverse('invoices:public-invoice-payment', args=[invoice.id])
    if invoice.status not in ('sent', 'viewed', 'overdue'):
        return redirect(payment_page)
    from django.db.models import Sum
    paid = invoice.payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    remaining = invoice.amount_due(paid)
    if remaining <= 0:
        return redirect(payment_page)
    try:
        url = create_checkout(
            invoice.organization, amount=remaining, currency=invoice.currency,
            label=f"Facture {invoice.invoice_number} — {invoice.organization.name}",
            metadata={'organization_id': invoice.organization_id, 'invoice_id': invoice.id},
            success_url=request.build_absolute_uri(reverse('invoices:public-invoice-pay-return', args=[invoice.id])) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.build_absolute_uri(payment_page) + '?paiement=annule',
            customer_email=invoice.client.email if invoice.client_id else '',
        )
    except ProviderError as exc:
        messages.error(request, str(exc))
        return redirect(payment_page)
    return redirect(url)


def public_invoice_pay_return(request, invoice_id):
    """Retour de Stripe Checkout : on relit la session côté serveur avant d'enregistrer le paiement."""
    from apps.integrations.providers import ProviderError
    from apps.payments.stripe_checkout import record_checkout, retrieve_session

    invoice = get_object_or_404(Invoice, id=invoice_id, invoice_type='sale')
    try:
        session = retrieve_session(invoice.organization, request.GET.get('session_id', ''))
    except ProviderError:
        session = None
    if session and str((session.get('metadata') or {}).get('invoice_id')) == str(invoice.id):
        record_checkout(invoice.organization, session)
    invoice.refresh_from_db()
    if invoice.status == 'paid':
        return redirect('invoices:public-invoice-receipt', invoice_id=invoice.id)
    messages.info(request, 'Paiement en cours de confirmation par la banque. Cette page se mettra à jour dès sa validation.')
    return redirect('invoices:public-invoice-payment', invoice_id=invoice.id)


def public_invoice_receipt(request, invoice_id):
    """Public receipt view after successful payment."""
    invoice = get_object_or_404(Invoice, id=invoice_id, invoice_type='sale')
    if invoice.status != 'paid':
        return redirect('invoices:public-invoice-payment', invoice_id=invoice.id)

    context = {
        'invoice': invoice,
        'page_title': f'Recu {invoice.receipt_number or invoice.invoice_number}',
    }
    return render(request, 'invoices/public_receipt.html', context)


def public_invoice_receipt_download(request, invoice_id):
    """Simple downloadable receipt text."""
    invoice = get_object_or_404(Invoice, id=invoice_id, invoice_type='sale')
    if invoice.status != 'paid':
        return HttpResponse("Recu indisponible.", status=400)

    lines = [
        "BILLIO - RECU DE PAIEMENT",
        "==========================",
        f"Recu: {invoice.receipt_number or ('RCPT-' + invoice.invoice_number)}",
        f"Facture: {invoice.invoice_number}",
        f"Client: {invoice.client.name}",
        f"Montant: {invoice.total_amount} {invoice.currency}",
        f"Paye le: {invoice.paid_at.strftime('%d/%m/%Y %H:%M') if invoice.paid_at else '-'}",
    ]
    content = "\n".join(lines)
    response = HttpResponse(content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="recu-{invoice.invoice_number}.txt"'
    return response


def _get_user_primary_organization(user):
    organization = user.owned_organizations.first()
    if organization:
        return organization
    membership = user.organization_memberships.select_related('organization').first()
    return membership.organization if membership else None


def _get_product_for_user(user, product_id):
    return get_object_or_404(
        Product.objects.filter(
            Q(organization__owner=user) | Q(organization__members__user=user)
        ).distinct(),
        id=product_id
    )


PRODUCT_UNITS = [
    ('heure', 'Heure'), ('jour', 'Jour'), ('forfait', 'Forfait'), ('unit', 'Unité'),
    ('mois', 'Mois'), ('page', 'Page'), ('km', 'Kilomètre'), ('lot', 'Lot'),
]


def _product_payload(product, stats=None):
    stats = stats or {}
    ttc = (product.unit_price * (Decimal('1') + (product.tax_rate or Decimal('0')) / Decimal('100'))).quantize(Decimal('0.01'))
    margin = None
    if product.cost_price is not None and product.unit_price:
        from decimal import ROUND_HALF_UP
        margin = float(((product.unit_price - product.cost_price) / product.unit_price * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))
    return {
        'id': product.id, 'name': product.name, 'description': product.description or '',
        'unit_price': str(product.unit_price), 'unit': product.unit or 'unit', 'tax_rate': str(product.tax_rate),
        'price_ttc': str(ttc), 'kind': product.kind, 'reference': product.reference, 'category': product.category,
        'cost_price': '' if product.cost_price is None else str(product.cost_price), 'margin_pct': margin,
        'is_active': product.is_active, 'updated': product.updated_at.strftime('%d/%m/%Y'),
        'invoices': stats.get('invoices', 0), 'quotes': stats.get('quotes', 0),
        'revenue': str(stats.get('revenue', Decimal('0'))), 'quantity': str(stats.get('quantity', Decimal('0'))),
        'last_used': stats['last'].strftime('%d/%m/%Y') if stats.get('last') else '',
        'recent': stats.get('recent', []),
    }


def _product_stats(organization, products):
    """Utilisation de chaque produit dans les factures (hors brouillons) et les devis, sur 12 mois."""
    from apps.invoices.models import QuoteItem
    since = timezone.localdate() - timedelta(days=365)
    by_name = {p.name.strip().lower(): p.id for p in products}
    stats = {p.id: {'invoices': 0, 'quotes': 0, 'revenue': Decimal('0'), 'quantity': Decimal('0'), 'last': None, 'recent': [], '_inv': set()} for p in products}
    items = (InvoiceItem.objects
             .filter(invoice__organization=organization, invoice__invoice_type='sale', invoice__issue_date__gte=since)
             .exclude(invoice__status__in=('draft', 'cancelled'))
             .select_related('invoice', 'invoice__client').order_by('-invoice__issue_date'))
    for item in items:
        pid = by_name.get((item.name or '').strip().lower())
        if pid is None:
            continue
        s = stats[pid]
        s['revenue'] += item.total or Decimal('0')
        s['quantity'] += item.quantity or Decimal('0')
        if item.invoice_id not in s['_inv']:
            s['_inv'].add(item.invoice_id)
            s['invoices'] += 1
            if len(s['recent']) < 5:
                s['recent'].append({
                    'label': item.invoice.invoice_number, 'client': item.invoice.client.name if item.invoice.client_id else '',
                    'date': item.invoice.issue_date.strftime('%d/%m/%Y'), 'amount': str(item.total),
                    'url': reverse('invoices:invoice-edit', args=[item.invoice_id]),
                })
        if s['last'] is None or item.invoice.issue_date > s['last']:
            s['last'] = item.invoice.issue_date
    quote_items = QuoteItem.objects.filter(quote__organization=organization, quote__issue_date__gte=since).values('quote_id', 'product_id', 'name')
    seen = set()
    for qi in quote_items:
        pid = qi['product_id'] if qi['product_id'] in stats else by_name.get((qi['name'] or '').strip().lower())
        if pid is not None and (pid, qi['quote_id']) not in seen:
            seen.add((pid, qi['quote_id']))
            stats[pid]['quotes'] += 1
    return stats


@login_required
def product_list(request):
    """Catalogue des produits et prestations, avec leur utilisation réelle."""
    organization = _get_user_primary_organization(request.user)
    products = list(Product.objects.filter(organization=organization).order_by('name')) if organization else []
    stats = _product_stats(organization, products) if organization else {}
    data = [_product_payload(p, stats.get(p.id)) for p in products]
    active = [d for d in data if d['is_active']]
    top = max(active, key=lambda d: Decimal(d['revenue']), default=None)
    context = {
        'products_data': data,
        'units': PRODUCT_UNITS,
        'categories': sorted({p.category for p in products if p.category}),
        'summary': {
            'active': len(active),
            'inactive': len(data) - len(active),
            'revenue': sum((Decimal(d['revenue']) for d in data), Decimal('0')),
            'top': top if top and Decimal(top['revenue']) > 0 else None,
            'unused': sum(1 for d in active if not d['invoices'] and not d['quotes']),
        },
        'page_title': 'Produits & prestations',
    }
    return render(request, 'invoices/products.html', context)


def _parse_product_form(request):
    """Champs communs création / modification. Retourne (dict, erreur)."""
    name = (request.POST.get('name') or '').strip()[:200]
    if not name:
        return None, 'Le nom est requis.'
    try:
        unit_price = Decimal((request.POST.get('unit_price') or '').replace(',', '.').replace(' ', ''))
        tax_rate = Decimal((request.POST.get('tax_rate') or '0').replace(',', '.'))
        cost_raw = (request.POST.get('cost_price') or '').replace(',', '.').replace(' ', '')
        cost_price = Decimal(cost_raw) if cost_raw else None
    except (InvalidOperation, ValueError):
        return None, 'Prix, coût ou taux de TVA invalide.'
    if unit_price < 0 or (cost_price is not None and cost_price < 0) or not (0 <= tax_rate <= 100):
        return None, 'Les montants doivent être positifs et la TVA entre 0 et 100 %.'
    kind = request.POST.get('kind') if request.POST.get('kind') in ('service', 'product') else 'service'
    return {
        'name': name,
        'description': (request.POST.get('description') or '').strip() or None,
        'unit_price': unit_price.quantize(Decimal('0.01')),
        'unit': (request.POST.get('unit') or 'unit').strip()[:50] or 'unit',
        'tax_rate': tax_rate,
        'kind': kind,
        'reference': (request.POST.get('reference') or '').strip()[:60],
        'category': (request.POST.get('category') or '').strip()[:80],
        'cost_price': cost_price.quantize(Decimal('0.01')) if cost_price is not None else None,
    }, None


@login_required
@require_POST
def product_quick_create(request):
    """Création depuis la page Produits ou depuis l'éditeur de facture."""
    fields, error = _parse_product_form(request)
    if error:
        return JsonResponse({'ok': False, 'error': error}, status=400)
    organization = _get_user_primary_organization(request.user)
    if not organization:
        return JsonResponse({'ok': False, 'error': 'Aucune organisation disponible.'}, status=400)
    product = Product.objects.create(organization=organization, is_active=True, **fields)
    payload = _product_payload(product)
    payload['ok'] = True
    return JsonResponse(payload)


@login_required
@require_POST
def product_quick_update(request, product_id):
    product = _get_product_for_user(request.user, product_id)
    fields, error = _parse_product_form(request)
    if error:
        return JsonResponse({'ok': False, 'error': error}, status=400)
    for key, value in fields.items():
        setattr(product, key, value)
    if 'is_active' in request.POST:
        product.is_active = request.POST.get('is_active') == 'true'
    product.save()
    return JsonResponse({'ok': True})


@login_required
@require_POST
def product_quick_toggle(request, product_id):
    """Toggle a product's active flag without touching other fields."""
    product = _get_product_for_user(request.user, product_id)
    product.is_active = request.POST.get('is_active', 'true') == 'true'
    product.save(update_fields=['is_active', 'updated_at'])
    return JsonResponse({'ok': True, 'is_active': product.is_active})


@login_required
@require_POST
def product_quick_delete(request, product_id):
    """Delete a product/service."""
    product = _get_product_for_user(request.user, product_id)
    product.delete()
    return JsonResponse({'ok': True})


def _export_request(request):
    """(organisation, début, fin) d'une demande d'export comptable, ou une redirection d'erreur."""
    from datetime import date

    from apps.accounts.views import list_editable_organizations_for_payment

    back = redirect(f"{reverse('accounts:user-settings')}?tab=facturation")
    organizations = {str(o.pk): o for o in list_editable_organizations_for_payment(request.user)}
    organization = organizations.get(request.GET.get('organization', ''))
    try:
        start = date.fromisoformat(request.GET.get('start', ''))
        end = date.fromisoformat(request.GET.get('end', ''))
    except ValueError:
        start = end = None
    if organization is None:
        messages.error(request, "Seuls le propriétaire et les administrateurs peuvent exporter la comptabilité.")
        return back
    if not start or not end or start > end or (end - start).days > 731:
        messages.error(request, 'Choisissez une période valide (24 mois au plus), par exemple votre exercice comptable.')
        return back
    return organization, start, end


@login_required
def accounting_export(request):
    """Export comptable universel (ZIP de CSV : factures, lignes, paiements), pour tous les pays."""
    from . import accounting_export as export

    result = _export_request(request)
    if not isinstance(result, tuple):
        return result
    organization, start, end = result
    response = HttpResponse(export.build(organization, start, end), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="billio-compta-{start:%Y%m%d}-{end:%Y%m%d}.zip"'
    return response


@login_required
def fec_export(request):
    """Fichier des écritures comptables (FEC) d'une organisation sur une période (apps/invoices/fec.py)."""
    from . import fec

    result = _export_request(request)
    if not isinstance(result, tuple):
        return result
    organization, start, end = result
    content, _count = fec.render(organization, start, end, request.GET.get('sales_account', '706000'))
    response = HttpResponse(content, content_type='text/plain; charset=iso-8859-15')
    response['Content-Disposition'] = f'attachment; filename="{fec.filename(organization, end)}"'
    return response
