from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils import timezone

from core.models import PublicIDModel


class SampleBatch(models.Model):
    code = models.CharField(max_length=64, unique=True)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="sample_batches",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_sample_batches",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class Sample(PublicIDModel):
    STATUS_RECEIVED = "RECEIVED"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_QC = "QC"
    STATUS_REPORTED = "REPORTED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_ARCHIVED = "ARCHIVED"

    STATUS_CHOICES = [
        (STATUS_RECEIVED, "Received"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_QC, "QC"),
        (STATUS_REPORTED, "Reported"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    sample_id = models.CharField(max_length=64, unique=True)
    form_schema = models.JSONField(default=dict, blank=True)
    form_values = models.JSONField(default=dict, blank=True)
    sample_type = models.CharField(
        max_length=64,
        default="GENERAL",
        help_text="Configurable sample classification used to select default pipelines.",
    )
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_RECEIVED)

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="samples",
    )

    linked_projects = models.ManyToManyField(
        "projects.Project",
        blank=True,
        related_name="linked_samples",
        help_text="Additional projects that can view this sample.",
    )

    container = models.ForeignKey(
        "inventory.Container",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="samples",
    )

    batch = models.ForeignKey(
        SampleBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="samples",
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_samples",
    )

    custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custodied_samples",
        help_text="User currently holding the physical sample, when checked out.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_samples",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    status_changed_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("sample_id"),
                name="samples_sample_id_ci_unique",
            )
        ]

    def __str__(self):
        return self.sample_id

    def save(self, *args, **kwargs):
        # Also cover ordinary ORM creation used by imports and assistant actions.
        # Bulk SQL writers must not be used for configured sample intake.
        from custom_fields.forms import schema_for, validate_values
        if self._state.adding:
            self.form_schema = schema_for(str(self.sample_type or "GENERAL").strip().upper())
        validate_values(self.form_schema, self.form_values)
        return super().save(*args, **kwargs)


class SampleRelationship(models.Model):
    TYPE_DERIVED = "DERIVED"
    TYPE_ALIQUOT = "ALIQUOT"
    TYPE_SPLIT = "SPLIT"
    TYPE_POOL_COMPONENT = "POOL_COMPONENT"
    TYPE_CHOICES = [
        (TYPE_DERIVED, "Derived sample"),
        (TYPE_ALIQUOT, "Aliquot"),
        (TYPE_SPLIT, "Split"),
        (TYPE_POOL_COMPONENT, "Pool component"),
    ]

    source_sample = models.ForeignKey(
        Sample,
        on_delete=models.PROTECT,
        related_name="outgoing_relationships",
    )
    derived_sample = models.ForeignKey(
        Sample,
        on_delete=models.PROTECT,
        related_name="incoming_relationships",
    )
    relationship_type = models.CharField(max_length=32, choices=TYPE_CHOICES)
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
    )
    unit = models.CharField(max_length=32, blank=True, default="")
    reason = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_sample_relationships",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(source_sample=F("derived_sample")),
                name="sample_relationship_no_self_link",
            ),
            models.UniqueConstraint(
                fields=["source_sample", "derived_sample", "relationship_type"],
                name="sample_relationship_unique_edge",
            ),
        ]

    def clean(self):
        super().clean()
        if self.source_sample_id == self.derived_sample_id:
            raise ValidationError("A sample cannot be derived from itself.")
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than zero."})

        # A new source -> derived edge must not create a lineage cycle.
        frontier = [self.derived_sample_id]
        visited = set()
        while frontier:
            current = frontier.pop()
            if current == self.source_sample_id:
                raise ValidationError("This relationship would create a lineage cycle.")
            if current in visited:
                continue
            visited.add(current)
            frontier.extend(
                SampleRelationship.objects.filter(source_sample_id=current)
                .exclude(pk=self.pk)
                .values_list("derived_sample_id", flat=True)
            )

    def __str__(self):
        return f"{self.source_sample.sample_id} -> {self.derived_sample.sample_id}"


class SampleCustodyEvent(models.Model):
    ACTION_RECEIVE = "RECEIVE"
    ACTION_CHECK_OUT = "CHECK_OUT"
    ACTION_CHECK_IN = "CHECK_IN"
    ACTION_TRANSFER = "TRANSFER"
    ACTION_MOVE = "MOVE"
    ACTION_PROCESS = "PROCESS"
    ACTION_DISPOSE = "DISPOSE"
    ACTION_CHOICES = [
        (ACTION_RECEIVE, "Receive"),
        (ACTION_CHECK_OUT, "Check out"),
        (ACTION_CHECK_IN, "Check in"),
        (ACTION_TRANSFER, "Transfer custody"),
        (ACTION_MOVE, "Move storage"),
        (ACTION_PROCESS, "Record processing"),
        (ACTION_DISPOSE, "Dispose/archive"),
    ]

    sample = models.ForeignKey(
        Sample,
        on_delete=models.PROTECT,
        related_name="custody_events",
    )
    action = models.CharField(max_length=24, choices=ACTION_CHOICES)
    scanned_code = models.CharField(max_length=128)
    from_container = models.ForeignKey(
        "inventory.Container",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="custody_events_from",
    )
    to_container = models.ForeignKey(
        "inventory.Container",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="custody_events_to",
    )
    from_custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custody_transfers_from",
    )
    to_custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custody_transfers_to",
    )
    reason = models.TextField()
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="performed_custody_events",
    )
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["sample", "-occurred_at"], name="custody_sample_time_idx"),
            models.Index(fields=["scanned_code", "-occurred_at"], name="custody_scan_time_idx"),
        ]

    def __str__(self):
        return f"{self.sample.sample_id} - {self.action}"

class SingleSampleAttachment(models.Model):
    sample = models.ForeignKey(
        "samples.Sample",
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(upload_to="sample_attachments/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sample_attachments",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def filename(self):
        return self.file.name.split("/")[-1]

    def __str__(self):
        return f"{self.sample.sample_id} - {self.filename()}"
