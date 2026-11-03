"""Validated chat uploads: frozen inputs, row accounting and atomic imports."""
import csv
import hashlib
import io
import json
import logging
import math
from itertools import islice
from types import SimpleNamespace

from django.db import transaction
from django.db.models.functions import Lower
from rest_framework.exceptions import ValidationError

from core.permissions import is_admin, is_tech
from core.upload_validators import MAX_UPLOAD_SIZE_BYTES
from custom_fields.forms import schema_for, validate_values
from events.models import Event
from samples.models import Sample
from .csv_utils import get_csv_dict_reader
from .models import ImportJob

MARKER = "assistant_upload"
MAX_ROWS = 10000
logger = logging.getLogger(__name__)


def deliver_import(job_id, action_id):
    from .tasks import process_assistant_import_job
    try:
        process_assistant_import_job.delay(job_id, action_id)
    except Exception:
        with transaction.atomic():
            job = ImportJob.objects.select_for_update().get(pk=job_id)
            if job.status == "PENDING" and job.summary.get("queued_by_action_id") == action_id:
                job.summary = {**job.summary, "queue_error": "Worker delivery could not be verified. Use Resume queued import to try again."}
                job.save(update_fields=["summary"])


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def require_writer(user, project):
    if not user or not user.is_active or not (is_admin(user) or is_tech(user)):
        raise ValueError("An active Tech or Admin is required to import instrument data.")
    if not project or not (is_admin(user) or project.members.filter(pk=user.pk).exists()):
        raise ValueError("The selected project is unavailable or your write access changed.")


def profile_snapshot(instrument):
    fields = ["id", "code", "name", "delimiter", "has_header", "header_row_index", "auto_detect_header", "sample_id_column"]
    config = {key: getattr(instrument, key) for key in fields}
    mappings = list(instrument.column_mappings.order_by("source_column").values(
        "source_column", "target_key", "value_type", "min_value", "max_value", "allowed_values"))
    if not instrument.has_header or len(instrument.delimiter) != 1 or not mappings:
        raise ValueError("Choose a header-based instrument profile with a delimiter and at least one configured mapping.")
    if len({row["target_key"] for row in mappings}) != len(mappings):
        raise ValueError("The instrument mapping repeats a result key. An administrator must correct it before importing.")
    for row in mappings:
        if (row["value_type"] not in {"STRING", "NUMBER", "BOOLEAN"} or not row["source_column"] or not row["target_key"] or len(row["target_key"]) > 64
                or any(value is not None and not math.isfinite(value) for value in [row["min_value"], row["max_value"]])
                or row["min_value"] is not None and row["max_value"] is not None and row["min_value"] > row["max_value"]):
            raise ValueError("The instrument mapping has invalid types or limits. Ask an administrator to correct it.")
    config["mappings"] = mappings
    try:
        digest(config)
    except (ValueError, TypeError):
        raise ValueError("The instrument mapping contains an invalid value.")
    return config


def inspect_upload(raw, instrument, project, user, skip_duplicates):
    from .tasks import validate_mapped_value
    from assistant.registration_input import _validate_json
    require_writer(user, project)
    config = profile_snapshot(instrument)
    if not raw or len(raw) > MAX_UPLOAD_SIZE_BYTES:
        raise ValueError("Upload a nonempty UTF-8 file no larger than 10 MB.")
    try:
        reader, metadata = get_csv_dict_reader(raw.decode("utf-8-sig"), instrument)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or any(not name for name in headers):
            raise ValueError("CSV headers must be nonempty and unique.")
        required = {instrument.sample_id_column, *(row["source_column"] for row in config["mappings"])}
        if required - set(headers):
            raise ValueError("The file is missing mapped columns: " + ", ".join(sorted(required - set(headers))))
        rows = list(islice(reader, MAX_ROWS + 1))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("The file must be valid UTF-8 CSV/TSV matching the selected profile.") from exc
    if not rows or len(rows) > MAX_ROWS:
        raise ValueError(f"Upload between 1 and {MAX_ROWS} data rows.")
    codes = {str(row.get(instrument.sample_id_column) or "").strip().lower() for row in rows}
    samples = {sample.import_code: sample for sample in Sample.objects.annotate(import_code=Lower("sample_id"))
               .filter(import_code__in=codes).only("id", "sample_id", "project_id", "created_by_id")}
    try:
        validate_values(schema_for("GENERAL"), {})
        can_create = True
    except ValidationError:
        can_create = False
    accepted, references, report, seen, new_codes, existing_ids, new_canonical = [], [], [], {}, set(), set(), {}
    result_cells = duplicate_detected = 0
    for index, row in enumerate(rows, 1):
        code = str(row.get(instrument.sample_id_column) or "").strip()
        sample = samples.get(code.lower())
        errors, cells = [], 0
        normalized_row = dict(row)
        if None in row or any(value is None for value in row.values()):
            errors.append("Row width does not match the CSV header.")
        if not code or len(code) > 64:
            errors.append("A sample ID of 1–64 characters is required.")
        if sample and not (sample.project_id == project.pk or sample.project_id is None and (is_admin(user) or sample.created_by_id == user.pk)):
            errors.append("Sample unavailable or not writable in the selected project.")
        if not sample and not can_create:
            errors.append("Register this sample with its required intake fields before importing results.")
        try:
            _validate_json(row)
        except ValueError:
            errors.append("Row contains invalid text or characters.")
        for mapping in config["mappings"]:
            value = row.get(mapping["source_column"])
            if value in (None, "") or isinstance(value, str) and not value.strip():
                normalized_row[mapping["source_column"]] = ""
                continue
            validation = validate_mapped_value(SimpleNamespace(**mapping), value)
            if not validation["ok"]:
                errors.append(mapping["source_column"] + ": " + validation["reason"][:200])
            else:
                cells += 1
        if not cells and not errors:
            errors.append("Row has no mapped result values.")
        identity = digest([row.get(header) for header in headers])
        duplicate_of = seen.get(identity)
        if errors:
            state, reason = "rejected", "; ".join(errors)
        elif duplicate_of and skip_duplicates:
            duplicate_detected += 1
            state, reason = "duplicate", f"Exact repeat of data row {duplicate_of}; skipped by the selected policy."
        else:
            if duplicate_of:
                duplicate_detected += 1
            seen.setdefault(identity, index)
            state, reason = "ready", f"Exact repeat of data row {duplicate_of}; retained as a replicate." if duplicate_of else ""
            canonical = sample.sample_id if sample else new_canonical.setdefault(code.lower(), code)
            accepted.append({**normalized_row, instrument.sample_id_column: canonical})
            references.append({"row": index, "sample_pk": sample.pk if sample else None, "code": canonical,
                               "project_id": sample.project_id if sample else None, "identity": identity})
            result_cells += cells
            if sample:
                existing_ids.add(sample.pk)
            else:
                new_codes.add(code.lower())
        report.append({"row": index, "sample_id": code, "status": state, "reason": reason, "result_cells": cells if state == "ready" else 0})
    counts = {"rows_received": len(rows), "rows_to_import": len(accepted),
              "rows_rejected": sum(row["status"] == "rejected" for row in report),
              "duplicates_skipped": sum(row["status"] == "duplicate" for row in report),
              "duplicates_detected": duplicate_detected, "expected_results": result_cells,
              "new_samples": len(new_codes), "existing_samples": len(existing_ids)}
    return {"config": config, "file_sha256": hashlib.sha256(raw).hexdigest(), "accepted": accepted,
            "references": references, "report": report, "counts": counts, "csv_metadata": metadata,
            "unmapped_columns": [key for key in headers if key not in required],
            "plan_digest": digest({"references": references, "report": report, "counts": counts})}


def read_file(job):
    if not job.uploaded_file:
        raise ValueError("The staged file is unavailable. Prepare the import again.")
    with job.uploaded_file.open("rb") as source:
        raw = source.read(MAX_UPLOAD_SIZE_BYTES + 1)
    return raw


def validate_prepared(job, user):
    frozen = job.summary.get(MARKER) or {}
    if (not frozen or frozen.get("owner_id") != user.pk or job.uploaded_by_id != user.pk
            or frozen.get("project_id") != job.project_id or frozen.get("instrument_id") != job.instrument_id
            or frozen.get("run_id") != job.run_id):
        raise ValueError("The prepared import identity changed. Revalidate it before confirming.")
    analysis = inspect_upload(read_file(job), job.instrument, job.project, user, frozen["skip_duplicates"])
    if (analysis["file_sha256"] != frozen["file_sha256"] or analysis["config"] != frozen["config"]
            or analysis["plan_digest"] != frozen["plan_digest"]):
        raise ValueError("The file, mapping, samples or validation changed. Revalidate the import before confirming.")
    if not analysis["accepted"]:
        raise ValueError("No rows are available to import.")
    return analysis


def process_prepared_job(job_id, expected_action_id=None):
    from .tasks import process_rows
    from assistant.lifecycle import finish_queued_action
    attempt = None
    try:
        with transaction.atomic():
            job = ImportJob.objects.select_for_update(of=("self",)).select_related("instrument", "project", "uploaded_by").get(pk=job_id)
            attempt = job.summary.get("queued_by_action_id")
            if expected_action_id is not None and attempt != str(expected_action_id):
                return job.summary
            if job.summary.get("awaiting_assistant_confirmation") or not attempt or job.status not in {"PENDING", "COMPLETED"}:
                return job.summary
            if job.status != "COMPLETED":
                analysis = validate_prepared(job, job.uploaded_by)
                ids = sorted({row["sample_pk"] for row in analysis["references"] if row["sample_pk"]})
                list(Sample.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
                analysis = validate_prepared(job, job.uploaded_by)
                job.status = "RUNNING"
                job.save(update_fields=["status"])
                mappings = {row["source_column"]: SimpleNamespace(**row) for row in analysis["config"]["mappings"]}
                imported = process_rows(job, analysis["accepted"], actor=job.uploaded_by, mappings=mappings)
                if imported["skipped_rows"] or imported["results_created"] != analysis["counts"]["expected_results"]:
                    raise ValueError("The import changed during processing. No measurements were committed; revalidate it.")
                report = [{**row, "status": "imported" if row["status"] == "ready" else row["status"]} for row in analysis["report"]]
                receipt = {**analysis["counts"], "rows_imported": imported["rows_processed"], "results_created": imported["results_created"],
                           "samples_created": imported["samples_created"], "rows_accounted": len(report)}
                job.status = "COMPLETED"
                job.summary = {**job.summary, "receipt": receipt, "row_report": report, "error": "", "queue_error": ""}
                job.progress_current = job.progress_total = receipt["rows_received"]
                job.progress_message = "Import completed; all file rows accounted for"
                job.save(update_fields=["status", "summary", "progress_current", "progress_total", "progress_message"])
                Event.objects.create(entity_type="ImportJob", entity_id=str(job.pk), action="RESULTS_IMPORTED", actor=job.uploaded_by,
                                     payload={"instrument_code": job.instrument.code, "run_id": job.run_id, **receipt})
    except Exception as exc:
        error = str(exc) if isinstance(exc, (ValueError, ValidationError)) else "Import failed during processing. No measurements were committed; revalidate the import."
        # The data transaction has rolled back before recording the failure.
        with transaction.atomic():
            job = ImportJob.objects.select_for_update().get(pk=job_id)
            if job.summary.get("queued_by_action_id") != attempt:
                return job.summary
            if job.status != "COMPLETED":
                job.status = "FAILED"
                counts = job.summary[MARKER]["counts"]
                report = [{**row, "status": "not_imported", "reason": "Import failed; no measurements committed."} if row["status"] == "ready" else row for row in job.summary.get("row_report", [])]
                job.summary = {**job.summary, "error": error, "row_report": report, "receipt": {
                    **counts, "rows_imported": 0, "rows_not_imported": counts["rows_to_import"], "rows_accounted": counts["rows_received"], "results_created": 0}}
                job.progress_current = 0
                job.progress_message = "Import failed; no measurements committed"
                job.save(update_fields=["status", "summary", "progress_current", "progress_message"])
    # Also runs on redelivery after data committed but action finalization was interrupted.
    receipt = job.summary.get("receipt", {})
    succeeded = job.status == "COMPLETED"
    message = (f"Imported {receipt['rows_imported']} of {receipt['rows_received']} rows; {receipt['rows_rejected']} rejected; {receipt['duplicates_skipped']} exact repeats skipped."
               if succeeded else "Import failed; no measurements committed.")
    finish_queued_action(action_type="QUEUE_IMPORT", result_key="import_job_id", result_id=job_id, succeeded=succeeded,
                         action_id=attempt, error_message=job.summary.get("error", ""), result_updates={"job_status": job.status, "message": message, **receipt})
    try:
        from .tasks import broadcast_import_job_update
        broadcast_import_job_update(job, message)
    except Exception:
        logger.warning("Could not publish final progress for instrument import %s", job_id, exc_info=True)
    return job.summary


def report_csv(job):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["data_row", "sample_id", "status", "reason", "result_cells"])
    rows = job.summary.get("row_report", [])
    for row in rows:
        values = [row.get(key, "") for key in ["row", "sample_id", "status", "reason", "result_cells"]]
        writer.writerow(["'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for value in values])
    return output.getvalue().encode("utf-8-sig")
