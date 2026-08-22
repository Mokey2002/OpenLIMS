from rest_framework import serializers

from .models import (
    MigrationDatabaseConnection,
    MigrationDataset,
    MigrationFieldMapping,
    MigrationJob,
    MigrationProfile,
    MigrationRowRecord,
    SampleExternalID,
)


class MigrationDatabaseConnectionSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = MigrationDatabaseConnection
        fields = [
            "id",
            "name",
            "engine",
            "host",
            "port",
            "database_name",
            "username",
            "password_env_var",
            "ssl_mode",
            "active",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]

    def validate_password_env_var(self, value):
        if value and (not value.replace("_", "A").isalnum() or not value[0].isalpha()):
            raise serializers.ValidationError("Use a valid environment variable name.")
        return value

    def validate(self, attrs):
        engine = attrs.get("engine", getattr(self.instance, "engine", None))
        if engine != MigrationDatabaseConnection.ENGINE_SQLITE:
            for field in ["host", "username", "password_env_var"]:
                value = attrs.get(field, getattr(self.instance, field, ""))
                if not value:
                    raise serializers.ValidationError({field: "This field is required."})
        return attrs


class MigrationDatasetSerializer(serializers.ModelSerializer):
    connection_name = serializers.CharField(source="connection.name", read_only=True)
    profile_name = serializers.CharField(source="profile.name", read_only=True)

    class Meta:
        model = MigrationDataset
        fields = [
            "id",
            "profile",
            "profile_name",
            "connection",
            "connection_name",
            "name",
            "entity_type",
            "source_schema",
            "source_table",
            "source_key_column",
            "row_limit",
            "active",
        ]

    def validate(self, attrs):
        profile = attrs.get("profile", getattr(self.instance, "profile", None))
        if profile and profile.source_type != MigrationProfile.SOURCE_TYPE_DATABASE:
            raise serializers.ValidationError(
                {"profile": "Datasets require a database migration profile."}
            )
        row_limit = attrs.get("row_limit", getattr(self.instance, "row_limit", 10000))
        if row_limit < 1 or row_limit > 50000:
            raise serializers.ValidationError({"row_limit": "Use a value from 1 to 50000."})
        return attrs


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
        ]
        read_only_fields = ["id", "sample_code", "created_at"]


class MigrationFieldMappingSerializer(serializers.ModelSerializer):
    DATABASE_TARGETS = {
        MigrationDataset.ENTITY_PROJECT: {
            MigrationFieldMapping.TARGET_PROJECT_CODE,
            MigrationFieldMapping.TARGET_PROJECT_NAME,
            MigrationFieldMapping.TARGET_PROJECT_DESCRIPTION,
        },
        MigrationDataset.ENTITY_USER: {
            MigrationFieldMapping.TARGET_USER_USERNAME,
            MigrationFieldMapping.TARGET_USER_EMAIL,
            MigrationFieldMapping.TARGET_USER_FIRST_NAME,
            MigrationFieldMapping.TARGET_USER_LAST_NAME,
            MigrationFieldMapping.TARGET_USER_ROLE,
        },
        MigrationDataset.ENTITY_SAMPLE: {
            MigrationFieldMapping.TARGET_PROJECT_CODE,
            MigrationFieldMapping.TARGET_SAMPLE_ID,
            MigrationFieldMapping.TARGET_SAMPLE_TYPE,
            MigrationFieldMapping.TARGET_SAMPLE_STATUS,
            MigrationFieldMapping.TARGET_SAMPLE_CREATED_AT,
            MigrationFieldMapping.TARGET_EXTERNAL_ID,
            MigrationFieldMapping.TARGET_CUSTOM_FIELD,
        },
        MigrationDataset.ENTITY_RESULT: {
            MigrationFieldMapping.TARGET_SAMPLE_ID,
            MigrationFieldMapping.TARGET_WORK_ITEM_NAME,
            MigrationFieldMapping.TARGET_WORK_ITEM_TYPE,
            MigrationFieldMapping.TARGET_WORK_ITEM_STATUS,
            MigrationFieldMapping.TARGET_WORK_ITEM_CREATED_AT,
            MigrationFieldMapping.TARGET_RESULT_KEY,
            MigrationFieldMapping.TARGET_RESULT_VALUE,
            MigrationFieldMapping.TARGET_RESULT_UNIT,
            MigrationFieldMapping.TARGET_RESULT_CREATED_AT,
            MigrationFieldMapping.TARGET_RESULT_QC_STATUS,
            MigrationFieldMapping.TARGET_RESULT_ENTERED_BY,
            MigrationFieldMapping.TARGET_RESULT_REFERENCE_MIN,
            MigrationFieldMapping.TARGET_RESULT_REFERENCE_MAX,
        },
    }

    class Meta:
        model = MigrationFieldMapping
        fields = [
            "id",
            "profile",
            "dataset",
            "source_column",
            "target_type",
            "target_field",
            "value_type",
            "required",
        ]

    def validate(self, attrs):
        profile = attrs.get("profile", getattr(self.instance, "profile", None))
        dataset = attrs.get("dataset", getattr(self.instance, "dataset", None))
        if dataset and profile and dataset.profile_id != profile.id:
            raise serializers.ValidationError(
                {"dataset": "The dataset must belong to the selected profile."}
            )
        if profile and profile.source_type == MigrationProfile.SOURCE_TYPE_DATABASE and not dataset:
            raise serializers.ValidationError({"dataset": "Database mappings require a dataset."})
        if profile and profile.source_type == MigrationProfile.SOURCE_TYPE_CSV and dataset:
            raise serializers.ValidationError({"dataset": "CSV mappings cannot use a dataset."})
        target_type = attrs.get("target_type", getattr(self.instance, "target_type", None))
        if dataset and target_type not in self.DATABASE_TARGETS[dataset.entity_type]:
            raise serializers.ValidationError(
                {"target_type": f"{target_type} is not supported for {dataset.entity_type} datasets."}
            )
        return attrs


class MigrationProfileSerializer(serializers.ModelSerializer):
    field_mappings = MigrationFieldMappingSerializer(many=True, read_only=True)
    datasets = MigrationDatasetSerializer(many=True, read_only=True)
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
            "datasets",
            "created_at",
        ]
        read_only_fields = ["id", "created_by", "created_by_username", "created_at"]

    def validate_source_type(self, value):
        if self.instance and value != self.instance.source_type:
            if (
                self.instance.jobs.exists()
                or self.instance.datasets.exists()
                or self.instance.field_mappings.exists()
            ):
                raise serializers.ValidationError(
                    "Source type cannot change after datasets or migration jobs exist."
                )
        return value


class MigrationJobSerializer(serializers.ModelSerializer):
    profile_name = serializers.CharField(source="profile.name", read_only=True)
    project_code = serializers.CharField(source="project.code", read_only=True)
    row_record_count = serializers.SerializerMethodField()
    uploaded_by_username = serializers.CharField(
        source="uploaded_by.username",
        read_only=True,
    )
    source_connection_name = serializers.CharField(
        source="source_connection.name",
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
            "source_connection",
            "source_connection_name",
            "uploaded_by",
            "uploaded_by_username",
            "status",
            "summary",
            "source_snapshot",
            "preview_fingerprint",
            "committed_by",
            "confirmed_at",
            "created_at",
            "row_record_count",
        ]
        read_only_fields = [
            "id",
            "profile_name",
            "project_code",
            "uploaded_by",
            "uploaded_by_username",
            "status",
            "summary",
            "source_snapshot",
            "preview_fingerprint",
            "committed_by",
            "confirmed_at",
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
            "source_dataset",
            "entity_type",
            "source_key",
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
