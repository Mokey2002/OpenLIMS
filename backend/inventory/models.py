from django.db import models

class Location(models.Model):
    name = models.CharField(max_length=128)
    kind = models.CharField(max_length=64)  # freezer, rack, shelf, etc.

    def __str__(self):
        return f"{self.name} ({self.kind})"


class Container(models.Model):
    container_id = models.CharField(max_length=64, unique=True)
    kind = models.CharField(max_length=64)  # tube, plate, box
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="containers",
    )

    def __str__(self):
        return self.container_id
