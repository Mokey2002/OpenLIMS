from django.conf import settings
from django.db import models


class AlignmentJob(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "PENDING"),
        ("RUNNING", "RUNNING"),
        ("COMPLETED", "COMPLETED"),
        ("FAILED", "FAILED"),
    ]

    TOOL_CHOICES = [
        ("CLUSTAL_OMEGA", "Clustal Omega"),
    ]

    name = models.CharField(max_length=255)

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alignment_jobs",
    )

    sequences = models.ManyToManyField(
        "sequences.Sequence",
        related_name="alignment_jobs",
        blank=True,
    )

    tool = models.CharField(
        max_length=50,
        choices=TOOL_CHOICES,
        default="CLUSTAL_OMEGA",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING",
    )

    input_fasta = models.TextField(blank=True)
    aligned_fasta = models.TextField(blank=True)
    summary = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alignment_jobs",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-updated_at"]

    def __str__(self):
        return f"{self.name} ({self.status})"
