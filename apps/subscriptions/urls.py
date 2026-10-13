"""URLs de l'abonnement Billio."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = 'subscriptions'

router = DefaultRouter()
router.register(r'plans', views.PlanViewSet)
router.register(r'subscriptions', views.SubscriptionViewSet)

urlpatterns = [
    path('', views.billing_page, name='billing'),
    path('choose/<slug:code>/', views.choose_plan, name='choose'),
    path('checkout/return/', views.checkout_return, name='checkout-return'),
    path('cancel/', views.cancel_subscription, name='cancel'),
    path('resume/', views.resume_subscription, name='resume'),
    path('portal/', views.billing_portal, name='portal'),
    path('webhooks/stripe/', views.stripe_webhook, name='stripe-webhook'),
    path('api/', include(router.urls)),
]
