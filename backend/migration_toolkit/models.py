from django.conf import settings
from django.db import models


class SampleExternalID(models.Model):
    sample = models.ForeignKey(
        "samples.Sample",
        on_delete=models.CASCADE,
        related_name="external_ids",
    )
    source_system = models.CharField(max_length=128)
    external_id = models.CharField(max_length=255)
    label = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("source_system", "external_id", "label")]
        indexes = [
            models.Index(fields=["source_system", "external_id"]),
            models.Index(fields=["label"]),
        ]

    def __str__(self):
        return f"{self.source_system}:{self.label}:{self.external_id}"


class MigrationProfile(models.Model):
    SOURCE_TYPE_CSV = "CSV"

    SOURCE_TYPE_CHOICES = [
        (SOURCE_TYPE_CSV, "CSV"),
    ]

    name = models.CharField(max_length=128, unique=True)
    source_system = models.CharField(max_length=128, default="Legacy DB")
    source_type = models.CharField(
        max_length=32,
        choices=SOURCE_TYPE_CHOICES,
        default=SOURCE_TYPE_CSV,
    )
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="migration_profiles",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class MigrationFieldMapping(models.Model):
    TARGET_PROJECT_CODE = "PROJECT_CODE"
    TARGET_PROJECT_NAME = "PROJECT_NAME"
    TARGET_SAMPLE_ID = "SAMPLE_ID"
    TARGET_EXTERNAL_ID = "EXTERNAL_ID"
    TARGET_CUSTOM_FIELD = "CUSTOM_FIELD"
    TARGET_WORK_ITEM_NAME = "WORK_ITEM_NAME"
    TARGET_RESULT_VALUE = "RESULT_VALUE"

    TARGET_TYPE_CHOICES = [
        (TARGET_PROJECT_CODE, "Project Code"),
        (TARGET_PROJECT_NAME, "Project Name"),
        (TARGET_SAMPLE_ID, "Sample ID"),
        (TARGET_EXTERNAL_ID, "External ID / Alias"),
        (TARGET_CUSTOM_FIELD, "Sample Custom Field"),
        (TARGET_WORK_ITEM_NAME, "Work Item Name"),
        (TARGET_RESULT_VALUE, "Result Value"),
    ]

    VALUE_TYPE_STRING = "STRING"
    VALUE_TYPE_NUMBER = "NUMBER"
    VALUE_TYPE_BOOLEAN = "BOOLEAN"

    VALUE_TYPE_CHOICES = [
        (VALUE_TYPE_STRING, "String"),
        (VALUE_TYPE_NUMBER, "Number"),
        (VALUE_TYPE_BOOLEAN, "Boolean"),
    ]

    profile = models.ForeignKey(
        MigrationProfile,
        on_delete=models.CASCADE,
        related_name="field_mappings",
    )
    source_column = models.CharField(max_length=128)
    target_type = models.CharField(max_length=64, choices=TARGET_TYPE_CHOICES)
    target_field = models.CharField(
        max_length=128,
        blank=True,
        help_text="Used for custom field name, external ID label, or result key.",
    )
    value_type = models.CharField(
        max_length=16,
        choices=VALUE_TYPE_CHOICES,
        default=VALUE_TYPE_STRING,
    )
    required = models.BooleanField(default=False)

    class Meta:
        unique_together = [("profile", "source_column", "target_type", "target_field")]

    def __str__(self):
        return f"{self.profile.name}: {self.source_column} -> {self.target_type}"


class MigrationJob(models.Model):
    STATUS_PREVIEWED = "PREVIEWED"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"

    STATUS_CHOICES = [
        (STATUS_PREVIEWED, "Previewed"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    profile = models.ForeignKey(
        MigrationProfile,
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="migration_jobs",
    )
    uploaded_file = models.FileField(upload_to="migration_jobs/", null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="migration_jobs",
    )
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_PREVIEWED,
    )
    summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"MigrationJob {self.id} - {self.profile.name}"
