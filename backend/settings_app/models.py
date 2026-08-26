from django.conf import settings
from django.db import models


class SystemSettings(models.Model):
    UI_LANGUAGE_ENGLISH = "en"
    UI_LANGUAGE_SPANISH = "es"
    UI_LANGUAGE_CHOICES = [
        (UI_LANGUAGE_ENGLISH, "English"),
        (UI_LANGUAGE_SPANISH, "Español"),
    ]

    lab_name = models.CharField(max_length=255, default="OpenLIMS Demo Lab")
    organization_name = models.CharField(max_length=255, default="OpenLIMS")
    ui_language = models.CharField(
        max_length=5,
        choices=UI_LANGUAGE_CHOICES,
        default=UI_LANGUAGE_ENGLISH,
    )

    default_timezone = models.CharField(max_length=100, default="UTC")
    default_sample_status = models.CharField(max_length=50, default="RECEIVED")

    max_upload_size_mb = models.PositiveIntegerField(default=10)
    require_import_preview = models.BooleanField(default=True)
    allowed_fasta_extensions = models.JSONField(
        default=list,
        blank=True,
    )

    alignments_enabled = models.BooleanField(default=True)
    max_sequences_per_alignment = models.PositiveIntegerField(default=25)
    max_sequence_length = models.PositiveIntegerField(default=100000)

    viewer_read_only = models.BooleanField(default=True)
    require_audit_reason = models.BooleanField(default=False)
    qc_separation_of_duties = models.BooleanField(default=False)

    notebook_enabled = models.BooleanField(default=False)
    registry_enabled = models.BooleanField(default=False)
    studies_enabled = models.BooleanField(default=False)
    insight_enabled = models.BooleanField(default=False)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_system_settings",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "System Settings"
        verbose_name_plural = "System Settings"

    def save(self, *args, **kwargs):
        self.pk = 1

        if not self.allowed_fasta_extensions:
            self.allowed_fasta_extensions = [".fasta", ".fa", ".fna", ".txt"]

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return None

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "lab_name": "OpenLIMS Demo Lab",
                "organization_name": "OpenLIMS",
                "ui_language": cls.UI_LANGUAGE_ENGLISH,
                "default_timezone": "UTC",
                "default_sample_status": "RECEIVED",
                "max_upload_size_mb": 10,
                "require_import_preview": True,
                "allowed_fasta_extensions": [".fasta", ".fa", ".fna", ".txt"],
                "alignments_enabled": True,
                "max_sequences_per_alignment": 25,
                "max_sequence_length": 100000,
                "viewer_read_only": True,
                "require_audit_reason": False,
                "qc_separation_of_duties": False,
                "notebook_enabled": False,
                "registry_enabled": False,
                "studies_enabled": False,
                "insight_enabled": False,
            },
        )
        return obj

    @property
    def feature_flags(self):
        return {
            "notebook": self.notebook_enabled,
            "registry": self.registry_enabled,
            "studies": self.studies_enabled,
            "insight": self.insight_enabled,
        }

    def __str__(self):
        return f"{self.organization_name} Settings"
