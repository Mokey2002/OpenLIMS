from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.models import PublicIDModel


class Notebook(PublicIDModel):
    SCOPE_USER = "USER"
    SCOPE_TEAM = "TEAM"
    SCOPE_PROJECT = "PROJECT"
    SCOPE_CHOICES = [
        (SCOPE_USER, "User"),
        (SCOPE_TEAM, "Team"),
        (SCOPE_PROJECT, "Project"),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    scope = models.CharField(max_length=16, choices=SCOPE_CHOICES, default=SCOPE_USER)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_notebooks",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="notebooks",
    )
    team_members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="team_notebooks",
    )
    readers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="readable_notebooks",
    )
    editors = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="editable_notebooks",
    )
    commenters = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="commentable_notebooks",
    )
    reviewers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="reviewable_notebooks",
    )
    lockers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="lockable_notebooks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def clean(self):
        super().clean()
        if self.scope == self.SCOPE_PROJECT and not self.project_id:
            raise ValidationError({"project": "Project-scoped notebooks require a project."})
        if self.scope != self.SCOPE_PROJECT and self.project_id:
            raise ValidationError({"project": "Only project-scoped notebooks may select a project."})

    def __str__(self):
        return self.name


class ExperimentTemplate(PublicIDModel):
    notebook = models.ForeignKey(
        Notebook,
        on_delete=models.PROTECT,
        related_name="templates",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    blocks = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_experiment_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["notebook", "name"],
                name="notebook_template_name_unique",
            )
        ]

    def __str__(self):
        return self.name


class Experiment(PublicIDModel):
    STATUS_DRAFT = "DRAFT"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_REVIEWED = "REVIEWED"
    STATUS_LOCKED = "LOCKED"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_REVIEWED, "Reviewed"),
        (STATUS_LOCKED, "Locked"),
    ]

    notebook = models.ForeignKey(
        Notebook,
        on_delete=models.PROTECT,
        related_name="experiments",
    )
    template = models.ForeignKey(
        ExperimentTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="experiments",
    )
    cloned_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clones",
    )
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_experiments",
    )
    assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="assigned_experiments",
    )
    current_revision = models.ForeignKey(
        "ExperimentRevision",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_for_experiments",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="locked_experiments",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [models.Index(fields=["status", "updated_at"])]

    @property
    def project(self):
        return self.notebook.project

    def __str__(self):
        return self.title


class ExperimentRevision(PublicIDModel):
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.PROTECT,
        related_name="revisions",
    )
    number = models.PositiveIntegerField()
    checksum = models.CharField(max_length=64, db_index=True)
    change_summary = models.TextField(blank=True)
    parent_revision = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="child_revisions",
    )
    restored_from = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="restore_revisions",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_experiment_revisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(
                fields=["experiment", "number"],
                name="notebook_experiment_revision_unique",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and ExperimentRevision.objects.filter(pk=self.pk).exists():
            raise ValidationError("Experiment revisions are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Experiment revisions are immutable.")

    def __str__(self):
        return f"{self.experiment.title} r{self.number}"


class ExperimentBlock(PublicIDModel):
    TYPE_RICH_TEXT = "RICH_TEXT"
    TYPE_HEADING = "HEADING"
    TYPE_TABLE = "TABLE"
    TYPE_CHECKLIST = "CHECKLIST"
    TYPE_PROTOCOL = "PROTOCOL_STEP"
    TYPE_CALCULATION = "CALCULATION"
    TYPE_IMAGE = "IMAGE"
    TYPE_ATTACHMENT = "ATTACHMENT"
    TYPE_RESULT = "STRUCTURED_RESULT"
    TYPE_SEQUENCE = "SEQUENCE_VIEW"
    TYPE_CHOICES = [
        (TYPE_RICH_TEXT, "Rich text"),
        (TYPE_HEADING, "Heading"),
        (TYPE_TABLE, "Table"),
        (TYPE_CHECKLIST, "Checklist"),
        (TYPE_PROTOCOL, "Protocol step"),
        (TYPE_CALCULATION, "Calculation"),
        (TYPE_IMAGE, "Image"),
        (TYPE_ATTACHMENT, "Attachment"),
        (TYPE_RESULT, "Structured result"),
        (TYPE_SEQUENCE, "Embedded sequence view"),
    ]

    revision = models.ForeignKey(
        ExperimentRevision,
        on_delete=models.PROTECT,
        related_name="blocks",
    )
    position = models.PositiveIntegerField()
    block_type = models.CharField(max_length=24, choices=TYPE_CHOICES)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["revision", "position"],
                name="notebook_revision_block_position_unique",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and ExperimentBlock.objects.filter(pk=self.pk).exists():
            raise ValidationError("Experiment blocks are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Experiment blocks are immutable.")


class ExperimentLink(PublicIDModel):
    revision = models.ForeignKey(
        ExperimentRevision,
        on_delete=models.PROTECT,
        related_name="links",
    )
    entity_type = models.SlugField(max_length=64)
    entity_public_id = models.UUIDField()
    relation_type = models.SlugField(max_length=64, default="used")
    label = models.CharField(max_length=255)
    version = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_experiment_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["entity_type", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["revision", "entity_type", "entity_public_id", "relation_type"],
                name="notebook_revision_entity_link_unique",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and ExperimentLink.objects.filter(pk=self.pk).exists():
            raise ValidationError("Experiment revision links are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Experiment revision links are immutable.")


class ExperimentComment(PublicIDModel):
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.PROTECT,
        related_name="comments",
    )
    revision = models.ForeignKey(
        ExperimentRevision,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="experiment_comments",
    )
    body = models.TextField()
    mentions = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="mentioned_experiment_comments",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_experiment_comments",
    )
    resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_experiment_comments",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class ExperimentReview(PublicIDModel):
    DECISION_APPROVED = "APPROVED"
    DECISION_CHANGES = "CHANGES_REQUESTED"
    DECISION_CHOICES = [
        (DECISION_APPROVED, "Approved"),
        (DECISION_CHANGES, "Changes requested"),
    ]

    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    revision = models.ForeignKey(
        ExperimentRevision,
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="experiment_reviews",
    )
    decision = models.CharField(max_length=24, choices=DECISION_CHOICES)
    comment = models.TextField(blank=True)
    signed_name = models.CharField(max_length=255)
    content_checksum = models.CharField(max_length=64)
    reviewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-reviewed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["revision", "reviewer"],
                name="notebook_revision_reviewer_unique",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and ExperimentReview.objects.filter(pk=self.pk).exists():
            raise ValidationError("Experiment reviews are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Experiment reviews are immutable.")
