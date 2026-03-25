from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Event(models.Model):
    entity_type = models.CharField(max_length=64)
    entity_id = models.CharField(max_length=64)
    action = models.CharField(max_length=32)
    timestamp = models.DateTimeField(auto_now_add=True)
    payload = models.JSONField(default=dict)

    actor = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )

    def __str__(self):
        return f"{self.entity_type} {self.action}"
