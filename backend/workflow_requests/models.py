from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from core.models import PublicIDModel


class AssayRequestType(PublicIDModel):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    form_schema = models.JSONField(default=dict, blank=True)
    default_pipeline = models.ForeignKey(
        "pipelines.PipelineTemplate",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assay_request_types",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="assay_request_types",
    )
    default_priority = models.CharField(max_length=16, default="NORMAL")
    sla_hours = models.PositiveIntegerField(default=120)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_assay_request_types",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(Lower("code"), name="workflow_request_type_code_ci_unique")]

    def __str__(self):
        return f"{self.code} - {self.name}"


class RequestResourceRequirement(PublicIDModel):
    KIND_MATERIAL = "MATERIAL"
    KIND_INSTRUMENT = "INSTRUMENT"
    KIND_PERSONNEL = "PERSONNEL"
    KIND_DURATION = "DURATION"
    KIND_CHOICES = [
        (KIND_MATERIAL, "Material"),
        (KIND_INSTRUMENT, "Instrument"),
        (KIND_PERSONNEL, "Personnel role"),
        (KIND_DURATION, "Estimated duration"),
    ]

    request_type = models.ForeignKey(AssayRequestType, on_delete=models.CASCADE, related_name="resource_requirements")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    inventory_item = models.ForeignKey(
        "inventory.InventoryItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_resource_requirements",
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    unit = models.CharField(max_length=32, blank=True)
    instrument_name = models.CharField(max_length=255, blank=True)
    personnel_role = models.CharField(max_length=128, blank=True)
    estimated_duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    pipeline_step_position = models.PositiveIntegerField(null=True, blank=True)
    required = models.BooleanField(default=True)

    class Meta:
        ordering = ["kind", "id"]

    def clean(self):
        super().clean()
        if self.kind == self.KIND_MATERIAL and not self.inventory_item_id:
            raise ValidationError({"inventory_item": "Material requirements need an inventory item."})


class WorkflowRequest(PublicIDModel):
    STATUS_DRAFT = "DRAFT"
    STATUS_SUBMITTED = "SUBMITTED"
    STATUS_TRIAGE = "TRIAGE"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_TRIAGE, "Triage"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_COMPLETED, "Completed"),
    ]
    PRIORITY_LOW = "LOW"
    PRIORITY_NORMAL = "NORMAL"
    PRIORITY_HIGH = "HIGH"
    PRIORITY_URGENT = "URGENT"
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_NORMAL, "Normal"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_URGENT, "Urgent"),
    ]

    request_number = models.CharField(max_length=64, unique=True)
    request_type = models.ForeignKey(AssayRequestType, on_delete=models.PROTECT, related_name="requests")
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="workflow_requests")
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="workflow_requests")
    title = models.CharField(max_length=255)
    form_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    priority = models.CharField(max_length=16, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL)
    due_at = models.DateTimeField(null=True, blank=True)
    assigned_pipeline = models.ForeignKey(
        "pipelines.PipelineTemplate",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="workflow_requests",
    )
    triaged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="triaged_workflow_requests")
    triaged_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_workflow_requests")
    approved_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["project", "status", "priority"]), models.Index(fields=["requester", "status"])]

    def __str__(self):
        return f"{self.request_number} - {self.title}"


class WorkflowRequestItem(PublicIDModel):
    request = models.ForeignKey(WorkflowRequest, on_delete=models.CASCADE, related_name="items")
    sample = models.ForeignKey("samples.Sample", on_delete=models.PROTECT, null=True, blank=True, related_name="workflow_request_items")
    registry_record = models.ForeignKey("registry.RegistryRecord", on_delete=models.PROTECT, null=True, blank=True, related_name="workflow_request_items")
    study_public_id = models.UUIDField(null=True, blank=True)
    pipeline_run = models.ForeignKey("pipelines.PipelineRun", on_delete=models.PROTECT, null=True, blank=True, related_name="workflow_request_items")
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["request", "sample"], condition=models.Q(sample__isnull=False), name="workflow_request_sample_unique"),
            models.UniqueConstraint(fields=["request", "registry_record"], condition=models.Q(registry_record__isnull=False), name="workflow_request_registry_unique"),
        ]

    def clean(self):
        super().clean()
        if not any([self.sample_id, self.registry_record_id, self.study_public_id]):
            raise ValidationError("A request item must link a sample, registry record, or study.")
        if self.sample_id and self.sample.project_id != self.request.project_id:
            raise ValidationError({"sample": "The sample belongs to another project."})
        if self.registry_record_id and self.registry_record.project_id not in {None, self.request.project_id}:
            raise ValidationError({"registry_record": "The registry record belongs to another project."})


class WorkflowRunGroup(PublicIDModel):
    request = models.ForeignKey(WorkflowRequest, on_delete=models.CASCADE, related_name="run_groups")
    name = models.CharField(max_length=255)
    batch = models.ForeignKey("samples.SampleBatch", on_delete=models.PROTECT, null=True, blank=True, related_name="workflow_run_groups")
    plate = models.ForeignKey("inventory.Container", on_delete=models.PROTECT, null=True, blank=True, related_name="workflow_run_groups")
    items = models.ManyToManyField(WorkflowRequestItem, blank=True, related_name="run_groups")
    pipeline_runs = models.ManyToManyField("pipelines.PipelineRun", blank=True, related_name="workflow_request_groups")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_workflow_run_groups")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["request", "name"], name="workflow_request_run_group_name_unique")]


class WorkflowRequestMessage(PublicIDModel):
    request = models.ForeignKey(WorkflowRequest, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="workflow_request_messages")
    body = models.TextField()
    internal_only = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


def request_report_upload_to(instance, filename):
    return f"workflow_requests/{instance.request.public_id}/{filename}"


class WorkflowRequestReport(PublicIDModel):
    request = models.ForeignKey(WorkflowRequest, on_delete=models.PROTECT, related_name="reports")
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to=request_report_upload_to)
    checksum_sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_workflow_request_reports")
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_workflow_request_reports")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
