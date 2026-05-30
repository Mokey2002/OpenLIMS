from celery import shared_task

from django.utils import timezone

from notifications.models import Notification

from .models import AlignmentJob
from .services import run_clustal_omega_alignment


@shared_task
def run_alignment_job(job_id):
    try:
        job = (
            AlignmentJob.objects
            .select_related("project", "created_by")
            .prefetch_related("sequences")
            .get(id=job_id)
        )
    except AlignmentJob.DoesNotExist:
        return

    actor = job.created_by

    try:
        # Your service already updates:
        # PENDING -> RUNNING -> COMPLETED / FAILED
        # and saves input_fasta, aligned_fasta, summary, error_message.
        run_clustal_omega_alignment(job, actor=actor)

        job.refresh_from_db()

        if actor and job.status == "COMPLETED":
            Notification.objects.get_or_create(
                user=actor,
                title=f"Alignment completed: {job.name}",
                defaults={
                    "message": "Your Clustal Omega alignment finished successfully.",
                    "link": "/alignments",
                },
            )

        if actor and job.status == "FAILED":
            Notification.objects.get_or_create(
                user=actor,
                title=f"Alignment failed: {job.name}",
                defaults={
                    "message": job.error_message or "The alignment failed.",
                    "link": "/alignments",
                },
            )

    except Exception as exc:
        job.status = "FAILED"
        job.error_message = str(exc)
        job.summary = {
            **(job.summary or {}),
            "error": str(exc),
            "failed_at": timezone.now().isoformat(),
        }
        job.save(
            update_fields=[
                "status",
                "error_message",
                "summary",
                "updated_at",
            ]
        )

        if actor:
            Notification.objects.get_or_create(
                user=actor,
                title=f"Alignment failed: {job.name}",
                defaults={
                    "message": str(exc),
                    "link": "/alignments",
                },
            )

        raise