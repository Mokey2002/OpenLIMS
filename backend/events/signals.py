from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.forms.models import model_to_dict

from .models import Event
from samples.models import Sample
from inventory.models import Container, Location


def snapshot(instance):
    """
    Convert model instance -> dict for audit payload.
    FK fields become their id (e.g., container: 3).
    """
    return model_to_dict(instance)


def write_event(instance, action):
    Event.objects.create(
        entity_type=instance.__class__.__name__,
        entity_id=str(instance.pk),
        action=action,
        payload=snapshot(instance),
    )


@receiver(post_save, sender=Sample)
def sample_saved(sender, instance, created, **kwargs):
    write_event(instance, "CREATED" if created else "UPDATED")


@receiver(post_delete, sender=Sample)
def sample_deleted(sender, instance, **kwargs):
    write_event(instance, "DELETED")


@receiver(post_save, sender=Container)
def container_saved(sender, instance, created, **kwargs):
    write_event(instance, "CREATED" if created else "UPDATED")


@receiver(post_delete, sender=Container)
def container_deleted(sender, instance, **kwargs):
    write_event(instance, "DELETED")


@receiver(post_save, sender=Location)
def location_saved(sender, instance, created, **kwargs):
    write_event(instance, "CREATED" if created else "UPDATED")


@receiver(post_delete, sender=Location)
def location_deleted(sender, instance, **kwargs):
    write_event(instance, "DELETED")
