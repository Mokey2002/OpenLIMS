from django.conf import settings

from .models import KafkaOutboxEvent


def queue_requester_event(event_type, workflow_request, *, occurred_at, data=None):
    """Save an event inside the transaction that changes the request."""
    if not settings.KAFKA_BOOTSTRAP_SERVERS:
        return

    event = KafkaOutboxEvent(request_id=workflow_request.public_id)
    event.payload = {
        "schema_version": 1,
        "event_id": str(event.event_id),
        "event_type": event_type,
        "occurred_at": occurred_at.isoformat(),
        "request_id": str(event.request_id),
        "project_id": str(workflow_request.project.public_id),
        "data": data or {},
    }
    event.save(force_insert=True)
