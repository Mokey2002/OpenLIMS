import os
import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class PublicIDModel(models.Model):
    """Abstract base for records exposed across module boundaries."""

    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    class Meta:
        abstract = True


class UserAdministrationLock(models.Model):
    """One transaction lock shared by account and administrator-group edits."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="core_single_user_admin_lock")]


class UserSessionState(models.Model):
    """A persistent generation invalidates credentials even after reactivation."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="session_state")
    generation = models.PositiveIntegerField(default=0)


class UserOffboarding(models.Model):
    """An administrator's expiring preview and repeat-safe completion receipt."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    target = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="offboarding_plans")
    administrator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="prepared_offboardings")
    successor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="received_offboardings")
    reason = models.TextField()
    snapshot = models.JSONField(default=dict)
    fingerprint = models.CharField(max_length=64)
    custody_confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    receipt = models.JSONField(default=dict)


class AccessRequest(models.Model):
    PROJECT = "PROJECT"
    ROLE = "ROLE"
    REQUESTABLE_ROLES = ("viewer", "tech", "qc_reviewer")
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="access_requests")
    requester_username = models.CharField(max_length=150)
    kind = models.CharField(max_length=16, choices=[(PROJECT, "Project membership"), (ROLE, "Application role")])
    project_code = models.CharField(max_length=64, blank=True)
    # Binding occurs only at approval; accepting a code does not reveal whether
    # that project exists, its name, its members or any other private metadata.
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.SET_NULL, related_name="access_requests")
    role = models.CharField(max_length=32, blank=True)
    target_key = models.CharField(max_length=256, editable=False)
    reason = models.TextField()
    status = models.CharField(max_length=16, default=PENDING, choices=[(value, value.title()) for value in (PENDING, APPROVED, REJECTED, CANCELLED)])
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_access_requests")
    reviewer_username = models.CharField(max_length=150, blank=True)
    decision_reason = models.TextField(blank=True)
    access_changed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["status", "-created_at"], name="core_access_queue_idx")]
        constraints = [
            models.UniqueConstraint(fields=["requester", "target_key"], condition=models.Q(status="PENDING"), name="core_access_pending_unique"),
            models.CheckConstraint(condition=(
                models.Q(kind="PROJECT", role="") & ~models.Q(project_code="")
                | models.Q(kind="ROLE", project_code="", project__isnull=True, role__in=["viewer", "tech", "qc_reviewer"])
            ), name="core_access_valid_target"),
            models.CheckConstraint(condition=(
                models.Q(status="PENDING", reviewed_at__isnull=True)
                | models.Q(status__in=["APPROVED", "REJECTED", "CANCELLED"], reviewed_at__isnull=False)
            ), name="core_access_valid_state"),
        ]


def shared_attachment_upload_to(instance, filename):
    safe_name = os.path.basename(filename or "attachment")
    return f"shared_attachments/{instance.public_id}/{safe_name}"


class EntityLink(PublicIDModel):
    """Auditable relationship between any two registered linkable records."""

    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="openlims_source_links",
    )
    source_object_id = models.CharField(max_length=64)
    source_object = GenericForeignKey("source_content_type", "source_object_id")

    target_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="openlims_target_links",
    )
    target_object_id = models.CharField(max_length=64)
    target_object = GenericForeignKey("target_content_type", "target_object_id")

    relation_type = models.SlugField(max_length=64)
    label = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="entity_links",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_entity_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "source_content_type",
                    "source_object_id",
                    "target_content_type",
                    "target_object_id",
                    "relation_type",
                ],
                name="core_entity_link_unique",
            )
        ]
        indexes = [
            models.Index(
                fields=["source_content_type", "source_object_id"],
                name="core_link_source_idx",
            ),
            models.Index(
                fields=["target_content_type", "target_object_id"],
                name="core_link_target_idx",
            ),
            models.Index(fields=["project", "-created_at"], name="core_link_project_idx"),
        ]


class SharedAttachment(PublicIDModel):
    """Reusable attachment contract for current and future OpenLIMS modules."""

    target_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="openlims_shared_attachments",
    )
    target_object_id = models.CharField(max_length=64)
    target_object = GenericForeignKey("target_content_type", "target_object_id")

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="shared_attachments",
    )
    file = models.FileField(upload_to=shared_attachment_upload_to)
    display_name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    media_type = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shared_attachments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["target_content_type", "target_object_id"],
                name="core_attach_target_idx",
            ),
            models.Index(
                fields=["project", "-created_at"],
                name="core_attach_project_idx",
            ),
        ]

    @property
    def filename(self):
        return os.path.basename(self.file.name or "")
