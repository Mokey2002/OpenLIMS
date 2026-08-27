from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response

from core.audit import record_audit_event
from core.permissions import is_admin, is_tech
from notifications.models import Notification
from pipelines.models import PipelineTemplate
from registry.services import registry_records_for_user
from samples.access import get_sample_access_queryset
from samples.models import Sample

from .models import (
    AssayRequestType,
    RequestResourceRequirement,
    WorkflowRequest,
    WorkflowRequestItem,
    WorkflowRequestMessage,
    WorkflowRequestReport,
    WorkflowRunGroup,
)
from .permissions import user_can_operate_request, user_can_submit, workflow_requests_for_user
from .serializers import (
    AssayRequestTypeSerializer,
    RequestResourceRequirementSerializer,
    WorkflowRequestItemSerializer,
    WorkflowRequestMessageSerializer,
    WorkflowRequestReportSerializer,
    WorkflowRequestSerializer,
    WorkflowRunGroupSerializer,
)
from .services import approve_request, file_checksum, next_request_number, validate_submission_form


class RequestConfigurationPermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return is_admin(request.user)


class AssayRequestTypeViewSet(viewsets.ModelViewSet):
    permission_classes = [RequestConfigurationPermission]
    serializer_class = AssayRequestTypeSerializer

    def get_queryset(self):
        queryset = AssayRequestType.objects.select_related("default_pipeline", "project", "created_by").prefetch_related("resource_requirements__inventory_item")
        if is_admin(self.request.user):
            return queryset
        return queryset.filter(Q(project__isnull=True) | Q(project__members=self.request.user), active=True).distinct()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class RequestResourceRequirementViewSet(viewsets.ModelViewSet):
    permission_classes = [RequestConfigurationPermission]
    serializer_class = RequestResourceRequirementSerializer
    queryset = RequestResourceRequirement.objects.select_related("request_type", "inventory_item").all()


class WorkflowRequestViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowRequestSerializer

    def get_queryset(self):
        queryset = (
            workflow_requests_for_user(self.request.user)
            .select_related("request_type", "project", "requester", "assigned_pipeline", "approved_by")
            .prefetch_related(
                "items__sample", "items__registry_record", "items__pipeline_run__steps__work_item__results",
                "messages__author", "reports", "run_groups__items", "run_groups__pipeline_runs",
            )
        )
        if not is_admin(self.request.user) and not is_tech(self.request.user):
            queryset = queryset.prefetch_related("reports")
        return queryset

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = serializer.validated_data["project"]
        if not user_can_submit(request.user, project):
            raise PermissionDenied("You must belong to the selected project.")
        request_type = serializer.validated_data["request_type"]
        if request_type.project_id not in {None, project.pk}:
            raise ValidationError({"request_type": "This request type belongs to another project."})
        form_data = validate_submission_form(request_type.form_schema, serializer.validated_data.get("form_data", {}))
        sample_ids = serializer.validated_data.pop("sample_ids", [])
        registry_ids = serializer.validated_data.pop("registry_record_ids", [])
        samples = list(get_sample_access_queryset(Sample.objects.filter(pk__in=sample_ids), request.user))
        if len(samples) != len(set(sample_ids)):
            raise ValidationError({"sample_ids": "One or more samples are inaccessible."})
        if any(sample.project_id != project.pk for sample in samples):
            raise ValidationError({"sample_ids": "All selected samples must belong to the request project."})
        registry_records = list(registry_records_for_user(request.user).filter(pk__in=registry_ids))
        if len(registry_records) != len(set(registry_ids)):
            raise ValidationError({"registry_record_ids": "One or more registry records are inaccessible."})
        if not samples and not registry_records:
            raise ValidationError({"items": "Select at least one sample or registry record."})
        due_at = serializer.validated_data.get("due_at") or timezone.now() + timedelta(hours=request_type.sla_hours)
        workflow_request = serializer.save(
            request_number=next_request_number(),
            requester=request.user,
            form_data=form_data,
            status=WorkflowRequest.STATUS_SUBMITTED,
            priority=serializer.validated_data.get("priority") or request_type.default_priority,
            due_at=due_at,
            assigned_pipeline=serializer.validated_data.get("assigned_pipeline") or request_type.default_pipeline,
            submitted_at=timezone.now(),
        )
        WorkflowRequestItem.objects.bulk_create(
            [WorkflowRequestItem(request=workflow_request, sample=sample) for sample in samples]
            + [WorkflowRequestItem(request=workflow_request, registry_record=record) for record in registry_records]
        )
        record_audit_event(entity=workflow_request, action="WORKFLOW_REQUEST_SUBMITTED", actor=request.user, after={"status": workflow_request.status, "item_count": len(samples) + len(registry_records)}, details={"due_at": due_at.isoformat(), "priority": workflow_request.priority})
        workflow_request.refresh_from_db()
        return Response(self.get_serializer(workflow_request).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        workflow_request = self.get_object()
        if workflow_request.status != WorkflowRequest.STATUS_DRAFT or workflow_request.requester_id != self.request.user.pk:
            raise ValidationError({"status": "Only the requester can edit a draft request."})
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        raise ValidationError({"detail": "Workflow requests are retained for audit history."})

    @action(detail=True, methods=["post"])
    def triage(self, request, pk=None):
        workflow_request = self.get_object()
        if not user_can_operate_request(request.user, workflow_request):
            raise PermissionDenied("You cannot triage this request.")
        if workflow_request.status != WorkflowRequest.STATUS_SUBMITTED:
            raise ValidationError({"status": "Only submitted requests can enter triage."})
        workflow_request.status = WorkflowRequest.STATUS_TRIAGE
        workflow_request.triaged_by = request.user
        workflow_request.triaged_at = timezone.now()
        if request.data.get("priority"):
            workflow_request.priority = request.data["priority"]
        if request.data.get("due_at"):
            workflow_request.due_at = request.data["due_at"]
        if request.data.get("pipeline"):
            workflow_request.assigned_pipeline = PipelineTemplate.objects.get(pk=request.data["pipeline"])
        workflow_request.save(update_fields=["status", "triaged_by", "triaged_at", "priority", "due_at", "assigned_pipeline", "updated_at"])
        return Response(self.get_serializer(workflow_request).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        if not is_admin(request.user):
            raise PermissionDenied("Only a director can approve workflow requests.")
        pipeline = PipelineTemplate.objects.filter(pk=request.data.get("pipeline")).first() if request.data.get("pipeline") else None
        workflow_request, reservations, runs = approve_request(
            workflow_request=self.get_object(),
            actor=request.user,
            pipeline=pipeline,
            reason=request.data.get("reason", ""),
            group_name=request.data.get("group_name") or "Approved run group",
        )
        return Response({"request": self.get_serializer(workflow_request).data, "reservation_count": len(reservations), "pipeline_runs": [str(run.public_id) for run in runs]})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        workflow_request = self.get_object()
        if not is_admin(request.user):
            raise PermissionDenied("Only a director can reject workflow requests.")
        if workflow_request.status not in {WorkflowRequest.STATUS_SUBMITTED, WorkflowRequest.STATUS_TRIAGE}:
            raise ValidationError({"status": "This request cannot be rejected now."})
        reason = str(request.data.get("reason") or "").strip()
        if not reason:
            raise ValidationError({"reason": "A rejection reason is required."})
        workflow_request.status = WorkflowRequest.STATUS_REJECTED
        workflow_request.approved_by = request.user
        workflow_request.approved_at = timezone.now()
        workflow_request.decision_reason = reason
        workflow_request.save(update_fields=["status", "approved_by", "approved_at", "decision_reason", "updated_at"])
        Notification.objects.create(user=workflow_request.requester, title=f"Request {workflow_request.request_number} rejected", message=reason, link=f"/workflow-requests?request={workflow_request.public_id}")
        record_audit_event(entity=workflow_request, action="WORKFLOW_REQUEST_REJECTED", actor=request.user, reason=reason, after={"status": workflow_request.status})
        return Response(self.get_serializer(workflow_request).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        workflow_request = self.get_object()
        if not (is_admin(request.user) or workflow_request.requester_id == request.user.pk):
            raise PermissionDenied("Only the requester or a director can cancel this request.")
        if workflow_request.status not in {WorkflowRequest.STATUS_DRAFT, WorkflowRequest.STATUS_SUBMITTED, WorkflowRequest.STATUS_TRIAGE}:
            raise ValidationError({"status": "Approved or completed requests cannot be cancelled here."})
        reason = str(request.data.get("reason") or "").strip()
        if not reason:
            raise ValidationError({"reason": "A cancellation reason is required."})
        workflow_request.status = WorkflowRequest.STATUS_CANCELLED
        workflow_request.decision_reason = reason
        workflow_request.save(update_fields=["status", "decision_reason", "updated_at"])
        record_audit_event(entity=workflow_request, action="WORKFLOW_REQUEST_CANCELLED", actor=request.user, reason=reason, after={"status": workflow_request.status})
        return Response(self.get_serializer(workflow_request).data)

    @action(detail=True, methods=["post"])
    def refresh_status(self, request, pk=None):
        workflow_request = self.get_object()
        if not user_can_operate_request(request.user, workflow_request):
            raise PermissionDenied("You cannot update this request.")
        runs = [item.pipeline_run for item in workflow_request.items.all() if item.pipeline_run]
        if runs and all(run.status == "COMPLETED" for run in runs):
            workflow_request.status = WorkflowRequest.STATUS_COMPLETED
            workflow_request.completed_at = timezone.now()
        elif runs:
            workflow_request.status = WorkflowRequest.STATUS_IN_PROGRESS
        workflow_request.save(update_fields=["status", "completed_at", "updated_at"])
        return Response(self.get_serializer(workflow_request).data)


class WorkflowRequestItemViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowRequestItemSerializer

    def get_queryset(self):
        return WorkflowRequestItem.objects.filter(request__in=workflow_requests_for_user(self.request.user)).select_related("request", "sample", "registry_record", "pipeline_run").prefetch_related("pipeline_run__steps__work_item__results")


class WorkflowRequestMessageViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowRequestMessageSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = WorkflowRequestMessage.objects.filter(request__in=workflow_requests_for_user(self.request.user)).select_related("request", "author")
        if is_admin(self.request.user) or is_tech(self.request.user):
            return queryset
        return queryset.filter(internal_only=False)

    def perform_create(self, serializer):
        workflow_request = serializer.validated_data["request"]
        if not workflow_requests_for_user(self.request.user).filter(pk=workflow_request.pk).exists():
            raise PermissionDenied("You cannot message this request.")
        if serializer.validated_data.get("internal_only") and not user_can_operate_request(self.request.user, workflow_request):
            raise PermissionDenied("Only laboratory staff can post internal messages.")
        message = serializer.save(author=self.request.user)
        if not message.internal_only and workflow_request.requester_id != self.request.user.pk:
            Notification.objects.create(user=workflow_request.requester, title=f"Message on {workflow_request.request_number}", message=message.body[:500], link=f"/workflow-requests?request={workflow_request.public_id}")


class WorkflowRunGroupViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowRunGroupSerializer

    def get_queryset(self):
        return WorkflowRunGroup.objects.filter(request__in=workflow_requests_for_user(self.request.user)).select_related("request", "batch", "plate", "created_by").prefetch_related("items", "pipeline_runs")

    def perform_create(self, serializer):
        workflow_request = serializer.validated_data["request"]
        if not user_can_operate_request(self.request.user, workflow_request):
            raise PermissionDenied("You cannot group runs for this request.")
        serializer.save(created_by=self.request.user)


class WorkflowRequestReportViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowRequestReportSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = WorkflowRequestReport.objects.filter(request__in=workflow_requests_for_user(self.request.user)).select_related("request", "uploaded_by", "approved_by")
        if is_admin(self.request.user) or is_tech(self.request.user):
            return queryset
        return queryset.filter(approved=True)

    def perform_create(self, serializer):
        workflow_request = serializer.validated_data["request"]
        if not user_can_operate_request(self.request.user, workflow_request):
            raise PermissionDenied("You cannot upload reports for this request.")
        upload = serializer.validated_data["file"]
        serializer.save(uploaded_by=self.request.user, checksum_sha256=file_checksum(upload))

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        if not is_admin(request.user):
            raise PermissionDenied("Only a director can approve reports.")
        report = self.get_object()
        report.approved = True
        report.approved_by = request.user
        report.approved_at = timezone.now()
        report.save(update_fields=["approved", "approved_by", "approved_at"])
        Notification.objects.create(user=report.request.requester, title=f"Approved report for {report.request.request_number}", message=report.title, link=f"/workflow-requests?request={report.request.public_id}")
        return Response(self.get_serializer(report).data)
