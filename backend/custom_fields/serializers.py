import re
from datetime import date

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

    def validate(self, attrs):
        """
        Validate value against FieldDefinition constraints.
        """
        # On create/update, field_definition might be instance or id
        field_def = attrs.get("field_definition") or getattr(self.instance, "field_definition", None)
        entity_type = attrs.get("entity_type") or getattr(self.instance, "entity_type", None)
        value = attrs.get("value") if "value" in attrs else getattr(self.instance, "value", None)

        if not field_def:
            return attrs

        # Ensure entity_type matches definition (basic safety)
        if entity_type and field_def.entity_type != entity_type:
            raise serializers.ValidationError({
                "entity_type": f"Must match FieldDefinition.entity_type ({field_def.entity_type})."
            })

        # Required check
        if field_def.required:
            if value is None or value == "" or value == {}:
                raise serializers.ValidationError({"value": "This field is required."})

        # If value is "empty" and not required, allow it
        if value is None or value == "" or value == {}:
            return attrs

        # Type validation + coercion rules
        dt = field_def.data_type
        rules = field_def.rules or {}

        # Helper: choices
        choices = rules.get("choices")
        if choices is not None:
            if value not in choices:
                raise serializers.ValidationError({"value": f"Must be one of {choices}."})

        if dt == "string":
            if not isinstance(value, str):
                raise serializers.ValidationError({"value": "Must be a string."})

            min_len = rules.get("min_length")
            max_len = rules.get("max_length")
            if min_len is not None and len(value) < int(min_len):
                raise serializers.ValidationError({"value": f"Must be at least {min_len} characters."})
            if max_len is not None and len(value) > int(max_len):
                raise serializers.ValidationError({"value": f"Must be at most {max_len} characters."})

            pattern = rules.get("regex")
            if pattern:
                if re.fullmatch(pattern, value) is None:
                    raise serializers.ValidationError({"value": "Does not match required pattern."})

        elif dt == "int":
            if not isinstance(value, int) or isinstance(value, bool):  # bool is subclass of int
                raise serializers.ValidationError({"value": "Must be an integer."})

            mn = rules.get("min")
            mx = rules.get("max")
            if mn is not None and value < int(mn):
                raise serializers.ValidationError({"value": f"Must be >= {mn}."})
            if mx is not None and value > int(mx):
                raise serializers.ValidationError({"value": f"Must be <= {mx}."})

        elif dt == "float":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise serializers.ValidationError({"value": "Must be a number."})

            value = float(value)
            attrs["value"] = value  # normalize

            mn = rules.get("min")
            mx = rules.get("max")
            if mn is not None and value < float(mn):
                raise serializers.ValidationError({"value": f"Must be >= {mn}."})
            if mx is not None and value > float(mx):
                raise serializers.ValidationError({"value": f"Must be <= {mx}."})

        elif dt == "bool":
            if not isinstance(value, bool):
                raise serializers.ValidationError({"value": "Must be true/false."})

        elif dt == "date":
            # Expect ISO string: "YYYY-MM-DD"
            if not isinstance(value, str):
                raise serializers.ValidationError({"value": "Must be an ISO date string (YYYY-MM-DD)."})
            try:
                date.fromisoformat(value)
            except ValueError:
                raise serializers.ValidationError({"value": "Invalid date format. Use YYYY-MM-DD."})

        elif dt == "json":
            # Any JSON is ok: dict/list/str/num/bool/null
            # JSONField already enforces JSON-serializable types.
            pass

        else:
            raise serializers.ValidationError({"value": f"Unsupported data_type: {dt}"})

        return attrs
