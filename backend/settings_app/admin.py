from django.contrib import admin

from .models import SystemSettings


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    list_display = [
        "lab_name",
        "organization_name",
        "default_timezone",
        "updated_by",
        "updated_at",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
    ]
