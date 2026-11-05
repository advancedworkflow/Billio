from django.contrib import admin

from .models import SignatureEvent, SignatureField, SignatureRequest, Signer


class SignerInline(admin.TabularInline):
    model = Signer
    extra = 0
    fields = ('name', 'email', 'order', 'status', 'signed_at', 'ip_address')
    readonly_fields = ('status', 'signed_at', 'ip_address')


class EventInline(admin.TabularInline):
    model = SignatureEvent
    extra = 0
    fields = ('at', 'action', 'signer', 'ip_address', 'detail')
    readonly_fields = fields
    can_delete = False


@admin.register(SignatureRequest)
class SignatureRequestAdmin(admin.ModelAdmin):
    list_display = ('title', 'organization', 'status', 'created_at', 'completed_at')
    list_filter = ('status', 'source')
    search_fields = ('title', 'organization__name', 'signers__email')
    readonly_fields = ('original_sha256', 'signed_sha256', 'pages', 'sent_at', 'completed_at')
    inlines = [SignerInline, EventInline]


admin.site.register(SignatureField)
