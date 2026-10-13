from django import template

register = template.Library()


@register.inclusion_tag('dashboard/_portal_notifications.html', takes_context=True)
def portal_notifications(context, client):
    """Cloche du portail client : 15 dernières notifications + nombre de non lues."""
    notifications = list(client.portal_notifications.select_related('project')[:15])
    return {
        'client': client,
        'notifications': notifications,
        'unread_count': client.portal_notifications.filter(read_at__isnull=True).count(),
        'csrf_token': context.get('csrf_token'),
    }
