"""
Views for integrations app.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from rest_framework import generics, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.organizations.models import OrganizationMember

from .models import Connector, ConnectionInstance, WebhookLog
from .serializers import ConnectorSerializer, ConnectionInstanceSerializer


class ConnectorViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only catalog of connectors."""
    queryset = Connector.objects.filter(is_active=True)
    serializer_class = ConnectorSerializer
    permission_classes = [IsAuthenticated]


class ConnectionInstanceViewSet(viewsets.ModelViewSet):
    """ViewSet for ConnectionInstance model."""
    queryset = ConnectionInstance.objects.all()  # Required for DRF router basename detection
    serializer_class = ConnectionInstanceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter connections based on user's organizations."""
        return ConnectionInstance.objects.filter(
            Q(organization__owner=self.request.user) |
            Q(organization__members__user=self.request.user)
        ).distinct().select_related('connector', 'organization')


class ConnectorWebhookView(generics.GenericAPIView):
    """Generic inbound webhook receiver for a connector, org-identified via ?org=<id>."""
    permission_classes = []  # No authentication for webhooks

    def post(self, request, connector_key, *args, **kwargs):
        connector = get_object_or_404(Connector, key=connector_key, is_active=True)
        payload = request.data if isinstance(request.data, dict) else {}
        org_id = request.query_params.get('org') or payload.get('organization_id')

        instance = None
        if org_id:
            try:
                instance = ConnectionInstance.objects.filter(
                    connector=connector, organization_id=org_id
                ).first()
            except (ValueError, TypeError):
                instance = None

        if not instance:
            WebhookLog.objects.create(
                connection_instance=None,
                event_type=payload.get('event', 'unknown'),
                payload=payload,
                success=False,
                error_message='No matching connection instance for this organization.',
            )
            return Response({'detail': 'Unknown organization for this connector.'}, status=404)

        WebhookLog.objects.create(
            connection_instance=instance,
            event_type=payload.get('event', 'unknown'),
            payload=payload,
            success=True,
        )
        return Response({'message': 'Webhook received'})


def _get_user_primary_organization(user):
    organization = user.owned_organizations.first()
    if organization:
        return organization
    membership = user.organization_memberships.select_related('organization').first()
    return membership.organization if membership else None


def _can_manage_integrations(user, organization):
    if organization.owner_id == user.id:
        return True
    return OrganizationMember.objects.filter(
        organization=organization,
        user=user,
        role__in=('owner', 'admin'),
        can_edit_organization=True,
    ).exists()


def _notify_integration_event(instance, notification_type, actor):
    from apps.dashboard.models import Notification

    recipients = {instance.organization.owner}
    if actor:
        recipients.add(actor)

    verb = 'connecté' if notification_type == 'integration_connected' else 'déconnecté'
    for user in recipients:
        if not user:
            continue
        Notification.objects.create(
            user=user,
            notification_type=notification_type,
            title=f"{instance.connector.name} {verb}",
            message=f"{actor.get_full_name() or actor.email} a {verb} {instance.connector.name}.",
            priority='low',
        )


# Outils affichés pour l'instant (dans cet ordre), avec leur vrai logo. Les autres connecteurs restent
# en base et réapparaissent dès qu'ils sont ajoutés ici ; un outil déjà connecté reste toujours visible.
VISIBLE_CONNECTORS = ['email', 'google-drive', 'slack', 'notion', 'whatsapp', 'telegram', 'trello', 'mailchimp']
# Briques internes de Billio : jamais dans la grille ni dans le quota d'intégrations du forfait.
# Stripe se règle dans Paramètres › Paiement (le panneau s'ouvre via ?plugin=stripe).
INTERNAL_CONNECTORS = ['stripe']
BRAND_LOGOS = set(VISIBLE_CONNECTORS) | set(INTERNAL_CONNECTORS)


@login_required
def integrations_page(request):
    """Integrations page: connectors grouped by category, per-org connection status."""
    organization = _get_user_primary_organization(request.user)
    connectors = Connector.objects.filter(is_active=True)

    instances_by_connector = {}
    if organization:
        instances_by_connector = {
            inst.connector_id: inst
            for inst in ConnectionInstance.objects.filter(
                organization=organization
            ).select_related('connector')
        }

    connected_ids = {cid for cid, inst in instances_by_connector.items() if inst.status in ('connected', 'error')}
    order = {key: index for index, key in enumerate(VISIBLE_CONNECTORS)}
    internal = [c for c in connectors if c.key in INTERNAL_CONNECTORS]
    connectors = sorted(
        [c for c in connectors if (c.key in order or c.id in connected_ids) and c.key not in INTERNAL_CONNECTORS],
        key=lambda c: order.get(c.key, len(order)),
    )
    categories = []
    for key, label in Connector.CATEGORY_CHOICES:
        items = [
            {'connector': c, 'instance': instances_by_connector.get(c.id), 'logo': c.key in BRAND_LOGOS}
            for c in connectors if c.category == key
        ]
        if items:
            categories.append({'key': key, 'label': label, 'items': items})

    from . import providers
    from .plugin_views import plugin_state
    from .recipes import needs_for_page
    available = {c.key for c in connectors} | {c.key for c in internal}
    context = {
        'categories': categories,
        # « Que voulez-vous faire ? » : on part du besoin, avec des recettes prêtes à l'emploi.
        'needs': needs_for_page(available),
        'tool_names': {c.key: c.name for c in list(connectors) + internal},
        'internal_connectors': [{'connector': c, 'instance': instances_by_connector.get(c.id)} for c in internal],
        'organization': organization,
        'can_manage': bool(organization) and _can_manage_integrations(request.user, organization),
        'page_title': 'Intégrations',
        # Plugins configurables (formulaire, guide, état masqué) pour le panneau latéral.
        'plugins_json': {
            'specs': providers.PROVIDERS,
            'state': plugin_state(organization),
            'googleReady': providers.google_configured(),
            'googleRedirect': request.build_absolute_uri(reverse('integrations:google-callback')),
            'open': request.GET.get('plugin', ''),
            'internal': INTERNAL_CONNECTORS,
            'clients': [{'id': str(c.id), 'name': c.name} for c in organization.clients.filter(is_active=True).order_by('name')] if organization else [],
        },
    }
    return render(request, 'integrations/list.html', context)


@login_required
@require_POST
def connect_connector(request, connector_key):
    """Persist connection config for a connector and mark it connected."""
    connector = get_object_or_404(Connector, key=connector_key, is_active=True)
    organization = _get_user_primary_organization(request.user)

    if not organization or not _can_manage_integrations(request.user, organization):
        messages.error(request, "Vous n'avez pas les droits pour gérer les intégrations.")
        return redirect('integrations:integrations-page')

    config = {
        key: value for key, value in {
            'api_key': (request.POST.get('api_key') or '').strip(),
            'webhook_url': (request.POST.get('webhook_url') or '').strip(),
            'access_token': (request.POST.get('access_token') or '').strip(),
            # Messagerie (action d'automatisation « Envoyer un message »)
            'chat_id': (request.POST.get('chat_id') or '').strip(),               # Telegram
            'phone_number_id': (request.POST.get('phone_number_id') or '').strip(),  # WhatsApp Cloud API
        }.items() if value
    }

    if not config:
        messages.error(request, "Veuillez renseigner au moins un champ de configuration.")
        return redirect('integrations:integrations-page')

    from apps.subscriptions.entitlements import require_quota
    if connector.key not in INTERNAL_CONNECTORS and not ConnectionInstance.objects.filter(
            organization=organization, connector=connector, status='connected').exists():
        require_quota(organization, 'integrations')
    instance, _created = ConnectionInstance.objects.get_or_create(
        organization=organization, connector=connector,
    )
    instance.config = config
    instance.status = 'connected'
    instance.connected_by = request.user
    instance.connected_at = timezone.now()
    instance.disconnected_at = None
    instance.last_error = ''
    instance.save()

    _notify_integration_event(instance, 'integration_connected', request.user)
    messages.success(request, f"{connector.name} connecté.")
    return redirect('integrations:integrations-page')


@login_required
@require_POST
def disconnect_connector(request, instance_id):
    """Disconnect a connection instance."""
    instance = get_object_or_404(
        ConnectionInstance.objects.select_related('organization', 'connector'),
        id=instance_id,
    )

    if not _can_manage_integrations(request.user, instance.organization):
        messages.error(request, "Vous n'avez pas les droits pour gérer les intégrations.")
        return redirect('integrations:integrations-page')

    instance.status = 'not_connected'
    instance.disconnected_at = timezone.now()
    instance.save(update_fields=['status', 'disconnected_at', 'updated_at'])

    _notify_integration_event(instance, 'integration_disconnected', request.user)
    messages.success(request, f"{instance.connector.name} déconnecté.")
    return redirect('integrations:integrations-page')
