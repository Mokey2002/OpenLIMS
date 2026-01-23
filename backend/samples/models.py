from django.db import models

class Sample(models.Model):
    sample_id = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=32, default="RECEIVED")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.sample_id
