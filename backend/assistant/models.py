import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class AssistantAction(models.Model):
    ACTION_RUN_BLAST = "RUN_BLAST"
    ACTION_RUN_ALIGNMENT = "RUN_ALIGNMENT"
    ACTION_CREATE_MIGRATION_MAPPINGS = "CREATE_MIGRATION_MAPPINGS"
    ACTION_QUEUE_REPORT = "QUEUE_REPORT"
    ACTION_QUEUE_IMPORT = "QUEUE_IMPORT"
    ACTION_CREATE_SAMPLES = "CREATE_SAMPLES"
    ACTION_BULK_SAMPLE_UPDATE = "BULK_SAMPLE_UPDATE"

    ACTION_CHOICES = [
        (ACTION_RUN_BLAST, "Run BLAST"),
        (ACTION_RUN_ALIGNMENT, "Run alignment"),
        (ACTION_CREATE_MIGRATION_MAPPINGS, "Create migration mappings"),
        (ACTION_QUEUE_REPORT, "Queue report"),
        (ACTION_QUEUE_IMPORT, "Queue import"),
        (ACTION_CREATE_SAMPLES, "Create samples"),
        (ACTION_BULK_SAMPLE_UPDATE, "Bulk sample update"),
    ]

    STATUS_PROPOSED = "PROPOSED"
    STATUS_QUEUED = "QUEUED"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_EXPIRED = "EXPIRED"
    STATUS_FAILED = "FAILED"

    STATUS_CHOICES = [
        (STATUS_PROPOSED, "Proposed"),
        (STATUS_QUEUED, "Queued"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    confirmation_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    action_type = models.CharField(max_length=40, choices=ACTION_CHOICES)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PROPOSED,
    )
    summary = models.CharField(max_length=500)
    payload = models.JSONField(default=dict)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_actions",
    )
    expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["requested_by", "status", "created_at"],
                name="asst_req_status_created_idx",
            ),
        ]

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    def __str__(self):
        return f"{self.action_type} ({self.status})"
