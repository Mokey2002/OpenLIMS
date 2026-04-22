import csv
import io

from rest_framework import status
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from core.permissions import (
    IsAdminOnly,
    IsAuthenticatedReadOnlyOrTechAdminWrite,
    HasInstrumentApiKey,
)
from events.models import Event
from notifications.models import Notification
from samples.models import Sample
from results.models import WorkItem, Result

from .models import InstrumentProfile, InstrumentColumnMapping, ImportJob
from .serializers import (
    InstrumentProfileSerializer,
    InstrumentColumnMappingSerializer,
    ImportJobSerializer,
)


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

    # -------------------------
    # 🔧 VALIDATION
    # -------------------------
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
                if raw_value not in [str(v) for v in mapping.allowed_values]:
                    return {"ok": False, "reason": "Invalid allowed value"}
            return {"ok": True, "normalized": raw_value}

        if mapping.value_type == "BOOLEAN":
            val = raw_value.lower()
            if val not in ["true", "1", "yes", "pass", "false", "0", "no", "fail"]:
                return {"ok": False, "reason": "Invalid boolean"}
            return {"ok": True, "normalized": val in ["true", "1", "yes", "pass"]}

        return {"ok": True, "normalized": raw_value}

    # -------------------------
    # 🔥 CORE PROCESSOR (shared)
    # -------------------------
    def _process_rows(self, *, instrument, project_id, rows, actor, job):
        mappings = {m.source_column: m for m in instrument.column_mappings.all()}

        rows_processed = 0
        samples_created = 0
        results_created = 0
        skipped_rows = []

        for row in rows:
            rows_processed += 1

            sample_code = row.get(instrument.sample_id_column)
            if not sample_code:
                skipped_rows.append({"row": rows_processed, "reason": "Missing sample_id"})
                continue

            sample_code = str(sample_code).strip()

            sample, created = Sample.objects.get_or_create(
                sample_id=sample_code,
                defaults={"project_id": project_id, "status": "RECEIVED"},
            )

            if created:
                samples_created += 1

            work_item = WorkItem.objects.create(
                sample=sample,
                name=f"{instrument.code} Run {job.run_id}",
                status="COMPLETED",
            )

            for source_column, mapping in mappings.items():
                raw_value = row.get(source_column)
                if raw_value in (None, ""):
                    continue

                validation = self._validate_mapped_value(mapping, raw_value)
                if not validation["ok"]:
                    skipped_rows.append({
                        "row": rows_processed,
                        "column": source_column,
                        "reason": validation["reason"],
                    })
                    continue

                val = validation["normalized"]

                Result.objects.update_or_create(
                    work_item=work_item,
                    key=mapping.target_key,
                    defaults={
                        "value_type": mapping.value_type,
                        "value_string": val if mapping.value_type == "STRING" else "",
                        "value_number": val if mapping.value_type == "NUMBER" else None,
                        "value_boolean": val if mapping.value_type == "BOOLEAN" else None,
                    },
                )
                results_created += 1

        return {
            "rows_processed": rows_processed,
            "samples_created": samples_created,
            "results_created": results_created,
            "skipped_rows": skipped_rows,
        }

    # -------------------------
    # 🚀 API KEY INGEST
    # -------------------------
    @action(
        detail=False,
        methods=["post"],
        url_path="instrument-ingest",
        authentication_classes=[],                 # 🔥 NO JWT REQUIRED
        permission_classes=[HasInstrumentApiKey],  # 🔐 API KEY ONLY
    )
    def instrument_ingest(self, request):
        instrument_code = request.data.get("instrument_code")
        project_id = request.data.get("project_id")
        run_id = request.data.get("run_id")
        rows = request.data.get("rows", [])

        if not instrument_code or not run_id:
            return Response({"detail": "Missing fields"}, status=400)

        try:
            instrument = InstrumentProfile.objects.get(code=instrument_code)
        except InstrumentProfile.DoesNotExist:
            return Response({"detail": "Instrument not found"}, status=404)

        if ImportJob.objects.filter(instrument=instrument, run_id=run_id).exists():
            return Response({"detail": "Run already exists"}, status=409)

        job = ImportJob.objects.create(
            instrument=instrument,
            project_id=project_id,
            run_id=run_id,
            source_type="API",
            status="PENDING",
        )

        summary = self._process_rows(
            instrument=instrument,
            project_id=project_id,
            rows=rows,
            actor=None,
            job=job,
        )

        job.status = "COMPLETED"
        job.summary = summary
        job.save()

        return Response(
            {"job_id": job.id, "run_id": run_id, **summary},
            status=201,
        )
