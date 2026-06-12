from django.conf import settings
from django.db import models

from projects.models import Project
from samples.models import Sample


class MassSpecRun(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_RUNNING = "RUNNING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    name = models.CharField(max_length=255)
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mass_spec_runs",
    )
    sample = models.ForeignKey(
        Sample,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mass_spec_runs",
    )

    uploaded_file = models.FileField(upload_to="mass_spec/")
    original_filename = models.CharField(max_length=255, blank=True)

    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    error_message = models.TextField(blank=True)

    spectra_count = models.PositiveIntegerField(default=0)
    ms1_count = models.PositiveIntegerField(default=0)
    ms2_count = models.PositiveIntegerField(default=0)

    rt_min = models.FloatField(null=True, blank=True)
    rt_max = models.FloatField(null=True, blank=True)
    mz_min = models.FloatField(null=True, blank=True)
    mz_max = models.FloatField(null=True, blank=True)

    chromatogram_data = models.JSONField(default=list, blank=True)

    peak_count = models.PositiveIntegerField(default=0)
    base_peak_mz = models.FloatField(null=True, blank=True)
    base_peak_intensity = models.FloatField(null=True, blank=True)
    top_peaks = models.JSONField(default=list, blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mass_spec_uploads",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name
