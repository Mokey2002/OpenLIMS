import csv
import hashlib
import io

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from core.permissions import (
    IsAuthenticatedReadOnlyAdminWrite,
    IsAuthenticatedReadOnlyOrTechAdminWrite,
)
from core.upload_validators import (
    validate_fasta_records,
    validate_text_file,
    validate_uploaded_file,
)
from events.models import Event
from projects.access import get_project_access_queryset
from samples.models import Sample
from samples.access import (
    get_sample_access_queryset,
    user_can_modify_sample,
    validate_sample_project_assignment,
)
from sequences.models import Sequence

from .instrument_qc import (
    ACTIVE_STATUSES, QUEUE_TIMEOUT, TIMEOUT_MESSAGE, WORKFLOW_VERSION, available_input,
    encode_input, serialize_run, snapshot_export, user_can_run_qc, workflow_digest,
)
from .models import (
    ImportJob, ImportRowReceipt, ImportRowRepair, InstrumentColumnMapping, InstrumentProfile, InstrumentQCRun,
)
from .serializers import (
    ImportJobSerializer,
    InstrumentQCParametersSerializer,
    InstrumentColumnMappingSerializer,
    InstrumentProfileSerializer,
)
from .tasks import deliver_instrument_qc, process_import_job, process_rows, validate_mapped_value
from .row_identity import classify_receipt, row_identity
from .tabular import read_tabular


class InstrumentProfileViewSet(viewsets.ModelViewSet):
    """
    Instrument configuration.

    Permissions:
    - admin: read/write
    - tech: read only
    - viewer: read only
    """

    permission_classes = [IsAuthenticatedReadOnlyAdminWrite]
    serializer_class = InstrumentProfileSerializer

    def get_queryset(self):
        return (
            InstrumentProfile.objects.prefetch_related("column_mappings")
            .all()
            .order_by("name")
        )


class InstrumentColumnMappingViewSet(viewsets.ModelViewSet):
    """
    Instrument column mapping configuration.

    Permissions:
    - admin: read/write
    - tech: read only
    - viewer: read only
    """

    permission_classes = [IsAuthenticatedReadOnlyAdminWrite]
    serializer_class = InstrumentColumnMappingSerializer

    def get_queryset(self):
        return (
            InstrumentColumnMapping.objects.select_related("instrument")
            .all()
            .order_by("instrument__name", "source_column")
        )


class ImportJobViewSet(viewsets.ModelViewSet):
    """
    Import jobs.

    Permissions:
    - admin: read/write
    - tech: read/write
    - viewer: read only
    """

    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = ImportJobSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _lock_editable_job(self, pk):
        job = ImportJob.objects.select_for_update().get(pk=pk)
        if job.summary.get("assistant_upload") or "tabular" in job.summary or job.qc_runs.exists():
            raise serializers.ValidationError({
                "detail": "Import identity and receipts are immutable. Use the import's retry controls."
            })
        return job

    def perform_update(self, serializer):
        with transaction.atomic():
            self._lock_editable_job(serializer.instance.pk)
            serializer.save()

    def perform_destroy(self, instance):
        with transaction.atomic():
            self._lock_editable_job(instance.pk)
            instance.delete()

    def get_queryset(self):
        queryset = (
            ImportJob.objects.select_related("instrument", "uploaded_by", "project")
            .annotate(
                linked_sample_count=Count("work_items__sample", distinct=True),
                linked_work_item_count=Count("work_items", distinct=True),
                linked_result_count=Count("work_items__results", distinct=True),
            )
            .all()
            .order_by("-created_at")
        )

        return get_project_access_queryset(
            queryset,
            self.request.user,
            project_lookup="project",
            owner_lookup="uploaded_by",
        )

    def _get_validated_project(self, project_id):
        if not project_id:
            return None

        from projects.models import Project

        project = Project.objects.filter(id=project_id).first()

        if not project:
            raise serializers.ValidationError({
                "project": "Project not found."
            })

        validate_sample_project_assignment(self.request.user, project)
        return project

    def _validate_mapped_value(self, mapping, raw_value):
        return validate_mapped_value(mapping, raw_value)

    def _tabular_options(self):
        return {
            "sheet": serializers.CharField(max_length=31, trim_whitespace=False, required=False),
            "source_system": serializers.CharField(max_length=128, required=False),
        }

    def _tabular_input(self, uploaded_file, instrument):
        options = serializers.Serializer(data=self.request.data)
        options.fields.update(self._tabular_options())
        options.is_valid(raise_exception=True)
        config = dict(options.validated_data)
        try:
            validate_uploaded_file(uploaded_file, [".csv", ".tsv", ".txt", ".xlsx"])
            rows, metadata = read_tabular(uploaded_file, instrument, config.get("sheet"))
        except ValidationError as exc:
            raise serializers.ValidationError({"uploaded_file": exc.messages}) from exc
        except (ValueError, csv.Error) as exc:
            raise serializers.ValidationError({"uploaded_file": str(exc)}) from exc
        if metadata.get("sheet"):
            config["sheet"] = metadata["sheet"]
        if rows is not None and config.get("source_system"):
            headers = metadata["fieldnames"]
            if "external_id" not in headers:
                raise serializers.ValidationError({"uploaded_file": "A source system requires an external_id column."})
            if len(headers) != len(set(headers)):
                raise serializers.ValidationError({"uploaded_file": "Column names must be unique for keyed imports."})
        return rows, metadata, config

    def _parse_preview(self, instrument, rows, csv_metadata, project=None, source_system=None):
        mappings = {m.source_column: m for m in instrument.column_mappings.all()}
        existing_receipts = {}
        if source_system:
            keys = {str(row["external_id"]).strip() for row in rows if row.get("external_id")}
            existing_receipts = {
                receipt.external_id: receipt
                for receipt in ImportRowReceipt.objects.filter(
                    instrument=instrument, source_system=source_system, external_id__in=keys,
                )
            }
        seen = {}
        preview_job = ImportJob(instrument=instrument, project=project)

        rows_processed = 0
        existing_samples = 0
        new_samples = 0
        valid_result_cells = 0
        skipped_rows = []
        preview_rows = []

        for row in rows:
            rows_processed += 1

            sample_code = str(row.get(instrument.sample_id_column) or "").strip()

            if not sample_code:
                skipped_rows.append(
                    {
                        "row": rows_processed,
                        "reason": (
                            f"Missing sample ID column "
                            f"'{instrument.sample_id_column}'"
                        ),
                    }
                )
                continue

            sample_code = str(sample_code).strip()
            matched_sample = (
                get_sample_access_queryset(
                    Sample.objects.filter(sample_id=sample_code),
                    self.request.user,
                )
                .first()
            )

            sample_exists = bool(matched_sample)

            if matched_sample and not user_can_modify_sample(self.request.user, matched_sample):
                skipped_rows.append(
                    {
                        "row": rows_processed,
                        "sample_id": sample_code,
                        "reason": "Sample exists but you do not have permission to import results into it.",
                    }
                )
                preview_rows.append({
                    "row": rows_processed, "sample_id": sample_code, "outcome": "REJECTED",
                    "valid_result_cells": 0, "errors": [skipped_rows[-1]],
                })
                continue

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
                    row_errors.append(
                        {
                            "column": source_column,
                            "reason": validation["reason"],
                        }
                    )
                    continue

                row_valid_cells += 1
                valid_result_cells += 1

            outcome = "READY"
            if source_system:
                if len(sample_code) > Sample._meta.get_field("sample_id").max_length:
                    row_errors.append({"reason": "Sample ID exceeds 64 characters."})
                if None in row:
                    row_errors.append({"reason": "More values than header columns."})
                try:
                    external_id, fingerprint = row_identity(preview_job, row)
                except ValueError as exc:
                    row_errors.append({"reason": str(exc)})
                if row_errors:
                    outcome = "REJECTED"
                elif external_id in existing_receipts:
                    outcome, reason = classify_receipt(existing_receipts[external_id], fingerprint)
                    row_errors.append({"reason": reason})
                elif external_id in seen:
                    outcome = "IDENTICAL" if seen[external_id] == fingerprint else "CONFLICT"
                    row_errors.append({"reason": "This external ID appears earlier in the upload."})
                else:
                    seen[external_id] = fingerprint
                if outcome in {"REJECTED", "CONFLICT"}:
                    skipped_rows.extend({"row": rows_processed, **issue} for issue in row_errors)

            preview_rows.append(
                {
                    "row": rows_processed,
                    "sample_id": sample_code,
                    "exists": sample_exists,
                    "external_id": row.get("external_id"),
                    "outcome": outcome,
                    "valid_result_cells": row_valid_cells,
                    "errors": row_errors,
                }
            )

        return {
            "rows_processed": rows_processed,
            "existing_samples": existing_samples,
            "new_samples": new_samples,
            "valid_result_cells": valid_result_cells,
            "skipped_rows": skipped_rows,
            "preview_rows": preview_rows[:20],
            "csv_metadata": csv_metadata,
        }

    def _parse_fasta_records(self, uploaded_file):
        uploaded_file.seek(0)
        decoded = uploaded_file.read().decode("utf-8")
        uploaded_file.seek(0)

        records = []
        current_header = None
        current_lines = []

        for raw_line in decoded.splitlines():
            line = raw_line.strip()

            if not line:
                continue

            if line.startswith(">"):
                if current_header:
                    sequence = "".join(current_lines).replace(" ", "").upper()
                    records.append(
                        {
                            "header": current_header,
                            "name": current_header,
                            "sample_code": current_header.split()[0],
                            "sequence": sequence,
                        }
                    )

                current_header = line[1:].strip()
                current_lines = []
            else:
                current_lines.append(line)

        if current_header:
            sequence = "".join(current_lines).replace(" ", "").upper()
            records.append(
                {
                    "header": current_header,
                    "name": current_header,
                    "sample_code": current_header.split()[0],
                    "sequence": sequence,
                }
            )

        return records

    def _infer_sequence_type(self, sequence):
        sequence = sequence.upper()
        sequence_chars = set(sequence)

        if sequence_chars.issubset(set("ACGTN-")):
            return "DNA"

        if sequence_chars.issubset(set("ACGUN-")):
            return "RNA"

        return "PROTEIN"

    def _validation_error_response(self, error):
        return Response(
            {"detail": error.messages if hasattr(error, "messages") else str(error)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request):
        instrument_id = request.data.get("instrument")
        project_id = request.data.get("project")
        uploaded_file = request.data.get("uploaded_file")

        if not instrument_id or not uploaded_file:
            return Response(
                {"detail": "instrument and uploaded_file are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            instrument = (
                InstrumentProfile.objects.prefetch_related("column_mappings").get(
                    id=instrument_id
                )
            )
        except InstrumentProfile.DoesNotExist:
            return Response(
                {"detail": "Instrument not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            project = self._get_validated_project(project_id)
        except serializers.ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        try:
            rows, metadata, config = self._tabular_input(uploaded_file, instrument)
            if rows is None:
                return Response({"sheet_required": True, "sheets": metadata["sheets"]})
            summary = self._parse_preview(
                instrument, rows, metadata, project=project, source_system=config.get("source_system"),
            )
        except serializers.ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        summary["project_id"] = project.id if project else None
        summary["project_code"] = project.code if project else None
        summary["instrument_code"] = instrument.code
        summary["instrument_name"] = instrument.name

        return Response(summary)

    @action(detail=False, methods=["post"], url_path="sequence-fasta-preview")
    def sequence_fasta_preview(self, request):
        instrument_id = request.data.get("instrument")
        project_id = request.data.get("project")
        uploaded_file = request.data.get("uploaded_file")

        if not instrument_id or not uploaded_file:
            return Response(
                {"detail": "instrument and uploaded_file are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_uploaded_file(
                uploaded_file,
                allowed_extensions=[".fasta", ".fa", ".fna", ".txt"],
            )
            validate_text_file(uploaded_file)
        except ValidationError as e:
            return self._validation_error_response(e)

        try:
            instrument = InstrumentProfile.objects.get(id=instrument_id)
        except InstrumentProfile.DoesNotExist:
            return Response(
                {"detail": "Instrument not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            project = self._get_validated_project(project_id)
        except serializers.ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        try:
            project = self._get_validated_project(project_id)
        except serializers.ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        try:
            records = self._parse_fasta_records(uploaded_file)
            validate_fasta_records(records)
        except UnicodeDecodeError:
            return Response(
                {"detail": "Unable to read FASTA file. Expected UTF-8 text."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValidationError as e:
            return self._validation_error_response(e)

        matched_records = []
        unmatched_records = []
        skipped_records = []

        for index, record in enumerate(records, start=1):
            sample_code = record["sample_code"]
            sequence_text = record["sequence"]

            if not sequence_text:
                skipped_records.append(
                    {
                        "row": index,
                        "header": record["header"],
                        "sample_code": sample_code,
                        "reason": "Empty sequence",
                    }
                )
                continue

            sample = (
                get_sample_access_queryset(
                    Sample.objects.select_related("project").filter(sample_id=sample_code),
                    request.user,
                )
                .first()
            )

            if not sample:
                unmatched_records.append(
                    {
                        "row": index,
                        "header": record["header"],
                        "sample_code": sample_code,
                        "sequence_length": len(sequence_text),
                        "reason": "No matching sample found",
                    }
                )
                continue

            if not user_can_modify_sample(request.user, sample):
                skipped_records.append(
                    {
                        "row": index,
                        "header": record["header"],
                        "sample_code": sample_code,
                        "sequence_length": len(sequence_text),
                        "reason": "You can view this sample, but you do not have permission to import sequence data into it.",
                    }
                )
                continue

            linked_project = sample.project

            if project_id and not linked_project:
                linked_project_id = int(project_id)
                linked_project_code = None
            else:
                linked_project_id = linked_project.id if linked_project else None
                linked_project_code = linked_project.code if linked_project else None

            matched_records.append(
                {
                    "row": index,
                    "header": record["header"],
                    "name": record["name"],
                    "sample_id": sample.id,
                    "sample_code": sample.sample_id,
                    "project_id": linked_project_id,
                    "project_code": linked_project_code,
                    "sequence_type": self._infer_sequence_type(sequence_text),
                    "sequence_length": len(sequence_text),
                    "will_create": True,
                }
            )

        return Response(
            {
                "instrument_id": instrument.id,
                "instrument_code": instrument.code,
                "instrument_name": instrument.name,
                "project_id": project_id,
                "records_processed": len(records),
                "matched_count": len(matched_records),
                "unmatched_count": len(unmatched_records),
                "skipped_count": len(skipped_records),
                "will_create_count": len(matched_records),
                "matched_records": matched_records,
                "unmatched_records": unmatched_records,
                "skipped_records": skipped_records,
            }
        )

    @action(detail=False, methods=["post"], url_path="sequence-fasta-import")
    def sequence_fasta_import(self, request):
        instrument_id = request.data.get("instrument")
        project_id = request.data.get("project")
        uploaded_file = request.data.get("uploaded_file")

        if not instrument_id or not uploaded_file:
            return Response(
                {"detail": "instrument and uploaded_file are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_uploaded_file(
                uploaded_file,
                allowed_extensions=[".fasta", ".fa", ".fna", ".txt"],
            )
            validate_text_file(uploaded_file)
        except ValidationError as e:
            return self._validation_error_response(e)

        try:
            instrument = InstrumentProfile.objects.get(id=instrument_id)
        except InstrumentProfile.DoesNotExist:
            return Response(
                {"detail": "Instrument not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            records = self._parse_fasta_records(uploaded_file)
            validate_fasta_records(records)
        except UnicodeDecodeError:
            return Response(
                {"detail": "Unable to read FASTA file. Expected UTF-8 text."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValidationError as e:
            return self._validation_error_response(e)

        actor = request.user if request.user.is_authenticated else None

        job = ImportJob.objects.create(
            instrument=instrument,
            project=project,
            uploaded_by=actor,
            source_type="SEQUENCE_FASTA",
            status="RUNNING",
            progress_current=0,
            progress_total=len(records),
            progress_message="Processing FASTA sequence import",
            summary={},
        )

        created_sequence_ids = []
        matched_sample_ids = []
        unmatched_records = []
        skipped_records = []

        try:
            with transaction.atomic():
                for index, record in enumerate(records, start=1):
                    job.progress_current = index
                    job.progress_message = (
                        f"Processing FASTA record {index} of {len(records)}"
                    )
                    job.save(
                        update_fields=[
                            "progress_current",
                            "progress_message",
                        ]
                    )

                    sample_code = record["sample_code"]
                    sequence_text = record["sequence"]

                    if not sequence_text:
                        skipped_records.append(
                            {
                                "header": record["header"],
                                "reason": "Empty sequence",
                            }
                        )
                        continue

                    sample = (
                        get_sample_access_queryset(
                            Sample.objects.select_related("project").filter(sample_id=sample_code),
                            request.user,
                        )
                        .first()
                    )

                    if not sample:
                        unmatched_records.append(
                            {
                                "header": record["header"],
                                "sample_code": sample_code,
                                "reason": "No matching sample found",
                            }
                        )
                        continue

                    if not user_can_modify_sample(request.user, sample):
                        skipped_records.append(
                            {
                                "header": record["header"],
                                "sample_code": sample_code,
                                "reason": "You can view this sample, but you do not have permission to import sequence data into it.",
                            }
                        )
                        continue

                    linked_project = sample.project or job.project

                    sequence_record = Sequence.objects.create(
                        name=record["name"],
                        description=(
                            f"Imported from FASTA file via Import Job #{job.id}."
                        ),
                        sequence_type=self._infer_sequence_type(sequence_text),
                        sequence=sequence_text,
                        sample=sample,
                        project=linked_project,
                        import_job=job,
                        source_type="FASTA_IMPORT",
                        source_metadata={
                            "header": record["header"],
                            "sample_code": sample_code,
                            "instrument_code": instrument.code,
                            "instrument_name": instrument.name,
                            "import_job_id": job.id,
                            "filename": uploaded_file.name,
                        },
                        created_by=actor,
                    )

                    created_sequence_ids.append(sequence_record.id)
                    matched_sample_ids.append(sample.id)

                    Event.objects.create(
                        entity_type="Sequence",
                        entity_id=str(sequence_record.id),
                        action="SEQUENCE_IMPORTED",
                        actor=actor,
                        payload={
                            "sequence_id": sequence_record.id,
                            "sequence_name": sequence_record.name,
                            "sample_id": sample.id,
                            "sample_code": sample.sample_id,
                            "project_id": linked_project.id if linked_project else None,
                            "import_job_id": job.id,
                            "instrument_code": instrument.code,
                            "source_type": "FASTA_IMPORT",
                        },
                    )

                    Event.objects.create(
                        entity_type="Sample",
                        entity_id=str(sample.id),
                        action="SEQUENCE_IMPORTED",
                        actor=actor,
                        payload={
                            "sequence_id": sequence_record.id,
                            "sequence_name": sequence_record.name,
                            "sample_id": sample.id,
                            "sample_code": sample.sample_id,
                            "project_id": linked_project.id if linked_project else None,
                            "import_job_id": job.id,
                            "instrument_code": instrument.code,
                            "source_type": "FASTA_IMPORT",
                        },
                    )

                summary = {
                    "source_type": "SEQUENCE_FASTA",
                    "records_processed": len(records),
                    "sequences_created": len(created_sequence_ids),
                    "samples_matched": len(set(matched_sample_ids)),
                    "unmatched_records": unmatched_records,
                    "skipped_records": skipped_records,
                    "created_sequence_ids": created_sequence_ids,
                    "matched_sample_ids": list(set(matched_sample_ids)),
                }

                job.status = "COMPLETED"
                job.summary = summary
                job.progress_current = len(records)
                job.progress_total = len(records)
                job.progress_message = "FASTA sequence import completed"
                job.save()

                Event.objects.create(
                    entity_type="ImportJob",
                    entity_id=str(job.id),
                    action="SEQUENCE_IMPORT_COMPLETED",
                    actor=actor,
                    payload={
                        "job_id": job.id,
                        "instrument_code": instrument.code,
                        **summary,
                    },
                )

        except Exception as e:
            job.status = "FAILED"
            job.summary = {"error": str(e)}
            job.progress_message = f"FASTA sequence import failed: {str(e)}"
            job.save()

            return Response(
                {"detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        serializer = self.get_serializer(job)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        uploaded_file = self.request.data.get("uploaded_file")
        project = serializer.validated_data.get("project")

        validate_sample_project_assignment(self.request.user, project)

        _, metadata, config = self._tabular_input(uploaded_file, serializer.validated_data["instrument"])
        if metadata.get("sheets") and not metadata.get("sheet"):
            raise serializers.ValidationError({"sheet": "Select an Excel sheet before importing."})

        requires_confirmation = str(
            self.request.data.get("assistant_confirmation", "")
        ).strip().lower() in ["1", "true", "yes", "on"]

        job = serializer.save(
            uploaded_by=self.request.user,
            source_type="UPLOAD",
            status="PENDING",
            progress_current=0,
            progress_total=0,
            progress_message=(
                "Awaiting assistant confirmation"
                if requires_confirmation
                else "Queued"
            ),
            summary={
                "tabular": config,
                **({"awaiting_assistant_confirmation": True} if requires_confirmation else {}),
            },
        )

        if not requires_confirmation:
            transaction.on_commit(lambda: process_import_job.delay(job.id))

    @action(detail=True, methods=["get"], url_path="status")
    def status(self, request, pk=None):
        job = self.get_object()

        percent = 0

        if job.status == "COMPLETED":
            percent = 100
        elif job.progress_total:
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

    @action(detail=True, methods=["get"], url_path="summary")
    def summary(self, request, pk=None):
        job = self.get_object()
        return Response(job.summary or {})

    @action(detail=True, methods=["get"], url_path="samples")
    def samples(self, request, pk=None):
        job = self.get_object()
        summary = job.summary or {}

        sample_ids = list(
            job.work_items.values_list("sample_id", flat=True).distinct()
        )

        sample_ids.extend(summary.get("touched_sample_ids", []))

        if not sample_ids:
            sample_ids = (
                summary.get("created_sample_ids", [])
                + summary.get("matched_sample_ids", [])
            )

        sample_ids = list(set(sample_ids))

        samples = (
            Sample.objects.filter(id__in=sample_ids)
            .select_related("project", "container", "created_by")
        )
        samples = (
            get_sample_access_queryset(samples, request.user)
            .order_by("sample_id")
        )

        created_ids = set(summary.get("created_sample_ids", []))
        matched_ids = set(summary.get("matched_sample_ids", []))

        data = []

        for sample in samples:
            if sample.id in created_ids:
                import_action = "CREATED"
            elif sample.id in matched_ids:
                import_action = "MATCHED"
            else:
                import_action = "TOUCHED"

            data.append(
                {
                    "id": sample.id,
                    "sample_id": sample.sample_id,
                    "status": sample.status,
                    "project_id": sample.project_id,
                    "project_code": sample.project.code if sample.project else None,
                    "container_id": sample.container_id,
                    "container_code": (
                        sample.container.container_id if sample.container else None
                    ),
                    "import_action": import_action,
                    "created_at": sample.created_at,
                }
            )

        return Response(data)

    @action(detail=True, methods=["get", "post"], url_path="qc-runs")
    def qc_runs(self, request, pk=None):
        job = self.get_object()
        if request.method == "POST":
            return self._queue_instrument_qc(request, job.pk)
        now = timezone.now()
        runs = job.qc_runs.defer("input_rows", "report_issues").order_by("-pk")[:10]
        source = available_input(job)
        return Response({
            "workflow": {
                "name": "Instrument export QC",
                "version": WORKFLOW_VERSION,
                **source,
            } if source else None,
            "runs": [serialize_run(run, now) for run in runs],
        })

    @action(detail=True, methods=["post"], url_path=r"qc-runs/(?P<run_id>\d+)/retry")
    def qc_retry(self, request, pk=None, run_id=None):
        return self._queue_instrument_qc(request, self.get_object().pk, retry_id=int(run_id))

    @transaction.atomic
    def _queue_instrument_qc(self, request, job_id, retry_id=None):
        job = ImportJob.objects.select_for_update().get(pk=job_id)
        if not user_can_run_qc(request.user, job.pk):
            raise NotFound()

        now = timezone.now()
        active = job.qc_runs.filter(status__in=ACTIVE_STATUSES)
        active.filter(deadline_at__lte=now).update(
            status=InstrumentQCRun.FAILED, progress_message=TIMEOUT_MESSAGE, finished_at=now,
        )
        if active.exists():
            return Response({"detail": "An analysis is already in progress."}, status=status.HTTP_409_CONFLICT)

        previous = None
        if retry_id is not None:
            previous = get_object_or_404(job.qc_runs.defer("report_issues"), pk=retry_id)
            latest = job.qc_runs.order_by("-pk").values_list("pk", flat=True).first()
            if previous.status != InstrumentQCRun.FAILED or previous.pk != latest:
                raise serializers.ValidationError({"detail": "Only the latest failed analysis can be retried."})
            metadata = previous.input_metadata
            rows = previous.input_rows
            version = previous.workflow_version
            definition = previous.workflow_sha256
            input_digest = previous.input_sha256
        else:
            source = available_input(job)
            if not source:
                raise serializers.ValidationError({"detail": "Choose a completed file import with a saved export."})

            parameters = InstrumentQCParametersSerializer(data=request.data)
            parameters.is_valid(raise_exception=True)
            fields = [parameters.validated_data["reading_column"], parameters.validated_data["well_column"]]
            if any(field and field not in source["columns"] for field in fields):
                raise serializers.ValidationError({"detail": "Select columns from the saved export."})

            try:
                metadata = snapshot_export(job, dict(parameters.validated_data))
            except ValueError as exc:
                raise serializers.ValidationError({"detail": str(exc)}) from exc
            input_digest = hashlib.sha256(encode_input(metadata)).hexdigest()
            rows = metadata.pop("rows")
            version = WORKFLOW_VERSION
            definition = workflow_digest(version)

        run = job.qc_runs.create(
            requested_by=request.user, retry_of=previous, workflow_version=version,
            workflow_sha256=definition, input_sha256=input_digest, input_metadata=metadata,
            input_rows=rows, deadline_at=timezone.now() + QUEUE_TIMEOUT,
        )
        transaction.on_commit(lambda: deliver_instrument_qc(run.pk))
        return Response(serialize_run(run, now), status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"], url_path=r"qc-runs/(?P<run_id>\d+)/report")
    def qc_report(self, request, pk=None, run_id=None):
        job = self.get_object()
        run = get_object_or_404(
            job.qc_runs.defer("input_rows"),
            pk=run_id, status=InstrumentQCRun.COMPLETED,
        )
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="instrument-qc-{run.pk}.csv"'
        response["Cache-Control"] = "private, no-store"
        writer = csv.DictWriter(response, ["type", "data_row", "well", "detail"])
        writer.writeheader()
        if run.report_issues:
            writer.writerows(run.report_issues)
        else:
            writer.writerow({"type": "PASS", "detail": "All checked readings and well positions passed."})
        return response

    @action(detail=True, methods=["post"], url_path="retry")
    @transaction.atomic
    def retry(self, request, pk=None):
        job = ImportJob.objects.select_for_update().get(pk=self.get_object().pk)
        if job.summary.get("assistant_upload"):
            return Response({"detail": "Revalidate this import in the assistant before retrying."}, status=400)

        if "corrections" in request.data:
            return self._retry_corrected_rows(request, job)

        if job.source_type != "UPLOAD" or job.status != "FAILED" or job.summary.get("tabular", {}).get("parent_job_id"):
            return Response({"detail": "Only failed uploads can be retried in full."}, status=400)

        if job.work_items.exists():
            return Response({"detail": "This older job already saved measurements. Review its results before importing again."}, status=409)

        if not job.uploaded_file:
            return Response(
                {"detail": "This import job has no uploaded file to retry."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        previous_summary = job.summary or {}

        job.status = "PENDING"
        job.progress_current = 0
        job.progress_total = 0
        job.progress_message = "Retry queued"
        job.summary = {
            "retry_of_job_id": job.id,
            "previous_summary": {key: value for key, value in previous_summary.items() if key != "previous_summary"},
            "tabular": previous_summary.get("tabular", {}),
        }
        job.save(
            update_fields=[
                "status",
                "progress_current",
                "progress_total",
                "progress_message",
                "summary",
            ]
        )

        Event.objects.create(
            entity_type="ImportJob",
            entity_id=str(job.id),
            action="IMPORT_RETRY_QUEUED",
            actor=request.user if request.user.is_authenticated else None,
            payload={
                "job_id": job.id,
                "instrument_code": job.instrument.code if job.instrument else None,
                "source_type": job.source_type,
            },
        )

        transaction.on_commit(lambda: process_import_job.delay(job.id))

        serializer = self.get_serializer(job)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

    def _retry_corrected_rows(self, request, job):
        config = job.summary.get("tabular", {})
        if job.status != "COMPLETED" or not config.get("source_system") or config.get("parent_job_id"):
            raise serializers.ValidationError({"corrections": "Corrections require a completed keyed import."})
        validate_sample_project_assignment(request.user, job.project)

        class CorrectionSerializer(serializers.Serializer):
            row = serializers.IntegerField(min_value=1)
            values = serializers.DictField(child=serializers.CharField(
                max_length=32767, allow_blank=True, allow_null=True, trim_whitespace=False,
            ))

        serializer = CorrectionSerializer(data=request.data["corrections"], many=True, allow_empty=False, max_length=100)
        serializer.is_valid(raise_exception=True)
        eligible = {item["row"] for item in job.summary["row_report"] if item["outcome"] == "REJECTED"}
        source_rows = [item["row"] for item in serializer.validated_data]
        if len(set(source_rows)) != len(source_rows) or not set(source_rows) <= eligible:
            raise serializers.ValidationError({"corrections": "Select each rejected source row at most once."})
        current_repairs = job.row_repairs.filter(row_number__in=source_rows).select_related("child")
        for repair in current_repairs:
            child = repair.child
            outcome = next((row["outcome"] for row in child.summary.get("row_report", [])
                            if row["row"] == repair.row_number), None)
            if child.status in {"PENDING", "RUNNING"} or outcome in {"IMPORTED", "IDENTICAL"}:
                raise serializers.ValidationError({"corrections": f"Row {repair.row_number} already has a queued or successful correction."})

        child = ImportJob.objects.create(
            instrument=job.instrument, project=job.project, uploaded_by=request.user,
            status="PENDING", progress_message="Corrected rows queued",
            summary={"tabular": {
                "source_system": config["source_system"],
                "parent_job_id": job.id,
                "original_rows": source_rows,
                "corrected_rows": [item["values"] for item in serializer.validated_data],
            }},
        )
        for row_number in source_rows:
            ImportRowRepair.objects.update_or_create(
                parent=job, row_number=row_number,
                defaults={"child": child, "created_by": request.user},
            )
        transaction.on_commit(lambda: process_import_job.delay(child.id))
        return Response(self.get_serializer(child).data, status=status.HTTP_202_ACCEPTED)

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
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            instrument = (
                InstrumentProfile.objects.prefetch_related("column_mappings").get(
                    code=instrument_code
                )
            )
        except InstrumentProfile.DoesNotExist:
            return Response(
                {"detail": "Instrument not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
            return Response(
                {"detail": "rows must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        options = serializers.Serializer(data=request.data)
        options.fields["source_system"] = self._tabular_options()["source_system"]
        options.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                job, created = ImportJob.objects.get_or_create(
                    instrument=instrument, run_id=run_id,
                    defaults={
                        "project_id": project_id or None,
                        "source_type": "API", "status": "RUNNING",
                        "progress_total": len(rows), "progress_message": "Processing API payload",
                        "summary": {"tabular": dict(options.validated_data)},
                    },
                )
        except IntegrityError:
            return Response({"detail": "Invalid project or import identity."}, status=400)
        if not created:
            return Response({"detail": "Duplicate run_id for this instrument."}, status=409)

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
                        **{key: value for key, value in summary.items() if key != "row_report"},
                    },
                )

            return Response(
                {
                    "job_id": job.id,
                    "run_id": run_id,
                    "status": job.status,
                    **summary,
                },
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            job.status = "FAILED"
            job.summary = {"error": str(e)}
            job.progress_message = f"API ingest failed: {e}"[:255]
            job.save()

            return Response(
                {"detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
