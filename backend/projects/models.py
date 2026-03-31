from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Project(models.Model):
    name = models.CharField(max_length=128, unique=True)
    code = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True)
    members = models.ManyToManyField(
        User,
        blank=True,
        related_name="projects",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.code} - {self.name}"
