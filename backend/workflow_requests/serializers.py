from rest_framework import serializers

from inventory.models import InventoryReservation

from .models import (
    AssayRequestType,
    RequestResourceRequirement,
    WorkflowRequest,
    WorkflowRequestItem,
    WorkflowRequestMessage,
    WorkflowRequestReport,
    WorkflowRunGroup,
)


class RequestResourceRequirementSerializer(serializers.ModelSerializer):
    inventory_item_code = serializers.CharField(source="inventory_item.code", read_only=True)

    class Meta:
        model = RequestResourceRequirement
        fields = [
            "id", "public_id", "request_type", "kind", "inventory_item",
            "inventory_item_code", "quantity", "unit", "instrument_name",
            "personnel_role", "estimated_duration_minutes", "pipeline_step_position", "required",
        ]
        read_only_fields = ["id", "public_id", "inventory_item_code"]


class AssayRequestTypeSerializer(serializers.ModelSerializer):
    default_pipeline_code = serializers.CharField(source="default_pipeline.code", read_only=True)
    project_code = serializers.CharField(source="project.code", read_only=True)
    resource_requirements = RequestResourceRequirementSerializer(many=True, read_only=True)

    class Meta:
        model = AssayRequestType
        fields = [
            "id", "public_id", "code", "name", "description", "version", "form_schema",
            "default_pipeline", "default_pipeline_code", "project", "project_code",
            "default_priority", "sla_hours", "active", "resource_requirements",
            "created_by", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "public_id", "default_pipeline_code", "project_code", "created_by", "created_at", "updated_at"]


class WorkflowRequestItemSerializer(serializers.ModelSerializer):
    sample_code = serializers.CharField(source="sample.sample_id", read_only=True)
    registry_id = serializers.CharField(source="registry_record.registry_id", read_only=True)
    pipeline_run_public_id = serializers.UUIDField(source="pipeline_run.public_id", read_only=True)
    execution = serializers.SerializerMethodField()
    reservations = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowRequestItem
        fields = [
            "id", "public_id", "request", "sample", "sample_code", "registry_record",
            "registry_id", "study_public_id", "pipeline_run", "pipeline_run_public_id",
            "notes", "status", "execution", "reservations", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "public_id", "pipeline_run", "pipeline_run_public_id", "execution", "reservations", "created_at", "updated_at"]

    def get_execution(self, obj):
        if not obj.pipeline_run_id:
            return None
        return {
            "status": obj.pipeline_run.status,
            "template": obj.pipeline_run.template_code,
            "steps": [
                {
                    "position": step.position,
                    "name": step.name,
                    "status": step.status,
                    "work_item_public_id": str(step.work_item.public_id) if step.work_item else None,
                    "work_item_status": step.work_item.status if step.work_item else None,
                    "qc_status": step.work_item.qc_status if step.work_item else None,
                    "results": [
                        {"key": result.key, "value": result.value, "unit": result.unit, "qc_status": result.qc_status}
                        for result in step.work_item.results.all()
                    ] if step.work_item else [],
                }
                for step in obj.pipeline_run.steps.all()
            ],
        }

    def get_reservations(self, obj):
        return [
            {
                "public_id": str(row.public_id),
                "lot_code": row.lot.lot_code,
                "quantity": str(row.quantity),
                "unit": row.unit,
                "status": row.status,
            }
            for row in InventoryReservation.objects.filter(request_item_public_id=obj.public_id).select_related("lot")
        ]


class WorkflowRequestMessageSerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source="author.username", read_only=True)

    class Meta:
        model = WorkflowRequestMessage
        fields = ["id", "public_id", "request", "author", "author_username", "body", "internal_only", "created_at"]
        read_only_fields = ["id", "public_id", "author", "author_username", "created_at"]


class WorkflowRequestReportSerializer(serializers.ModelSerializer):
    uploaded_by_username = serializers.CharField(source="uploaded_by.username", read_only=True)
    approved_by_username = serializers.CharField(source="approved_by.username", read_only=True)

    class Meta:
        model = WorkflowRequestReport
        fields = [
            "id", "public_id", "request", "title", "file", "checksum_sha256",
            "uploaded_by", "uploaded_by_username", "approved", "approved_by",
            "approved_by_username", "approved_at", "created_at",
        ]
        read_only_fields = ["id", "public_id", "checksum_sha256", "uploaded_by", "uploaded_by_username", "approved", "approved_by", "approved_by_username", "approved_at", "created_at"]


class WorkflowRunGroupSerializer(serializers.ModelSerializer):
    batch_code = serializers.CharField(source="batch.code", read_only=True)
    plate_code = serializers.CharField(source="plate.container_id", read_only=True)

    class Meta:
        model = WorkflowRunGroup
        fields = [
            "id", "public_id", "request", "name", "batch", "batch_code", "plate",
            "plate_code", "items", "pipeline_runs", "created_by", "created_at",
        ]
        read_only_fields = ["id", "public_id", "batch_code", "plate_code", "created_by", "created_at"]


class WorkflowRequestSerializer(serializers.ModelSerializer):
    request_type_code = serializers.CharField(source="request_type.code", read_only=True)
    project_code = serializers.CharField(source="project.code", read_only=True)
    requester_username = serializers.CharField(source="requester.username", read_only=True)
    assigned_pipeline_code = serializers.CharField(source="assigned_pipeline.code", read_only=True)
    approved_by_username = serializers.CharField(source="approved_by.username", read_only=True)
    items = WorkflowRequestItemSerializer(many=True, read_only=True)
    messages = serializers.SerializerMethodField()
    reports = serializers.SerializerMethodField()
    run_groups = WorkflowRunGroupSerializer(many=True, read_only=True)
    sample_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    registry_record_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)

    class Meta:
        model = WorkflowRequest
        fields = [
            "id", "public_id", "request_number", "request_type", "request_type_code",
            "project", "project_code", "requester", "requester_username", "title", "form_data",
            "status", "priority", "due_at", "assigned_pipeline", "assigned_pipeline_code",
            "triaged_by", "triaged_at", "approved_by", "approved_by_username", "approved_at",
            "decision_reason", "submitted_at", "completed_at", "created_at", "updated_at",
            "items", "messages", "reports", "run_groups", "sample_ids", "registry_record_ids",
        ]
        read_only_fields = [
            "id", "public_id", "request_number", "requester", "requester_username", "status",
            "triaged_by", "triaged_at", "approved_by", "approved_by_username", "approved_at",
            "decision_reason", "submitted_at", "completed_at", "created_at", "updated_at",
            "items", "messages", "reports", "run_groups", "request_type_code", "project_code",
            "assigned_pipeline_code",
        ]

    def get_messages(self, obj):
        from core.permissions import is_admin, is_tech

        user = self.context.get("request").user if self.context.get("request") else None
        messages = obj.messages.all()
        if not user or not (is_admin(user) or is_tech(user)):
            messages = messages.filter(internal_only=False)
        return WorkflowRequestMessageSerializer(messages, many=True, context=self.context).data

    def get_reports(self, obj):
        from core.permissions import is_admin, is_tech

        user = self.context.get("request").user if self.context.get("request") else None
        reports = obj.reports.all()
        if not user or not (is_admin(user) or is_tech(user)):
            reports = reports.filter(approved=True)
        return WorkflowRequestReportSerializer(reports, many=True, context=self.context).data
