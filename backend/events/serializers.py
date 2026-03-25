from rest_framework import serializers
from .models import Event

class EventSerializer(serializers.ModelSerializer):
    actor_username=serializers.SerializerMethodField()
    class Meta:
        model = Event
        fields = ["id", "entity_type", "entity_id", "action", "timestamp", "payload","actor","actor_username"]
        read_only_fields = fields

    def get_actor_username(self,obj):
        return obj.actor.username if obj.actor else None
