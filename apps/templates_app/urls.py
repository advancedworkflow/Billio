"""
URLs for templates_app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import editor_views, views

app_name = 'templates_app'

router = DefaultRouter()
router.register(r'templates', views.InvoiceTemplateViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('list/', editor_views.template_list, name='template-list'),
    path('create/', editor_views.template_new, name='template-create'),
    path('<int:template_id>/edit/', editor_views.template_editor, name='template-edit'),
    path('<int:template_id>/preview/', editor_views.template_preview_frame, name='template-preview-frame'),
    path('<int:template_id>/editor/preview/', editor_views.template_editor_preview, name='template-editor-preview'),
    path('<int:template_id>/editor/save/', editor_views.template_editor_save, name='template-editor-save'),
    path('<int:template_id>/set-default/', editor_views.template_set_default, name='template-set-default'),

    # Marketplace URLs
    path('marketplace/preview-frame/<int:pk>/', editor_views.marketplace_preview_frame, name='marketplace-preview-frame'),
    path('marketplace/', views.marketplace_list, name='marketplace-list'),
    path('marketplace/<slug:slug>/', views.marketplace_detail, name='marketplace-detail'),
    path('marketplace/<slug:slug>/purchase/', views.marketplace_purchase, name='marketplace-purchase'),
    path('marketplace/<slug:slug>/clone/', views.marketplace_clone, name='marketplace-clone'),
    path('marketplace/<slug:slug>/review/', views.template_review, name='template-review'),
    path('api/live-preview/', views.template_live_preview, name='template-live-preview'),
    path('api/preview-raw/', views.template_preview_raw, name='template-preview-raw'),
    path('api/save-as-personal/', views.template_save_as_personal, name='template-save-as-personal'),
    path('api/delete-personal/', views.template_delete_personal, name='template-delete-personal'),
]
