from django.conf import settings
from django.db import models


class BlastDatabase(models.Model):
    DATABASE_TYPE_DNA = "DNA"
    DATABASE_TYPE_PROTEIN = "PROTEIN"

    DATABASE_TYPE_CHOICES = [
        (DATABASE_TYPE_DNA, "DNA"),
        (DATABASE_TYPE_PROTEIN, "Protein"),
    ]

    STATUS_NEW = "NEW"
    STATUS_BUILDING = "BUILDING"
    STATUS_READY = "READY"
    STATUS_FAILED = "FAILED"

    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        (STATUS_BUILDING, "Building"),
        (STATUS_READY, "Ready"),
        (STATUS_FAILED, "Failed"),
    ]

    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)

    database_type = models.CharField(
        max_length=20,
        choices=DATABASE_TYPE_CHOICES,
        default=DATABASE_TYPE_DNA,
    )

    source_fasta = models.FileField(
        upload_to="blast_databases/source_fastas/",
        null=True,
        blank=True,
    )

    db_path = models.CharField(
        max_length=500,
        blank=True,
        help_text="Path prefix to the built BLAST database inside the container.",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NEW,
    )

    error_message = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blast_databases",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.database_type})"


class BlastJob(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_RUNNING = "RUNNING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    PROGRAM_BLASTN = "blastn"
    PROGRAM_BLASTP = "blastp"

    PROGRAM_CHOICES = [
        (PROGRAM_BLASTN, "blastn"),
        (PROGRAM_BLASTP, "blastp"),
    ]

    name = models.CharField(max_length=255)

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blast_jobs",
    )

    query_sequence = models.ForeignKey(
        "sequences.Sequence",
        on_delete=models.CASCADE,
        related_name="blast_jobs",
    )

    database = models.ForeignKey(
        BlastDatabase,
        on_delete=models.PROTECT,
        related_name="blast_jobs",
    )

    program = models.CharField(
        max_length=20,
        choices=PROGRAM_CHOICES,
        default=PROGRAM_BLASTN,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    max_target_seqs = models.PositiveIntegerField(default=25)
    evalue = models.CharField(max_length=50, default="10")

    query_fasta = models.TextField(blank=True)
    result_json = models.JSONField(default=dict, blank=True)
    hits_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blast_jobs",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-updated_at"]

    def __str__(self):
        return f"{self.name} ({self.status})"


class BlastHit(models.Model):
    job = models.ForeignKey(
        BlastJob,
        on_delete=models.CASCADE,
        related_name="hits",
    )

    rank = models.PositiveIntegerField(default=0)

    hit_id = models.CharField(max_length=500, blank=True)
    hit_def = models.TextField(blank=True)
    accession = models.CharField(max_length=255, blank=True)
    hit_length = models.PositiveIntegerField(default=0)

    bit_score = models.FloatField(null=True, blank=True)
    evalue = models.FloatField(null=True, blank=True)
    identity_percent = models.FloatField(null=True, blank=True)
    alignment_length = models.PositiveIntegerField(default=0)

    query_from = models.PositiveIntegerField(null=True, blank=True)
    query_to = models.PositiveIntegerField(null=True, blank=True)
    hit_from = models.PositiveIntegerField(null=True, blank=True)
    hit_to = models.PositiveIntegerField(null=True, blank=True)

    query_aligned = models.TextField(blank=True)
    hit_aligned = models.TextField(blank=True)
    midline = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["rank", "id"]

    def __str__(self):
        return f"{self.job_id} - {self.hit_id or self.accession}"
