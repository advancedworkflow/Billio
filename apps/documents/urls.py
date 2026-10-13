from django.urls import path

from . import views

app_name = 'documents'

urlpatterns = [
    path('gallery/', views.document_gallery, name='document-gallery'),
    path('create/', views.document_create, name='document-create'),
    path('create/<int:template_id>/', views.document_create, name='document-create-from-template'),
    path('<uuid:document_id>/edit/', views.document_editor, name='document-editor'),
    path('save/', views.document_save, name='document-save'),
    path('<uuid:document_id>/image-upload/', views.document_image_upload, name='document-image-upload'),
    path('<uuid:document_id>/delete/', views.document_delete, name='document-delete'),
    path('<uuid:document_id>/duplicate/', views.document_duplicate, name='document-duplicate'),
    path('<uuid:document_id>/favorite/', views.document_toggle_favorite, name='document-toggle-favorite'),
    path('<uuid:document_id>/save-as-template/', views.document_save_as_template, name='document-save-as-template'),
    path('<uuid:document_id>/pdf/', views.document_pdf, name='document-pdf'),
]
