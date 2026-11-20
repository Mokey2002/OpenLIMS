import json
import logging
from functools import partial

from celery import shared_task
from confluent_kafka import Producer
from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef

from .models import KafkaOutboxEvent


logger = logging.getLogger(__name__)


def _producer():
    config = {
        "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "security.protocol": settings.KAFKA_SECURITY_PROTOCOL,
        "client.id": "openlims-requester",
        "enable.idempotence": True,
        "message.timeout.ms": 5000,
    }
    if settings.KAFKA_SECURITY_PROTOCOL.startswith("SASL_"):
        config.update({
            "sasl.mechanism": settings.KAFKA_SASL_MECHANISM,
            "sasl.username": settings.KAFKA_SASL_USERNAME,
            "sasl.password": settings.KAFKA_SASL_PASSWORD,
        })
    return Producer(config)


@shared_task(ignore_result=True)
def publish_kafka_outbox():
    if not settings.KAFKA_BOOTSTRAP_SERVERS:
        return 0

    with transaction.atomic():
        earlier = KafkaOutboxEvent.objects.filter(request_id=OuterRef("request_id"), pk__lt=OuterRef("pk"))
        # Let concurrent workers pick other requests and keep each request in order.
        ready = list(
            KafkaOutboxEvent.objects.filter(~Exists(earlier))
            .order_by("pk").select_for_update(skip_locked=True)[:100]
        )
        if not ready:
            return 0

        producer = _producer()
        acknowledged = []
        errors = set()

        def on_delivery(event_pk, error, _message):
            if error is None:
                acknowledged.append(event_pk)
            else:
                errors.add(error.name())

        for event in ready:
            producer.produce(
                settings.KAFKA_TOPIC,
                key=str(event.request_id).encode("utf-8"),
                value=json.dumps(event.payload).encode("utf-8"),
                on_delivery=partial(on_delivery, event.pk),
            )
        producer.flush(6)
        KafkaOutboxEvent.objects.filter(pk__in=acknowledged).delete()
        pending = len(ready) - len(acknowledged)
        if pending:
            logger.warning(
                "Kafka delivery left %s requester events pending (%s).",
                pending, ", ".join(sorted(errors)) or "delivery timed out",
            )
        return len(acknowledged)
