from rest_framework import serializers
from .models import FieldDefinition, FieldValue

class FieldDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FieldDefinition
        fields = ["id", "entity_type", "name", "label", "data_type", "required", "rules", "created_at"]
        read_only_fields = ["id", "created_at"]


class FieldValueSerializer(serializers.ModelSerializer):
    class Meta:
        model = FieldValue
        fields = ["id", "field_definition", "entity_type", "entity_id", "value", "updated_at"]
        read_only_fields = ["id", "updated_at"]
