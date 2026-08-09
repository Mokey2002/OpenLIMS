from django.contrib import admin

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


admin.site.register(AssistantAction)
admin.site.register(BarcodeLabel)
admin.site.register(GeneratedArtifact)
admin.site.register(NotificationSubscription)
admin.site.register(NotificationDelivery)
