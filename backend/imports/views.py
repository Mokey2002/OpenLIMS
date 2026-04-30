import csv
import io

from django.conf import settings
from django.db import transaction

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from core.permissions import IsAdminOnly, IsAuthenticatedReadOnlyOrTechAdminWrite
from events.models import Event
from notifications.models import Notification

from .models import InstrumentProfile, InstrumentColumnMapping, ImportJob
from .serializers import (
    InstrumentProfileSerializer,
    InstrumentColumnMappingSerializer,
    ImportJobSerializer,
)
from .tasks import process_import_job, process_rows


class InstrumentProfileViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOnly]
    serializer_class = InstrumentProfileSerializer

    def get_queryset(self):
        return (
            InstrumentProfile.objects
            .prefetch_related("column_mappings")
            .all()
            .order_by("name")
        )


class InstrumentColumnMappingViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOnly]
    serializer_class = InstrumentColumnMappingSerializer

    def get_queryset(self):
        return (
            InstrumentColumnMapping.objects
            .select_related("instrument")
            .all()
            .order_by("instrument__name", "source_column")
        )


class ImportJobViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = ImportJobSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return (
            ImportJob.objects
            .select_related("instrument", "uploaded_by", "project")
            .all()
            .order_by("-created_at")
        )

    def _validate_mapped_value(self, mapping, raw_value):
        if raw_value in (None, ""):
            return {"ok": True, "normalized": None}

        raw_value = str(raw_value).strip()

        if mapping.value_type == "NUMBER":
            try:
                val = float(raw_value)
            except ValueError:
                return {"ok": False, "reason": f"Invalid NUMBER '{raw_value}'"}

            if mapping.min_value is not None and val < mapping.min_value:
                return {"ok": False, "reason": "Below min_value"}

            if mapping.max_value is not None and val > mapping.max_value:
                return {"ok": False, "reason": "Above max_value"}

            return {"ok": True, "normalized": val}

        if mapping.value_type == "STRING":
            if mapping.allowed_values:
                allowed = [str(v) for v in mapping.allowed_values]
                if raw_value not in allowed:
                    return {"ok": False, "reason": "Invalid allowed value"}

            return {"ok": True, "normalized": raw_value}

        if mapping.value_type == "BOOLEAN":
            val = raw_value.lower()

            if val not in [
                "true",
                "1",
                "yes",
                "pass",
                "ok",
                "false",
                "0",
                "no",
                "fail",
            ]:
                return {"ok": False, "reason": "Invalid boolean"}

            return {
                "ok": True,
                "normalized": val in ["true", "1", "yes", "pass", "ok"],
            }

        return {"ok": True, "normalized": raw_value}

    def _parse_preview(self, instrument, uploaded_file):
        mappings = {
            m.source_column: m
            for m in instrument.column_mappings.all()
        }

        uploaded_file.seek(0)
        decoded = uploaded_file.read().decode("utf-8")
        uploaded_file.seek(0)

        reader = csv.DictReader(
            io.StringIO(decoded),
            delimiter=instrument.delimiter,
        )

        rows_processed = 0
        existing_samples = 0
        new_samples = 0
        valid_result_cells = 0
        skipped_rows = []
        preview_rows = []

        from samples.models import Sample

        for row in reader:
            rows_processed += 1

            sample_code = row.get(instrument.sample_id_column)

            if not sample_code:
                skipped_rows.append({
                    "row": rows_processed,
                    "reason": f"Missing sample ID column '{instrument.sample_id_column}'",
                })
                continue

            sample_code = str(sample_code).strip()
            sample_exists = Sample.objects.filter(sample_id=sample_code).exists()

            if sample_exists:
                existing_samples += 1
            else:
                new_samples += 1

            row_valid_cells = 0
            row_errors = []

            for source_column, mapping in mappings.items():
                raw_value = row.get(source_column)

                if raw_value in (None, ""):
                    continue

                validation = self._validate_mapped_value(mapping, raw_value)

                if not validation["ok"]:
                    row_errors.append({
                        "column": source_column,
                        "reason": validation["reason"],
                    })
                    continue

                row_valid_cells += 1
                valid_result_cells += 1

            preview_rows.append({
                "row": rows_processed,
                "sample_id": sample_code,
                "exists": sample_exists,
                "valid_result_cells": row_valid_cells,
                "errors": row_errors,
            })

        return {
            "rows_processed": rows_processed,
            "existing_samples": existing_samples,
            "new_samples": new_samples,
            "valid_result_cells": valid_result_cells,
            "skipped_rows": skipped_rows,
            "preview_rows": preview_rows[:20],
        }

    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request):
        instrument_id = request.data.get("instrument")
        uploaded_file = request.data.get("uploaded_file")

        if not instrument_id or not uploaded_file:
            return Response(
                {"detail": "instrument and uploaded_file are required."},
                status=400,
            )

        try:
            instrument = (
                InstrumentProfile.objects
                .prefetch_related("column_mappings")
                .get(id=instrument_id)
            )
        except InstrumentProfile.DoesNotExist:
            return Response({"detail": "Instrument not found."}, status=404)

        summary = self._parse_preview(instrument, uploaded_file)
        summary["instrument_code"] = instrument.code
        summary["instrument_name"] = instrument.name

        return Response(summary)

    def perform_create(self, serializer):
        job = serializer.save(
            uploaded_by=self.request.user,
            source_type="UPLOAD",
            status="PENDING",
            progress_message="Queued",
        )

        process_import_job.delay(job.id)

    @action(detail=True, methods=["get"], url_path="status")
    def status(self, request, pk=None):
        job = self.get_object()

        percent = 0
        if job.progress_total:
            percent = round((job.progress_current / job.progress_total) * 100)

        return Response({
            "id": job.id,
            "status": job.status,
            "progress_current": job.progress_current,
            "progress_total": job.progress_total,
            "progress_percent": percent,
            "progress_message": job.progress_message,
            "summary": job.summary,
        })

    @action(
        detail=False,
        methods=["post"],
        url_path="instrument-ingest",
        authentication_classes=[],
        permission_classes=[],
    )
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
                {"detail": "instrument_code and run_id are required."},
                status=400,
            )

        try:
            instrument = (
                InstrumentProfile.objects
                .prefetch_related("column_mappings")
                .get(code=instrument_code)
            )
        except InstrumentProfile.DoesNotExist:
            return Response(
                {"detail": "Instrument not found."},
                status=404,
            )

        if not isinstance(rows, list) or len(rows) == 0:
            return Response(
                {"detail": "rows must be a non-empty list."},
                status=400,
            )

        if ImportJob.objects.filter(instrument=instrument, run_id=run_id).exists():
            return Response(
                {"detail": "Duplicate run_id for this instrument."},
                status=409,
            )

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
                    "job_id": job.id,
                    "run_id": run_id,
                    "status": job.status,
                    **summary,
                },
                status=201,
            )

        except Exception as e:
            job.status = "FAILED"
            job.summary = {"error": str(e)}
            job.progress_message = f"API ingest failed: {str(e)}"
            job.save()

            return Response(
                {"detail": str(e)},
                status=500,
            )

    @action(detail=True, methods=["get"], url_path="summary")
    def summary(self, request, pk=None):
        job = self.get_object()
        return Response(job.summary)