from django.contrib import admin

from .models import PlatformSetting


@admin.register(PlatformSetting)
class PlatformSettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'updated_at', 'updated_by')
    readonly_fields = ('updated_at', 'updated_by')
