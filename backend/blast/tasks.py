from celery import shared_task

from notifications.models import Notification

from core.realtime import broadcast_job_update

from .models import BlastDatabase, BlastJob
from .services import build_blast_database, run_blast_job


def broadcast_blast_database_update(database, message):
    broadcast_job_update(
        {
            "type": "blast_database_update",
            "database_id": database.id,
            "name": database.name,
            "status": database.status,
            "message": message,
        }
    )


def broadcast_blast_job_update(job, message):
    broadcast_job_update(
        {
            "type": "blast_job_update",
            "job_id": job.id,
            "name": job.name,
            "status": job.status,
            "hits_count": job.hits_count,
            "message": message,
        }
    )


@shared_task
def build_blast_database_task(database_id, actor_id=None):
    try:
        database = BlastDatabase.objects.get(id=database_id)
    except BlastDatabase.DoesNotExist:
        return

    actor = database.created_by

    try:
        database.refresh_from_db()
        broadcast_blast_database_update(
            database,
            f"BLAST database build started: {database.name}",
        )

        build_blast_database(database, actor=actor)

        database.refresh_from_db()
        broadcast_blast_database_update(
            database,
            f"BLAST database ready: {database.name}",
        )

        if actor:
            Notification.objects.get_or_create(
                user=actor,
                title=f"BLAST database ready: {database.name}",
                defaults={
                    "message": "The BLAST database was built successfully.",
                    "link": "/blast",
                },
            )

    except Exception as exc:
        database.refresh_from_db()
        broadcast_blast_database_update(
            database,
            f"BLAST database build failed: {database.name}",
        )

        if actor:
            Notification.objects.get_or_create(
                user=actor,
                title=f"BLAST database failed: {database.name}",
                defaults={
                    "message": str(exc),
                    "link": "/blast",
                },
            )

        raise


@shared_task
def run_blast_job_task(job_id):
    try:
        job = (
            BlastJob.objects.select_related(
                "query_sequence",
                "database",
                "project",
                "created_by",
            )
            .get(id=job_id)
        )
    except BlastJob.DoesNotExist:
        return

    actor = job.created_by

    try:
        job.refresh_from_db()
        broadcast_blast_job_update(
            job,
            f"BLAST job started: {job.name}",
        )

        run_blast_job(job, actor=actor)

        job.refresh_from_db()
        broadcast_blast_job_update(
            job,
            f"BLAST completed: {job.name} with {job.hits_count} hit(s).",
        )

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
        job.refresh_from_db()
        broadcast_blast_job_update(
            job,
            f"BLAST failed: {job.name}",
        )

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
