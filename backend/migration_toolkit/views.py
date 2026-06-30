from django.core.exceptions import ValidationError as DjangoValidationError

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
    SampleExternalID,
)
from .serializers import (
    MigrationFieldMappingSerializer,
    MigrationJobSerializer,
    MigrationProfileSerializer,
    SampleExternalIDSerializer,
)
from .services import apply_migration, build_preview


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
            status=MigrationJob.STATUS_PREVIEWED,
            summary={},
        )

        try:
            summary = apply_migration(
                profile=profile,
                uploaded_file=uploaded_file,
                actor=request.user,
                default_project=project,
            )

            job.status = MigrationJob.STATUS_COMPLETED
            job.summary = summary
            job.save(update_fields=["status", "summary"])
        except Exception as exc:
            job.status = MigrationJob.STATUS_FAILED
            job.summary = {"error": str(exc)}
            job.save(update_fields=["status", "summary"])

            return Response(
                {"detail": str(exc), "job_id": job.id},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(job)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
