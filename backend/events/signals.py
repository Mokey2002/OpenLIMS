from django.db.models.signals import post_save
from django.dispatch import receiver
from django.forms.models import model_to_dict

from .models import Event
from samples.models import Sample


def snapshot(instance):
    return model_to_dict(instance)


def actor_from_instance(instance):
    actor = getattr(instance, "created_by", None)

    if actor and getattr(actor, "is_authenticated", False):
        return actor

    return None


@receiver(post_save, sender=Sample)
def sample_created(sender, instance, created, **kwargs):
    """
    Signals do not have request.user, so Sample.created_by is used for
    create audit actor. Updates/deletes are handled in the view layer.
    """
    if not created:
        return

    actor = actor_from_instance(instance)

    payload = snapshot(instance)
    payload.update({
        "sample_id": instance.id,
        "sample_code": instance.sample_id,
        "actor_id": actor.id if actor else None,
        "actor_username": actor.username if actor else None,
    })

    Event.objects.create(
        entity_type="Sample",
        entity_id=str(instance.pk),
        action="CREATED",
        actor=actor,
        payload=payload,
    )
