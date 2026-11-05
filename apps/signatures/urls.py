from django.urls import path

from . import public_views, views

app_name = 'signatures'

urlpatterns = [
    path('', views.signature_list, name='requests'),
    path('new/', views.signature_new, name='new'),
    path('<uuid:request_id>/', views.signature_detail, name='detail'),
    path('<uuid:request_id>/save/', views.signature_save, name='save'),
    path('<uuid:request_id>/pdf/', views.signature_pdf, name='pdf'),
    path('<uuid:request_id>/remind/<int:signer_id>/', views.signature_remind, name='remind'),
    path('<uuid:request_id>/cancel/', views.signature_cancel, name='cancel'),
    path('<uuid:request_id>/delete/', views.signature_delete, name='delete'),
    path('<uuid:request_id>/finalize/', views.signature_finalize, name='finalize'),

    # Pages publiques (lien secret du signataire)
    path('s/<str:token>/', public_views.sign_page, name='sign'),
    path('s/<str:token>/pdf/', public_views.sign_pdf, name='sign-pdf'),
    path('s/<str:token>/submit/', public_views.sign_submit, name='sign-submit'),
    path('s/<str:token>/decline/', public_views.sign_decline, name='sign-decline'),
    path('s/<str:token>/download/', public_views.sign_download, name='sign-download'),
    path('verifier/', public_views.verify, name='verify'),
]
