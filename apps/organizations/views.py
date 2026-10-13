"""
Views for organizations app.
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from rest_framework import viewsets, generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.contrib.auth import login as auth_login
from django.contrib import messages
from django.urls import reverse
from django.views.decorators.http import require_POST
from .models import Organization, OrganizationMember, OrganizationInvite
from .serializers import OrganizationSerializer, OrganizationMemberSerializer


class OrganizationViewSet(viewsets.ModelViewSet):
    """ViewSet for Organization model."""
    queryset = Organization.objects.all()  # Required for DRF router basename detection
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter organizations based on user membership."""
        return Organization.objects.filter(
            members__user=self.request.user
        ).distinct()

    def perform_create(self, serializer):
        """Create organization and add creator as owner."""
        organization = serializer.save(owner=self.request.user)
        # Add creator as owner member
        OrganizationMember.objects.create(
            organization=organization,
            user=self.request.user,
            role='owner'
        )

    @action(detail=True, methods=['post'])
    def invite_member(self, request, pk=None):
        """Invite a new member to the organization."""
        organization = self.get_object()
        # Implementation for member invitation
        return Response({'message': 'Member invitation not implemented yet'})

    @action(detail=True, methods=['get'])
    def members(self, request, pk=None):
        """Get organization members."""
        organization = self.get_object()
        members = organization.members.all()
        serializer = OrganizationMemberSerializer(members, many=True)
        return Response(serializer.data)


class OrganizationMemberViewSet(viewsets.ModelViewSet):
    """ViewSet for OrganizationMember model."""
    queryset = OrganizationMember.objects.all()  # Required for DRF router basename detection
    serializer_class = OrganizationMemberSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter members based on user's organizations."""
        from django.db.models import Q
        return OrganizationMember.objects.filter(
            Q(organization__owner=self.request.user) |
            Q(organization__members__user=self.request.user)
        ).distinct()


@login_required
def organization_list(request):
    """List all organizations for the user."""
    organizations = Organization.objects.filter(
        members__user=request.user
    ).distinct().order_by('-created_at')

    context = {
        'organizations': organizations,
        'page_title': 'Organisations',
    }
    return render(request, 'organizations/list.html', context)


@login_required
def organization_create(request):
    """Create a new organization (simple HTML form)."""
    if request.method == "POST" and Organization.objects.filter(owner=request.user).exists():
        from apps.subscriptions.entitlements import require_feature
        require_feature(Organization.objects.filter(owner=request.user).first(), 'multi_org')
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        org_type = request.POST.get("type", "freelancer").strip() or "freelancer"
        email = request.POST.get("email", "").strip() or None
        phone = request.POST.get("phone", "").strip() or None
        website = request.POST.get("website", "").strip() or None
        address = request.POST.get("address", "").strip() or None
        city = request.POST.get("city", "").strip() or None
        postal_code = request.POST.get("postal_code", "").strip() or None
        country = request.POST.get("country", "").strip() or None
        tax_id = request.POST.get("tax_id", "").strip() or None
        registration_number = request.POST.get("registration_number", "").strip() or None

        if not name:
            # Minimal validation: go back to list (no extra message system yet).
            return redirect("organizations:organization-list")

        organization = Organization.objects.create(
            owner=request.user,
            name=name,
            type=org_type,
            email=email,
            phone=phone,
            website=website,
            address=address,
            city=city,
            postal_code=postal_code,
            country=country,
            tax_id=tax_id,
            registration_number=registration_number,
        )

        OrganizationMember.objects.create(
            organization=organization,
            user=request.user,
            role="owner",
            **OrganizationMember.ROLE_PERMISSIONS["owner"],
        )
        from .trade_packs import TRADE_PACKS, apply_trade_pack
        trade = request.POST.get("trade")
        if trade in TRADE_PACKS:
            apply_trade_pack(organization, trade, user=request.user)

        return redirect("organizations:organization-list")

    from .trade_packs import TRADE_CHOICES
    context = {
        "page_title": "Créer une organisation",
        "trade_choices": TRADE_CHOICES,
    }
    return render(request, "organizations/create.html", context)


def _get_user_primary_organization(user):
    organization = user.owned_organizations.first()
    if organization:
        return organization
    membership = user.organization_memberships.select_related('organization').first()
    return membership.organization if membership else None


def _can_manage_team(user, organization):
    """Propriétaire, ou membre admin / avec le droit « gérer l'équipe »."""
    if not organization:
        return False
    if organization.owner_id == user.id:
        return True
    return OrganizationMember.objects.filter(
        organization=organization, user=user, role__in=('owner', 'admin'),
    ).exists() or OrganizationMember.objects.filter(
        organization=organization, user=user, can_manage_members=True,
    ).exists()


def _team_redirect():
    return redirect(f"{reverse('accounts:user-settings')}?tab=equipe")


@login_required
@require_POST
def member_update(request, member_id):
    """Change le rôle d'un membre et/ou ses droits individuels."""
    organization = _get_user_primary_organization(request.user)
    if not _can_manage_team(request.user, organization):
        messages.error(request, "Vous n'avez pas le droit de gérer l'équipe.")
        return _team_redirect()
    member = get_object_or_404(OrganizationMember.objects.select_related('user'), id=member_id, organization=organization)
    if member.role == 'owner' or member.user_id == organization.owner_id:
        messages.error(request, "Le rôle du propriétaire ne peut pas être modifié.")
        return _team_redirect()

    name = member.user.get_full_name() or member.user.email
    role = request.POST.get('role')
    if role:
        if role not in ('admin', 'member', 'viewer'):
            messages.error(request, "Rôle invalide.")
            return _team_redirect()
        if member.user_id == request.user.id and role != member.role:
            messages.error(request, "Vous ne pouvez pas modifier votre propre rôle.")
            return _team_redirect()
        member.apply_role(role)
        messages.success(request, f"{name} est maintenant « {member.get_role_display()} ».")
    else:
        for field in OrganizationMember.PERMISSION_FIELDS:
            setattr(member, field, request.POST.get(field) == 'on')
        messages.success(request, f"Droits de {name} enregistrés.")
    member.save(update_fields=['role', *OrganizationMember.PERMISSION_FIELDS])
    return _team_redirect()


@login_required
@require_POST
def member_remove(request, member_id):
    """Retire un membre de l'organisation (son compte n'est pas supprimé)."""
    organization = _get_user_primary_organization(request.user)
    if not _can_manage_team(request.user, organization):
        messages.error(request, "Vous n'avez pas le droit de gérer l'équipe.")
        return _team_redirect()
    member = get_object_or_404(OrganizationMember.objects.select_related('user'), id=member_id, organization=organization)
    if member.role == 'owner' or member.user_id == organization.owner_id:
        messages.error(request, "Le propriétaire ne peut pas être retiré de l'organisation.")
    elif member.user_id == request.user.id:
        messages.error(request, "Vous ne pouvez pas vous retirer vous-même.")
    else:
        name = member.user.get_full_name() or member.user.email
        member.delete()
        messages.success(request, f"{name} a été retiré(e) de l'équipe.")
    return _team_redirect()


@login_required
def automation_settings(request):
    """Automation settings page: reminder / recurring-invoice toggles.

    These are saved preferences only — no scheduler currently reads them
    (Celery beat is scaffolded but not wired up, see CLAUDE.md).
    """
    organization = _get_user_primary_organization(request.user)

    if request.method == 'POST' and organization:
        organization.automation_reminder_j7 = request.POST.get('automation_reminder_j7') == 'on'
        organization.automation_reminder_j14 = request.POST.get('automation_reminder_j14') == 'on'
        organization.automation_reminder_j30 = request.POST.get('automation_reminder_j30') == 'on'
        organization.automation_recurring_invoices = request.POST.get('automation_recurring_invoices') == 'on'
        organization.save(update_fields=[
            'automation_reminder_j7', 'automation_reminder_j14',
            'automation_reminder_j30', 'automation_recurring_invoices', 'updated_at',
        ])
        return redirect('organizations:automation-settings')

    context = {
        'organization': organization,
        'page_title': 'Automatisations',
    }
    return render(request, 'organizations/automations.html', context)


def _send_invite_email(invite, request):
    from django.core.mail import send_mail

    accept_url = request.build_absolute_uri(
        reverse('organizations:invite-accept', args=[invite.token])
    )
    send_mail(
        subject=f"Invitation à rejoindre {invite.organization.name} sur Billio",
        message=(
            f"Vous avez été invité(e) à rejoindre {invite.organization.name} sur Billio.\n\n"
            f"Cliquez sur ce lien pour accepter l'invitation :\n{accept_url}"
        ),
        from_email=None,
        recipient_list=[invite.email],
        fail_silently=True,
    )


@login_required
@require_POST
def invite_member_create(request):
    """Crée une invitation par email et l'envoie (backend console en dev)."""
    organization = _get_user_primary_organization(request.user)
    if not organization:
        messages.error(request, "Aucune organisation trouvée.")
        return redirect(f"{reverse('accounts:user-settings')}?tab=equipe")
    if not _can_manage_team(request.user, organization):
        messages.error(request, "Vous n'avez pas le droit d'inviter des membres.")
        return _team_redirect()

    email = (request.POST.get('email') or '').strip().lower()
    role = request.POST.get('role') or 'member'
    if role not in ('admin', 'member', 'viewer'):  # on n'invite pas un second propriétaire
        role = 'member'

    if not email:
        messages.error(request, "Veuillez indiquer une adresse email.")
        return redirect(f"{reverse('accounts:user-settings')}?tab=equipe")
    from apps.subscriptions.entitlements import require_quota
    require_quota(organization, 'users')

    if OrganizationMember.objects.filter(organization=organization, user__email__iexact=email).exists():
        messages.error(request, "Cette personne est déjà membre de l'organisation.")
        return redirect(f"{reverse('accounts:user-settings')}?tab=equipe")

    invite, created = OrganizationInvite.objects.get_or_create(
        organization=organization, email=email, accepted_at__isnull=True,
        defaults={'role': role, 'invited_by': request.user},
    )
    if not created:
        invite.role = role
        invite.save(update_fields=['role'])

    _send_invite_email(invite, request)
    messages.success(request, f"Invitation envoyée à {email}.")
    return redirect(f"{reverse('accounts:user-settings')}?tab=equipe")


@login_required
@require_POST
def invite_cancel(request, invite_id):
    """Annule une invitation en attente."""
    organization = _get_user_primary_organization(request.user)
    if not _can_manage_team(request.user, organization):
        messages.error(request, "Vous n'avez pas le droit de gérer l'équipe.")
        return _team_redirect()
    invite = get_object_or_404(
        OrganizationInvite, id=invite_id, organization=organization, accepted_at__isnull=True
    )
    invite.delete()
    messages.success(request, "Invitation annulée.")
    return redirect(f"{reverse('accounts:user-settings')}?tab=equipe")


def invite_accept(request, token):
    """Page d'acceptation d'une invitation (compte existant ou création de compte)."""
    from django.contrib.auth import get_user_model
    from apps.accounts.forms import RegisterForm
    from apps.accounts.models import UserProfile

    User = get_user_model()
    invite = get_object_or_404(OrganizationInvite, token=token)

    if invite.is_accepted:
        messages.info(request, "Cette invitation a déjà été acceptée.")
        return redirect('dashboard:dashboard-home')

    if request.user.is_authenticated:
        if request.user.email.lower() != invite.email.lower():
            context = {
                'invite': invite,
                'email_mismatch': True,
                'page_title': 'Invitation',
            }
            return render(request, 'organizations/invite_accept.html', context)

        if request.method == 'POST':
            invite.accept(request.user)
            messages.success(request, f"Vous avez rejoint {invite.organization.name}.")
            return redirect('dashboard:dashboard-home')

        context = {'invite': invite, 'page_title': 'Invitation'}
        return render(request, 'organizations/invite_accept.html', context)

    account_exists = User.objects.filter(email__iexact=invite.email).exists()

    if account_exists:
        context = {
            'invite': invite,
            'account_exists': True,
            'login_url': f"{reverse('accounts:login')}?next={request.path}",
            'page_title': 'Invitation',
        }
        return render(request, 'organizations/invite_accept.html', context)

    if request.method == 'POST':
        data = request.POST.copy()
        data['email'] = invite.email
        form = RegisterForm(data)
        if form.is_valid():
            user = form.save()
            UserProfile.objects.get_or_create(user=user)
            auth_login(request, user)
            invite.accept(user)
            messages.success(request, f"Compte créé, bienvenue dans {invite.organization.name} !")
            return redirect('dashboard:dashboard-home')
    else:
        form = RegisterForm(initial={'email': invite.email})

    context = {'invite': invite, 'form': form, 'page_title': 'Invitation'}
    return render(request, 'organizations/invite_accept.html', context)


class MyOrganizationsView(generics.ListAPIView):
    """List organizations for current user."""
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Organization.objects.filter(
            members__user=self.request.user
        ).distinct()


LOGO_MAX_BYTES = 2 * 1024 * 1024
# Pas de SVG : servi depuis notre domaine, il pourrait embarquer du script.
LOGO_CONTENT_TYPES = {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}


def _editable_organization(user):
    """Organisation dont l'utilisateur peut modifier l'identité visuelle (propriétaire ou admin)."""
    organization = user.owned_organizations.first()
    if organization:
        return organization
    membership = user.organization_memberships.filter(role__in=('owner', 'admin')).select_related('organization').first()
    return membership.organization if membership else None


@login_required
@require_POST
def organization_logo(request):
    """
    Logo de l'organisation (utilisé dans l'en-tête des factures, devis et du portail client).
    POST `logo` (fichier) pour importer / remplacer, ou `remove=1` pour le retirer.
    """
    from django.http import JsonResponse

    organization = _editable_organization(request.user)
    if not organization:
        return JsonResponse({'ok': False, 'error': "Seuls le propriétaire ou un administrateur peuvent modifier le logo."}, status=403)

    if request.POST.get('remove') == '1':
        if organization.logo:
            organization.logo.delete(save=False)
        organization.logo = None
        organization.save(update_fields=['logo'])
        return JsonResponse({'ok': True, 'url': ''})

    upload = request.FILES.get('logo')
    if not upload:
        return JsonResponse({'ok': False, 'error': 'Aucun fichier reçu.'}, status=400)
    if upload.size > LOGO_MAX_BYTES:
        return JsonResponse({'ok': False, 'error': 'Le logo ne doit pas dépasser 2 Mo.'}, status=400)
    if (upload.content_type or '').lower() not in LOGO_CONTENT_TYPES:
        return JsonResponse({'ok': False, 'error': 'Format accepté : PNG, JPG, WEBP ou GIF.'}, status=400)
    try:
        from PIL import Image
        Image.open(upload).verify()
        upload.seek(0)
    except Exception:
        return JsonResponse({'ok': False, 'error': "Ce fichier n'est pas une image valide."}, status=400)

    if organization.logo:
        organization.logo.delete(save=False)
    organization.logo = upload
    organization.save(update_fields=['logo'])
    return JsonResponse({'ok': True, 'url': organization.logo.url})
