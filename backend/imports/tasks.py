import csv
import io

from celery import shared_task
from django.db import transaction

from events.models import Event
from notifications.models import Notification
from samples.models import Sample
from results.models import WorkItem, Result

from .models import ImportJob


def validate_mapped_value(mapping, raw_value):
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
        if val not in ["true", "1", "yes", "pass", "ok", "false", "0", "no", "fail"]:
            return {"ok": False, "reason": "Invalid boolean"}

        return {"ok": True, "normalized": val in ["true", "1", "yes", "pass", "ok"]}

    return {"ok": True, "normalized": raw_value}


def process_rows(job, rows, actor=None):
    instrument = job.instrument
    mappings = {m.source_column: m for m in instrument.column_mappings.all()}

    rows_processed = 0
    samples_matched = 0
    samples_created = 0
    results_created = 0
    skipped_rows = []

    created_sample_ids = []
    matched_sample_ids = []
    touched_sample_ids = []

    job.progress_total = len(rows)
    job.progress_current = 0
    job.progress_message = "Starting import"
    job.save(update_fields=["progress_total", "progress_current", "progress_message"])

    for row in rows:
        rows_processed += 1

        sample_code = row.get(instrument.sample_id_column)

        if not sample_code:
            skipped_rows.append({
                "row": rows_processed,
                "reason": f"Missing sample ID column '{instrument.sample_id_column}'",
            })
            continue

        sample_code = str(sample_code).strip()

        defaults = {"status": "RECEIVED"}

        if job.project_id:
            defaults["project_id"] = job.project_id

        sample, created = Sample.objects.get_or_create(
            sample_id=sample_code,
            defaults=defaults,
        )

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
            name=f"{instrument.code} Import - Job {job.id}",
            status="COMPLETED",
            notes=f"Imported from {instrument.name} (Import Job {job.id})",
        )

        for source_column, mapping in mappings.items():
            raw_value = row.get(source_column)

            if raw_value in (None, ""):
                continue

            validation = validate_mapped_value(mapping, raw_value)

            if not validation["ok"]:
                skipped_rows.append({
                    "row": rows_processed,
                    "sample_id": sample_code,
                    "column": source_column,
                    "reason": validation["reason"],
                })
                continue

            normalized = validation["normalized"]

            defaults = {
                "value_type": mapping.value_type,
                "value_string": "",
                "value_number": None,
                "value_boolean": None,
            }

            if mapping.value_type == "STRING":
                defaults["value_string"] = normalized
            elif mapping.value_type == "NUMBER":
                defaults["value_number"] = normalized
            elif mapping.value_type == "BOOLEAN":
                defaults["value_boolean"] = normalized

            Result.objects.update_or_create(
                work_item=work_item,
                key=mapping.target_key,
                defaults=defaults,
            )

            results_created += 1

        job.progress_current = rows_processed
        job.progress_message = f"Processed {rows_processed} of {len(rows)} rows"
        job.save(update_fields=["progress_current", "progress_message"])




    return {
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


@shared_task
def process_import_job(job_id):
    job = ImportJob.objects.select_related("instrument", "project", "uploaded_by").get(id=job_id)

    try:
        job.status = "RUNNING"
        job.progress_message = "Reading CSV file"
        job.save(update_fields=["status", "progress_message"])

        job.uploaded_file.seek(0)
        decoded = job.uploaded_file.read().decode("utf-8")
        job.uploaded_file.seek(0)

        reader = csv.DictReader(
            io.StringIO(decoded),
            delimiter=job.instrument.delimiter,
        )
        rows = list(reader)

        with transaction.atomic():
            summary = process_rows(job, rows, actor=job.uploaded_by)

            job.status = "COMPLETED"
            job.summary = summary
            job.progress_current = summary["rows_processed"]
            job.progress_total = summary["rows_processed"]
            job.progress_message = "Import completed"
            job.save()

            Event.objects.create(
                entity_type="ImportJob",
                entity_id=str(job.id),
                action="RESULTS_IMPORTED",
                actor=job.uploaded_by,
                payload={
                    "instrument_code": job.instrument.code,
                    "instrument_name": job.instrument.name,
                    "run_id": job.run_id,
                    **summary,
                },
            )

            if job.uploaded_by:
                Notification.objects.create(
                    user=job.uploaded_by,
                    title="Import completed",
                    message=f"{job.instrument.code} import finished. {summary['results_created']} results created.",
                    link="/imports",
                )

    except Exception as e:
        job.status = "FAILED"
        job.summary = {"error": str(e)}
        job.progress_message = f"Import failed: {str(e)}"
        job.save()

        if job.uploaded_by:
            Notification.objects.create(
                user=job.uploaded_by,
                title="Import failed",
                message=f"{job.instrument.code} import failed: {str(e)}",
                link="/imports",
            )

        raise
