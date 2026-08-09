from rest_framework import serializers

from .models import NotificationSubscription, SOPDocument


class SOPDocumentSerializer(serializers.ModelSerializer):
    uploaded_by_username = serializers.CharField(source="uploaded_by.username", read_only=True)

    class Meta:
        model = SOPDocument
        fields = [
            "id", "document_code", "title", "version", "section", "content",
            "source_file", "status", "approved", "project", "allowed_groups",
            "effective_at", "archived_at", "uploaded_by", "uploaded_by_username",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "uploaded_by", "uploaded_by_username", "created_at", "updated_at"]


class NotificationSubscriptionSerializer(serializers.ModelSerializer):
    recipient_username = serializers.CharField(source="recipient.username", read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    project_code = serializers.CharField(source="project.code", read_only=True)

    class Meta:
        model = NotificationSubscription
        fields = [
            "id", "trigger", "recipient", "recipient_username", "delivery_channel",
            "frequency", "expires_at", "project", "project_code", "target_type",
            "target_id", "threshold", "active", "next_run_at", "last_checked_at",
            "created_by", "created_by_username", "created_at", "cancelled_at",
        ]
        read_only_fields = fields
