"""Match account/confirmation lock order before publishing owner notifications."""
from contextlib import contextmanager

from django.contrib.auth import get_user_model
from django.db import transaction
from .models import AssistantAction


@contextmanager
def locked_action(lookup):
    with transaction.atomic():
        owner_id = AssistantAction.objects.filter(**lookup).values_list("requested_by_id", flat=True).first()
        if owner_id is None:
            yield None
            return
        # A non-key lock serializes account changes while allowing normal
        # scientific records to keep referencing their original author.
        owner = get_user_model().objects.select_for_update(no_key=True).filter(pk=owner_id).first()
        action = (AssistantAction.objects.select_for_update(of=("self",)).select_related("requested_by")
                  .filter(**lookup).first()) if owner else None
        yield action
