from .models import ConnectionInstance


def plugins(request):
    """Plugins connectés de l'organisation (boutons Drive / Notion / exports affichés seulement s'ils servent)."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {'connected_plugins': []}
    from .views import _get_user_primary_organization
    organization = _get_user_primary_organization(user)
    if not organization:
        return {'connected_plugins': []}
    keys = list(ConnectionInstance.objects.filter(organization=organization, status='connected').values_list('connector__key', flat=True))
    return {'connected_plugins': keys}
