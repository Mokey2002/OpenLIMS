from django.contrib.auth.models import Group
from rest_framework import serializers

from .models import NotificationSubscription, SOPDocument


class SOPDocumentSerializer(serializers.ModelSerializer):
    uploaded_by_username = serializers.CharField(source="uploaded_by.username", read_only=True)
    project_code = serializers.CharField(
        source="project.code",
        read_only=True,
        allow_null=True,
        default=None,
    )
    allowed_groups = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Group.objects.all(),
        required=False,
    )
    allowed_group_names = serializers.SlugRelatedField(
        source="allowed_groups",
        many=True,
        slug_field="name",
        queryset=Group.objects.filter(
            name__in=["tech", "viewer", "qc_reviewer"],
        ),
        required=False,
    )

    class Meta:
        model = SOPDocument
        fields = [
            "id", "document_code", "title", "version", "section", "content",
            "source_file", "status", "approved", "project", "project_code",
            "allowed_groups", "allowed_group_names",
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
