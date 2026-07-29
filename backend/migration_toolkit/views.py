import csv
import json
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.http import HttpResponse

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite
from core.upload_validators import validate_text_file, validate_uploaded_file
from projects.models import Project
from samples.access import validate_sample_project_assignment

from .models import (
    MigrationFieldMapping,
    MigrationJob,
    MigrationProfile,
    MigrationRowRecord,
    SampleExternalID,
)
from .serializers import (
    MigrationFieldMappingSerializer,
    MigrationJobSerializer,
    MigrationProfileSerializer,
    MigrationRowRecordSerializer,
    SampleExternalIDSerializer,
)
from .services import build_preview, suggest_field_mappings
from .tasks import run_migration_job


class SampleExternalIDViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = SampleExternalIDSerializer

    def get_queryset(self):
        return (
            SampleExternalID.objects
            .select_related("sample", "sample__project")
            .all()
            .order_by("-created_at")
        )


class MigrationProfileViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = MigrationProfileSerializer

    def get_queryset(self):
        return (
            MigrationProfile.objects
            .select_related("created_by")
            .prefetch_related("field_mappings")
            .all()
            .order_by("name")
        )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class MigrationFieldMappingViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = MigrationFieldMappingSerializer

    def get_queryset(self):
        queryset = (
            MigrationFieldMapping.objects
            .select_related("profile")
            .all()
            .order_by("profile__name", "id")
        )

        profile_id = self.request.query_params.get("profile")

        if profile_id:
            queryset = queryset.filter(profile_id=profile_id)

        return queryset



class MigrationRowRecordViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = MigrationRowRecordSerializer

    def get_queryset(self):
        queryset = (
            MigrationRowRecord.objects
            .select_related("migration_job", "project", "sample")
            .all()
            .order_by("-created_at", "row_number")
        )

        job_id = self.request.query_params.get("job")
        project_id = self.request.query_params.get("project")
        sample_id = self.request.query_params.get("sample")
        status_filter = self.request.query_params.get("status")
        search = self.request.query_params.get("search")

        if job_id:
            queryset = queryset.filter(migration_job_id=job_id)

        if project_id:
            queryset = queryset.filter(project_id=project_id)

        if sample_id:
            queryset = queryset.filter(sample_id=sample_id)

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        if search:
            queryset = queryset.filter(
                Q(project_code__icontains=search)
                | Q(project_name__icontains=search)
                | Q(sample_code__icontains=search)
                | Q(raw_row_text__icontains=search)
            )

        return queryset


class MigrationJobViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = MigrationJobSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return (
            MigrationJob.objects
            .select_related("profile", "project", "uploaded_by")
            .all()
            .order_by("-created_at")
        )

    def _get_profile(self, request):
        profile_id = request.data.get("profile")

        if not profile_id:
            return None, Response(
                {"detail": "profile is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = (
            MigrationProfile.objects
            .prefetch_related("field_mappings")
            .filter(id=profile_id)
            .first()
        )

        if not profile:
            return None, Response(
                {"detail": "Migration profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return profile, None

    def _get_project(self, request):
        project_id = request.data.get("project")

        if not project_id:
            return None, None

        project = Project.objects.filter(id=project_id).first()

        if not project:
            return None, Response(
                {"detail": "Project not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            validate_sample_project_assignment(request.user, project)
        except Exception as exc:
            return None, Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return project, None

    def _validate_file(self, uploaded_file):
        try:
            validate_uploaded_file(
                uploaded_file,
                allowed_extensions=[".csv", ".txt"],
            )
            validate_text_file(uploaded_file)
        except DjangoValidationError as exc:
            return Response(
                {"uploaded_file": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return None

    @action(detail=False, methods=["post"], url_path="suggest-mappings")
    def suggest_mappings(self, request):
        profile, error_response = self._get_profile(request)

        if error_response:
            return error_response

        uploaded_file = request.data.get("uploaded_file")

        if not uploaded_file:
            return Response(
                {"detail": "uploaded_file is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        error_response = self._validate_file(uploaded_file)

        if error_response:
            return error_response

        try:
            summary = suggest_field_mappings(
                profile=profile,
                uploaded_file=uploaded_file,
            )
        except Exception as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(summary, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request):
        profile, error_response = self._get_profile(request)

        if error_response:
            return error_response

        project, error_response = self._get_project(request)

        if error_response:
            return error_response

        uploaded_file = request.data.get("uploaded_file")

        if not uploaded_file:
            return Response(
                {"detail": "uploaded_file is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        error_response = self._validate_file(uploaded_file)

        if error_response:
            return error_response

        try:
            summary = build_preview(
                profile=profile,
                uploaded_file=uploaded_file,
                default_project=project,
            )
        except Exception as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job = MigrationJob.objects.create(
            profile=profile,
            project=project,
            uploaded_file=uploaded_file,
            uploaded_by=request.user,
            status=MigrationJob.STATUS_PREVIEWED,
            summary=summary,
        )

        serializer = self.get_serializer(job)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="confirm")
    def confirm(self, request):
        profile, error_response = self._get_profile(request)

        if error_response:
            return error_response

        project, error_response = self._get_project(request)

        if error_response:
            return error_response

        uploaded_file = request.data.get("uploaded_file")

        if not uploaded_file:
            return Response(
                {"detail": "uploaded_file is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        error_response = self._validate_file(uploaded_file)

        if error_response:
            return error_response

        job = MigrationJob.objects.create(
            profile=profile,
            project=project,
            uploaded_file=uploaded_file,
            uploaded_by=request.user,
            status=MigrationJob.STATUS_PENDING,
            summary={
                "queued": True,
                "progress": {
                    "processed_rows": 0,
                    "total_rows": None,
                    "percent": 0,
                },
            },
        )

        run_migration_job.delay(job.id)

        serializer = self.get_serializer(job)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"], url_path="export-rows")
    def export_rows(self, request, pk=None):
        job = self.get_object()

        queryset = MigrationRowRecord.objects.filter(
            migration_job=job,
        ).order_by("row_number")

        status_filter = request.query_params.get("status")
        search = request.query_params.get("search")

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        if search:
            queryset = queryset.filter(
                Q(project_code__icontains=search)
                | Q(project_name__icontains=search)
                | Q(sample_code__icontains=search)
                | Q(raw_row_text__icontains=search)
            )

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="migration_job_{job.id}_rows.csv"'
        )

        writer = csv.writer(response)
        writer.writerow([
            "row_number",
            "status",
            "project_code",
            "project_name",
            "sample_code",
            "errors",
            "unmapped_data",
            "raw_row",
        ])

        for row in queryset.iterator(chunk_size=500):
            writer.writerow([
                row.row_number,
                row.status,
                row.project_code,
                row.project_name,
                row.sample_code,
                json.dumps(row.errors),
                json.dumps(row.unmapped_data),
                json.dumps(row.raw_row),
            ])

        return response
