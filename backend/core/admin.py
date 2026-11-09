from django.contrib import admin
from .models import AccessRequest


@admin.register(AccessRequest)
class AccessRequestAdmin(admin.ModelAdmin):
    list_display = ["requester_username", "kind", "project_code", "role", "status", "created_at"]
    list_filter = ["status", "kind"]
    readonly_fields = [field.name for field in AccessRequest._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
