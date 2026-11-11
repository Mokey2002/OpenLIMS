from django.utils import timezone

from events.models import Event

from .models import AssistantAction
from .action_locking import locked_action


def finish_queued_action(
    *,
    action_type,
    result_key=None,
    result_id=None,
    succeeded,
    error_message="",
    result_updates=None,
    action_id=None,
):
    """Finish the queued assistant action associated with a background job.

    Background tasks may be delivered more than once. Restricting the lookup to
    QUEUED actions makes the transition and its audit event idempotent.
    """
    lookup = {
        "action_type": action_type,
        "status": AssistantAction.STATUS_QUEUED,
    }
    if action_id is not None:
        lookup["pk"] = action_id
    elif result_key:
        lookup[f"result__{result_key}"] = result_id
    else:
        raise ValueError("Completion requires an action or job identity.")

    with locked_action(lookup) as action:
        if action is None:
            return None

        result = dict(action.result or {})
        result.update(result_updates or {})

        action.status = (
            AssistantAction.STATUS_COMPLETED
            if succeeded
            else AssistantAction.STATUS_FAILED
        )
        action.result = result
        action.error_message = "" if succeeded else str(error_message or "")
        action.progress = {**(action.progress or {}), "current_step": "Completed" if succeeded else "Failed"}
        if succeeded:
            action.progress["last_completed_step"] = "Results saved"
        action.last_progress_at = timezone.now()
        action.save(
            update_fields=[
                "status",
                "result",
                "error_message",
                "updated_at",
                "progress", "last_progress_at",
            ]
        )

        event_action = (
            "ASSISTANT_ACTION_COMPLETED"
            if succeeded
            else "ASSISTANT_ACTION_FAILED"
        )
        event_payload = {
            "assistant_action_id": str(action.id),
            "action_type": action.action_type,
            "summary": action.summary,
            "idempotency_key": str(action.idempotency_key),
            "result": result,
        }
        if result_key:
            event_payload[result_key] = result_id

        if not succeeded:
            event_payload["error"] = action.error_message

        Event.objects.create(
            entity_type="AssistantAction",
            entity_id=str(action.id),
            action=event_action,
            actor=action.requested_by,
            payload=event_payload,
        )
        action.health_alerts.filter(kind="STALLED", resolved_at__isnull=True).update(resolved_at=action.last_progress_at)
        if not succeeded:
            from .job_health import ensure_action_alert
            ensure_action_alert(action, "FAILED")

        return action
