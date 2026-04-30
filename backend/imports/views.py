import csv
import io

from django.conf import settings
from django.db import transaction

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from core.permissions import (
    HasInstrumentApiKey,
    IsAdminOnly,
    IsAuthenticatedReadOnlyOrTechAdminWrite,
)
from events.models import Event
from notifications.models import Notification
from results.models import Result, WorkItem
from samples.models import Sample

from .models import ImportJob, InstrumentColumnMapping, InstrumentProfile
from .serializers import (
    ImportJobSerializer,
    InstrumentColumnMappingSerializer,
    InstrumentProfileSerializer,
)
from .tasks import process_import_job, process_rows

# =========================
# Instrument Profile
# =========================
class InstrumentProfileViewSet(ModelViewSet):
    permission_classes = [IsAdminOnly]
    serializer_class = InstrumentProfileSerializer

    def get_queryset(self):
        return (
            InstrumentProfile.objects
            .prefetch_related("column_mappings")
            .all()
            .order_by("name")
        )


# =========================
# Column Mapping
# =========================
class InstrumentColumnMappingViewSet(ModelViewSet):
    permission_classes = [IsAdminOnly]
    serializer_class = InstrumentColumnMappingSerializer

    def get_queryset(self):
        return (
            InstrumentColumnMapping.objects
            .select_related("instrument")
            .all()
            .order_by("instrument__name", "source_column")
        )

class ImportJobViewSet(ModelViewSet):
    queryset = ImportJob.objects.select_related("instrument", "uploaded_by", "project")
    serializer_class = ImportJobSerializer

    # -------------------------
    # CSV Upload (ASYNC)
    # -------------------------
    def perform_create(self, serializer):
        job = serializer.save(
            uploaded_by=self.request.user,
            source_type="UPLOAD",
            status="PENDING",
            progress_message="Queued",
        )

        # queue async task
        process_import_job.delay(job.id)

    # -------------------------
    # Status endpoint
    # -------------------------
    @action(detail=True, methods=["get"], url_path="status")
    def status(self, request, pk=None):
        job = self.get_object()

        percent = 0
        if job.progress_total:
            percent = round((job.progress_current / job.progress_total) * 100)

        return Response(
            {
                "id": job.id,
                "status": job.status,
                "progress_current": job.progress_current,
                "progress_total": job.progress_total,
                "progress_percent": percent,
                "progress_message": job.progress_message,
                "summary": job.summary,
            }
        )

    # -------------------------
    # Instrument API ingest (SYNC)
    # -------------------------
    @action(detail=False, methods=["post"], url_path="instrument-ingest")
    def instrument_ingest(self, request):
        api_key = request.headers.get("X-Instrument-Api-Key")

        if api_key != settings.INSTRUMENT_API_KEY:
            return Response(
                {"detail": "Invalid API key"},
                status=status.HTTP_403_FORBIDDEN,
            )

        instrument_code = request.data.get("instrument_code")
        run_id = request.data.get("run_id")
        rows = request.data.get("rows")
        project_id = request.data.get("project_id")

        if not instrument_code or not run_id:
            return Response(
                {"detail": "instrument_code and run_id are required"},
                status=400,
            )

        # check instrument first
        try:
            instrument = InstrumentProfile.objects.prefetch_related(
                "column_mappings"
            ).get(code=instrument_code)
        except InstrumentProfile.DoesNotExist:
            return Response(
                {"detail": "Instrument not found"},
                status=404,
            )

        # validate rows
        if not isinstance(rows, list) or len(rows) == 0:
            return Response(
                {"detail": "rows must be a non-empty list"},
                status=400,
            )

        # prevent duplicate run_id
        if ImportJob.objects.filter(run_id=run_id).exists():
            return Response(
                {"detail": "Duplicate run_id"},
                status=409,
            )

        # create job
        job = ImportJob.objects.create(
            instrument=instrument,
            project_id=project_id if project_id else None,
            uploaded_by=None,
            run_id=run_id,
            source_type="API",
            status="RUNNING",
            progress_message="Processing API payload",
        )

        try:
            with transaction.atomic():
                summary = process_rows(
                    job=job,
                    rows=rows,
                    actor=None,
                )

                job.status = "COMPLETED"
                job.summary = summary
                job.progress_current = summary["rows_processed"]
                job.progress_total = summary["rows_processed"]
                job.progress_message = "API ingest completed"
                job.save()

                Event.objects.create(
                    entity_type="ImportJob",
                    entity_id=str(job.id),
                    action="RESULTS_IMPORTED",
                    actor=None,
                    payload={
                        "instrument_code": instrument.code,
                        "instrument_name": instrument.name,
                        "run_id": run_id,
                        **summary,
                    },
                )

            return Response(
                {
                    "id": job.id,
                    "status": job.status,
                    "summary": job.summary,
                },
                status=201,
            )

        except Exception as e:
            job.status = "FAILED"
            job.summary = {"error": str(e)}
            job.progress_message = "API ingest failed"
            job.save()

            return Response(
                {"detail": str(e)},
                status=500,
            )