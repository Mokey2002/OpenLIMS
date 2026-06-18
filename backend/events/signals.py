from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.forms.models import model_to_dict

from .models import Event
from samples.models import Sample


def snapshot(instance):
    """
    Convert model instance -> dict for audit payload.
    FK fields become their id.

    This signal file is intentionally minimal.
    Detailed user-driven changes should be audited in the view layer
    where request.user and reason-for-change are available.
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
def sample_created(sender, instance, created, **kwargs):
    """
    Keep generic Sample CREATED events for basic creation traceability.

    Do NOT write generic UPDATED events here.
    Updates should be written explicitly in samples/views.py so actor,
    before/after values, and reason-for-change are recorded correctly.
    """
    if created:
        write_event(instance, "CREATED")


@receiver(post_delete, sender=Sample)
def sample_deleted(sender, instance, **kwargs):
    write_event(instance, "DELETED")
