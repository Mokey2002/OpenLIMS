from rest_framework import serializers
from .models import WorkItem, Result


class ResultSerializer(serializers.ModelSerializer):
    value = serializers.SerializerMethodField()

    class Meta:
        model = Result
        fields = [
            "id",
            "work_item",
            "key",
            "value_type",
            "value_string",
            "value_number",
            "value_boolean",
            "value",
            "created_at",
        ]
        read_only_fields = ["id", "value", "created_at"]

    def get_value(self, obj):
        return obj.value

    def validate(self, attrs):
        value_type = attrs.get("value_type", getattr(self.instance, "value_type", None))

        if value_type == "STRING":
            if not attrs.get("value_string"):
                raise serializers.ValidationError({"value_string": "Required for STRING results."})

        elif value_type == "NUMBER":
            if attrs.get("value_number") is None:
                raise serializers.ValidationError({"value_number": "Required for NUMBER results."})

        elif value_type == "BOOLEAN":
            if attrs.get("value_boolean") is None:
                raise serializers.ValidationError({"value_boolean": "Required for BOOLEAN results."})

        return attrs


class WorkItemSerializer(serializers.ModelSerializer):
    results = ResultSerializer(many=True, read_only=True)

    class Meta:
        model = WorkItem
        fields = [
            "id",
            "sample",
            "name",
            "status",
            "notes",
            "created_at",
            "results",
        ]
        read_only_fields = ["id", "created_at", "results"]
