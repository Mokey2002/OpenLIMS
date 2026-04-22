from django.db import models
from django.conf import settings
from projects.models import Project

class InstrumentProfile(models.Model):
    name = models.CharField(max_length=128, unique=True)
    code = models.CharField(max_length=64, unique=True)
    delimiter = models.CharField(max_length=5, default=",")
    has_header = models.BooleanField(default=True)
    sample_id_column = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.code} - {self.name}"


class InstrumentColumnMapping(models.Model):
    VALUE_TYPE_CHOICES = [
        ("STRING", "STRING"),
        ("NUMBER", "NUMBER"),
        ("BOOLEAN", "BOOLEAN"),
    ]

    instrument = models.ForeignKey(
        InstrumentProfile,
        on_delete=models.CASCADE,
        related_name="column_mappings",
    )
    source_column = models.CharField(max_length=128)
    target_key = models.CharField(max_length=128)
    value_type = models.CharField(max_length=20, choices=VALUE_TYPE_CHOICES)

    class Meta:
        unique_together = ("instrument", "source_column")

    def __str__(self):
        return f"{self.instrument.code}: {self.source_column} -> {self.target_key}"


class ImportJob(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "PENDING"),
        ("COMPLETED", "COMPLETED"),
        ("FAILED", "FAILED"),
    ]

    instrument = models.ForeignKey(
        InstrumentProfile,
        on_delete=models.CASCADE,
        related_name="import_jobs",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="import_jobs",
    )
    uploaded_file = models.FileField(upload_to="imports/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="import_jobs",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ImportJob {self.id} - {self.instrument.code}"
