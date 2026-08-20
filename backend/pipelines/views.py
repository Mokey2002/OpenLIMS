from rest_framework import status
from rest_framework.decorators import action
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
from samples.access import get_sample_access_queryset, require_sample_modify_access
from samples.models import Sample

from .models import AnalysisDefinition, PipelineRun, PipelineTemplate, ProcedureDefinition
from .serializers import (
    AnalysisDefinitionSerializer,
    PipelineRunCancelSerializer,
    PipelineRunSerializer,
    PipelineRunStartSerializer,
    PipelineTemplateSerializer,
    ProcedureDefinitionSerializer,
)
from .services import cancel_pipeline, resolve_default_template, start_pipeline


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
        run_status = self.request.query_params.get("status")
        if sample_id:
            queryset = queryset.filter(sample_id=sample_id)
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

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        run = self.get_object()
        require_sample_modify_access(request.user, run.sample)
        input_serializer = PipelineRunCancelSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        reason = input_serializer.validated_data["reason"]
        run = cancel_pipeline(run=run, actor=request.user, reason=reason)
        return Response(self.get_serializer(run).data)
