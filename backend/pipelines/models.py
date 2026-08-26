from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from core.models import PublicIDModel


class AnalysisDefinition(models.Model):
    VALUE_TYPE_STRING = "STRING"
    VALUE_TYPE_NUMBER = "NUMBER"
    VALUE_TYPE_BOOLEAN = "BOOLEAN"
    VALUE_TYPE_CHOICES = [
        (VALUE_TYPE_STRING, "String"),
        (VALUE_TYPE_NUMBER, "Number"),
        (VALUE_TYPE_BOOLEAN, "Boolean"),
    ]

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    category = models.CharField(max_length=64, blank=True)
    description = models.TextField(blank=True)
    required_fields = models.JSONField(
        default=list,
        blank=True,
        help_text="Result fields required before a pipeline step can complete.",
    )
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_analysis_definitions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                name="pipelines_analysis_code_ci_unique",
            )
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class ProcedureDefinition(models.Model):
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=128)
    version = models.CharField(max_length=32, default="1")
    analysis = models.ForeignKey(
        AnalysisDefinition,
        on_delete=models.PROTECT,
        related_name="procedures",
    )
    sop_document = models.ForeignKey(
        "assistant.SOPDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="procedure_definitions",
    )
    instructions = models.TextField(blank=True)
    estimated_duration_minutes = models.PositiveIntegerField(default=60)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_procedure_definitions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code", "version"]
        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                "version",
                name="pipelines_procedure_code_version_ci_unique",
            )
        ]

    def __str__(self):
        return f"{self.code} v{self.version} - {self.name}"


class PipelineTemplate(models.Model):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    default_project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_pipeline_templates",
    )
    default_sample_type = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pipeline_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                name="pipelines_template_code_ci_unique",
            )
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class PipelineTemplateStep(models.Model):
    template = models.ForeignKey(
        PipelineTemplate,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    position = models.PositiveIntegerField()
    procedure = models.ForeignKey(
        ProcedureDefinition,
        on_delete=models.PROTECT,
        related_name="pipeline_steps",
    )
    name = models.CharField(
        max_length=128,
        blank=True,
        help_text="Optional display name. The procedure name is used when blank.",
    )
    requires_qc = models.BooleanField(default=False)
    dependency_positions = models.JSONField(
        default=None,
        null=True,
        blank=True,
        help_text="Positions that must complete before this step can start.",
    )
    activation_condition = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional result-based condition evaluated after dependencies complete.",
    )
    optional = models.BooleanField(
        default=False,
        help_text="Allow the workflow to continue when this step fails or is cancelled.",
    )
    max_retries = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["template", "position"],
                name="pipelines_template_step_position_unique",
            )
        ]

    @property
    def display_name(self):
        return self.name or self.procedure.name

    def __str__(self):
        return f"{self.template.code} #{self.position} - {self.display_name}"


class PipelineRun(PublicIDModel):
    STATUS_ACTIVE = "ACTIVE"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_BLOCKED = "BLOCKED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_BLOCKED, "Blocked"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    sample = models.ForeignKey(
        "samples.Sample",
        on_delete=models.CASCADE,
        related_name="pipeline_runs",
    )
    template = models.ForeignKey(
        PipelineTemplate,
        on_delete=models.PROTECT,
        related_name="runs",
    )
    template_code = models.CharField(max_length=64)
    template_name = models.CharField(max_length=128)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="started_pipeline_runs",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["sample"],
                condition=models.Q(status__in=["ACTIVE", "BLOCKED"]),
                name="pipelines_one_active_run_per_sample",
            )
        ]

    def __str__(self):
        return f"{self.sample.sample_id} - {self.template_code}"


class PipelineStepRun(models.Model):
    STATUS_BLOCKED = "BLOCKED"
    STATUS_READY = "READY"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_AWAITING_QC = "AWAITING_QC"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_SKIPPED = "SKIPPED"
    STATUS_CHOICES = [
        (STATUS_BLOCKED, "Blocked"),
        (STATUS_READY, "Ready"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_AWAITING_QC, "Awaiting QC"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_SKIPPED, "Skipped"),
    ]

    pipeline_run = models.ForeignKey(
        PipelineRun,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    template_step = models.ForeignKey(
        PipelineTemplateStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="step_runs",
    )
    position = models.PositiveIntegerField()
    name = models.CharField(max_length=128)
    analysis_code = models.CharField(max_length=64)
    procedure_code = models.CharField(max_length=64)
    procedure_version = models.CharField(max_length=32)
    work_type = models.CharField(max_length=64)
    required_fields = models.JSONField(default=list, blank=True)
    requires_qc = models.BooleanField(default=False)
    dependency_positions = models.JSONField(default=list, blank=True)
    activation_condition = models.JSONField(default=dict, blank=True)
    optional = models.BooleanField(default=False)
    max_retries = models.PositiveIntegerField(default=0)
    retry_count = models.PositiveIntegerField(default=0)
    estimated_duration_minutes = models.PositiveIntegerField(default=60)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_BLOCKED,
    )
    work_item = models.OneToOneField(
        "results.WorkItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pipeline_step_run",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline_run", "position"],
                name="pipelines_run_step_position_unique",
            )
        ]

    def __str__(self):
        return f"{self.pipeline_run_id} #{self.position} - {self.name}"
