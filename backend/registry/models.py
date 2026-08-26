from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from core.models import PublicIDModel


class RegistrySchema(PublicIDModel):
    """Immutable, versioned definition for one configurable registry type."""

    code = models.SlugField(max_length=64)
    name = models.CharField(max_length=128)
    entity_type = models.SlugField(max_length=64)
    version = models.PositiveIntegerField(default=1)
    id_prefix = models.CharField(max_length=24, blank=True)
    description = models.TextField(blank=True)
    schema = models.JSONField(default=dict, blank=True)
    matching_fields = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_registry_schemas",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["entity_type", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["code", "version"],
                name="registry_schema_code_version_unique",
            ),
        ]
        indexes = [models.Index(fields=["entity_type", "active"])]

    def __str__(self):
        return f"{self.name} v{self.version}"


class RegistryRecord(PublicIDModel):
    STATUS_DRAFT = "DRAFT"
    STATUS_IN_REVIEW = "IN_REVIEW"
    STATUS_REGISTERED = "REGISTERED"
    STATUS_RETIRED = "RETIRED"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_IN_REVIEW, "In review"),
        (STATUS_REGISTERED, "Registered"),
        (STATUS_RETIRED, "Retired"),
    ]

    VISIBILITY_PROJECT = "PROJECT"
    VISIBILITY_PRIVATE = "PRIVATE"
    VISIBILITY_INSTITUTION = "INSTITUTION"
    VISIBILITY_CHOICES = [
        (VISIBILITY_PROJECT, "Project"),
        (VISIBILITY_PRIVATE, "Owner only"),
        (VISIBILITY_INSTITUTION, "Institution"),
    ]

    registry_id = models.CharField(max_length=64, unique=True)
    schema = models.ForeignKey(
        RegistrySchema,
        on_delete=models.PROTECT,
        related_name="records",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    catalog_number = models.CharField(max_length=128, blank=True)
    external_identifiers = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=list, blank=True)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="registry_records",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_registry_records",
    )
    visibility = models.CharField(
        max_length=16,
        choices=VISIBILITY_CHOICES,
        default=VISIBILITY_PROJECT,
    )
    lifecycle_status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    current_version = models.ForeignKey(
        "RegistryRecordVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_for_records",
    )
    registered_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["registry_id"]
        indexes = [
            models.Index(fields=["project", "lifecycle_status"]),
            models.Index(fields=["schema", "lifecycle_status"]),
            models.Index(fields=["catalog_number"]),
        ]

    def __str__(self):
        return f"{self.registry_id} - {self.name}"


class RegistryRecordVersion(PublicIDModel):
    """An immutable snapshot of registry data and its linked sequence revision."""

    record = models.ForeignKey(
        RegistryRecord,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    schema = models.ForeignKey(
        RegistrySchema,
        on_delete=models.PROTECT,
        related_name="record_versions",
    )
    version = models.PositiveIntegerField()
    data = models.JSONField(default=dict, blank=True)
    sequence_revision = models.ForeignKey(
        "sequences.SequenceRevision",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="registry_versions",
    )
    sequence_checksum = models.CharField(max_length=64, blank=True)
    change_summary = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_registry_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["record", "version"],
                name="registry_record_version_unique",
            )
        ]
        indexes = [models.Index(fields=["sequence_checksum"])]

    def save(self, *args, **kwargs):
        if self.pk and RegistryRecordVersion.objects.filter(pk=self.pk).exists():
            raise ValidationError("Registry record versions are immutable.")
        if self.sequence_revision_id:
            self.sequence_checksum = self.sequence_revision.checksum
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Registry record versions are immutable.")

    def __str__(self):
        return f"{self.record.registry_id} v{self.version}"


class RegistryAlias(PublicIDModel):
    record = models.ForeignKey(
        RegistryRecord,
        on_delete=models.CASCADE,
        related_name="aliases",
    )
    alias = models.CharField(max_length=255)
    alias_type = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["alias"]
        constraints = [
            models.UniqueConstraint(
                Lower("alias"),
                "record",
                name="registry_record_alias_ci_unique",
            )
        ]
        indexes = [models.Index(fields=["alias"])]

    def __str__(self):
        return self.alias


class RegistryRelationship(PublicIDModel):
    RELATION_DERIVED_FROM = "derived_from"
    RELATION_CONTAINS = "contains"
    RELATION_EXPRESSES = "expresses"
    RELATION_BINDS = "binds"
    RELATION_COMPONENT_OF = "component_of"
    RELATION_CUSTOM = "custom"
    RELATION_CHOICES = [
        (RELATION_DERIVED_FROM, "Derived from"),
        (RELATION_CONTAINS, "Contains"),
        (RELATION_EXPRESSES, "Expresses"),
        (RELATION_BINDS, "Binds"),
        (RELATION_COMPONENT_OF, "Component of"),
        (RELATION_CUSTOM, "Custom"),
    ]

    source = models.ForeignKey(
        RegistryRecord,
        on_delete=models.CASCADE,
        related_name="outgoing_relationships",
    )
    target = models.ForeignKey(
        RegistryRecord,
        on_delete=models.CASCADE,
        related_name="incoming_relationships",
    )
    relationship_type = models.CharField(max_length=32, choices=RELATION_CHOICES)
    custom_type = models.SlugField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_registry_relationships",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "target", "relationship_type", "custom_type"],
                name="registry_relationship_unique",
            )
        ]

    def clean(self):
        if self.source_id == self.target_id:
            raise ValidationError("A registry record cannot relate to itself.")
        if self.relationship_type == self.RELATION_CUSTOM and not self.custom_type:
            raise ValidationError("Custom relationships require custom_type.")


class RegistrationReview(PublicIDModel):
    DECISION_PENDING = "PENDING"
    DECISION_APPROVED = "APPROVED"
    DECISION_REJECTED = "REJECTED"
    DECISION_CHOICES = [
        (DECISION_PENDING, "Pending"),
        (DECISION_APPROVED, "Approved"),
        (DECISION_REJECTED, "Rejected"),
    ]

    record = models.ForeignKey(
        RegistryRecord,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    version = models.ForeignKey(
        RegistryRecordVersion,
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_registration_reviews",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registration_reviews",
    )
    decision = models.CharField(
        max_length=16,
        choices=DECISION_CHOICES,
        default=DECISION_PENDING,
    )
    comments = models.TextField(blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["record"],
                condition=models.Q(decision="PENDING"),
                name="registry_one_pending_review",
            )
        ]
