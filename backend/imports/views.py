import csv
import io

from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework.decorators import action

from core.permissions import IsAdminOnly, IsAuthenticatedReadOnlyOrTechAdminWrite
from events.models import Event
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

    def get_queryset(self):
        return (
            ImportJob.objects
            .select_related("instrument", "uploaded_by")
            .all()
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        job = serializer.save(uploaded_by=self.request.user)

        try:
            instrument = job.instrument

            mappings = {
                m.source_column: m
                for m in instrument.column_mappings.all()
            }

            decoded = job.uploaded_file.read().decode("utf-8")
            reader = csv.DictReader(
                io.StringIO(decoded),
                delimiter=instrument.delimiter,
            )

            rows_processed = 0
            samples_matched = 0
            samples_created = 0
            results_created = 0
            skipped_rows = []

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

                sample, created = Sample.objects.get_or_create(
                    sample_id=sample_code,
                    defaults={
                        "status": "RECEIVED",
                    },
                )

                if created:
                    samples_created += 1
                    Event.objects.create(
                        entity_type="Sample",
                        entity_id=str(sample.id),
                        action="CREATED",
                        actor=self.request.user,
                        payload={
                            "sample_id": sample.id,
                            "sample_code": sample.sample_id,
                            "source": "instrument_import",
                            "instrument_code": instrument.code,
                        },
                    )

                samples_matched += 1

                work_item, _ = WorkItem.objects.get_or_create(
                    sample=sample,
                    name=f"{instrument.code} Import",
                    defaults={
                        "status": "COMPLETED",
                        "notes": f"Imported from {instrument.name} (Import Job {job.id})",
                    },
                )

                for source_column, mapping in mappings.items():
                    raw_value = row.get(source_column)

                    if raw_value in (None, ""):
                        continue

                    raw_value = str(raw_value).strip()

                    defaults = {
                        "value_type": mapping.value_type,
                        "value_string": "",
                        "value_number": None,
                        "value_boolean": None,
                    }

                    if mapping.value_type == "STRING":
                        defaults["value_string"] = raw_value

                    elif mapping.value_type == "NUMBER":
                        try:
                            defaults["value_number"] = float(raw_value)
                        except ValueError:
                            skipped_rows.append({
                                "row": rows_processed,
                                "sample_id": sample_code,
                                "column": source_column,
                                "reason": f"Invalid NUMBER value '{raw_value}'",
                            })
                            continue

                    elif mapping.value_type == "BOOLEAN":
                        defaults["value_boolean"] = raw_value.lower() in [
                            "true", "1", "yes", "pass", "ok"
                        ]

                    Result.objects.update_or_create(
                        work_item=work_item,
                        key=mapping.target_key,
                        defaults=defaults,
                    )
                    results_created += 1

            job.status = "COMPLETED"
            job.summary = {
                "rows_processed": rows_processed,
                "samples_matched": samples_matched,
                "samples_created": samples_created,
                "results_created": results_created,
                "skipped_rows": skipped_rows,
            }
            job.save()

            Event.objects.create(
                entity_type="ImportJob",
                entity_id=str(job.id),
                action="RESULTS_IMPORTED",
                actor=self.request.user,
                payload={
                    "instrument_code": instrument.code,
                    "instrument_name": instrument.name,
                    "rows_processed": rows_processed,
                    "samples_matched": samples_matched,
                    "samples_created": samples_created,
                    "results_created": results_created,
                },
            )

        except Exception as e:
            job.status = "FAILED"
            job.summary = {"error": str(e)}
            job.save()
            raise

    @action(detail=True, methods=["get"], url_path="summary")
    def summary(self, request, pk=None):
        job = self.get_object()
        return Response(job.summary)
