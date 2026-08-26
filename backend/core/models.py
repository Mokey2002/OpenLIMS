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
