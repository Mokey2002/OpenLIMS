from rest_framework import serializers

from .models import (
    MigrationFieldMapping,
    MigrationJob,
    MigrationProfile,
    MigrationRowRecord,
    SampleExternalID,
)


class SampleExternalIDSerializer(serializers.ModelSerializer):
    sample_code = serializers.CharField(source="sample.sample_id", read_only=True)

    class Meta:
        model = SampleExternalID
        fields = [
            "id",
            "sample",
            "sample_code",
            "source_system",
            "external_id",
            "label",
            "metadata",
            "created_at",
            "row_record_count",
        ]
        read_only_fields = ["id", "sample_code", "created_at"]


class MigrationFieldMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = MigrationFieldMapping
        fields = [
            "id",
            "profile",
            "source_column",
            "target_type",
            "target_field",
            "value_type",
            "required",
        ]


class MigrationProfileSerializer(serializers.ModelSerializer):
    field_mappings = MigrationFieldMappingSerializer(many=True, read_only=True)
    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    class Meta:
        model = MigrationProfile
        fields = [
            "id",
            "name",
            "source_system",
            "source_type",
            "description",
            "created_by",
            "created_by_username",
            "field_mappings",
            "created_at",
        ]
        read_only_fields = ["id", "created_by", "created_by_username", "created_at"]


class MigrationJobSerializer(serializers.ModelSerializer):
    profile_name = serializers.CharField(source="profile.name", read_only=True)
    project_code = serializers.CharField(source="project.code", read_only=True)
    row_record_count = serializers.SerializerMethodField()
    uploaded_by_username = serializers.CharField(
        source="uploaded_by.username",
        read_only=True,
    )

    class Meta:
        model = MigrationJob
        fields = [
            "id",
            "profile",
            "profile_name",
            "project",
            "project_code",
            "uploaded_file",
            "uploaded_by",
            "uploaded_by_username",
            "status",
            "summary",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "profile_name",
            "project_code",
            "uploaded_by",
            "uploaded_by_username",
            "status",
            "summary",
            "created_at",
            "row_record_count",
        ]

    def get_row_record_count(self, obj):
        return obj.row_records.count()



class MigrationRowRecordSerializer(serializers.ModelSerializer):
    project_code_resolved = serializers.CharField(source="project.code", read_only=True)
    sample_code_resolved = serializers.CharField(source="sample.sample_id", read_only=True)

    class Meta:
        model = MigrationRowRecord
        fields = [
            "id",
            "migration_job",
            "project",
            "project_code_resolved",
            "sample",
            "sample_code_resolved",
            "row_number",
            "project_code",
            "project_name",
            "sample_code",
            "raw_row",
            "raw_row_text",
            "unmapped_data",
            "status",
            "errors",
            "created_at",
        ]
        read_only_fields = fields
