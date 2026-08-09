from celery import shared_task
from django.db.models import Count, Q
from django.utils import timezone

from blast.models import BlastJob
from events.models import Event
from projects.models import Project
from results.models import WorkItem
from samples.models import Sample

from .models import AssistantAction
from .models import NotificationSubscription
from .notification_operations import dispatch_subscription


@shared_task
def generate_assistant_report(action_id):
    try:
        action = AssistantAction.objects.get(id=action_id)
    except AssistantAction.DoesNotExist:
        return

    filters = action.payload.get("filters") or {}
    project_id = filters.get("project_id")

    samples = Sample.objects.all()
    work_items = WorkItem.objects.all()
    blast_jobs = BlastJob.objects.all()
    projects = Project.objects.all()
    events = Event.objects.all()

    if project_id:
        samples = samples.filter(project_id=project_id)
        work_items = work_items.filter(sample__project_id=project_id)
        blast_jobs = blast_jobs.filter(project_id=project_id)
        projects = projects.filter(id=project_id)
        events = events.filter(payload__project_id=project_id)

    try:
        report = {
            "report_type": action.payload.get("report_type", "OPERATIONS_SUMMARY"),
            "filters": filters,
            "project_count": projects.count(),
            "sample_count": samples.count(),
            "sample_status_counts": list(
                samples.values("status").annotate(count=Count("id")).order_by("status")
            ),
            "work_item_status_counts": list(
                work_items.values("status").annotate(count=Count("id")).order_by("status")
            ),
            "blast_job_status_counts": list(
                blast_jobs.values("status").annotate(count=Count("id")).order_by("status")
            ),
            "audit_event_count": events.count(),
        }

        action.status = AssistantAction.STATUS_COMPLETED
        action.result = {"report": report}
        action.error_message = ""
        action.save(update_fields=["status", "result", "error_message", "updated_at"])

        Event.objects.create(
            entity_type="AssistantAction",
            entity_id=str(action.id),
            action="ASSISTANT_ACTION_COMPLETED",
            actor=action.requested_by,
            payload={
                "action_type": action.action_type,
                "report_type": report["report_type"],
            },
        )
    except Exception as exc:
        action.status = AssistantAction.STATUS_FAILED
        action.error_message = str(exc)
        action.save(update_fields=["status", "error_message", "updated_at"])

        Event.objects.create(
            entity_type="AssistantAction",
            entity_id=str(action.id),
            action="ASSISTANT_ACTION_FAILED",
            actor=action.requested_by,
            payload={
                "action_type": action.action_type,
                "error": str(exc),
            },
        )
        raise


@shared_task
def dispatch_due_notifications():
    now = timezone.now()
    subscription_ids = list(
        NotificationSubscription.objects.filter(
            active=True,
            next_run_at__lte=now,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .values_list("id", flat=True)[:500]
    )
    delivered = 0
    for subscription_id in subscription_ids:
        subscription = NotificationSubscription.objects.filter(id=subscription_id).first()
        if subscription and dispatch_subscription(subscription, now=now):
            delivered += 1
    return {"checked": len(subscription_ids), "delivered_or_skipped": delivered}
