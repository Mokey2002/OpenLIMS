# Generated for OpenLIMS v0.20.0 confirmed assistant actions.

import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AssistantAction",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("confirmation_token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("idempotency_key", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("action_type", models.CharField(choices=[
                    ("RUN_BLAST", "Run BLAST"),
                    ("RUN_ALIGNMENT", "Run alignment"),
                    ("CREATE_MIGRATION_MAPPINGS", "Create migration mappings"),
                    ("QUEUE_REPORT", "Queue report"),
                    ("QUEUE_IMPORT", "Queue import"),
                ], max_length=40)),
                ("status", models.CharField(choices=[
                    ("PROPOSED", "Proposed"),
                    ("QUEUED", "Queued"),
                    ("COMPLETED", "Completed"),
                    ("CANCELLED", "Cancelled"),
                    ("EXPIRED", "Expired"),
                    ("FAILED", "Failed"),
                ], default="PROPOSED", max_length=20)),
                ("summary", models.CharField(max_length=500)),
                ("payload", models.JSONField(default=dict)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("expires_at", models.DateTimeField()),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("executed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assistant_actions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="assistantaction",
            index=models.Index(fields=["requested_by", "status", "created_at"], name="asst_req_status_created_idx"),
        ),
    ]
