from django.db import models

class Sample(models.Model):
    sample_id = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=32, default="RECEIVED")

    # Cross-app relationship (samples -> inventory)
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
