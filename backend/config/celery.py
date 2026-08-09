import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("openlims")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "dispatch-openlims-notifications": {
        "task": "assistant.tasks.dispatch_due_notifications",
        "schedule": 300.0,
    },
}
