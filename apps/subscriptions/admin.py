from django.contrib import admin

from .models import Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'price_monthly', 'is_active', 'is_popular', 'order', 'stripe_price_id')
    list_editable = ('price_monthly', 'is_active', 'is_popular', 'order')
    help_texts = {}


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'status', 'current_period_end', 'cancel_at_period_end', 'comped')
    list_filter = ('status', 'plan', 'comped')
    search_fields = ('user__email', 'stripe_customer_id', 'stripe_subscription_id')
    raw_id_fields = ('user',)
