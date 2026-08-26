from django.db import transaction
from rest_framework import serializers

from .models import (
    AnalysisDefinition,
    PipelineRun,
    PipelineStepRun,
    PipelineTemplate,
    PipelineTemplateStep,
    ProcedureDefinition,
)


class AnalysisDefinitionSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = AnalysisDefinition
        fields = [
            "id",
            "code",
            "name",
            "category",
            "description",
            "required_fields",
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

    def validate_code(self, value):
        normalized = str(value or "").strip().upper()
        if not normalized:
            raise serializers.ValidationError("Analysis code is required.")
        return normalized

    def validate_required_fields(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Required fields must be a list.")

        cleaned = []
        seen = set()
        allowed_types = {
            AnalysisDefinition.VALUE_TYPE_STRING,
            AnalysisDefinition.VALUE_TYPE_NUMBER,
            AnalysisDefinition.VALUE_TYPE_BOOLEAN,
        }
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise serializers.ValidationError(f"Field {index + 1} must be an object.")
            key = str(item.get("key") or "").strip()
            label = str(item.get("label") or key).strip()
            value_type = str(item.get("value_type") or "STRING").strip().upper()
            if not key:
                raise serializers.ValidationError(f"Field {index + 1} requires a key.")
            if key.lower() in seen:
                raise serializers.ValidationError(f"Duplicate required field key: {key}.")
            if value_type not in allowed_types:
                raise serializers.ValidationError(
                    f"Field {key} has unsupported value type {value_type}."
                )
            seen.add(key.lower())
            cleaned.append({
                "key": key,
                "label": label or key,
                "value_type": value_type,
                "required": bool(item.get("required", True)),
                "unit": str(item.get("unit") or "").strip(),
            })
        return cleaned


class ProcedureDefinitionSerializer(serializers.ModelSerializer):
    analysis_code = serializers.CharField(source="analysis.code", read_only=True)
    analysis_name = serializers.CharField(source="analysis.name", read_only=True)
    sop_document_code = serializers.CharField(
        source="sop_document.document_code",
        read_only=True,
        allow_null=True,
        default=None,
    )
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = ProcedureDefinition
        fields = [
            "id",
            "code",
            "name",
            "version",
            "analysis",
            "analysis_code",
            "analysis_name",
            "sop_document",
            "sop_document_code",
            "instructions",
            "estimated_duration_minutes",
            "active",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "analysis_code",
            "analysis_name",
            "sop_document_code",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]

    def validate_code(self, value):
        normalized = str(value or "").strip().upper()
        if not normalized:
            raise serializers.ValidationError("Procedure code is required.")
        return normalized

    def validate_estimated_duration_minutes(self, value):
        if value < 1:
            raise serializers.ValidationError("Estimated duration must be at least one minute.")
        return value


class PipelineTemplateStepSerializer(serializers.ModelSerializer):
    procedure_code = serializers.CharField(source="procedure.code", read_only=True)
    procedure_name = serializers.CharField(source="procedure.name", read_only=True)
    procedure_version = serializers.CharField(source="procedure.version", read_only=True)
    analysis_code = serializers.CharField(source="procedure.analysis.code", read_only=True)
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = PipelineTemplateStep
        fields = [
            "id",
            "position",
            "procedure",
            "procedure_code",
            "procedure_name",
            "procedure_version",
            "analysis_code",
            "name",
            "display_name",
            "requires_qc",
            "dependency_positions",
            "activation_condition",
            "optional",
            "max_retries",
        ]
        read_only_fields = [
            "id",
            "procedure_code",
            "procedure_name",
            "procedure_version",
            "analysis_code",
            "display_name",
        ]

    def validate_procedure(self, procedure):
        if not procedure.active or not procedure.analysis.active:
            raise serializers.ValidationError(
                "Pipeline steps must use an active procedure and analysis."
            )
        return procedure

    def validate_dependency_positions(self, value):
        if value is None:
            return None
        if not isinstance(value, list) or any(not isinstance(item, int) for item in value):
            raise serializers.ValidationError("Dependencies must be a list of step positions.")
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Dependency positions must be unique.")
        return sorted(value)

    def validate_activation_condition(self, value):
        if not value:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Activation condition must be an object.")
        required = {"source_position", "result_key", "operator", "value"}
        missing = required - set(value)
        if missing:
            raise serializers.ValidationError(
                f"Activation condition is missing: {', '.join(sorted(missing))}."
            )
        operator = str(value.get("operator") or "").upper()
        if operator not in {"EQ", "NE", "GT", "GTE", "LT", "LTE", "IN"}:
            raise serializers.ValidationError("Unsupported activation condition operator.")
        try:
            source_position = int(value["source_position"])
        except (TypeError, ValueError) as exc:
            raise serializers.ValidationError("Condition source position must be an integer.") from exc
        result_key = str(value["result_key"]).strip()
        if not result_key:
            raise serializers.ValidationError("Condition result key is required.")
        return {
            "source_position": source_position,
            "result_key": result_key,
            "operator": operator,
            "value": value["value"],
        }

    def validate_max_retries(self, value):
        if value > 10:
            raise serializers.ValidationError("Maximum retries cannot exceed 10.")
        return value


class PipelineTemplateSerializer(serializers.ModelSerializer):
    steps = PipelineTemplateStepSerializer(many=True)
    default_project_code = serializers.CharField(
        source="default_project.code",
        read_only=True,
        allow_null=True,
        default=None,
    )
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    run_count = serializers.IntegerField(source="runs.count", read_only=True)

    class Meta:
        model = PipelineTemplate
        fields = [
            "id",
            "code",
            "name",
            "description",
            "active",
            "is_default",
            "default_project",
            "default_project_code",
            "default_sample_type",
            "steps",
            "run_count",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "default_project_code",
            "run_count",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]

    def validate_code(self, value):
        normalized = str(value or "").strip().upper()
        if not normalized:
            raise serializers.ValidationError("Pipeline code is required.")
        return normalized

    def validate_default_sample_type(self, value):
        return str(value or "").strip().upper()

    def validate_steps(self, value):
        if not value:
            raise serializers.ValidationError("A pipeline needs at least one ordered step.")
        positions = [item["position"] for item in value]
        if any(position < 1 for position in positions):
            raise serializers.ValidationError("Step positions must start at 1 or greater.")
        if len(positions) != len(set(positions)):
            raise serializers.ValidationError("Step positions must be unique.")
        ordered = sorted(value, key=lambda item: item["position"])
        known_positions = set(positions)
        for index, item in enumerate(ordered):
            position = item["position"]
            # Omitted dependencies retain the historical sequential behavior.
            if "dependency_positions" not in item or item["dependency_positions"] is None:
                item["dependency_positions"] = [] if index == 0 else [ordered[index - 1]["position"]]
            dependencies = item["dependency_positions"]
            unknown = set(dependencies) - known_positions
            if unknown:
                raise serializers.ValidationError(
                    f"Step {position} depends on unknown positions: {sorted(unknown)}."
                )
            if any(dependency >= position for dependency in dependencies):
                raise serializers.ValidationError(
                    f"Step {position} may depend only on earlier positions."
                )
            condition = item.get("activation_condition") or {}
            if condition and condition["source_position"] not in dependencies:
                raise serializers.ValidationError(
                    f"Step {position}'s condition source must be one of its dependencies."
                )
        return ordered

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = self.instance
        active = attrs.get("active", instance.active if instance else True)
        is_default = attrs.get("is_default", instance.is_default if instance else False)
        project = attrs.get("default_project", instance.default_project if instance else None)
        sample_type = attrs.get(
            "default_sample_type",
            instance.default_sample_type if instance else "",
        )
        if active and is_default:
            duplicates = PipelineTemplate.objects.filter(
                active=True,
                is_default=True,
                default_project=project,
                default_sample_type=sample_type,
            )
            if instance:
                duplicates = duplicates.exclude(pk=instance.pk)
            if duplicates.exists():
                scope = project.code if project else "all projects"
                type_scope = sample_type or "all sample types"
                raise serializers.ValidationError({
                    "is_default": f"A default already exists for {scope} / {type_scope}."
                })
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        steps = validated_data.pop("steps")
        template = PipelineTemplate.objects.create(**validated_data)
        PipelineTemplateStep.objects.bulk_create(
            [PipelineTemplateStep(template=template, **step) for step in steps]
        )
        return template

    @transaction.atomic
    def update(self, instance, validated_data):
        steps = validated_data.pop("steps", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if steps is not None:
            instance.steps.all().delete()
            PipelineTemplateStep.objects.bulk_create(
                [PipelineTemplateStep(template=instance, **step) for step in steps]
            )
        return instance


class PipelineStepRunSerializer(serializers.ModelSerializer):
    work_item_status = serializers.CharField(source="work_item.status", read_only=True)
    work_item_qc_status = serializers.CharField(source="work_item.qc_status", read_only=True)
    assigned_to_username = serializers.CharField(
        source="work_item.assigned_to.username",
        read_only=True,
        allow_null=True,
        default=None,
    )

    class Meta:
        model = PipelineStepRun
        fields = [
            "id",
            "position",
            "name",
            "analysis_code",
            "procedure_code",
            "procedure_version",
            "work_type",
            "required_fields",
            "requires_qc",
            "dependency_positions",
            "activation_condition",
            "optional",
            "max_retries",
            "retry_count",
            "estimated_duration_minutes",
            "status",
            "work_item",
            "work_item_status",
            "work_item_qc_status",
            "assigned_to_username",
            "started_at",
            "completed_at",
            "failure_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PipelineRunSerializer(serializers.ModelSerializer):
    sample_code = serializers.CharField(source="sample.sample_id", read_only=True)
    sample_type = serializers.CharField(source="sample.sample_type", read_only=True)
    project_code = serializers.CharField(
        source="sample.project.code",
        read_only=True,
        allow_null=True,
        default=None,
    )
    started_by_username = serializers.CharField(source="started_by.username", read_only=True)
    steps = PipelineStepRunSerializer(many=True, read_only=True)
    current_step = serializers.SerializerMethodField()
    current_steps = serializers.SerializerMethodField()

    class Meta:
        model = PipelineRun
        fields = [
            "id",
            "public_id",
            "sample",
            "sample_code",
            "sample_type",
            "project_code",
            "template",
            "template_code",
            "template_name",
            "status",
            "current_step",
            "current_steps",
            "steps",
            "started_by",
            "started_by_username",
            "started_at",
            "completed_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_current_step(self, obj):
        terminal = {
            PipelineStepRun.STATUS_COMPLETED,
            PipelineStepRun.STATUS_CANCELLED,
        }
        step = next((item for item in obj.steps.all() if item.status not in terminal), None)
        return PipelineStepRunSerializer(step).data if step else None

    def get_current_steps(self, obj):
        active = {
            PipelineStepRun.STATUS_READY,
            PipelineStepRun.STATUS_IN_PROGRESS,
            PipelineStepRun.STATUS_AWAITING_QC,
            PipelineStepRun.STATUS_FAILED,
        }
        steps = [item for item in obj.steps.all() if item.status in active]
        return PipelineStepRunSerializer(steps, many=True).data


class PipelineRunStartSerializer(serializers.Serializer):
    sample = serializers.IntegerField()
    template = serializers.IntegerField(required=False, allow_null=True)


class WorkflowAssignmentSerializer(serializers.Serializer):
    SCOPE_SAMPLE = "SAMPLE"
    SCOPE_BATCH = "BATCH"
    SCOPE_PROJECT = "PROJECT"
    ASSIGNMENT_ANALYSIS = "ANALYSIS"
    ASSIGNMENT_PIPELINE = "PIPELINE"

    scope_type = serializers.ChoiceField(
        choices=[SCOPE_SAMPLE, SCOPE_BATCH, SCOPE_PROJECT]
    )
    assignment_type = serializers.ChoiceField(
        choices=[ASSIGNMENT_ANALYSIS, ASSIGNMENT_PIPELINE]
    )
    sample = serializers.IntegerField(required=False)
    batch = serializers.IntegerField(required=False)
    project = serializers.IntegerField(required=False)
    analysis = serializers.IntegerField(required=False)
    pipeline_template = serializers.IntegerField(required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        scope_type = attrs["scope_type"]
        assignment_type = attrs["assignment_type"]
        scope_fields = {
            self.SCOPE_SAMPLE: "sample",
            self.SCOPE_BATCH: "batch",
            self.SCOPE_PROJECT: "project",
        }
        expected_scope_field = scope_fields[scope_type]
        supplied_scope_fields = [
            field for field in scope_fields.values() if attrs.get(field) is not None
        ]
        if supplied_scope_fields != [expected_scope_field]:
            raise serializers.ValidationError({
                expected_scope_field: (
                    f"Provide only {expected_scope_field} when scope_type is {scope_type}."
                )
            })

        expected_assignment_field = (
            "analysis"
            if assignment_type == self.ASSIGNMENT_ANALYSIS
            else "pipeline_template"
        )
        supplied_assignment_fields = [
            field
            for field in ["analysis", "pipeline_template"]
            if attrs.get(field) is not None
        ]
        if supplied_assignment_fields != [expected_assignment_field]:
            raise serializers.ValidationError({
                expected_assignment_field: (
                    f"Provide only {expected_assignment_field} when assignment_type "
                    f"is {assignment_type}."
                )
            })
        return attrs


class PipelineRunCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=10, max_length=2000)


class PipelineStepRetrySerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=10, max_length=2000)
