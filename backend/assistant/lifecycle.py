from django.db import transaction

from events.models import Event

from .models import AssistantAction


def finish_queued_action(
    *,
    action_type,
    result_key,
    result_id,
    succeeded,
    error_message="",
    result_updates=None,
):
    """Finish the queued assistant action associated with a background job.

    Background tasks may be delivered more than once. Restricting the lookup to
    QUEUED actions makes the transition and its audit event idempotent.
    """
    lookup = {
        "action_type": action_type,
        "status": AssistantAction.STATUS_QUEUED,
        f"result__{result_key}": result_id,
    }

    with transaction.atomic():
        action = (
            AssistantAction.objects.select_for_update()
            .filter(**lookup)
            .first()
        )

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
        action.save(
            update_fields=[
                "status",
                "result",
                "error_message",
                "updated_at",
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
            "idempotency_key": str(action.idempotency_key),
            result_key: result_id,
            "result": result,
        }

        if not succeeded:
            event_payload["error"] = action.error_message

        Event.objects.create(
            entity_type="AssistantAction",
            entity_id=str(action.id),
            action=event_action,
            actor=action.requested_by,
            payload=event_payload,
        )

        return action
