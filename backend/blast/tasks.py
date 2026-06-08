from celery import shared_task

from notifications.models import Notification

from .models import BlastDatabase, BlastJob
from .services import build_blast_database, run_blast_job


@shared_task
def build_blast_database_task(database_id, actor_id=None):
    try:
        database = BlastDatabase.objects.get(id=database_id)
    except BlastDatabase.DoesNotExist:
        return

    actor = database.created_by

    build_blast_database(database, actor=actor)

    if actor:
        Notification.objects.get_or_create(
            user=actor,
            title=f"BLAST database ready: {database.name}",
            defaults={
                "message": "The BLAST database was built successfully.",
                "link": "/blast",
            },
        )


@shared_task
def run_blast_job_task(job_id):
    try:
        job = (
            BlastJob.objects
            .select_related("query_sequence", "database", "project", "created_by")
            .get(id=job_id)
        )
    except BlastJob.DoesNotExist:
        return

    actor = job.created_by

    try:
        run_blast_job(job, actor=actor)

        job.refresh_from_db()

        if actor and job.status == BlastJob.STATUS_COMPLETED:
            Notification.objects.get_or_create(
                user=actor,
                title=f"BLAST completed: {job.name}",
                defaults={
                    "message": f"Your BLAST search completed with {job.hits_count} hit(s).",
                    "link": "/blast",
                },
            )

    except Exception as exc:
        if actor:
            Notification.objects.get_or_create(
                user=actor,
                title=f"BLAST failed: {job.name}",
                defaults={
                    "message": str(exc),
                    "link": "/blast",
                },
            )

        raise
