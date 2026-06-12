from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.response import Response

from core.permissions import is_admin, is_tech
from events.models import Event

from .models import MassSpecRun
from .serializers import MassSpecRunSerializer
from .tasks import process_mass_spec_run_task


class MassSpecRunPermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            return True

        return is_admin(request.user) or is_tech(request.user)


class MassSpecRunViewSet(viewsets.ModelViewSet):
    serializer_class = MassSpecRunSerializer
    permission_classes = [MassSpecRunPermission]

    def get_queryset(self):
        queryset = (
            MassSpecRun.objects
            .select_related("project", "sample", "uploaded_by")
            .all()
            .order_by("-created_at")
        )

        project = self.request.query_params.get("project")
        sample = self.request.query_params.get("sample")
        status = self.request.query_params.get("status")
        search = self.request.query_params.get("search")

        if project:
            queryset = queryset.filter(project_id=project)

        if sample:
            queryset = queryset.filter(sample_id=sample)

        if status:
            queryset = queryset.filter(status__iexact=status)

        if search:
            queryset = queryset.filter(name__icontains=search)

        return queryset

    def perform_create(self, serializer):
        uploaded_file = self.request.FILES.get("uploaded_file")

        run = serializer.save(
            uploaded_by=self.request.user,
            original_filename=uploaded_file.name if uploaded_file else "",
            status=MassSpecRun.STATUS_PENDING,
        )

        Event.objects.create(
            entity_type="mass_spec_run",
            entity_id=str(run.id),
            action="MASS_SPEC_UPLOADED",
            actor=self.request.user,
            payload={
                "name": run.name,
                "original_filename": run.original_filename,
                "project": run.project_id,
                "sample": run.sample_id,
            },
        )

        process_mass_spec_run_task.delay(run.id)

    @action(detail=True, methods=["post"], url_path="reprocess")
    def reprocess(self, request, pk=None):
        run = self.get_object()
        run.status = MassSpecRun.STATUS_PENDING
        run.error_message = ""
        run.save(update_fields=["status", "error_message"])

        Event.objects.create(
            entity_type="mass_spec_run",
            entity_id=str(run.id),
            action="MASS_SPEC_REPROCESS_QUEUED",
            actor=request.user,
            payload={
                "name": run.name,
                "original_filename": run.original_filename,
            },
        )

        process_mass_spec_run_task.delay(run.id)

        return Response(self.get_serializer(run).data)
