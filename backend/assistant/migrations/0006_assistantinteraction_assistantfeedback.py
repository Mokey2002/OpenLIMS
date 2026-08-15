import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("assistant", "0005_alter_notificationsubscription_deduplication_key_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssistantInteraction",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("message_hash", models.CharField(max_length=64)),
                ("route", models.CharField(default="unknown", max_length=64)),
                ("routing_source", models.CharField(default="rules", max_length=64)),
                ("confidence", models.FloatField(default=0.0)),
                ("response_type", models.CharField(default="text", max_length=64)),
                ("record_count", models.PositiveIntegerField(default=0)),
                ("clarification_requested", models.BooleanField(default=False)),
                ("success", models.BooleanField(default=True)),
                ("latency_ms", models.PositiveIntegerField(default=0)),
                ("context_keys", models.JSONField(blank=True, default=list)),
                ("error_code", models.CharField(blank=True, default="", max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assistant_interactions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="AssistantFeedback",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rating", models.CharField(choices=[("UP", "Helpful"), ("DOWN", "Not helpful")], max_length=8)),
                ("category", models.CharField(blank=True, choices=[("", "No category"), ("WRONG_ROUTE", "Wrong route"), ("WRONG_RECORDS", "Wrong records"), ("MISSING_DETAIL", "Missing detail"), ("UNWANTED_CHART", "Unwanted chart"), ("OTHER", "Other")], default="", max_length=32)),
                ("note", models.CharField(blank=True, default="", max_length=1000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("interaction", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="feedback", to="assistant.assistantinteraction")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assistant_feedback", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(
            model_name="assistantinteraction",
            index=models.Index(fields=["route", "success", "created_at"], name="asst_route_success_idx"),
        ),
        migrations.AddIndex(
            model_name="assistantinteraction",
            index=models.Index(fields=["user", "created_at"], name="asst_user_created_idx"),
        ),
        migrations.AddConstraint(
            model_name="assistantfeedback",
            constraint=models.UniqueConstraint(fields=("interaction", "user"), name="assistant_feedback_user_unique"),
        ),
    ]
