from django.db import IntegrityError
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from core.permissions import (
    IsAuthenticatedReadOnlyOrTechAdminWrite,
    is_admin,
    is_qc_reviewer,
    is_tech,
    is_viewer,
)
from events.models import Event
from projects.models import Project
from samples.access import get_sample_access_queryset, require_sample_modify_access
from samples.models import Sample, SampleBatch

from .models import (
    AnalysisDefinition,
    PipelineRun,
    PipelineTemplate,
    ProcedureDefinition,
)
from .serializers import (
    AnalysisDefinitionSerializer,
    PipelineRunCancelSerializer,
    PipelineRunSerializer,
    PipelineRunStartSerializer,
    PipelineTemplateSerializer,
    ProcedureDefinitionSerializer,
    WorkflowAssignmentSerializer,
)
from .services import (
    assign_analysis,
    cancel_pipeline,
    resolve_default_template,
    start_pipeline,
)


MAX_WORKFLOW_ASSIGNMENT_SAMPLES = 500


def _assignment_scope(request, validated_data):
    scope_type = validated_data["scope_type"]
    if scope_type == WorkflowAssignmentSerializer.SCOPE_SAMPLE:
        sample = (
            get_sample_access_queryset(
                Sample.objects.select_related("project", "batch"),
                request.user,
            )
            .filter(pk=validated_data["sample"])
            .first()
        )
        if not sample:
            raise NotFound("Sample not found.")
        require_sample_modify_access(request.user, sample)
        return [sample], sample.id, sample.sample_id

    if scope_type == WorkflowAssignmentSerializer.SCOPE_BATCH:
        batches = SampleBatch.objects.select_related("project")
        if not is_admin(request.user):
            batches = batches.filter(project__members=request.user)
        batch = batches.filter(pk=validated_data["batch"]).first()
        if not batch:
            raise NotFound("Sample batch not found.")
        samples = list(
            Sample.objects.select_related("project", "batch")
            .filter(batch=batch)
            .order_by("sample_id")
        )
        return samples, batch.id, batch.code

    projects = Project.objects.all()
    if not is_admin(request.user):
        projects = projects.filter(members=request.user)
    project = projects.filter(pk=validated_data["project"]).first()
    if not project:
        raise NotFound("Project not found.")
    samples = list(
        Sample.objects.select_related("project", "batch")
        .filter(project=project)
        .order_by("sample_id")
    )
    return samples, project.id, project.code


def _assignment_error_message(exc):
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        detail = detail.get("detail") or next(iter(detail.values()), None)
    if isinstance(detail, (list, tuple)):
        detail = detail[0] if detail else None
    return str(detail or exc)


def _configuration_event(request, instance, action):
    Event.objects.create(
        entity_type=instance.__class__.__name__,
        entity_id=str(instance.id),
        action=action,
        actor=request.user,
        payload={
            "id": instance.id,
            "code": getattr(instance, "code", None),
            "name": getattr(instance, "name", None),
            "active": getattr(instance, "active", None),
        },
    )


class PipelineConfigurationPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return is_admin(user) or is_tech(user) or is_viewer(user) or is_qc_reviewer(user)
        return is_admin(user)


class ImmutableDeleteMixin:
    def destroy(self, request, *args, **kwargs):
        return Response(
            {"detail": "Configuration records are retained for audit history. Set active=false instead."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class AnalysisDefinitionViewSet(ImmutableDeleteMixin, ModelViewSet):
    permission_classes = [PipelineConfigurationPermission]
    serializer_class = AnalysisDefinitionSerializer

    def get_queryset(self):
        queryset = AnalysisDefinition.objects.select_related("created_by").all()
        return queryset if is_admin(self.request.user) else queryset.filter(active=True)

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        _configuration_event(self.request, instance, "ANALYSIS_DEFINITION_CREATED")

    def perform_update(self, serializer):
        instance = serializer.save()
        _configuration_event(self.request, instance, "ANALYSIS_DEFINITION_UPDATED")


class ProcedureDefinitionViewSet(ImmutableDeleteMixin, ModelViewSet):
    permission_classes = [PipelineConfigurationPermission]
    serializer_class = ProcedureDefinitionSerializer

    def get_queryset(self):
        queryset = ProcedureDefinition.objects.select_related(
            "analysis", "sop_document", "created_by"
        ).all()
        return queryset if is_admin(self.request.user) else queryset.filter(active=True, analysis__active=True)

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        _configuration_event(self.request, instance, "PROCEDURE_DEFINITION_CREATED")

    def perform_update(self, serializer):
        instance = serializer.save()
        _configuration_event(self.request, instance, "PROCEDURE_DEFINITION_UPDATED")


class PipelineTemplateViewSet(ImmutableDeleteMixin, ModelViewSet):
    permission_classes = [PipelineConfigurationPermission]
    serializer_class = PipelineTemplateSerializer

    def get_queryset(self):
        queryset = (
            PipelineTemplate.objects.select_related("default_project", "created_by")
            .prefetch_related("steps__procedure__analysis")
            .all()
        )
        return queryset if is_admin(self.request.user) else queryset.filter(active=True)

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        _configuration_event(self.request, instance, "PIPELINE_TEMPLATE_CREATED")

    def perform_update(self, serializer):
        instance = serializer.save()
        _configuration_event(self.request, instance, "PIPELINE_TEMPLATE_UPDATED")


class PipelineRunViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = PipelineRunSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        allowed_samples = get_sample_access_queryset(Sample.objects.all(), self.request.user)
        queryset = (
            PipelineRun.objects.select_related(
                "sample",
                "sample__project",
                "template",
                "started_by",
            )
            .prefetch_related("steps__work_item__assigned_to")
            .filter(sample__in=allowed_samples)
        )
        sample_id = self.request.query_params.get("sample")
        project_id = self.request.query_params.get("project")
        batch_id = self.request.query_params.get("batch")
        run_status = self.request.query_params.get("status")
        if sample_id:
            queryset = queryset.filter(sample_id=sample_id)
        if project_id:
            queryset = queryset.filter(sample__project_id=project_id)
        if batch_id:
            queryset = queryset.filter(sample__batch_id=batch_id)
        if run_status:
            queryset = queryset.filter(status=run_status)
        return queryset

    def create(self, request, *args, **kwargs):
        input_serializer = PipelineRunStartSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        sample = get_sample_access_queryset(Sample.objects.all(), request.user).filter(
            pk=input_serializer.validated_data["sample"]
        ).first()
        if not sample:
            return Response({"detail": "Sample not found."}, status=status.HTTP_404_NOT_FOUND)
        require_sample_modify_access(request.user, sample)

        template_id = input_serializer.validated_data.get("template")
        if template_id:
            template = PipelineTemplate.objects.filter(pk=template_id, active=True).first()
            if not template:
                return Response(
                    {"template": "Active pipeline template not found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            template = resolve_default_template(sample)
            if not template:
                return Response(
                    {"template": "No default pipeline matches this sample's project and sample type."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        run = start_pipeline(sample=sample, template=template, actor=request.user)
        output = self.get_serializer(run)
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="assign")
    def assign(self, request):
        input_serializer = WorkflowAssignmentSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        validated = input_serializer.validated_data
        samples, scope_id, scope_label = _assignment_scope(request, validated)
        if not samples:
            raise ValidationError({"scope": "The selected scope contains no samples."})
        if len(samples) > MAX_WORKFLOW_ASSIGNMENT_SAMPLES:
            raise ValidationError({
                "scope": (
                    f"A single assignment is limited to {MAX_WORKFLOW_ASSIGNMENT_SAMPLES} "
                    "samples. Select a smaller batch."
                )
            })

        assignment_type = validated["assignment_type"]
        assignment = None
        if assignment_type == WorkflowAssignmentSerializer.ASSIGNMENT_PIPELINE:
            assignment = PipelineTemplate.objects.filter(
                pk=validated["pipeline_template"],
                active=True,
            ).first()
            if not assignment:
                raise ValidationError({
                    "pipeline_template": "Active pipeline template not found."
                })
        else:
            assignment = AnalysisDefinition.objects.filter(
                pk=validated["analysis"],
                active=True,
            ).first()
            if not assignment:
                raise ValidationError({"analysis": "Active analysis not found."})

        assigned = []
        skipped = []
        for sample in samples:
            if sample.status in [Sample.STATUS_CANCELLED, Sample.STATUS_ARCHIVED]:
                skipped.append({
                    "sample": sample.id,
                    "sample_code": sample.sample_id,
                    "reason": f"Samples in {sample.status} status cannot receive new work.",
                })
                continue
            try:
                if assignment_type == WorkflowAssignmentSerializer.ASSIGNMENT_PIPELINE:
                    run = start_pipeline(
                        sample=sample,
                        template=assignment,
                        actor=request.user,
                    )
                    assigned.append({
                        "sample": sample.id,
                        "sample_code": sample.sample_id,
                        "pipeline_run": run.id,
                    })
                else:
                    work_item = assign_analysis(
                        sample=sample,
                        analysis=assignment,
                        actor=request.user,
                        scope_type=validated["scope_type"],
                        scope_id=scope_id,
                    )
                    assigned.append({
                        "sample": sample.id,
                        "sample_code": sample.sample_id,
                        "work_item": work_item.id,
                    })
            except (IntegrityError, ValidationError) as exc:
                skipped.append({
                    "sample": sample.id,
                    "sample_code": sample.sample_id,
                    "reason": _assignment_error_message(exc),
                })

        event_entity_type = {
            WorkflowAssignmentSerializer.SCOPE_SAMPLE: "Sample",
            WorkflowAssignmentSerializer.SCOPE_BATCH: "SampleBatch",
            WorkflowAssignmentSerializer.SCOPE_PROJECT: "Project",
        }[validated["scope_type"]]
        Event.objects.create(
            entity_type=event_entity_type,
            entity_id=str(scope_id),
            action="WORKFLOW_ASSIGNMENT_COMPLETED",
            actor=request.user,
            payload={
                "scope_type": validated["scope_type"],
                "scope_id": scope_id,
                "scope_label": scope_label,
                "project_id": (
                    samples[0].project_id if samples and samples[0].project_id else None
                ),
                "assignment_type": assignment_type,
                "assignment_id": assignment.id,
                "assignment_code": assignment.code,
                "assignment_name": assignment.name,
                "assigned_sample_ids": [item["sample"] for item in assigned],
                "skipped_sample_ids": [item["sample"] for item in skipped],
                "assigned_count": len(assigned),
                "skipped_count": len(skipped),
            },
        )

        response_data = {
            "scope": {
                "type": validated["scope_type"],
                "id": scope_id,
                "label": scope_label,
                "sample_count": len(samples),
            },
            "assignment": {
                "type": assignment_type,
                "id": assignment.id,
                "code": assignment.code,
                "name": assignment.name,
            },
            "assigned_count": len(assigned),
            "skipped_count": len(skipped),
            "assigned": assigned,
            "skipped": skipped,
        }
        response_status = (
            status.HTTP_201_CREATED if assigned else status.HTTP_200_OK
        )
        return Response(response_data, status=response_status)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        run = self.get_object()
        require_sample_modify_access(request.user, run.sample)
        input_serializer = PipelineRunCancelSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        reason = input_serializer.validated_data["reason"]
        run = cancel_pipeline(run=run, actor=request.user, reason=reason)
        return Response(self.get_serializer(run).data)
