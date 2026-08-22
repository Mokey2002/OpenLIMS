import csv
import json
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from core.permissions import IsAdminOnly, IsAuthenticatedReadOnlyOrTechAdminWrite, is_admin
from core.upload_validators import validate_text_file, validate_uploaded_file
from projects.models import Project
from samples.access import validate_sample_project_assignment

from .models import (
    MigrationDatabaseConnection,
    MigrationDataset,
    MigrationFieldMapping,
    MigrationJob,
    MigrationProfile,
    MigrationRowRecord,
    SampleExternalID,
)
from .serializers import (
    MigrationDatabaseConnectionSerializer,
    MigrationDatasetSerializer,
    MigrationFieldMappingSerializer,
    MigrationJobSerializer,
    MigrationProfileSerializer,
    MigrationRowRecordSerializer,
    SampleExternalIDSerializer,
)
from .database_services import prepare_database_preview
from .database_sources import inspect_source
from .services import build_csv_source_snapshot, build_preview, suggest_field_mappings
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


class MigrationDatabaseConnectionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOnly]
    serializer_class = MigrationDatabaseConnectionSerializer
    queryset = MigrationDatabaseConnection.objects.select_related("created_by").order_by("name")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"], url_path="test")
    def test_connection(self, request, pk=None):
        try:
            result = inspect_source(self.get_object())
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "ok": True,
                "engine": result["engine"],
                "table_count": len(result["tables"]),
            }
        )

    @action(detail=True, methods=["get"], url_path="inspect")
    def inspect(self, request, pk=None):
        try:
            return Response(inspect_source(self.get_object()))
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class MigrationDatasetViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOnly]
    serializer_class = MigrationDatasetSerializer

    def get_queryset(self):
        queryset = MigrationDataset.objects.select_related("profile", "connection")
        profile_id = self.request.query_params.get("profile")
        if profile_id:
            queryset = queryset.filter(profile_id=profile_id)
        return queryset.order_by("entity_type", "id")


class MigrationProfileViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = MigrationProfileSerializer

    def get_queryset(self):
        queryset = (
            MigrationProfile.objects
            .select_related("created_by")
            .prefetch_related("field_mappings", "datasets", "datasets__field_mappings")
            .all()
            .order_by("name")
        )
        if not is_admin(self.request.user):
            queryset = queryset.exclude(source_type=MigrationProfile.SOURCE_TYPE_DATABASE)
        return queryset

    def perform_create(self, serializer):
        if (
            serializer.validated_data.get("source_type")
            == MigrationProfile.SOURCE_TYPE_DATABASE
            and not is_admin(self.request.user)
        ):
            raise PermissionDenied("Only a director can create database migration profiles.")
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        source_type = serializer.validated_data.get("source_type", serializer.instance.source_type)
        if source_type == MigrationProfile.SOURCE_TYPE_DATABASE and not is_admin(self.request.user):
            raise PermissionDenied("Only a director can update database migration profiles.")
        serializer.save()


class MigrationFieldMappingViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = MigrationFieldMappingSerializer

    def get_queryset(self):
        queryset = (
            MigrationFieldMapping.objects
            .select_related("profile", "dataset")
            .all()
            .order_by("profile__name", "id")
        )

        profile_id = self.request.query_params.get("profile")

        if profile_id:
            queryset = queryset.filter(profile_id=profile_id)

        if not is_admin(self.request.user):
            queryset = queryset.exclude(profile__source_type=MigrationProfile.SOURCE_TYPE_DATABASE)

        return queryset

    def _require_admin_for_database(self, serializer):
        profile = serializer.validated_data.get(
            "profile",
            getattr(serializer.instance, "profile", None),
        )
        if (
            profile
            and profile.source_type == MigrationProfile.SOURCE_TYPE_DATABASE
            and not is_admin(self.request.user)
        ):
            raise PermissionDenied("Only a director can configure database mappings.")

    def perform_create(self, serializer):
        self._require_admin_for_database(serializer)
        serializer.save()

    def perform_update(self, serializer):
        self._require_admin_for_database(serializer)
        serializer.save()

    def perform_destroy(self, instance):
        if (
            instance.profile.source_type == MigrationProfile.SOURCE_TYPE_DATABASE
            and not is_admin(self.request.user)
        ):
            raise PermissionDenied("Only a director can delete database mappings.")
        instance.delete()



class MigrationRowRecordViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = MigrationRowRecordSerializer

    def get_queryset(self):
        queryset = (
            MigrationRowRecord.objects
            .select_related("migration_job", "source_dataset", "project", "sample")
            .all()
            .order_by("-created_at", "row_number")
        )
        if not is_admin(self.request.user):
            queryset = queryset.exclude(
                migration_job__profile__source_type=MigrationProfile.SOURCE_TYPE_DATABASE
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
        queryset = (
            MigrationJob.objects
            .select_related(
                "profile",
                "project",
                "uploaded_by",
                "source_connection",
                "committed_by",
            )
            .all()
            .order_by("-created_at")
        )
        if not is_admin(self.request.user):
            queryset = queryset.exclude(profile__source_type=MigrationProfile.SOURCE_TYPE_DATABASE)
        return queryset

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

        if profile.source_type != MigrationProfile.SOURCE_TYPE_CSV:
            return Response(
                {"detail": "CSV mapping suggestions require a CSV profile."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

        if profile.source_type == MigrationProfile.SOURCE_TYPE_DATABASE:
            if not is_admin(request.user):
                raise PermissionDenied("Only a director can preview database migrations.")
            try:
                summary, source_snapshot, _ = prepare_database_preview(profile)
            except Exception as exc:
                return Response(
                    {"detail": str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            connection_ids = list(
                profile.datasets.filter(active=True)
                .values_list("connection_id", flat=True)
                .distinct()
            )
            job = MigrationJob.objects.create(
                profile=profile,
                source_connection_id=(connection_ids[0] if len(connection_ids) == 1 else None),
                uploaded_by=request.user,
                status=MigrationJob.STATUS_PREVIEWED,
                summary=summary,
                source_snapshot=source_snapshot,
                preview_fingerprint=summary["preview_fingerprint"],
            )
        else:
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
                source_snapshot=summary["source_snapshot"],
                preview_fingerprint=summary["preview_fingerprint"],
            )

        serializer = self.get_serializer(job)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="confirm")
    def confirm(self, request):
        preview_job_id = request.data.get("preview_job")
        if not preview_job_id:
            return Response(
                {"detail": "preview_job is required. Preview and review the source first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return self._commit_job(request, preview_job_id)

    def _commit_job(self, request, job_id):
        job = self.get_queryset().filter(id=job_id).first()
        if not job:
            return Response({"detail": "Migration preview not found."}, status=404)
        if job.profile.source_type == MigrationProfile.SOURCE_TYPE_DATABASE and not is_admin(
            request.user
        ):
            raise PermissionDenied("Only a director can commit database migrations.")
        if job.status != MigrationJob.STATUS_PREVIEWED:
            return Response(
                {"detail": "Only a PREVIEWED migration can be committed."},
                status=status.HTTP_409_CONFLICT,
            )
        if not job.summary.get("ready_to_commit"):
            return Response(
                {"detail": "Resolve all validation errors and preview again before committing."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            if job.profile.source_type == MigrationProfile.SOURCE_TYPE_DATABASE:
                fresh_summary, _, _ = prepare_database_preview(job.profile)
                fresh_fingerprint = fresh_summary["preview_fingerprint"]
            else:
                job.uploaded_file.open("rb")
                _, fresh_fingerprint = build_csv_source_snapshot(
                    job.profile,
                    job.uploaded_file,
                    job.project,
                )
                job.uploaded_file.close()
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if fresh_fingerprint != job.preview_fingerprint:
            return Response(
                {
                    "detail": (
                        "The source data or mappings changed after preview. "
                        "Create and review a new preview."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            job = MigrationJob.objects.select_for_update().get(id=job.id)
            if job.status != MigrationJob.STATUS_PREVIEWED:
                return Response(
                    {"detail": "Only a PREVIEWED migration can be committed."},
                    status=status.HTTP_409_CONFLICT,
                )
            if job.preview_fingerprint != fresh_fingerprint:
                return Response(
                    {"detail": "The preview fingerprint changed. Preview again."},
                    status=status.HTTP_409_CONFLICT,
                )
            job.status = MigrationJob.STATUS_PENDING
            job.committed_by = request.user
            job.confirmed_at = timezone.now()
            job.summary = {
                **job.summary,
                "queued": True,
                "progress": {
                    "processed_rows": 0,
                    "total_rows": job.summary.get("rows_processed"),
                    "percent": 0,
                },
            }
            job.save(update_fields=["status", "committed_by", "confirmed_at", "summary"])
        run_migration_job.delay(job.id)
        return Response(self.get_serializer(job).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="commit")
    def commit(self, request, pk=None):
        return self._commit_job(request, pk)

    @action(detail=True, methods=["get"], url_path="export-rows")
    def export_rows(self, request, pk=None):
        job = self.get_object()

        queryset = MigrationRowRecord.objects.filter(
            migration_job=job,
        ).select_related("source_dataset").order_by("source_dataset_id", "row_number")

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
            "dataset",
            "entity_type",
            "source_key",
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
                row.source_dataset.name if row.source_dataset else "CSV",
                row.entity_type,
                row.source_key,
                row.project_code,
                row.project_name,
                row.sample_code,
                json.dumps(row.errors),
                json.dumps(row.unmapped_data),
                json.dumps(row.raw_row),
            ])

        return response
