from django.conf import settings
from django.db import models

from core.models import PublicIDModel


class Sequence(PublicIDModel):
    SEQUENCE_TYPE_CHOICES = [
        ("DNA", "DNA"),
        ("RNA", "RNA"),
        ("PROTEIN", "Protein"),
    ]

    SOURCE_TYPE_CHOICES = [
        ("MANUAL", "Manual"),
        ("FASTA_IMPORT", "FASTA Import"),
        ("FASTQ_IMPORT", "FASTQ Import"),
        ("GENBANK_IMPORT", "GenBank Import"),
    ]

    TOPOLOGY_LINEAR = "LINEAR"
    TOPOLOGY_CIRCULAR = "CIRCULAR"
    TOPOLOGY_CHOICES = [
        (TOPOLOGY_LINEAR, "Linear"),
        (TOPOLOGY_CIRCULAR, "Circular"),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    sequence_type = models.CharField(
        max_length=20,
        choices=SEQUENCE_TYPE_CHOICES,
        default="DNA",
    )

    sequence = models.TextField()
    topology = models.CharField(
        max_length=16,
        choices=TOPOLOGY_CHOICES,
        default=TOPOLOGY_LINEAR,
    )

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sequences",
    )

    sample = models.ForeignKey(
        "samples.Sample",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sequences",
    )

    import_job = models.ForeignKey(
        "imports.ImportJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sequences",
    )

    source_type = models.CharField(
        max_length=30,
        choices=SOURCE_TYPE_CHOICES,
        default="MANUAL",
    )
    source_metadata = models.JSONField(default=dict, blank=True)

    viewer = models.CharField(max_length=50, default="both")
    show_complement = models.BooleanField(default=True)
    rotate_on_scroll = models.BooleanField(default=False)
    zoom = models.IntegerField(default=50)

    enzymes = models.JSONField(default=list, blank=True)
    bp_colors = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_sequences",
    )

    current_revision = models.ForeignKey(
        "SequenceRevision",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_for_sequences",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]

    def __str__(self):
        return self.name


class SequenceFeature(models.Model):
    FEATURE_TYPE_CHOICES = [
        ("ANNOTATION", "Annotation"),
        ("PRIMER", "Primer"),
        ("TRANSLATION", "Translation"),
        ("HIGHLIGHT", "Highlight"),
    ]

    sequence_record = models.ForeignKey(
        Sequence,
        on_delete=models.CASCADE,
        related_name="features",
    )

    feature_type = models.CharField(
        max_length=30,
        choices=FEATURE_TYPE_CHOICES,
    )

    name = models.CharField(max_length=255, blank=True)
    start = models.PositiveIntegerField()
    end = models.PositiveIntegerField()
    direction = models.IntegerField(default=1)
    color = models.CharField(max_length=30, default="#22c55e")

    metadata = models.JSONField(default=dict, blank=True)
    library_feature = models.ForeignKey(
        "SequenceFeatureLibrary",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workspace_features",
    )
    primer_sequence = models.TextField(blank=True)
    melting_temperature = models.FloatField(null=True, blank=True)
    gc_content = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start", "end", "id"]

    def __str__(self):
        return f"{self.feature_type}: {self.name or self.start}"


class SequenceRevision(PublicIDModel):
    """Immutable sequence and annotation snapshot."""

    sequence_record = models.ForeignKey(
        Sequence,
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    revision = models.PositiveIntegerField()
    sequence_type = models.CharField(max_length=20, choices=Sequence.SEQUENCE_TYPE_CHOICES)
    topology = models.CharField(max_length=16, choices=Sequence.TOPOLOGY_CHOICES)
    sequence = models.TextField()
    checksum = models.CharField(max_length=64, db_index=True)
    change_summary = models.TextField(blank=True)
    registry_record = models.ForeignKey(
        "registry.RegistryRecord",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sequence_revisions",
    )
    source_metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_sequence_revisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-revision"]
        constraints = [
            models.UniqueConstraint(
                fields=["sequence_record", "revision"],
                name="sequence_revision_number_unique",
            )
        ]

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError

        if self.pk and SequenceRevision.objects.filter(pk=self.pk).exists():
            raise ValidationError("Sequence revisions are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError

        raise ValidationError("Sequence revisions are immutable.")

    def __str__(self):
        return f"{self.sequence_record.name} r{self.revision}"


class SequenceRevisionFeature(PublicIDModel):
    revision = models.ForeignKey(
        SequenceRevision,
        on_delete=models.CASCADE,
        related_name="features",
    )
    library_feature = models.ForeignKey(
        "SequenceFeatureLibrary",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revision_features",
    )
    feature_type = models.CharField(max_length=30, choices=SequenceFeature.FEATURE_TYPE_CHOICES)
    name = models.CharField(max_length=255, blank=True)
    start = models.PositiveIntegerField()
    end = models.PositiveIntegerField()
    direction = models.IntegerField(default=1)
    color = models.CharField(max_length=30, default="#22c55e")
    metadata = models.JSONField(default=dict, blank=True)
    primer_sequence = models.TextField(blank=True)
    melting_temperature = models.FloatField(null=True, blank=True)
    gc_content = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["start", "end", "id"]


class SequenceFeatureLibrary(PublicIDModel):
    name = models.CharField(max_length=255)
    feature_type = models.CharField(max_length=30, choices=SequenceFeature.FEATURE_TYPE_CHOICES)
    sequence_type = models.CharField(max_length=20, choices=Sequence.SEQUENCE_TYPE_CHOICES, default="DNA")
    motif = models.TextField(blank=True)
    color = models.CharField(max_length=30, default="#22c55e")
    qualifiers = models.JSONField(default=dict, blank=True)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sequence_feature_library",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_sequence_features",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "name", "sequence_type"],
                name="sequence_feature_library_unique",
            )
        ]


class ConstructAssemblyPlan(PublicIDModel):
    STATUS_DRAFT = "DRAFT"
    STATUS_ASSEMBLED = "ASSEMBLED"
    STATUS_CHOICES = [(STATUS_DRAFT, "Draft"), (STATUS_ASSEMBLED, "Assembled")]

    name = models.CharField(max_length=255)
    target_sequence = models.ForeignKey(
        Sequence,
        on_delete=models.CASCADE,
        related_name="assembly_plans",
    )
    method = models.CharField(max_length=64, default="SIMPLE_FRAGMENT_ASSEMBLY")
    cloning_notes = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_assembly_plans",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class AssemblyFragment(PublicIDModel):
    plan = models.ForeignKey(
        ConstructAssemblyPlan,
        on_delete=models.CASCADE,
        related_name="fragments",
    )
    source_revision = models.ForeignKey(
        SequenceRevision,
        on_delete=models.PROTECT,
        related_name="assembly_fragments",
    )
    order = models.PositiveIntegerField()
    start = models.PositiveIntegerField(default=0)
    end = models.PositiveIntegerField(null=True, blank=True)
    reverse_complement = models.BooleanField(default=False)
    left_overhang = models.CharField(max_length=64, blank=True)
    right_overhang = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "order"], name="assembly_fragment_order_unique")
        ]
