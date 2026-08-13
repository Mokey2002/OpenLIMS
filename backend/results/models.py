from django.conf import settings
from django.db import models


class WorkItem(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    QC_PENDING_REVIEW = "PENDING_REVIEW"
    QC_APPROVED = "APPROVED"
    QC_REJECTED = "REJECTED"
    QC_RERUN_REQUIRED = "RERUN_REQUIRED"

    QC_STATUS_CHOICES = [
        (QC_PENDING_REVIEW, "Pending Review"),
        (QC_APPROVED, "Approved"),
        (QC_REJECTED, "Rejected"),
        (QC_RERUN_REQUIRED, "Re-run Required"),
    ]

    sample = models.ForeignKey(
        "samples.Sample",
        on_delete=models.CASCADE,
        related_name="work_items",
    )
    source_import_job = models.ForeignKey(
        "imports.ImportJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_items",
        help_text="Instrument import job that created this work item, when applicable.",
    )
    name = models.CharField(max_length=128)
    work_type = models.CharField(max_length=64, default="GENERAL")
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    notes = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_work_items",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_work_items",
    )
    due_at = models.DateTimeField(null=True, blank=True)

    qc_status = models.CharField(
        max_length=32,
        choices=QC_STATUS_CHOICES,
        default=QC_PENDING_REVIEW,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_work_items",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sample", "work_type"],
                condition=models.Q(status__in=["PENDING", "IN_PROGRESS"]),
                name="active_work_sample_type_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "due_at", "assigned_to"],
                name="work_status_due_assignee_idx",
            ),
        ]

    def __str__(self):
        return f"{self.sample.sample_id} - {self.name}"


class Result(models.Model):
    VALUE_TYPE_STRING = "STRING"
    VALUE_TYPE_NUMBER = "NUMBER"
    VALUE_TYPE_BOOLEAN = "BOOLEAN"

    VALUE_TYPE_CHOICES = [
        (VALUE_TYPE_STRING, "String"),
        (VALUE_TYPE_NUMBER, "Number"),
        (VALUE_TYPE_BOOLEAN, "Boolean"),
    ]

    QC_PENDING_REVIEW = "PENDING_REVIEW"
    QC_APPROVED = "APPROVED"
    QC_REJECTED = "REJECTED"
    QC_REOPENED = "REOPENED"

    QC_STATUS_CHOICES = [
        (QC_PENDING_REVIEW, "Pending Review"),
        (QC_APPROVED, "Approved"),
        (QC_REJECTED, "Rejected"),
        (QC_REOPENED, "Reopened"),
    ]

    work_item = models.ForeignKey(
        WorkItem,
        on_delete=models.CASCADE,
        related_name="results",
    )
    key = models.CharField(max_length=64)
    value_type = models.CharField(
        max_length=16,
        choices=VALUE_TYPE_CHOICES,
        default=VALUE_TYPE_STRING,
    )

    value_string = models.CharField(max_length=255, blank=True, default="")
    value_number = models.FloatField(null=True, blank=True)
    value_boolean = models.BooleanField(null=True, blank=True)

    unit = models.CharField(max_length=32, blank=True, default="")
    reference_min = models.FloatField(null=True, blank=True)
    reference_max = models.FloatField(null=True, blank=True)
    qc_rule = models.CharField(max_length=255, blank=True, default="")
    qc_passed = models.BooleanField(null=True, blank=True)
    qc_failure_reason = models.TextField(blank=True, default="")
    qc_status = models.CharField(
        max_length=32,
        choices=QC_STATUS_CHOICES,
        default=QC_PENDING_REVIEW,
    )
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entered_results",
    )
    qc_assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_qc_results",
    )
    qc_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_results",
    )
    qc_reviewed_at = models.DateTimeField(null=True, blank=True)
    qc_review_note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("work_item", "key")]

    def __str__(self):
        return f"{self.work_item.name} - {self.key}"

    @property
    def value(self):
        if self.value_type == self.VALUE_TYPE_NUMBER:
            return self.value_number
        if self.value_type == self.VALUE_TYPE_BOOLEAN:
            return self.value_boolean
        return self.value_string

    @property
    def reference_comparison(self):
        if self.value_type != self.VALUE_TYPE_NUMBER or self.value_number is None:
            return "not_numeric"
        if self.reference_min is None and self.reference_max is None:
            return "not_configured"
        if self.reference_min is not None and self.value_number < self.reference_min:
            return "below"
        if self.reference_max is not None and self.value_number > self.reference_max:
            return "above"
        return "within"


class SampleAttachment(models.Model):
    sample = models.ForeignKey(
        "samples.Sample",
        on_delete=models.CASCADE,
        related_name="result_attachments",
    )
    file = models.FileField(upload_to="sample_attachments/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.sample.sample_id} - {self.file.name.split('/')[-1]}"
