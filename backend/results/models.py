from django.conf import settings
from django.db import models


class WorkItem(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
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
    name = models.CharField(max_length=128)
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    notes = models.TextField(blank=True)

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

    created_at = models.DateTimeField(auto_now_add=True)

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