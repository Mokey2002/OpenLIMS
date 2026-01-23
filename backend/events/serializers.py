from rest_framework import serializers
from .models import Event

class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "entity_type", "entity_id", "action", "timestamp", "payload"]
        read_only_fields = fields
