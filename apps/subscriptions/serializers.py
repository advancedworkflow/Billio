"""Sérialiseurs (lecture) des forfaits et de l'abonnement."""
from rest_framework import serializers

from .models import Plan, Subscription


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ['id', 'code', 'name', 'tagline', 'price_monthly', 'limits', 'features', 'is_popular', 'order']


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)

    class Meta:
        model = Subscription
        fields = ['id', 'plan', 'status', 'current_period_end', 'cancel_at_period_end', 'past_due_since']
