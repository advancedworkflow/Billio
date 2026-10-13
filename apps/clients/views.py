"""
Views for clients app.
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from apps.organizations.models import Organization
from .models import Client, ClientContact
from .serializers import ClientSerializer, ClientContactSerializer


@login_required
def client_list(request):
    """List all clients for the user."""
    from django.db.models import Q
    clients = Client.objects.filter(
        Q(organization__owner=request.user) |
        Q(organization__members__user=request.user)
    ).distinct().order_by('-created_at')

    clients_data = [
        {
            'id': str(c.id),
            'name': c.name,
            'email': c.email or '',
            'phone': c.phone or '',
            'is_active': c.is_active,
            'created_at': c.created_at.isoformat(),
        }
        for c in clients
    ]

    context = {
        'clients': clients,
        'clients_data': clients_data,
        'page_title': 'Clients',
    }
    return render(request, 'clients/list.html', context)


@login_required
def client_detail(request, client_id):
    """
    Fiche client : coordonnées, chiffres clés, projets, devis, factures, documents,
    réponses aux formulaires, fichiers échangés et historique, au même endroit.
    """
    from decimal import Decimal
    from django.db.models import Q as _Q, Sum
    from django.db.models.functions import Coalesce
    from django.urls import reverse
    from django.utils import timezone
    from apps.dashboard.models import ClientForm, DeliverableFile, Project, ProjectFile
    from apps.documents.models import DocumentResponse
    from apps.invoices.models import Invoice, Quote
    from apps.payments.models import Payment

    client = _get_client_for_user(request.user, client_id)
    zero = Decimal('0.00')
    today = timezone.localdate()

    invoices = list(
        Invoice.objects.filter(client=client).exclude(status='cancelled')
        .annotate(paid_sum=Coalesce(Sum('payments__amount', filter=_Q(payments__status='completed')), zero))
        .order_by('-issue_date', '-created_at')
    )
    for inv in invoices:
        inv.remaining = zero if inv.status == 'paid' else inv.amount_due(inv.paid_sum)
        inv.is_late = inv.status in ('sent', 'viewed', 'overdue') and inv.due_date and inv.due_date < today
    quotes = list(Quote.objects.filter(client=client).order_by('-created_at'))
    projects = list(Project.objects.filter(client=client).order_by('-created_at'))
    documents = list(client.documents.order_by('-created_at'))
    responses = list(DocumentResponse.objects.filter(client=client).select_related('document').order_by('-updated_at'))
    forms = list(ClientForm.objects.filter(client=client).order_by('-created_at'))
    project_files = list(ProjectFile.objects.filter(project__client=client).select_related('project').order_by('-uploaded_at'))
    deliverable_files = list(
        DeliverableFile.objects.filter(deliverable__project__client=client)
        .select_related('deliverable__project').order_by('-id')
    )
    payments = list(
        Payment.objects.filter(invoice__client=client, status='completed').select_related('invoice').order_by('-created_at')[:20]
    )

    sales = [i for i in invoices if i.invoice_type == 'sale' and i.status != 'draft']
    invoiced = sum((i.total_amount for i in sales), zero)
    due = sum((i.remaining for i in sales), zero)
    open_quotes = [q for q in quotes if q.status in ('sent', 'viewed')]
    stats = {
        'invoiced': invoiced,
        'collected': invoiced - due,
        'due': due,
        'late_count': sum(1 for i in sales if i.is_late),
        'open_quotes_total': sum((q.total_amount for q in open_quotes), zero),
        'open_quotes_count': len(open_quotes),
        'accepted_quotes': sum(1 for q in quotes if q.status == 'accepted'),
        'active_projects': sum(1 for p in projects if p.status != 'completed'),
    }

    # Fichiers échangés : fichiers de projet (dont ceux déposés par le client) et fichiers de livrables.
    assets = [
        {'name': f.name or f.file.name.rsplit('/', 1)[-1], 'url': f.file.url, 'source': f"Projet « {f.project.name} »",
         'by_client': f.uploaded_by_client, 'date': f.uploaded_at}
        for f in project_files if f.file
    ] + [
        {'name': f.name or f.file.name.rsplit('/', 1)[-1], 'url': f.file.url,
         'source': f"Livrable « {f.deliverable.title} »", 'by_client': False, 'date': getattr(f, 'uploaded_at', None)}
        for f in deliverable_files if f.file
    ]

    # Historique : derniers événements, du plus récent au plus ancien.
    from apps.templates_app.templatetags.billio_format import money
    quote_labels = {'draft': 'brouillon', 'sent': 'envoyé', 'viewed': 'consulté', 'accepted': 'accepté', 'rejected': 'refusé', 'expired': 'expiré'}
    invoice_labels = {'draft': 'brouillon', 'sent': 'envoyée', 'viewed': 'consultée', 'paid': 'payée', 'overdue': 'en retard', 'cancelled': 'annulée'}
    for q in quotes:
        q.status_fr = quote_labels.get(q.status, q.status).capitalize()
    for i in invoices:
        i.status_fr = invoice_labels.get(i.status, i.status).capitalize()
    events = []
    for q in quotes:
        events.append((q.created_at, 'file-pen-line', f"Devis {q.quote_number} — {quote_labels.get(q.status, q.status)}", reverse('invoices:quote-preview', args=[q.id])))
    for i in invoices:
        events.append((i.created_at, 'receipt', f"Facture {i.invoice_number} — {invoice_labels.get(i.status, i.status)}", reverse('invoices:invoice-preview', args=[i.id])))
    for p in payments:
        events.append((p.created_at, 'banknote', f"Paiement reçu : {money(p.amount)} ({p.invoice.invoice_number})", reverse('invoices:invoice-preview', args=[p.invoice_id])))
    for d in documents:
        events.append((d.created_at, 'file-text', f"Document « {d.title} » créé", reverse('documents:document-editor', args=[d.id])))
    for r in responses:
        events.append((r.updated_at, 'clipboard-check', f"A répondu au formulaire « {r.document.title} »", f"#reponse-{r.id}"))
    for f in forms:
        if f.submitted_at:
            events.append((f.submitted_at, 'clipboard-check', f"A rempli « {f.title} »", f"#form-{f.id}"))
    for p in projects:
        events.append((p.created_at, 'folder-kanban', f"Projet « {p.name} » démarré", reverse('dashboard:project-detail', args=[p.id])))
    events.sort(key=lambda e: e[0], reverse=True)

    address = ', '.join(x for x in (client.address, client.postal_code, client.city, client.country) if x)
    tab = request.GET.get('tab') or 'apercu'
    return render(request, 'clients/detail.html', {
        'client': client,
        'address': address,
        'contacts': list(client.contacts.all()) if hasattr(client, 'contacts') else [],
        'stats': stats,
        'invoices': invoices,
        'quotes': quotes,
        'projects': projects,
        'documents': documents,
        'responses': responses,
        'forms': forms,
        'assets': assets,
        'events': [{'date': d, 'icon': icon, 'text': text, 'url': url} for d, icon, text, url in events[:14]],
        'tab': tab if tab in ('apercu', 'projets', 'devis', 'factures', 'documents', 'fichiers') else 'apercu',
        'page_title': client.name,
    })


class ClientViewSet(viewsets.ModelViewSet):
    """ViewSet for Client model."""
    queryset = Client.objects.all()  # Required for DRF router basename detection
    serializer_class = ClientSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter clients based on user's organizations."""
        from django.db.models import Q
        return Client.objects.filter(
            Q(organization__owner=self.request.user) |
            Q(organization__members__user=self.request.user)
        ).distinct()

    def perform_create(self, serializer):
        """Set organization based on user's organizations."""
        # For now, use the first organization the user belongs to
        organization = self.request.user.owned_organizations.first()
        if not organization:
            organization = self.request.user.organization_memberships.first().organization
        serializer.save(organization=organization)


class ClientContactViewSet(viewsets.ModelViewSet):
    """ViewSet for ClientContact model."""
    queryset = ClientContact.objects.all()  # Required for DRF router basename detection
    serializer_class = ClientContactSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter contacts based on user's organizations."""
        from django.db.models import Q
        return ClientContact.objects.filter(
            Q(client__organization__owner=self.request.user) |
            Q(client__organization__members__user=self.request.user)
        ).distinct()


def _get_user_primary_organization(user):
    organization = user.owned_organizations.first()
    if organization:
        return organization
    membership = user.organization_memberships.select_related('organization').first()
    return membership.organization if membership else None


def _resolve_organization_for_client_create(user, organization_id=None):
    """
    Organisme cible pour création rapide : id explicite si l’utilisateur y a accès,
    sinon première organisation possédée / membre.
    """
    oid = (organization_id or '').strip()
    if oid:
        org = Organization.objects.filter(
            Q(id=oid) & (Q(owner=user) | Q(members__user=user))
        ).distinct().first()
        if org:
            return org
    return _get_user_primary_organization(user)


def _get_client_for_user(user, client_id):
    from django.db.models import Q
    return get_object_or_404(
        Client.objects.filter(
            Q(organization__owner=user) | Q(organization__members__user=user)
        ).distinct(),
        id=client_id
    )


@login_required
@require_POST
def client_quick_create(request):
    """Create a new client from modal popup."""
    name = (request.POST.get('name') or '').strip()
    email = (request.POST.get('email') or '').strip()
    phone = (request.POST.get('phone') or '').strip()

    if not name or not email:
        return JsonResponse({'ok': False, 'error': 'Nom et email requis.'}, status=400)

    organization = _resolve_organization_for_client_create(
        request.user,
        organization_id=request.POST.get('organization_id'),
    )
    if not organization:
        return JsonResponse({'ok': False, 'error': 'Aucune organisation disponible.'}, status=400)

    try:
        client = Client.objects.create(
            organization=organization,
            name=name,
            email=email,
            phone=phone or None,
            is_active=True,
        )
    except IntegrityError:
        return JsonResponse({'ok': False, 'error': 'Un client avec cet email existe déjà.'}, status=409)

    from apps.dashboard.automation_engine import run_automations
    run_automations(
        organization, 'client_created',
        target_type='client', target_id=client.id, client_id=client.id,
        context_label=f"Nouveau client : {client.name}.",
    )

    return JsonResponse({
        'ok': True,
        'id': str(client.id),
        'name': client.name,
        'email': client.email,
        'phone': client.phone or '',
        'is_active': client.is_active,
    })


@login_required
def client_quick_detail(request, client_id):
    """Return client details for context menu actions."""
    client = _get_client_for_user(request.user, client_id)
    return JsonResponse({
        'ok': True,
        'id': str(client.id),
        'name': client.name,
        'email': client.email,
        'phone': client.phone or '',
        'address': client.address or '',
        'company_name': client.company_name or '',
        'registration_number': client.registration_number or '',
        'tax_id': client.tax_id or '',
        'postal_code': client.postal_code or '',
        'city': client.city or '',
        'country': client.country or '',
        'notes': client.notes or '',
        'is_active': client.is_active,
        'created_at': client.created_at.strftime('%d/%m/%Y'),
    })


@login_required
@require_POST
def client_quick_update(request, client_id):
    """Update key client fields from edit modal."""
    client = _get_client_for_user(request.user, client_id)

    name = (request.POST.get('name') or '').strip()
    email = (request.POST.get('email') or '').strip()
    phone = (request.POST.get('phone') or '').strip()
    address = (request.POST.get('address') or '').strip()
    notes = (request.POST.get('notes') or '').strip()
    is_active = request.POST.get('is_active', 'true') == 'true'

    if not name or not email:
        return JsonResponse({'ok': False, 'error': 'Nom et email requis.'}, status=400)

    client.name = name
    client.email = email
    client.phone = phone or None
    client.address = address or None
    client.notes = notes or None
    client.is_active = is_active
    # Identité légale : nécessaire aux factures électroniques B2B (SIREN, TVA, adresse complète).
    limits = {'company_name': 200, 'registration_number': 50, 'tax_id': 50, 'postal_code': 20, 'city': 100, 'country': 100}
    for field, limit in limits.items():
        if field in request.POST:
            setattr(client, field, (request.POST.get(field) or '').strip()[:limit] or None)

    try:
        client.save()
    except IntegrityError:
        return JsonResponse({'ok': False, 'error': 'Un client avec cet email existe déjà.'}, status=409)

    return JsonResponse({'ok': True})
