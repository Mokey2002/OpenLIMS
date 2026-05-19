from rest_framework import serializers

from .models import InstrumentProfile, InstrumentColumnMapping, ImportJob


class InstrumentColumnMappingSerializer(serializers.ModelSerializer):
    instrument_code = serializers.CharField(source="instrument.code", read_only=True)
    instrument_name = serializers.CharField(source="instrument.name", read_only=True)

    class Meta:
        model = InstrumentColumnMapping
        fields = [
            "id",
            "instrument",
            "instrument_code",
            "instrument_name",
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
            "column_mappings",
        ]


class ImportJobSerializer(serializers.ModelSerializer):
    instrument_name = serializers.CharField(source="instrument.name", read_only=True)
    instrument_code = serializers.CharField(source="instrument.code", read_only=True)
    project_code = serializers.CharField(source="project.code", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True)
    uploaded_by_username = serializers.CharField(
        source="uploaded_by.username",
        read_only=True,
    )

    progress_percent = serializers.SerializerMethodField()

    class Meta:
        model = ImportJob
        fields = [
            "id",
            "instrument",
            "instrument_name",
            "instrument_code",
            "project",
            "project_code",
            "project_name",
            "uploaded_by",
            "uploaded_by_username",
            "uploaded_file",
            "source_type",
            "run_id",
            "status",
            "summary",
            "progress_current",
            "progress_total",
            "progress_message",
            "progress_percent",
            "created_at",
        ]

        read_only_fields = [
            "uploaded_by",
            "uploaded_by_username",
            "source_type",
            "status",
            "summary",
            "progress_current",
            "progress_total",
            "progress_message",
            "progress_percent",
            "created_at",
        ]

    def get_progress_percent(self, obj):
        if obj.status == "COMPLETED":
            return 100

        if not obj.progress_total:
            return 0

        return round((obj.progress_current / obj.progress_total) * 100)