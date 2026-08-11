from django.contrib import admin

from core.permissions import is_admin

from .models import (
    AssistantAction,
    BarcodeLabel,
    GeneratedArtifact,
    NotificationDelivery,
    NotificationSubscription,
    SOPDocument,
)


@admin.register(SOPDocument)
class SOPDocumentAdmin(admin.ModelAdmin):
    list_display = ("document_code", "version", "section", "status", "approved", "project")
    list_filter = ("status", "approved", "project")
    search_fields = ("document_code", "title", "section", "content")

    def has_add_permission(self, request):
        return is_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_admin(request.user)


admin.site.register(AssistantAction)
admin.site.register(BarcodeLabel)
admin.site.register(GeneratedArtifact)
admin.site.register(NotificationSubscription)
admin.site.register(NotificationDelivery)
