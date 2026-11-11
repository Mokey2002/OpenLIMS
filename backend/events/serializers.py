from rest_framework import serializers
from .models import Event
from .presentation import event_presentation
from .comparison import can_compare_revision, field_changes

class EventSerializer(serializers.ModelSerializer):
    actor_username=serializers.SerializerMethodField()
    entity_label = serializers.CharField(read_only=True)
    action_label = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    source = serializers.CharField(read_only=True)
    field_changes = serializers.ListField(read_only=True)
    can_compare_revision = serializers.BooleanField(read_only=True)
    class Meta:
        model = Event
        fields = ["id", "entity_type", "entity_id", "action", "timestamp", "payload","actor","actor_username",
                  "entity_label", "action_label", "description", "source", "field_changes", "can_compare_revision"]
        read_only_fields = fields

    def get_actor_username(self,obj):
        return obj.actor.username if obj.actor else None

    def to_representation(self, instance):
        return {**super().to_representation(instance), **event_presentation(instance),
                "field_changes": field_changes(instance), "can_compare_revision": can_compare_revision(instance)}
