"""Bandeau « paiement de l'abonnement refusé » affiché dans toute l'application."""


def billing_alert(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    from .models import Subscription
    subscription = Subscription.objects.select_related('plan').filter(
        user=user, status__in=('past_due', 'unpaid')).first()
    return {'billing_alert': subscription} if subscription else {}
