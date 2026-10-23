"""
URLs for invoices app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import quote_views

app_name = 'invoices'

router = DefaultRouter()
router.register(r'invoices', views.InvoiceViewSet)
router.register(r'quotes', views.QuoteViewSet)
router.register(r'taxes', views.TaxViewSet)

urlpatterns = [
    # API endpoints
    path('api/', include(router.urls)),
    path('api/public/<uuid:invoice_id>/', views.PublicInvoiceView.as_view(), name='public-invoice'),
    path('public/<uuid:invoice_id>/pay/', views.public_invoice_payment, name='public-invoice-payment'),
    path('public/<uuid:invoice_id>/pdf/', views.public_invoice_pdf, name='public-invoice-pdf'),
    path('public/<uuid:invoice_id>/pay/confirm/', views.public_invoice_pay, name='public-invoice-pay'),
    path('public/<uuid:invoice_id>/pay/return/', views.public_invoice_pay_return, name='public-invoice-pay-return'),
    path('public/<uuid:invoice_id>/receipt/', views.public_invoice_receipt, name='public-invoice-receipt'),
    path('public/<uuid:invoice_id>/receipt/download/', views.public_invoice_receipt_download, name='public-invoice-receipt-download'),
    path('api/public/<uuid:quote_id>/quote/', quote_views.PublicQuoteView.as_view(), name='public-quote'),
    path('public/<uuid:quote_id>/quote/', quote_views.public_quote_view, name='public-quote-view'),
    path('public/<uuid:quote_id>/quote/accept/', quote_views.public_quote_accept, name='public-quote-accept'),
    path('public/<uuid:quote_id>/quote/reject/', quote_views.public_quote_reject, name='public-quote-reject'),
    path('public/<uuid:quote_id>/quote/confirmation/', quote_views.public_quote_confirmation, name='public-quote-confirmation'),

    # Main views
    path('demo/', views.invoice_demo, name='invoice-demo'),
    path('create/', views.invoice_create, name='invoice-create'),
    path('<uuid:invoice_id>/edit/', views.invoice_edit, name='invoice-edit'),
    path('quotes/<uuid:quote_id>/situation/', quote_views.quote_situation_create, name='quote-situation-create'),
    path('<uuid:invoice_id>/preview/', views.invoice_preview, name='invoice-preview'),
    path('<uuid:invoice_id>/credit-note/', views.invoice_credit_note_create, name='invoice-credit-note-create'),
    path('<uuid:invoice_id>/recurrence/', views.invoice_recurrence_update, name='invoice-recurrence-update'),
    path('<uuid:invoice_id>/retention/release/', views.invoice_retention_release, name='invoice-retention-release'),
    path('<uuid:invoice_id>/facturx.<str:fmt>', views.invoice_facturx, name='invoice-facturx'),
    path('save/', views.save_invoice, name='invoice-save'),
    path('<uuid:invoice_id>/save/', views.save_invoice, name='invoice-update'),

    # HTMX views
    path('list/', views.invoice_list, name='invoice-list'),
    path('api/list/', views.invoice_list_api, name='invoice-list-api'),
    path('api/create/', views.invoice_create_api, name='invoice-create-api'),
    path('<uuid:invoice_id>/send/', views.send_invoice, name='send-invoice'),
    path('export/fec/', views.fec_export, name='fec-export'),
    path('export/compta/', views.accounting_export, name='accounting-export'),
    path('<uuid:invoice_id>/schedule-send/', views.schedule_invoice_send, name='schedule-invoice-send'),
    path('<uuid:invoice_id>/duplicate/', views.duplicate_invoice, name='duplicate-invoice'),
    path('<uuid:invoice_id>/toggle-favorite/', views.invoice_toggle_favorite, name='invoice-toggle-favorite'),
    path('<uuid:invoice_id>/mark-paid/', views.mark_invoice_paid, name='mark-invoice-paid'),
    # Devis (Quote) - HTML views
    path('quotes/list/', quote_views.quote_list, name='quote-list'),
    path('quotes/create/', quote_views.quote_create, name='quote-create'),
    path('quotes/<uuid:quote_id>/edit/', quote_views.quote_edit, name='quote-edit'),
    path('quotes/<uuid:quote_id>/preview/', quote_views.quote_preview, name='quote-preview'),
    path('quotes/save/', quote_views.save_quote, name='quote-save'),
    path('quotes/<uuid:quote_id>/save/', quote_views.save_quote, name='quote-update'),
    path('quotes/<uuid:quote_id>/duplicate/', quote_views.duplicate_quote, name='quote-duplicate'),
    path('quotes/<uuid:quote_id>/toggle-favorite/', quote_views.quote_toggle_favorite, name='quote-toggle-favorite'),
    path('quotes/<uuid:quote_id>/attachments/upload/', quote_views.quote_attachment_upload, name='quote-attachment-upload'),
    path('quotes/<uuid:quote_id>/send/', quote_views.send_quote, name='quote-send'),
    path('quotes/<uuid:quote_id>/mark-accepted/', quote_views.quote_mark_accepted, name='quote-mark-accepted'),
    path('quotes/<uuid:quote_id>/mark-rejected/', quote_views.quote_mark_rejected, name='quote-mark-rejected'),
    path('quotes/<uuid:quote_id>/convert-to-invoice/', quote_views.convert_quote_to_invoice, name='quote-convert-to-invoice'),
    path('quotes/<uuid:quote_id>/convert-to-subscription/', quote_views.quote_convert_to_subscription, name='quote-convert-to-subscription'),
    path('quotes/<uuid:quote_id>/milestones/<int:milestone_id>/generate-invoice/', quote_views.generate_milestone_invoice, name='quote-milestone-generate-invoice'),

    # Produits (catalogue) - HTML view
    path('products/', views.product_list, name='product-list'),
    path('products/quick-create/', views.product_quick_create, name='product-quick-create'),
    path('products/quick-update/<int:product_id>/', views.product_quick_update, name='product-quick-update'),
    path('products/quick-toggle/<int:product_id>/', views.product_quick_toggle, name='product-quick-toggle'),
    path('products/quick-delete/<int:product_id>/', views.product_quick_delete, name='product-quick-delete'),
]
