from django.conf import settings
from django.db import models
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

    min_value = models.FloatField(null=True, blank=True)
    max_value = models.FloatField(null=True, blank=True)
    allowed_values = models.JSONField(null=True, blank=True)

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

    SOURCE_TYPE_CHOICES = [
        ("UPLOAD", "UPLOAD"),
        ("API", "API"),
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
    uploaded_file = models.FileField(upload_to="imports/", null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="import_jobs",
    )
    run_id = models.CharField(max_length=128, null=True, blank=True)
    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_TYPE_CHOICES,
        default="UPLOAD",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["instrument", "run_id"],
                condition=models.Q(run_id__isnull=False),
                name="unique_instrument_run_id",
            )
        ]

    def __str__(self):
        return f"ImportJob {self.id} - {self.instrument.code}"
