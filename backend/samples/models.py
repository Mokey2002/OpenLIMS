from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


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


class Sample(models.Model):
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
