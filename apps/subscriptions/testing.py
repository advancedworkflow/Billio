"""Aide aux tests : attribuer un forfait à un compte sans passer par Stripe."""
from .models import Plan, Subscription


def give_plan(user, code):
    plan = Plan.objects.get(code=code)
    subscription, _ = Subscription.objects.update_or_create(
        user=user, defaults={'plan': plan, 'status': 'active', 'comped': True})
    return subscription
