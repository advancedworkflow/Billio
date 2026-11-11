from django.contrib import admin

from .models import ContactMessage


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'name', 'email', 'subject', 'handled')
    list_filter = ('handled', 'subject')
    list_editable = ('handled',)
    search_fields = ('name', 'email', 'company', 'message')
    readonly_fields = ('name', 'email', 'company', 'subject', 'message', 'created_at')
