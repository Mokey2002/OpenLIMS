from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=128, unique=True)
    code = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.code} - {self.name}"
