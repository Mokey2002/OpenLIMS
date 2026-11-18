import logging
import math

from celery import shared_task
from django.core.exceptions import PermissionDenied
from django.db import OperationalError, transaction
from django.utils import timezone

from core.realtime import broadcast_job_update
from events.models import Event
from notifications.models import Notification
from samples.models import Sample
from samples.access import user_can_modify_sample
from results.models import WorkItem, Result

from .models import ImportJob, InstrumentProfile, InstrumentQCRun
from .row_identity import claim_row
from .tabular import read_tabular


logger = logging.getLogger(__name__)

def broadcast_import_job_update(job, message):
    from django.db import connection
    from assistant.job_health import record_action_progress
    # Atomic prepared imports must not hold an Action lock during their full
    # data transaction: the independent stall monitor needs to inspect it.
    if not (job.summary.get("assistant_upload") and connection.in_atomic_block):
        record_action_progress(action_type="QUEUE_IMPORT", result_key="import_job_id", result_id=job.pk,
            current_step="Importing rows" if job.status == "RUNNING" else job.status.capitalize(),
            last_completed_step=f"{job.progress_current} of {job.progress_total} rows processed" if job.progress_current else "Worker received import",
            current=job.progress_current, total=job.progress_total)
    progress_percent = 0

    if job.progress_total:
        progress_percent = round((job.progress_current / job.progress_total) * 100)

    if job.status == "COMPLETED":
        progress_percent = 100

    broadcast_job_update(
        {
            "type": "import_job_update",
            "import_job_id": job.id,
            "job_id": job.id,
            "status": job.status,
            "progress_current": job.progress_current,
            "progress_total": job.progress_total,
            "progress_percent": progress_percent,
            "progress_message": job.progress_message,
            "message": message,
        }
    )


def validate_mapped_value(mapping, raw_value):
    if raw_value in (None, ""):
        return {"ok": True, "normalized": None}

    raw_value = str(raw_value).strip()

    if mapping.value_type == "NUMBER":
        try:
            val = float(raw_value)
        except (ValueError, OverflowError):
            return {"ok": False, "reason": f"Invalid NUMBER '{raw_value}'"}
        if not math.isfinite(val):
            return {"ok": False, "reason": "Numeric values must be finite."}

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

        return {"ok": True, "normalized": val in ["true", "1", "yes", "pass", "ok"]}

    return {"ok": True, "normalized": raw_value}


def process_rows(job, rows, actor=None, *, mappings=None):
    instrument = job.instrument
    if mappings is None:
        mappings = {m.source_column: m for m in instrument.column_mappings.all()}

    rows_processed = 0
    samples_matched = 0
    samples_created = 0
    results_created = 0
    skipped_rows = []
    row_report = []
    tabular = job.summary.get("tabular")
    keyed = bool(tabular and tabular.get("source_system"))
    if keyed:
        # Serialize competing claims for an instrument, including batches whose IDs
        # appear in opposite orders. The caller owns the data transaction.
        InstrumentProfile.objects.select_for_update().get(pk=instrument.pk)
    original_rows = tabular.get("original_rows") if tabular else None

    def report(row_number, row, outcome, issues=()):
        if tabular is not None:
            row_report.append({
                "row": row_number,
                "sample_id": row.get(instrument.sample_id_column) or "",
                "external_id": row.get("external_id") or "",
                "outcome": outcome,
                "issues": list(issues),
                **({"values": {k: v for k, v in row.items() if k is not None}}
                   if keyed and outcome in {"REJECTED", "CONFLICT"} else {}),
            })

    created_sample_ids = []
    matched_sample_ids = []
    touched_sample_ids = []

    job.progress_total = len(rows)
    job.progress_current = 0
    job.progress_message = "Starting import"
    job.save(update_fields=["progress_total", "progress_current", "progress_message"])

    broadcast_import_job_update(
        job,
        f"Import started: {instrument.code}",
    )

    for row in rows:
        rows_processed += 1

        row_number = original_rows[rows_processed - 1] if original_rows else rows_processed
        issue_start = len(skipped_rows)
        sample_code = str(row.get(instrument.sample_id_column) or "").strip()

        if not sample_code:
            skipped_rows.append(
                {
                    "row": row_number,
                    "reason": f"Missing sample ID column '{instrument.sample_id_column}'",
                }
            )
            report(row_number, row, "REJECTED", skipped_rows[issue_start:])
            continue

        if keyed:
            issues = []
            for column, mapping in mappings.items():
                validation = validate_mapped_value(mapping, row.get(column))
                if not validation["ok"]:
                    issues.append({"row": row_number, "sample_id": sample_code,
                                   "column": column, "reason": validation["reason"]})
            if len(sample_code) > Sample._meta.get_field("sample_id").max_length:
                issues.append({"row": row_number, "reason": "Sample ID exceeds 64 characters."})
            if None in row:
                issues.append({"row": row_number, "reason": "More values than header columns."})
            if issues:
                skipped_rows.extend(issues)
                report(row_number, row, "REJECTED", issues)
                continue

            sample = Sample.objects.filter(sample_id=sample_code).first()
            if sample and actor and not user_can_modify_sample(actor, sample):
                issue = {"row": row_number, "reason": "Sample exists but this user cannot import results into it."}
                skipped_rows.append(issue)
                report(row_number, row, "REJECTED", [issue])
                continue
            try:
                outcome, reason, receipt = claim_row(job, row, row_number)
            except ValueError as exc:
                outcome, reason = "REJECTED", str(exc)
            if outcome != "IMPORTED":
                issue = {"row": row_number, "sample_id": sample_code, "reason": reason}
                if outcome != "IDENTICAL":
                    skipped_rows.append(issue)
                report(row_number, row, outcome, [issue])
                continue

        defaults = {
            "status": "RECEIVED",
            "created_by": actor,
        }

        if job.project_id:
            defaults["project_id"] = job.project_id

        sample, created = Sample.objects.get_or_create(
            sample_id=sample_code,
            defaults=defaults,
        )

        if not created and actor and not user_can_modify_sample(actor, sample):
            skipped_rows.append(
                {
                    "row": row_number,
                    "sample_id": sample_code,
                    "reason": "Sample exists but this user cannot import results into it.",
                }
            )
            if keyed:
                receipt.delete()
            report(row_number, row, "REJECTED", skipped_rows[issue_start:])
            continue

        touched_sample_ids.append(sample.id)

        if created:
            samples_created += 1
            created_sample_ids.append(sample.id)

            Event.objects.create(
                entity_type="Sample",
                entity_id=str(sample.id),
                action="CREATED",
                actor=actor,
                payload={
                    **({'assistant_action_id': job.summary.get('queued_by_action_id')} if job.summary.get('assistant_upload') else {}),
                    "sample_id": sample.id,
                    "sample_code": sample.sample_id,
                    "source": "instrument_import",
                    "instrument_code": instrument.code,
                    "import_job_id": job.id,
                    "project_id": job.project_id,
                },
            )
        else:
            samples_matched += 1
            matched_sample_ids.append(sample.id)

            if job.project_id and sample.project_id is None:
                before = {"project_id": sample.project_id}

                sample.project_id = job.project_id
                sample.save(update_fields=["project"])

                after = {"project_id": sample.project_id}

                Event.objects.create(
                    entity_type="Sample",
                    entity_id=str(sample.id),
                    action="UPDATED",
                    actor=actor,
                    payload={
                        **({'assistant_action_id': job.summary.get('queued_by_action_id')} if job.summary.get('assistant_upload') else {}),
                        "sample_id": sample.id,
                        "sample_code": sample.sample_id,
                        "source": "instrument_import",
                        "import_job_id": job.id,
                        "before": before,
                        "after": after,
                    },
                )

        work_item = WorkItem.objects.create(
            sample=sample,
            source_import_job=job,
            name=f"{instrument.code} Import - Job {job.id}",
            status="COMPLETED",
            notes=f"Imported from {instrument.name} (Import Job {job.id})",
            created_by=actor,
        )

        for source_column, mapping in mappings.items():
            raw_value = row.get(source_column)

            if raw_value in (None, ""):
                continue

            validation = validate_mapped_value(mapping, raw_value)

            if not validation["ok"]:
                skipped_rows.append(
                    {
                        "row": row_number,
                        "sample_id": sample_code,
                        "column": source_column,
                        "reason": validation["reason"],
                    }
                )
                continue

            normalized = validation["normalized"]

            defaults = {
                "value_type": mapping.value_type,
                "value_string": "",
                "value_number": None,
                "value_boolean": None,
                "entered_by": actor,
                "reference_min": mapping.min_value,
                "reference_max": mapping.max_value,
                "qc_rule": (
                    f"{mapping.target_key} must satisfy the configured instrument mapping."
                ),
            }

            if mapping.value_type == "STRING":
                defaults["value_string"] = normalized
            elif mapping.value_type == "NUMBER":
                defaults["value_number"] = normalized
            elif mapping.value_type == "BOOLEAN":
                defaults["value_boolean"] = normalized

            if mapping.value_type == "NUMBER":
                defaults["qc_passed"] = True
            elif mapping.value_type == "STRING" and str(normalized).upper() in {
                "PASS",
                "FAIL",
                "REVIEW",
            }:
                defaults["qc_passed"] = str(normalized).upper() == "PASS"
                defaults["qc_failure_reason"] = (
                    ""
                    if defaults["qc_passed"]
                    else f"Instrument reported {str(normalized).upper()}."
                )

            Result.objects.update_or_create(
                work_item=work_item,
                key=mapping.target_key,
                defaults=defaults,
            )

            results_created += 1

        issues = skipped_rows[issue_start:]
        report(row_number, row, "IMPORTED_WITH_WARNINGS" if issues else "IMPORTED", issues)

        job.progress_current = rows_processed
        job.progress_message = f"Processed {rows_processed} of {len(rows)} rows"
        job.save(update_fields=["progress_current", "progress_message"])

        broadcast_import_job_update(
            job,
            job.progress_message,
        )

    return {
        **({"tabular": tabular, "row_report": row_report} if tabular is not None else {}),
        "rows_processed": rows_processed,
        "samples_matched": samples_matched,
        "samples_created": samples_created,
        "results_created": results_created,
        "skipped_rows": skipped_rows,
        "project_id": job.project_id,
        "created_sample_ids": sorted(set(created_sample_ids)),
        "matched_sample_ids": sorted(set(matched_sample_ids)),
        "touched_sample_ids": sorted(set(touched_sample_ids)),
    }


@shared_task(acks_late=True, reject_on_worker_lost=True)
def process_import_job(job_id):
    if ImportJob.objects.filter(pk=job_id, summary__has_key="assistant_upload").exists():
        from .assistant_uploads import process_prepared_job
        return process_prepared_job(job_id)
    with transaction.atomic():
        result = _process_tabular_job(job_id)
    if isinstance(result, Exception):
        raise result
    return result


def _process_tabular_job(job_id):
    # Lock only the import job. Some related records are nullable, and
    # PostgreSQL rejects SELECT FOR UPDATE across those outer joins.
    job = ImportJob.objects.select_for_update().get(id=job_id)
    if job.status != "PENDING":
        return job.summary
    job.status = "RUNNING"
    job.progress_message = "Reading staged rows"
    job.save(update_fields=["status", "progress_message"])

    initial_summary = job.summary.copy()
    try:
        with transaction.atomic():
            broadcast_import_job_update(
                job,
                f"Import running: {job.instrument.code}",
            )

            tabular = job.summary.get("tabular", {})
            if "corrected_rows" in tabular:
                rows, csv_metadata = tabular["corrected_rows"], {}
            else:
                rows, csv_metadata = read_tabular(job.uploaded_file, job.instrument, tabular.get("sheet"))
                if rows is None:
                    raise ValueError("Select an Excel sheet before importing.")
            job.summary.setdefault("tabular", tabular)

            summary = process_rows(job, rows, actor=job.uploaded_by)
            summary["csv_metadata"] = csv_metadata
            summary["tabular"] = {k: v for k, v in tabular.items() if k != "corrected_rows"}

            job.status = "COMPLETED"
            job.summary = summary
            job.progress_current = summary["rows_processed"]
            job.progress_total = summary["rows_processed"]
            job.progress_message = "Import completed"
            job.save(
                update_fields=[
                    "status",
                    "summary",
                    "progress_current",
                    "progress_total",
                    "progress_message",
                ]
            )

            job.refresh_from_db()

            transaction.on_commit(
                lambda: broadcast_import_job_update(job, f"Import completed: {job.instrument.code}"),
                robust=True,
            )

            Event.objects.create(
                entity_type="ImportJob",
                entity_id=str(job.id),
                action="RESULTS_IMPORTED",
                actor=job.uploaded_by,
                payload={
                    "instrument_code": job.instrument.code,
                    "instrument_name": job.instrument.name,
                    "run_id": job.run_id,
                    **{key: value for key, value in summary.items() if key != "row_report"},
                },
            )

            from assistant.lifecycle import finish_queued_action

            finish_queued_action(
                action_type="QUEUE_IMPORT",
                result_key="import_job_id",
                result_id=job.id,
                succeeded=True,
                result_updates={
                    "job_status": job.status,
                    "rows_processed": summary.get("rows_processed", 0),
                    "samples_created": summary.get("samples_created", 0),
                    "results_created": summary.get("results_created", 0),
                    "skipped_row_count": len(summary.get("skipped_rows", [])),
                },
            )

            if job.uploaded_by:
                Notification.objects.create(
                    user=job.uploaded_by,
                    title="Import completed",
                    message=f"{job.instrument.code} import finished. {summary['results_created']} results created.",
                    link="/imports",
                )

            return summary

    except Exception as e:
        job.status = "FAILED"
        job.summary = {**initial_summary, "error": str(e)}
        job.progress_message = f"Import failed: {e}"[:255]
        job.save(
            update_fields=[
                "status",
                "summary",
                "progress_message",
            ]
        )

        job.refresh_from_db()

        transaction.on_commit(
            lambda: broadcast_import_job_update(job, f"Import failed: {job.instrument.code}"),
            robust=True,
        )

        from assistant.lifecycle import finish_queued_action

        finish_queued_action(
            action_type="QUEUE_IMPORT",
            result_key="import_job_id",
            result_id=job.id,
            succeeded=False,
            error_message=str(e),
            result_updates={"job_status": job.status},
        )

        from assistant.job_health import assistant_managed_job
        if job.uploaded_by and not assistant_managed_job("QUEUE_IMPORT", "import_job_id", job.pk):
            Notification.objects.create(
                user=job.uploaded_by,
                title="Import failed",
                message=f"{job.instrument.code} import failed: {str(e)}",
                link="/imports",
            )

        return e


@shared_task(acks_late=True, reject_on_worker_lost=True, autoretry_for=(OperationalError, OSError), retry_backoff=True, retry_kwargs={"max_retries": 5})
def process_assistant_import_job(job_id, action_id):
    from .assistant_uploads import process_prepared_job
    return process_prepared_job(job_id, action_id)


@shared_task(
    acks_late=True, reject_on_worker_lost=True, ignore_result=True,
)
def run_instrument_qc(run_id):
    from .instrument_qc import RUN_TIMEOUT, execute_workflow, user_can_run_qc

    runs = InstrumentQCRun.objects.filter(pk=run_id)
    now = timezone.now()
    if not runs.filter(status=InstrumentQCRun.QUEUED, deadline_at__gt=now).update(
        status=InstrumentQCRun.RUNNING, started_at=now, deadline_at=now + RUN_TIMEOUT,
        progress_message="Checking the readings and well positions.",
    ):
        return

    run = runs.select_related("requested_by").get()
    running = runs.filter(status=InstrumentQCRun.RUNNING)

    def report_progress():
        running.update(progress_message="Preparing the report.")

    try:
        if not user_can_run_qc(run.requested_by, run.job_id):
            raise PermissionDenied("The requester no longer has access to run this analysis.")
        report = execute_workflow(run, report_progress)
        if not user_can_run_qc(run.requested_by, run.job_id):
            raise PermissionDenied("The requester no longer has access to run this analysis.")
    except (TimeoutError, PermissionDenied, FileNotFoundError) as exc:
        if isinstance(exc, TimeoutError):
            message = "The analysis timed out. Retry to run it again."
        elif isinstance(exc, PermissionDenied):
            message = "The requester lost access. Ask a project technician or admin to retry."
        else:
            message = "The instrument QC worker is missing a workflow file or the Snakemake executable."
        running.update(status=InstrumentQCRun.FAILED, progress_message=message, finished_at=timezone.now())
        return
    except Exception:
        logger.exception("Instrument QC run %s failed.", run_id)
        running.update(
            status=InstrumentQCRun.FAILED,
            progress_message="Analysis failed. Check the instrument QC worker logs and retry.",
            finished_at=timezone.now(),
        )
        return

    now = timezone.now()
    running.filter(deadline_at__gt=now).update(
        status=InstrumentQCRun.COMPLETED,
        progress_message="Report ready.",
        finished_at=now,
        engine_version=report["engine_version"],
        report_summary=report["summary"],
        report_issues=report["issues"],
    )


def deliver_instrument_qc(run_id):
    try:
        run_instrument_qc.apply_async(args=(run_id,), retry=False)
    except Exception:
        logger.exception("Could not queue instrument QC run %s.", run_id)
        InstrumentQCRun.objects.filter(pk=run_id, status=InstrumentQCRun.QUEUED).update(
            status=InstrumentQCRun.FAILED,
            progress_message="Could not queue the analysis. Check the instrument QC worker and retry.",
            finished_at=timezone.now(),
        )
