"""Requester-only, deduplicated job alerts, independent of Celery availability."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.project_access import get_project_access_queryset
from core.permissions import application_roles, is_admin
from notifications.models import Notification
from .models import AssistantAction, AssistantActionAlert
from .action_locking import locked_action


def job_reference(action):
    from alignments.models import AlignmentJob
    from blast.models import BlastJob
    from imports.models import ImportJob
    references = {
        "RUN_BLAST": (BlastJob, "blast_job_id", "/blast", "created_by"),
        "RUN_ALIGNMENT": (AlignmentJob, "alignment_job_id", "/alignments", "created_by"),
        "QUEUE_IMPORT": (ImportJob, "import_job_id", "/imports", "uploaded_by"),
    }
    reference = references.get(action.action_type)
    if reference is None:
        return None, None, None
    model, key, url, owner = reference
    identifier = (action.result if isinstance(action.result, dict) else {}).get(key)
    if type(identifier) is not int and not (isinstance(identifier, str) and identifier.isdigit()):
        return None, url, owner
    job = model.objects.select_related("project").filter(pk=identifier).first()
    return job, url, owner


def _job_access(action, job, owner):
    if job is None:
        return True
    if not {"admin", "tech", "viewer", "qc_reviewer"}.intersection(application_roles(action.requested_by)):
        return False
    return get_project_access_queryset(type(job).objects.filter(pk=job.pk), action.requested_by,
                                      owner_lookup=owner).exists()


def action_health(action):
    if action.status not in {"QUEUED", "FAILED", "COMPLETED"}:
        return None
    job, url, owner = job_reference(action)
    accessible = action.requested_by.is_active and _job_access(action, job, owner)
    if action.action_type == "QUEUE_REPORT" and not is_admin(action.requested_by):
        accessible = False
    progress = action.progress if isinstance(action.progress, dict) else {}
    recorded_step = progress.get("current_step") if isinstance(progress.get("current_step"), str) else None
    completed_step = progress.get("last_completed_step") if isinstance(progress.get("last_completed_step"), str) else None
    anchor = action.last_progress_at or action.confirmed_at or action.updated_at
    queueing = recorded_step in {None, "Waiting for worker"} and (job is None or job.status == "PENDING")
    limit = settings.ASSISTANT_QUEUE_STALL_SECONDS if queueing else settings.ASSISTANT_PROGRESS_STALL_SECONDS
    stalled = action.status == "QUEUED" and anchor <= timezone.now() - timedelta(seconds=limit)
    recovery = [{"label": "Review task in assistant", "url": f"/assistant?job_action={action.pk}"}]
    if accessible and job is not None and url:
        recovery.append({"label": "Review import receipt" if action.action_type == "QUEUE_IMPORT" else "Review job",
                         "url": f"{url}/{job.pk}" if action.action_type == "QUEUE_IMPORT" else f"{url}?job={job.pk}"})
    if not accessible:
        return {"accessible": False, "stalled": False, "current_step": "Access to the source record changed.",
                "last_completed_step": "Progress is unavailable with your current access.", "recovery": recovery}
    hint = "Refresh the status before starting another attempt; the original job may still be running."
    if action.status == "FAILED":
        hint = ("Review the import receipt and source mapping. Repair rejected rows without resubmitting rows already imported."
                if action.action_type == "QUEUE_IMPORT" else
                "Review the job details and inputs. Ask the assistant to prepare a new attempt after correcting the problem; confirmation is required.")
    current_step = "Completed" if action.status == "COMPLETED" else "Failed" if action.status == "FAILED" else recorded_step or ("Waiting for worker" if queueing else "Worker running")
    return {"accessible": True, "stalled": stalled, "current_step": current_step,
            "last_completed_step": completed_step or ("Completion recorded" if action.status == "COMPLETED" else "No completed step was recorded for this attempt."),
            "last_progress_at": anchor.isoformat(),
            "progress_current": progress.get("current") if type(progress.get("current")) is int else None,
            "progress_total": progress.get("total") if type(progress.get("total")) is int else None,
            "failure_reason": str(action.error_message)[:1000] if action.status == "FAILED" else "",
            "recovery_hint": hint, "recovery": recovery}


@transaction.atomic
def ensure_action_alert(action, kind):
    """The action row lock and database uniqueness protect concurrent monitors."""
    with locked_action({"pk": action.pk}) as current:
        if current is None:
            return None
        action = current
        health = action_health(action)
        if not health or not action.requested_by.is_active or (not health["accessible"] and kind != "FAILED"):
            return None
        if kind not in {"FAILED", "STALLED"} or (kind == "FAILED" and action.status != "FAILED") or (kind == "STALLED" and not health["stalled"]):
            return None
        alert, created = AssistantActionAlert.objects.get_or_create(action=action, kind=kind, defaults={"snapshot": health})
        if not created:
            return alert
        title = "Assistant task failed" if kind == "FAILED" else "Assistant task needs attention"
        state = "failed" if kind == "FAILED" else "has not reported progress within the configured waiting period; it may still be running"
        notification = Notification.objects.create(user=action.requested_by, title=title,
            message=f"{action.summary}: {state}. Last completed step: {health['last_completed_step']}",
            link=f"/assistant?job_action={action.pk}")
        alert.notification = notification
        alert.save(update_fields=["notification"])
        return alert


def record_action_progress(*, action_type, result_key=None, result_id=None, action_id=None,
                           current_step, last_completed_step=None, current=None, total=None):
    lookup = {"action_type": action_type, "status": "QUEUED"}
    if action_id is not None:
        lookup["pk"] = action_id
    elif result_key:
        lookup[f"result__{result_key}"] = result_id
    else:
        raise ValueError("Progress requires a job identity or action ID.")
    with locked_action(lookup) as action:
        if action is None:
            return None
        progress = dict(action.progress or {})
        progress["current_step"] = str(current_step)[:300]
        if last_completed_step is not None:
            progress["last_completed_step"] = str(last_completed_step)[:300]
        if current is not None:
            progress["current"] = int(current)
        if total is not None:
            progress["total"] = int(total)
        action.progress, action.last_progress_at = progress, timezone.now()
        action.save(update_fields=["progress", "last_progress_at"])
        action.health_alerts.filter(kind="STALLED", resolved_at__isnull=True).update(resolved_at=timezone.now())
        return action


def assistant_managed_job(action_type, result_key, result_id):
    return AssistantAction.objects.filter(action_type=action_type, **{f"result__{result_key}": result_id}).exists()


def scan_action_health(*, user=None, limit=500, after_id=None):
    """Bounded scans never change a queued job to failed based on its age."""
    query = AssistantAction.objects.filter(status="QUEUED")
    if user is not None:
        query = query.filter(requested_by=user)
    if after_id is not None:
        query = query.filter(pk__gt=after_id)
    ids = list(query.order_by("pk").values_list("pk", flat=True)[:limit])
    delivered = 0
    for action_id in ids:
        with locked_action({"pk": action_id, "status": "QUEUED"}) as action:
            if action is None:
                continue
            job, _, _ = job_reference(action)
            if job is not None and job.status in {"COMPLETED", "FAILED"}:
                from .lifecycle import finish_queued_action
                finished = finish_queued_action(action_type=action.action_type, action_id=action.pk,
                    succeeded=job.status == "COMPLETED", result_updates={"job_status": job.status},
                    error_message="The background job reported a failure." if job.status == "FAILED" else "")
                if finished and job.status == "FAILED" and finished.health_alerts.filter(kind="FAILED", notification__isnull=False).exists():
                    delivered += 1
                continue
            # A legacy running job may have written its native update timestamp
            # without an action checkpoint. Respect that timestamp, never now.
            native_update = getattr(job, "updated_at", None)
            if not action.progress and native_update and native_update > (action.last_progress_at or action.updated_at):
                action.last_progress_at = native_update
                action.save(update_fields=["last_progress_at"])
            health = action_health(action)
            if health and health["stalled"] and not action.health_alerts.filter(kind="STALLED").exists():
                alert = ensure_action_alert(action, "STALLED")
                delivered += int(alert is not None)
    return {"checked": len(ids), "delivered": delivered, "cursor": str(ids[-1]) if len(ids) == limit else None}
