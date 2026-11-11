from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    assistant_alert = serializers.SerializerMethodField()

    def get_assistant_alert(self, obj):
        alert = getattr(obj, "assistant_alert", None)
        if alert is None or alert.action.requested_by_id != obj.user_id:
            return None
        return {"action_id": str(alert.action_id), "kind": alert.kind, "status": alert.action.status,
                "resolved_at": alert.resolved_at, "snapshot": alert.snapshot}

    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "message",
            "link",
            "is_read",
            "created_at",
            "assistant_alert",
        ]
        read_only_fields = [
            "id",
            "title",
            "message",
            "link",
            "created_at",
        ]
