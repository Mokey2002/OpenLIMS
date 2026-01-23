from django.db import models

class Event(models.Model):
    entity_type = models.CharField(max_length=64)
    entity_id = models.CharField(max_length=64)
    action = models.CharField(max_length=32)  # CREATED, UPDATED, DELETED
    timestamp = models.DateTimeField(auto_now_add=True)
    payload = models.JSONField(default=dict)

    def __str__(self):
        return f"{self.entity_type} {self.action}"
