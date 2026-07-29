from celery import shared_task
from django.utils import timezone

from .models import MigrationJob
from .services import apply_migration


@shared_task(bind=True)
def run_migration_job(self, job_id):
    job = (
        MigrationJob.objects
        .select_related("profile", "project", "uploaded_by")
        .filter(id=job_id)
        .first()
    )

    if not job:
        return {"error": f"MigrationJob {job_id} not found."}

    job.status = MigrationJob.STATUS_RUNNING
    job.summary = {
        **(job.summary or {}),
        "queued": False,
        "started_at": timezone.now().isoformat(),
        "progress": {
            "processed_rows": 0,
            "total_rows": None,
            "percent": 0,
        },
    }
    job.save(update_fields=["status", "summary"])

    def update_progress(progress):
        job.refresh_from_db(fields=["summary"])

        summary = job.summary or {}
        summary["progress"] = progress
        summary["last_progress_at"] = timezone.now().isoformat()

        job.summary = summary
        job.save(update_fields=["summary"])

    try:
        job.uploaded_file.open("rb")

        summary = apply_migration(
            profile=job.profile,
            uploaded_file=job.uploaded_file,
            actor=job.uploaded_by,
            default_project=job.project,
            job=job,
            progress_callback=update_progress,
        )

        summary["started_at"] = job.summary.get("started_at")
        summary["finished_at"] = timezone.now().isoformat()

        if summary.get("skipped_rows"):
            job.status = MigrationJob.STATUS_PARTIAL_FAILED
        else:
            job.status = MigrationJob.STATUS_COMPLETED

        job.summary = summary
        job.save(update_fields=["status", "summary"])

        return summary

    except Exception as exc:
        job.refresh_from_db(fields=["summary"])

        summary = job.summary or {}
        summary["error"] = str(exc)
        summary["failed_at"] = timezone.now().isoformat()

        job.status = MigrationJob.STATUS_FAILED
        job.summary = summary
        job.save(update_fields=["status", "summary"])

        return {"error": str(exc), "job_id": job.id}

    finally:
        try:
            job.uploaded_file.close()
        except Exception:
            pass
