from django.contrib import admin

from .models import Document, DocumentTemplate


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('number', 'title', 'document_type', 'organization', 'client', 'status', 'created_at')
    list_filter = ('document_type', 'status')
    search_fields = ('number', 'title')


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'organization', 'created_at')
    list_filter = ('category',)
    search_fields = ('name',)
