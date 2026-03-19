from django.db import models


class Sample(models.Model):
    STATUS_RECEIVED = "RECEIVED"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_QC = "QC"
    STATUS_REPORTED = "REPORTED"
    STATUS_ARCHIVED = "ARCHIVED"

    STATUS_CHOICES = [
        (STATUS_RECEIVED, "Received"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_QC, "QC"),
        (STATUS_REPORTED, "Reported"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    sample_id = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_RECEIVED)

    container = models.ForeignKey(
        "inventory.Container",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="samples",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.sample_id
