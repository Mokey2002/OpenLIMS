from rest_framework import serializers
from .models import InstrumentProfile, InstrumentColumnMapping, ImportJob


class InstrumentColumnMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = InstrumentColumnMapping
        fields = [
            "id",
            "instrument",
            "source_column",
            "target_key",
            "value_type",
            "min_value",
            "max_value",
            "allowed_values",
        ]

class InstrumentProfileSerializer(serializers.ModelSerializer):
    column_mappings = InstrumentColumnMappingSerializer(many=True, read_only=True)

    class Meta:
        model = InstrumentProfile
        fields = [
            "id",
            "name",
            "code",
            "delimiter",
            "has_header",
            "sample_id_column",
            "created_at",
            "column_mappings",
        ]


class ImportJobSerializer(serializers.ModelSerializer):
    uploaded_by_username = serializers.SerializerMethodField()

    class Meta:
        model = ImportJob
        fields = [
            "id",
            "instrument",
            "project",
            "uploaded_file",
            "uploaded_by",
            "uploaded_by_username",
            "status",
            "summary",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "uploaded_by",
            "uploaded_by_username",
            "status",
            "summary",
            "created_at",
        ]

    def get_uploaded_by_username(self, obj):
        return obj.uploaded_by.username if obj.uploaded_by else None
