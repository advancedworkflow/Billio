"""
Views for the Devis (Quote) module: editor, workflow actions, public link,
conversion to invoice, recurring quotes.
"""
import json
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from rest_framework import generics
from rest_framework.permissions import AllowAny

from apps.clients.models import Client
from apps.templates_app.models import InvoiceTemplate

from .models import Quote, QuoteItem, QuotePaymentMilestone, QuoteAttachment, Product
from .serializers import PublicQuoteSerializer
from .views import (
    billing_editor_data,
    format_eur,
    build_invoice_editor_templates_library,
    resolve_invoice_template_selection,
    _get_user_primary_organization,
)


def _parse_date(value):
    """Parse a 'YYYY-MM-DD' string (or falsy value) into a date object, or None."""
    if not value:
        return None
    return parse_date(value)


def _user_quotes_queryset(user):
    return Quote.objects.filter(
        Q(organization__owner=user) | Q(organization__members__user=user)
    ).distinct()


def _quote_organization_data(organization):
    return {
        'name': organization.name,
        'logo_url': organization.logo.url if organization.logo else '',
        'address': organization.address or '',
        'city': organization.city or '',
        'postal_code': organization.postal_code or '',
        'phone': organization.phone or '',
        'email': organization.email or '',
        'website': organization.website or '',
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


def build_quote_editor_bootstrap(quote, *, preselected_client_id='', page_title='Créer un devis'):
    """
    État initial pour l'éditeur devis (même technique anti-injection JS que
    build_invoice_editor_bootstrap : tout passe par json_script, jamais de texte
    brut interpolé dans le <script>).
    """
    if quote is not None:
        items = []
        for item in quote.items.all():
            items.append({
                'product_id': str(item.product_id) if item.product_id else '',
                'name': item.name or '',
                'description': item.description or '',
                'quantity': float(item.quantity or 0),
                'unit_price': float(item.unit_price or 0),
                'unit': item.unit or 'unit',
                'discount_percent': float(item.discount_percent or 0),
                'tax_rate': float(item.tax_rate or 0),
            })
        milestones = []
        for m in quote.payment_milestones.all():
            milestones.append({
                'id': m.id,
                'status': m.status,
                'label': m.label or '',
                'due_date': m.due_date.isoformat() if m.due_date else '',
                'percentage': float(m.percentage) if m.percentage is not None else None,
                'amount': float(m.amount or 0),
            })
        client_id_val = str(quote.client_id) if quote.client_id else ''
        pcid = (preselected_client_id or '').strip()
        if pcid:
            client_id_val = str(pcid)
        return {
            'page_title': page_title,
            'selected_template': str(quote.template_id) if getattr(quote, 'template_id', None) else '',
            'quote_data': {
                'client_id': client_id_val,
                'quote_number': quote.quote_number or 'AUTO-001',
                'title': quote.title or '',
                'description': quote.description or '',
                'project_reference': quote.project_reference or '',
                'project_name': quote.project_name or '',
                'project_location': quote.project_location or '',
                'project_start_date': quote.project_start_date.isoformat() if quote.project_start_date else '',
                'project_delivery_date': quote.project_delivery_date.isoformat() if quote.project_delivery_date else '',
                'issue_date': quote.issue_date.isoformat() if quote.issue_date else '',
                'expiry_date': quote.expiry_date.isoformat() if quote.expiry_date else '',
                'currency': quote.currency or 'EUR',
                'logo_asset_id': quote.logo_asset_id or '',
                'discount_amount': float(quote.discount_amount or 0),
                'notes': quote.notes or '',
                'payment_terms': quote.payment_terms or '',
                'delivery_terms': quote.delivery_terms or '',
                'terms_and_conditions': quote.terms_and_conditions or '',
                'footer': quote.footer or '',
                'is_recurring': bool(quote.is_recurring),
                'recurrence_interval': quote.recurrence_interval or 'monthly',
                'recurrence_count': quote.recurrence_count or 12,
                'recurrence_start_date': quote.recurrence_start_date.isoformat() if quote.recurrence_start_date else '',
                'items': items,
                'milestones': milestones,
                'status': quote.status,
                'converted_invoice_id': str(quote.converted_to_invoice_id) if quote.converted_to_invoice_id else '',
            },
        }
    return {
        'page_title': page_title,
        'selected_template': '',
        'quote_data': {
            'client_id': str(preselected_client_id or ''),
            'quote_number': 'AUTO-001',
            'title': 'Devis',
            'description': '',
            'project_reference': '',
            'project_name': '',
            'project_location': '',
            'project_start_date': '',
            'project_delivery_date': '',
            'issue_date': timezone.now().date().isoformat(),
            'expiry_date': (timezone.now().date() + timezone.timedelta(days=30)).isoformat(),
            'currency': 'EUR',
            'discount_amount': 0,
            'notes': '',
            'payment_terms': '',
            'delivery_terms': '',
            'terms_and_conditions': '',
            'footer': '',
            'is_recurring': False,
            'recurrence_interval': 'monthly',
            'recurrence_count': 12,
            'recurrence_start_date': '',
            'items': [],
            'milestones': [],
        },
    }


def _quote_editor_context(request, quote, *, page_title, preselected_client_id=''):
    organization = quote.organization if quote else _get_user_primary_organization(request.user)
    clients = Client.objects.filter(organization=organization) if organization else Client.objects.none()
    clients_data = list(clients.values(
        'id', 'name', 'email', 'address', 'phone', 'registration_number', 'tax_id', 'company_name'
    ))
    products_data = list(Product.objects.filter(
        organization=organization, is_active=True
    ).values('id', 'name', 'description', 'unit_price', 'unit', 'tax_rate', 'reference')) if organization else []

    from apps.organizations.currencies import editor_context
    bootstrap = build_quote_editor_bootstrap(quote, preselected_client_id=preselected_client_id, page_title=page_title)
    return {
        **editor_context(organization, bootstrap, new=quote is None),
        'quote': quote,
        'organization': organization,
        'templates_data_obj': build_invoice_editor_templates_library(organization) if organization else [],
        'clients': clients,
        'clients_data': clients_data,
        'products_data': products_data,
        'organization_data': _quote_organization_data(organization) if organization else {},
        'page_title': page_title,
        'preselected_client_id': preselected_client_id,
        # Même éditeur que la facture (templates/invoices/create.html), en mode « devis ».
        'editor_mode': 'quote',
        'invoice_editor_bootstrap': bootstrap,
    }


@login_required
def quote_list(request):
    """Page liste des devis."""
    quotes = _user_quotes_queryset(request.user).select_related('client', 'organization').order_by('-created_at')

    search = (request.GET.get('search') or '').strip()
    status = (request.GET.get('status') or '').strip()

    if search:
        quotes = quotes.filter(
            Q(quote_number__icontains=search) |
            Q(title__icontains=search) |
            Q(client__name__icontains=search)
        )
    if status:
        quotes = quotes.filter(status=status)

    context = {
        'quotes': quotes,
        'search': search,
        'status': status,
        'page_title': 'Devis',
    }
    return render(request, 'invoices/quote_list.html', context)


@login_required
def quote_create(request):
    """Page de création d'un nouveau devis (assistant 4 étapes)."""
    preselected_client_id = request.GET.get('client', '')
    context = _quote_editor_context(
        request, None, page_title='Créer un devis', preselected_client_id=preselected_client_id,
    )
    return render(request, 'invoices/create.html', context)


@login_required
def quote_edit(request, quote_id):
    """Page d'édition d'un devis existant (même assistant 4 étapes)."""
    quote = get_object_or_404(_user_quotes_queryset(request.user), id=quote_id)
    preselected_client_id = (request.GET.get('client') or '').strip()
    context = _quote_editor_context(
        request, quote,
        page_title=f'Éditer le devis #{quote.quote_number}',
        preselected_client_id=preselected_client_id,
    )
    return render(request, 'invoices/create.html', context)


@login_required
def save_quote(request, quote_id=None):
    """Sauvegarder un devis (création ou mise à jour) avec calcul réel par taux de TVA ligne à ligne."""
    organization = _get_user_primary_organization(request.user)
    if not organization:
        return JsonResponse({'error': 'Aucune organisation trouvée'}, status=400)

    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)

    try:
        data = request.POST
        items_data = json.loads(data.get('items', '[]'))
        milestones_data = json.loads(data.get('milestones', '[]'))

        if quote_id:
            quote = get_object_or_404(Quote, id=quote_id, organization=organization)
        else:
            quote = Quote(organization=organization, created_by=request.user)

        raw_client_id = (data.get('client_id') or data.get('client') or '').strip()
        if not raw_client_id:
            return JsonResponse({'error': 'Veuillez sélectionner un client.'}, status=400)
        client = Client.objects.filter(id=raw_client_id, organization=organization).first()
        if not client:
            return JsonResponse({'error': 'Client introuvable pour votre organisation.'}, status=400)
        quote.client = client

        quote.title = data.get('title') or 'Devis'
        quote.description = data.get('description', '')
        quote.project_reference = data.get('project_reference', '')
        quote.project_name = data.get('project_name', '')
        quote.project_location = data.get('project_location', '')
        quote.project_start_date = _parse_date(data.get('project_start_date'))
        quote.project_delivery_date = _parse_date(data.get('project_delivery_date'))
        quote.issue_date = _parse_date(data.get('issue_date')) or timezone.now().date()
        quote.expiry_date = _parse_date(data.get('expiry_date')) or (timezone.now().date() + timezone.timedelta(days=30))
        quote.currency = data.get('currency') or 'EUR'
        quote.notes = data.get('notes', '')
        quote.payment_terms = data.get('payment_terms', '')
        quote.delivery_terms = data.get('delivery_terms', '')
        quote.terms_and_conditions = data.get('terms_and_conditions', '')
        quote.footer = data.get('footer', '')
        from .views import apply_document_logo
        apply_document_logo(quote, quote.organization, data.get('logo_asset_id'))

        try:
            quote.discount_amount = Decimal(str(data.get('discount_amount') or '0'))
        except InvalidOperation:
            quote.discount_amount = Decimal('0')

        quote.is_recurring = str(data.get('is_recurring', '')).lower() in ('1', 'true', 'on')
        quote.recurrence_interval = data.get('recurrence_interval') or ''
        recurrence_count_raw = data.get('recurrence_count')
        quote.recurrence_count = int(recurrence_count_raw) if recurrence_count_raw else None
        quote.recurrence_start_date = _parse_date(data.get('recurrence_start_date'))

        if not quote.quote_number:
            quote.quote_number = quote._generate_quote_number()

        template_ref = data.get('template')
        if template_ref:
            template = resolve_invoice_template_selection(organization, template_ref)
            if template:
                quote.template = template

        quote.save()

        # Lignes de prestations : suppression + recréation, calcul TVA réel par ligne
        quote.items.all().delete()
        subtotal = Decimal('0')
        tax_amount = Decimal('0')
        for idx, item_data in enumerate(items_data):
            qty = Decimal(str(item_data.get('quantity') or 0))
            price = Decimal(str(item_data.get('unit_price') or 0))
            discount = Decimal(str(item_data.get('discount_percent') or 0))
            rate = Decimal(str(item_data.get('tax_rate') or 0))
            line_gross = qty * price
            line_ht = line_gross - (line_gross * discount / Decimal('100'))
            QuoteItem.objects.create(
                quote=quote,
                product_id=item_data.get('product_id') or None,
                name=item_data.get('name', ''),
                description=item_data.get('description', ''),
                quantity=qty,
                unit_price=price,
                unit=item_data.get('unit', 'unit'),
                discount_percent=discount,
                tax_rate=rate,
                order=idx,
            )
            subtotal += line_ht
            tax_amount += line_ht * rate / Decimal('100')

        quote.subtotal = subtotal
        quote.tax_amount = tax_amount
        quote.total_amount = subtotal + tax_amount - quote.discount_amount

        # Échéancier de paiement : suppression + recréation
        quote.payment_milestones.filter(status='pending').delete()
        for idx, m in enumerate(milestones_data):
            if not (m.get('label') or m.get('amount')):
                continue
            try:
                amount = Decimal(str(m.get('amount') or 0))
            except InvalidOperation:
                amount = Decimal('0')
            percentage_raw = m.get('percentage')
            QuotePaymentMilestone.objects.create(
                quote=quote,
                label=m.get('label') or f"Échéance {idx + 1}",
                due_date=m.get('due_date') or None,
                percentage=Decimal(str(percentage_raw)) if percentage_raw not in (None, '') else None,
                amount=amount,
                order=idx,
            )

        quote.save()

        if quote.is_recurring:
            quote.generate_recurrence_milestones()

        return JsonResponse({
            'success': True,
            'quote_id': str(quote.id),
            'message': 'Devis sauvegardé avec succès',
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
def quote_preview(request, quote_id):
    """Prévisualisation HTML d'un devis."""
    quote = get_object_or_404(_user_quotes_queryset(request.user), id=quote_id)

    try:
        html_content = quote.render_html()
        css_content = quote.render_css()
    except Exception as e:
        html_content = f"<div class='error'>Erreur lors de la génération: {str(e)}</div>"
        css_content = "body { color: red; }"

    situations = list(quote.situations.exclude(status='cancelled').order_by('situation_number'))
    context = {
        'quote': quote,
        'html_content': html_content,
        'css_content': css_content,
        'page_title': f'Prévisualisation devis #{quote.quote_number}',
        'situations': situations,
        'situation_progress': situations[-1].situation_progress if situations else 0,
    }
    return render(request, 'invoices/quote_preview.html', context)


@require_POST
@login_required
def quote_situation_create(request, quote_id):
    """Facture de situation (avancement cumulé + retenue de garantie) depuis un devis accepté."""
    from decimal import Decimal, InvalidOperation
    from django.contrib import messages
    quote = get_object_or_404(_user_quotes_queryset(request.user), id=quote_id)
    try:
        progress = Decimal((request.POST.get('progress') or '').replace(',', '.'))
        retention = Decimal((request.POST.get('retention_rate') or '0').replace(',', '.'))
    except InvalidOperation:
        messages.error(request, 'Avancement ou retenue invalide.')
        return redirect('invoices:quote-preview', quote_id=quote.id)
    if not (0 <= retention <= 10):
        messages.error(request, 'La retenue de garantie est limitée à 5 % (10 % au plus).')
        return redirect('invoices:quote-preview', quote_id=quote.id)
    try:
        invoice = quote.create_situation_invoice(progress, retention_rate=retention, user=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('invoices:quote-preview', quote_id=quote.id)
    messages.success(request, f"Situation n° {invoice.situation_number} créée en brouillon : vérifiez-la puis envoyez-la.")
    return redirect('invoices:invoice-preview', invoice_id=invoice.id)


@require_POST
@login_required
def quote_toggle_favorite(request, quote_id):
    """Bascule le statut favori d'un devis."""
    quote = get_object_or_404(_user_quotes_queryset(request.user), id=quote_id)
    quote.is_favorite = not quote.is_favorite
    quote.save(update_fields=['is_favorite', 'updated_at'])
    return JsonResponse({'success': True, 'is_favorite': quote.is_favorite})


@require_POST
@login_required
def duplicate_quote(request, quote_id):
    """Duplique un devis (nouveau brouillon, sans milestones/pièces jointes/signature)."""
    try:
        original = get_object_or_404(_user_quotes_queryset(request.user), id=quote_id)

        duplicate = Quote.objects.create(
            organization=original.organization,
            client=original.client,
            template=original.template,
            title=f"Copie de {original.title}",
            description=original.description,
            project_reference=original.project_reference,
            project_name=original.project_name,
            project_location=original.project_location,
            project_start_date=original.project_start_date,
            project_delivery_date=original.project_delivery_date,
            issue_date=timezone.now().date(),
            expiry_date=timezone.now().date() + timezone.timedelta(days=30),
            subtotal=original.subtotal,
            tax_amount=original.tax_amount,
            discount_amount=original.discount_amount,
            total_amount=original.total_amount,
            currency=original.currency,
            status='draft',
            notes=original.notes,
            payment_terms=original.payment_terms,
            delivery_terms=original.delivery_terms,
            terms_and_conditions=original.terms_and_conditions,
            footer=original.footer,
            created_by=request.user,
        )
        for item in original.items.all():
            QuoteItem.objects.create(
                quote=duplicate,
                product=item.product,
                name=item.name,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                unit=item.unit,
                discount_percent=item.discount_percent,
                tax_rate=item.tax_rate,
                order=item.order,
            )

        return JsonResponse({'success': True, 'quote_id': str(duplicate.id), 'message': 'Devis dupliqué avec succès'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)


@require_POST
@login_required
def quote_attachment_upload(request, quote_id):
    """Upload d'une pièce jointe sur un devis (POST multipart séparé)."""
    quote = get_object_or_404(_user_quotes_queryset(request.user), id=quote_id)
    uploaded = request.FILES.get('file')
    if not uploaded:
        return JsonResponse({'success': False, 'message': 'Aucun fichier fourni.'}, status=400)

    from apps.subscriptions.entitlements import forget_storage, require_quota
    require_quota(quote.organization, 'storage_mb', adding=uploaded.size)
    forget_storage(quote.organization)
    attachment = QuoteAttachment.objects.create(
        quote=quote,
        file=uploaded,
        name=request.POST.get('name') or uploaded.name,
        uploaded_by=request.user,
    )
    return JsonResponse({
        'success': True,
        'attachment': {
            'id': attachment.id,
            'name': attachment.name,
            'url': attachment.file.url,
        },
    })


@require_POST
@login_required
def send_quote(request, quote_id):
    """Envoie le devis au client (statut doit être 'draft')."""
    quote = get_object_or_404(_user_quotes_queryset(request.user), id=quote_id)

    if quote.status != 'draft':
        return JsonResponse({
            'success': False,
            'message': f'Impossible d\'envoyer un devis avec le statut "{quote.get_status_display()}"',
        }, status=400)

    from apps.accounts.email_verification import client_email_blocked
    blocked = client_email_blocked(quote.organization) if quote.client_id and quote.client.email else ''
    if blocked:
        return JsonResponse({'success': False, 'message': blocked}, status=400)

    success, message = quote.send_to_client()
    if success:
        return JsonResponse({'success': True, 'message': message})
    return JsonResponse({'success': False, 'message': message}, status=400)


@require_POST
@login_required
def quote_mark_accepted(request, quote_id):
    """Acceptation manuelle interne (ex : le client a répondu par téléphone)."""
    quote = get_object_or_404(_user_quotes_queryset(request.user), id=quote_id)
    quote.mark_as_accepted(name=request.user.get_full_name() or request.user.email)
    return JsonResponse({'success': True, 'message': 'Devis marqué comme accepté'})


@require_POST
@login_required
def quote_mark_rejected(request, quote_id):
    """Refus manuel interne."""
    quote = get_object_or_404(_user_quotes_queryset(request.user), id=quote_id)
    quote.mark_as_rejected(reason=request.POST.get('reason', ''))
    return JsonResponse({'success': True, 'message': 'Devis marqué comme refusé'})


# ---------------------------------------------------------------------------
# Lien public du devis (pas d'authentification requise, l'UUID sert de jeton)
# ---------------------------------------------------------------------------

def public_quote_view(request, quote_id):
    """Page publique de consultation d'un devis, partagée avec le client."""
    quote = get_object_or_404(Quote, id=quote_id)

    if quote.status == 'draft':
        return HttpResponse("Devis non envoyé.", status=400)

    if quote.status == 'sent':
        quote.mark_as_viewed()
        from apps.dashboard.automation_engine import run_automations
        run_automations(
            quote.organization, 'quote_viewed',
            target_type='quote', target_id=quote.id,
            amount=quote.total_amount, client_id=quote.client_id,
            variables={'numero': quote.quote_number},
            context_label=f"Devis {quote.quote_number} consulté par le client.",
        )
        client_label = quote.client.name if quote.client_id else "Un client"
        quote._notify(
            'quote_viewed',
            f"Devis {quote.quote_number} consulté",
            f"{client_label} a consulté le devis.",
            priority='low',
        )

    from apps.subscriptions.entitlements import has_feature
    context = {
        'quote': quote,
        'page_title': f'Devis {quote.quote_number}',
        # Free : acceptation en ligne par nom et email ; signature manuscrite à partir du forfait Starter.
        'online_signature': has_feature(quote.organization, 'quote_signature'),
    }
    return render(request, 'invoices/public_quote.html', context)


@require_POST
def public_quote_accept(request, quote_id):
    """Action publique : le client accepte le devis (avec signature optionnelle)."""
    quote = get_object_or_404(Quote, id=quote_id)
    if quote.status in ('accepted', 'rejected'):
        return redirect('invoices:public-quote-confirmation', quote_id=quote.id)

    from apps.subscriptions.entitlements import has_feature
    signature = request.POST.get('signature_data', '') if has_feature(quote.organization, 'quote_signature') else ''
    quote.mark_as_accepted(
        name=request.POST.get('name', ''),
        email=request.POST.get('email', ''),
        signature_data=signature,
        ip=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
    )
    return redirect('invoices:public-quote-confirmation', quote_id=quote.id)


@require_POST
def public_quote_reject(request, quote_id):
    """Action publique : le client refuse le devis (avec motif optionnel)."""
    quote = get_object_or_404(Quote, id=quote_id)
    if quote.status in ('accepted', 'rejected'):
        return redirect('invoices:public-quote-confirmation', quote_id=quote.id)

    quote.mark_as_rejected(reason=request.POST.get('reason', ''))
    return redirect('invoices:public-quote-confirmation', quote_id=quote.id)


def public_quote_confirmation(request, quote_id):
    """Page de confirmation après acceptation/refus."""
    quote = get_object_or_404(Quote, id=quote_id)
    if quote.status not in ('accepted', 'rejected'):
        return redirect('invoices:public-quote-view', quote_id=quote.id)

    context = {'quote': quote, 'page_title': f'Devis {quote.quote_number}'}
    return render(request, 'invoices/public_quote_confirmation.html', context)


class PublicQuoteView(generics.RetrieveAPIView):
    """Public API view for quotes (no authentication required)."""
    serializer_class = PublicQuoteSerializer
    permission_classes = [AllowAny]

    def get_object(self):
        return get_object_or_404(Quote, id=self.kwargs['quote_id'])


@require_POST
@login_required
def convert_quote_to_invoice(request, quote_id):
    """Convertit un devis accepté en facture, sans ressaisie."""
    quote = get_object_or_404(_user_quotes_queryset(request.user), id=quote_id)

    if quote.status != 'accepted':
        return JsonResponse({
            'success': False,
            'message': 'Seul un devis accepté peut être converti en facture.',
        }, status=400)

    if quote.converted_to_invoice_id:
        return JsonResponse({
            'success': False,
            'message': 'Ce devis a déjà été converti en facture.',
        }, status=400)

    invoice = quote.convert_to_invoice(user=request.user)
    return JsonResponse({
        'success': True,
        'invoice_id': str(invoice.id),
        'redirect': reverse('invoices:invoice-edit', args=[invoice.id]),
    })


@require_POST
@login_required
def quote_convert_to_subscription(request, quote_id):
    """Transforme un devis en devis récurrent et génère ses échéances."""
    quote = get_object_or_404(_user_quotes_queryset(request.user), id=quote_id)

    quote.is_recurring = True
    quote.recurrence_interval = request.POST.get('recurrence_interval', 'monthly')
    try:
        quote.recurrence_count = int(request.POST.get('recurrence_count', 12))
    except (TypeError, ValueError):
        quote.recurrence_count = 12
    quote.recurrence_start_date = _parse_date(request.POST.get('recurrence_start_date')) or quote.issue_date
    quote.save(update_fields=[
        'is_recurring', 'recurrence_interval', 'recurrence_count', 'recurrence_start_date', 'updated_at',
    ])
    milestones = quote.generate_recurrence_milestones()
    return JsonResponse({'success': True, 'milestones_created': len(milestones)})


@require_POST
@login_required
def generate_milestone_invoice(request, quote_id, milestone_id):
    """Génère une facture brouillon à partir d'une échéance en attente."""
    quote = get_object_or_404(_user_quotes_queryset(request.user), id=quote_id)
    milestone = get_object_or_404(
        QuotePaymentMilestone, id=milestone_id, quote=quote, status='pending'
    )
    invoice = quote.generate_invoice_for_milestone(milestone, request.user)
    return JsonResponse({
        'success': True,
        'invoice_id': str(invoice.id),
        'redirect': reverse('invoices:invoice-edit', args=[invoice.id]),
    })
