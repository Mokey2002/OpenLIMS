from django.conf import settings
from django.db import models


class Sequence(models.Model):
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

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    sequence_type = models.CharField(
        max_length=20,
        choices=SEQUENCE_TYPE_CHOICES,
        default="DNA",
    )

    sequence = models.TextField()

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

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start", "end", "id"]

    def __str__(self):
        return f"{self.feature_type}: {self.name or self.start}"
