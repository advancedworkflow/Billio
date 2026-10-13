"""Jeton d'API : accepté seulement si le forfait du compte inclut l'API (Business et Agency)."""
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication

from .entitlements import _enforced, plan_for_user, plan_with_feature


def user_has_api(user):
    """Le forfait de l'utilisateur, ou celui d'une organisation dont il est membre, inclut l'API."""
    if plan_for_user(user).feature('api'):
        return True
    from apps.organizations.models import Organization
    owners = Organization.objects.filter(members__user=user).exclude(owner=user).values_list('owner', flat=True).distinct()
    from django.contrib.auth import get_user_model
    return any(plan_for_user(owner).feature('api') for owner in get_user_model().objects.filter(pk__in=owners))


class PlanTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if not user.is_superuser:
            if not user_has_api(user):
                plan = plan_with_feature('api')
                raise exceptions.PermissionDenied(
                    f"L'API est disponible à partir du forfait {plan.name if plan else 'Business'}.")
            _enforced.set(True)  # quotas appliqués aussi aux créations par l'API
        return user, token
