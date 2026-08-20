from django.db.models.signals import post_save
from django.dispatch import receiver

from results.models import WorkItem

from .services import sync_pipeline_step_from_work_item


@receiver(post_save, sender=WorkItem)
def synchronize_pipeline_work_item(sender, instance, **kwargs):
    sync_pipeline_step_from_work_item(
        instance,
        actor=getattr(instance, "_pipeline_actor", None),
    )
