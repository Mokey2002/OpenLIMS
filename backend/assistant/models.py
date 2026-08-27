import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import Group

from core.models import PublicIDModel


class AssistantAction(models.Model):
    ACTION_RUN_BLAST = "RUN_BLAST"
    ACTION_RUN_ALIGNMENT = "RUN_ALIGNMENT"
    ACTION_CREATE_MIGRATION_MAPPINGS = "CREATE_MIGRATION_MAPPINGS"
    ACTION_QUEUE_REPORT = "QUEUE_REPORT"
    ACTION_QUEUE_IMPORT = "QUEUE_IMPORT"
    ACTION_CREATE_SAMPLES = "CREATE_SAMPLES"
    ACTION_BULK_SAMPLE_UPDATE = "BULK_SAMPLE_UPDATE"
    ACTION_QC_REVIEW = "QC_REVIEW"
    ACTION_INVENTORY_OPERATION = "INVENTORY_OPERATION"
    ACTION_WORK_ITEM_OPERATION = "WORK_ITEM_OPERATION"
    ACTION_LABEL_GENERATION = "LABEL_GENERATION"
    ACTION_COMPLIANCE_REPORT = "COMPLIANCE_REPORT"
    ACTION_NOTIFICATION_MANAGEMENT = "NOTIFICATION_MANAGEMENT"

    ACTION_CHOICES = [
        (ACTION_RUN_BLAST, "Run BLAST"),
        (ACTION_RUN_ALIGNMENT, "Run alignment"),
        (ACTION_CREATE_MIGRATION_MAPPINGS, "Create migration mappings"),
        (ACTION_QUEUE_REPORT, "Queue report"),
        (ACTION_QUEUE_IMPORT, "Queue import"),
        (ACTION_CREATE_SAMPLES, "Create samples"),
        (ACTION_BULK_SAMPLE_UPDATE, "Bulk sample update"),
        (ACTION_QC_REVIEW, "QC review"),
        (ACTION_INVENTORY_OPERATION, "Inventory operation"),
        (ACTION_WORK_ITEM_OPERATION, "Work-item operation"),
        (ACTION_LABEL_GENERATION, "Label generation"),
        (ACTION_COMPLIANCE_REPORT, "Compliance report"),
        (ACTION_NOTIFICATION_MANAGEMENT, "Notification management"),
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


class GeneratedArtifact(models.Model):
    KIND_LABEL_PDF = "LABEL_PDF"
    KIND_REPORT_PDF = "REPORT_PDF"
    KIND_REPORT_CSV = "REPORT_CSV"
    KIND_CHOICES = [
        (KIND_LABEL_PDF, "Label PDF"),
        (KIND_REPORT_PDF, "Report PDF"),
        (KIND_REPORT_CSV, "Report CSV"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=24, choices=KIND_CHOICES)
    file = models.FileField(upload_to="assistant_artifacts/%Y/%m/")
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    checksum_sha256 = models.CharField(max_length=64)
    parameters = models.JSONField(default=dict)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assistant_artifacts",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="generated_assistant_artifacts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class BarcodeLabel(models.Model):
    sample = models.ForeignKey(
        "samples.Sample",
        on_delete=models.CASCADE,
        related_name="barcode_labels",
    )
    template = models.CharField(max_length=64, default="STANDARD_SAMPLE")
    barcode = models.CharField(max_length=128, unique=True)
    generation_count = models.PositiveIntegerField(default=0)
    last_artifact = models.ForeignKey(
        GeneratedArtifact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="barcode_labels",
    )
    last_generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_barcode_labels",
    )
    last_generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sample", "template"],
                name="barcode_sample_template_unique",
            )
        ]


class SOPDocument(PublicIDModel):
    STATUS_CURRENT = "CURRENT"
    STATUS_ARCHIVED = "ARCHIVED"
    STATUS_CHOICES = [
        (STATUS_CURRENT, "Current"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    document_code = models.CharField(max_length=64)
    title = models.CharField(max_length=255)
    version = models.CharField(max_length=32)
    section = models.CharField(max_length=128)
    content = models.TextField()
    source_file = models.FileField(upload_to="sops/", null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_CURRENT,
    )
    approved = models.BooleanField(default=False)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sop_documents",
    )
    allowed_groups = models.ManyToManyField(
        Group,
        blank=True,
        related_name="sop_documents",
    )
    effective_at = models.DateTimeField(default=timezone.now)
    archived_at = models.DateTimeField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_sop_documents",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document_code", "version", "section"],
                name="sop_code_version_section_unique",
            )
        ]
        ordering = ["document_code", "section", "-effective_at"]


class NotificationSubscription(models.Model):
    CHANNEL_IN_APP = "IN_APP"
    CHANNEL_EMAIL = "EMAIL"
    CHANNEL_CHOICES = [
        (CHANNEL_IN_APP, "In-app"),
        (CHANNEL_EMAIL, "Email"),
    ]
    FREQUENCY_ONCE = "ONCE"
    FREQUENCY_IMMEDIATE = "IMMEDIATE"
    FREQUENCY_DAILY = "DAILY"
    FREQUENCY_CHOICES = [
        (FREQUENCY_ONCE, "Once"),
        (FREQUENCY_IMMEDIATE, "Immediate"),
        (FREQUENCY_DAILY, "Daily summary"),
    ]

    trigger = models.CharField(max_length=64)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_subscriptions",
    )
    delivery_channel = models.CharField(
        max_length=16,
        choices=CHANNEL_CHOICES,
        default=CHANNEL_IN_APP,
    )
    frequency = models.CharField(
        max_length=16,
        choices=FREQUENCY_CHOICES,
        default=FREQUENCY_ONCE,
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notification_subscriptions",
    )
    target_type = models.CharField(max_length=64)
    target_id = models.CharField(max_length=128)
    threshold = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
    )
    active = models.BooleanField(default=True)
    deduplication_key = models.CharField(max_length=255)
    next_run_at = models.DateTimeField(default=timezone.now)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_notification_subscriptions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["active", "next_run_at"],
                name="notify_active_next_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["deduplication_key"],
                condition=models.Q(active=True),
                name="active_notification_dedup_unique",
            )
        ]


class NotificationDelivery(models.Model):
    STATUS_DELIVERED = "DELIVERED"
    STATUS_SKIPPED = "SKIPPED"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = [
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_SKIPPED, "Skipped"),
        (STATUS_FAILED, "Failed"),
    ]

    subscription = models.ForeignKey(
        NotificationSubscription,
        on_delete=models.CASCADE,
        related_name="deliveries",
    )
    event_key = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    permission_rechecked = models.BooleanField(default=False)
    detail = models.JSONField(default=dict)
    delivered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "event_key"],
                name="notification_delivery_unique",
            )
        ]


class AssistantInteraction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_interactions",
    )
    message_hash = models.CharField(max_length=64)
    route = models.CharField(max_length=64, default="unknown")
    routing_source = models.CharField(max_length=64, default="rules")
    confidence = models.FloatField(default=0.0)
    response_type = models.CharField(max_length=64, default="text")
    record_count = models.PositiveIntegerField(default=0)
    clarification_requested = models.BooleanField(default=False)
    success = models.BooleanField(default=True)
    latency_ms = models.PositiveIntegerField(default=0)
    context_keys = models.JSONField(default=list, blank=True)
    error_code = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["route", "success", "created_at"],
                name="asst_route_success_idx",
            ),
            models.Index(
                fields=["user", "created_at"],
                name="asst_user_created_idx",
            ),
        ]


class AssistantFeedback(models.Model):
    RATING_UP = "UP"
    RATING_DOWN = "DOWN"
    RATING_CHOICES = [
        (RATING_UP, "Helpful"),
        (RATING_DOWN, "Not helpful"),
    ]
    CATEGORY_CHOICES = [
        ("", "No category"),
        ("WRONG_ROUTE", "Wrong route"),
        ("WRONG_RECORDS", "Wrong records"),
        ("MISSING_DETAIL", "Missing detail"),
        ("UNWANTED_CHART", "Unwanted chart"),
        ("OTHER", "Other"),
    ]

    interaction = models.ForeignKey(
        AssistantInteraction,
        on_delete=models.CASCADE,
        related_name="feedback",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_feedback",
    )
    rating = models.CharField(max_length=8, choices=RATING_CHOICES)
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES, blank=True, default="")
    note = models.CharField(max_length=1000, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["interaction", "user"],
                name="assistant_feedback_user_unique",
            )
        ]
