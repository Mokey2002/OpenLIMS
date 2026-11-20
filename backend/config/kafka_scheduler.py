from django.conf import settings

from .celery import app


app.conf.beat_schedule = {}
if settings.KAFKA_BOOTSTRAP_SERVERS:
    app.conf.beat_schedule["publish-kafka-outbox"] = {
        "task": "events.tasks.publish_kafka_outbox",
        "schedule": 15.0,
        "options": {"expires": 15},
    }
