from rest_framework import serializers

from .models import WorkItem, Result, SampleAttachment


class ResultSerializer(serializers.ModelSerializer):
    work_item_name = serializers.CharField(source="work_item.name", read_only=True)
    sample_id = serializers.IntegerField(source="work_item.sample_id", read_only=True)
    sample_code = serializers.CharField(
        source="work_item.sample.sample_id",
        read_only=True,
    )
    project_id = serializers.IntegerField(
        source="work_item.sample.project_id",
        read_only=True,
        allow_null=True,
    )
    project_code = serializers.CharField(
        source="work_item.sample.project.code",
        read_only=True,
        allow_null=True,
        default=None,
    )
    value = serializers.SerializerMethodField()
    entered_by_username = serializers.CharField(
        source="entered_by.username",
        read_only=True,
    )
    qc_assigned_to_username = serializers.CharField(
        source="qc_assigned_to.username",
        read_only=True,
    )
    qc_reviewed_by_username = serializers.CharField(
        source="qc_reviewed_by.username",
        read_only=True,
    )
    reference_comparison = serializers.CharField(read_only=True)
    source_import_job = serializers.IntegerField(
        source="work_item.source_import_job_id",
        read_only=True,
        allow_null=True,
    )
    source_import_run_id = serializers.CharField(
        source="work_item.source_import_job.run_id",
        read_only=True,
        allow_null=True,
        default=None,
    )
    source_import_type = serializers.CharField(
        source="work_item.source_import_job.source_type",
        read_only=True,
        allow_null=True,
        default=None,
    )
    source_instrument_code = serializers.CharField(
        source="work_item.source_import_job.instrument.code",
        read_only=True,
        allow_null=True,
        default=None,
    )
    source_instrument_name = serializers.CharField(
        source="work_item.source_import_job.instrument.name",
        read_only=True,
        allow_null=True,
        default=None,
    )

    class Meta:
        model = Result
        fields = [
            "id",
            "public_id",
            "work_item",
            "work_item_name",
            "sample_id",
            "sample_code",
            "project_id",
            "project_code",
            "source_import_job",
            "source_import_run_id",
            "source_import_type",
            "source_instrument_code",
            "source_instrument_name",
            "key",
            "value_type",
            "value_string",
            "value_number",
            "value_boolean",
            "value",
            "unit",
            "reference_min",
            "reference_max",
            "reference_comparison",
            "qc_rule",
            "qc_passed",
            "qc_failure_reason",
            "qc_status",
            "entered_by",
            "entered_by_username",
            "qc_assigned_to",
            "qc_assigned_to_username",
            "qc_reviewed_by",
            "qc_reviewed_by_username",
            "qc_reviewed_at",
            "qc_review_note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "value",
            "reference_comparison",
            "qc_status",
            "entered_by",
            "entered_by_username",
            "qc_assigned_to",
            "qc_assigned_to_username",
            "qc_reviewed_by",
            "qc_reviewed_by_username",
            "qc_reviewed_at",
            "qc_review_note",
            "created_at",
            "updated_at",
        ]

    def get_value(self, obj):
        return obj.value

    def validate(self, attrs):
        value_type = attrs.get("value_type", getattr(self.instance, "value_type", None))

        if value_type == "STRING":
            if not attrs.get("value_string"):
                raise serializers.ValidationError(
                    {"value_string": "Required for STRING results."}
                )

        elif value_type == "NUMBER":
            if attrs.get("value_number") is None:
                raise serializers.ValidationError(
                    {"value_number": "Required for NUMBER results."}
                )

        elif value_type == "BOOLEAN":
            if attrs.get("value_boolean") is None:
                raise serializers.ValidationError(
                    {"value_boolean": "Required for BOOLEAN results."}
                )

        reference_min = attrs.get(
            "reference_min",
            getattr(self.instance, "reference_min", None),
        )
        reference_max = attrs.get(
            "reference_max",
            getattr(self.instance, "reference_max", None),
        )
        if (
            reference_min is not None
            and reference_max is not None
            and reference_min > reference_max
        ):
            raise serializers.ValidationError(
                {"reference_max": "Reference maximum must be at least the minimum."}
            )

        return attrs


class WorkItemSerializer(serializers.ModelSerializer):
    sample_code = serializers.CharField(source="sample.sample_id", read_only=True)
    project_id = serializers.IntegerField(
        source="sample.project_id",
        read_only=True,
        allow_null=True,
    )
    project_code = serializers.CharField(
        source="sample.project.code",
        read_only=True,
        allow_null=True,
        default=None,
    )
    batch_code = serializers.CharField(
        source="sample.batch.code",
        read_only=True,
        allow_null=True,
        default=None,
    )
    results = ResultSerializer(many=True, read_only=True)
    reviewed_by_username = serializers.CharField(
        source="reviewed_by.username",
        read_only=True,
    )
    assigned_to_username = serializers.CharField(
        source="assigned_to.username",
        read_only=True,
    )
    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )
    source_import_run_id = serializers.CharField(
        source="source_import_job.run_id",
        read_only=True,
        allow_null=True,
        default=None,
    )
    source_import_type = serializers.CharField(
        source="source_import_job.source_type",
        read_only=True,
        allow_null=True,
        default=None,
    )
    source_instrument_code = serializers.CharField(
        source="source_import_job.instrument.code",
        read_only=True,
        allow_null=True,
        default=None,
    )
    source_instrument_name = serializers.CharField(
        source="source_import_job.instrument.name",
        read_only=True,
        allow_null=True,
        default=None,
    )
    pipeline_step_run_id = serializers.IntegerField(
        source="pipeline_step_run.id",
        read_only=True,
        allow_null=True,
        default=None,
    )
    pipeline_run_id = serializers.IntegerField(
        source="pipeline_step_run.pipeline_run_id",
        read_only=True,
        allow_null=True,
        default=None,
    )
    pipeline_step_position = serializers.IntegerField(
        source="pipeline_step_run.position",
        read_only=True,
        allow_null=True,
        default=None,
    )

    class Meta:
        model = WorkItem
        fields = [
            "id",
            "public_id",
            "sample",
            "sample_code",
            "project_id",
            "project_code",
            "batch_code",
            "source_import_job",
            "source_import_run_id",
            "source_import_type",
            "source_instrument_code",
            "source_instrument_name",
            "pipeline_step_run_id",
            "pipeline_run_id",
            "pipeline_step_position",
            "name",
            "work_type",
            "analysis_code",
            "required_fields",
            "status",
            "notes",
            "assigned_to",
            "assigned_to_username",
            "created_by",
            "created_by_username",
            "due_at",
            "qc_status",
            "reviewed_by",
            "reviewed_by_username",
            "reviewed_at",
            "review_note",
            "created_at",
            "updated_at",
            "results",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "source_import_job",
            "analysis_code",
            "required_fields",
            "qc_status",
            "reviewed_by",
            "reviewed_by_username",
            "reviewed_at",
            "review_note",
            "created_at",
            "results",
            "created_by",
            "created_by_username",
            "updated_at",
        ]


class WorkItemQCReviewSerializer(serializers.Serializer):
    qc_status = serializers.ChoiceField(
        choices=[
            WorkItem.QC_APPROVED,
            WorkItem.QC_REJECTED,
            WorkItem.QC_RERUN_REQUIRED,
            WorkItem.QC_PENDING_REVIEW,
        ]
    )
    review_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
    )


class SampleAttachmentSerializer(serializers.ModelSerializer):
    filename = serializers.SerializerMethodField()

    class Meta:
        model = SampleAttachment
        fields = ["id", "sample", "file", "filename", "uploaded_at"]
        read_only_fields = ["id", "filename", "uploaded_at"]

    def get_filename(self, obj):
        return obj.file.name.split("/")[-1]
