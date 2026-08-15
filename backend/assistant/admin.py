from django.contrib import admin

from core.permissions import is_admin

from .models import (
    AssistantAction,
    AssistantFeedback,
    AssistantInteraction,
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


@admin.register(AssistantInteraction)
class AssistantInteractionAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "user",
        "route",
        "routing_source",
        "confidence",
        "response_type",
        "record_count",
        "success",
        "latency_ms",
    )
    list_filter = ("route", "routing_source", "response_type", "success")
    search_fields = ("user__username", "message_hash", "error_code")
    readonly_fields = [field.name for field in AssistantInteraction._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return is_admin(request.user)


@admin.register(AssistantFeedback)
class AssistantFeedbackAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "rating", "category", "interaction")
    list_filter = ("rating", "category")
    search_fields = ("user__username", "note")
    readonly_fields = [field.name for field in AssistantFeedback._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return is_admin(request.user)
