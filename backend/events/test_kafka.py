import json
from unittest.mock import patch
from uuid import uuid4

from confluent_kafka import KafkaError
from django.test import TestCase, override_settings

from .models import KafkaOutboxEvent
from .tasks import publish_kafka_outbox


@override_settings(KAFKA_BOOTSTRAP_SERVERS="kafka:9092", KAFKA_TOPIC="test.requester.v1")
class KafkaOutboxTests(TestCase):
    def queue(self, request_id, event_type):
        event = KafkaOutboxEvent(request_id=request_id)
        event.payload = {"event_id": str(event.event_id), "event_type": event_type}
        event.save()
        return event

    @patch("events.tasks.Producer")
    def test_delivery_failure_retries_in_request_order_and_keeps_the_event_id(self, producer):
        request_id = uuid4()
        submitted = self.queue(request_id, "request.submitted")
        received = self.queue(request_id, "sample.received")
        released = self.queue(request_id, "report.released")
        other_request = self.queue(uuid4(), "request.submitted")
        timed_out = self.queue(uuid4(), "request.submitted")
        sender = producer.return_value
        failure = KafkaError(KafkaError._MSG_TIMED_OUT)
        attempted = []

        def flush(_timeout):
            for call in sender.produce.call_args_list:
                self.assertEqual(call.args, ("test.requester.v1",))
                payload = json.loads(call.kwargs["value"])
                event = KafkaOutboxEvent.objects.get(event_id=payload["event_id"])
                self.assertEqual(payload, event.payload)
                self.assertEqual(call.kwargs["key"], str(event.request_id).encode())
                attempted.append(event.event_id)
                if event != timed_out:
                    error = failure if event == submitted else None
                    call.kwargs["on_delivery"](error, None)
            return 1

        sender.flush.side_effect = flush
        self.assertEqual(publish_kafka_outbox(), 1)
        self.assertEqual(attempted, [submitted.event_id, other_request.event_id, timed_out.event_id])
        self.assertCountEqual(
            KafkaOutboxEvent.objects.values_list("event_id", flat=True),
            [submitted.event_id, received.event_id, released.event_id, timed_out.event_id],
        )

        def acknowledge(_timeout):
            for call in sender.produce.call_args_list:
                attempted.append(json.loads(call.kwargs["value"])["event_id"])
                call.kwargs["on_delivery"](None, None)
            return 0

        sender.flush.side_effect = acknowledge
        for expected in ([submitted, timed_out], [received], [released]):
            sender.produce.reset_mock()
            attempted.clear()
            self.assertEqual(publish_kafka_outbox(), len(expected))
            self.assertEqual(attempted, [str(event.event_id) for event in expected])
        self.assertFalse(KafkaOutboxEvent.objects.exists())

    @patch("events.tasks.Producer")
    def test_empty_outbox_skips_connection(self, producer):
        self.assertEqual(publish_kafka_outbox(), 0)
        producer.assert_not_called()
