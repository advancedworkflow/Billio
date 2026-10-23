"""
URLs for payments app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import reconcile_views, views

app_name = 'payments'

router = DefaultRouter()
router.register(r'payments', views.PaymentViewSet)
router.register(r'methods', views.PaymentMethodViewSet)

urlpatterns = [
    # HTML views
    path('dashboard/', views.payments_page, name='payments-page'),
    path('methods/quick-create/', views.payment_method_quick_create, name='payment-method-quick-create'),
    path('methods/quick-update/<int:method_id>/', views.payment_method_quick_update, name='payment-method-quick-update'),
    path('methods/quick-set-default/<int:method_id>/', views.payment_method_set_default, name='payment-method-set-default'),
    path('methods/quick-delete/<int:method_id>/', views.payment_method_quick_delete, name='payment-method-quick-delete'),
    path('record/', views.record_payment, name='record-payment'),
    path('reconcile/', reconcile_views.reconcile_page, name='reconcile'),
    path('reconcile/import/', reconcile_views.reconcile_import, name='reconcile-import'),
    path('reconcile/add/', reconcile_views.reconcile_add, name='reconcile-add'),
    path('reconcile/match-sure/', reconcile_views.reconcile_match_sure, name='reconcile-match-sure'),
    path('reconcile/<int:line_id>/match/', reconcile_views.reconcile_match, name='reconcile-match'),
    path('reconcile/<int:line_id>/ignore/', reconcile_views.reconcile_ignore, name='reconcile-ignore'),
    path('reconcile/<int:line_id>/undo/', reconcile_views.reconcile_undo, name='reconcile-undo'),
    path('remind/<uuid:invoice_id>/', views.send_payment_reminder, name='send-payment-reminder'),

    path('', include(router.urls)),
    path('webhooks/stripe/<int:organization_id>/', views.stripe_webhook, name='stripe-webhook'),
]


