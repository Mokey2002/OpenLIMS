"""Keep an active administrator through supported account-management paths."""
from contextlib import contextmanager

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import APIException, PermissionDenied

from .models import UserAdministrationLock
from .permissions import is_admin


LAST_ADMIN_MESSAGE = (
    "Keep at least one active administrator. Create or activate another "
    "administrator before removing this access."
)


class LastAdministratorError(ValidationError):
    def __init__(self):
        super().__init__(LAST_ADMIN_MESSAGE, code="last_active_administrator")


class LastAdministratorConflict(APIException):
    status_code = 409
    default_code = "last_active_administrator"

    def __init__(self):
        super().__init__({"detail": LAST_ADMIN_MESSAGE, "code": "last_active_administrator"})


@contextmanager
def user_administration():
    # Locking only the target or counting before a write lets two administrators
    # remove each other concurrently. This stable row also covers group edits.
    with transaction.atomic():
        UserAdministrationLock.objects.select_for_update().get_or_create(pk=1)
        yield


def active_administrators():
    return get_user_model().objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(groups__name="admin")
    ).distinct()


def last_administrator_id():
    ids = list(active_administrators().order_by("pk").values_list("pk", flat=True)[:2])
    return ids[0] if len(ids) == 1 else None


def lock_users(actor, targets=()):
    # Match the ascending User lock order used by access-request reviews.
    ids = {actor.pk}
    ids.update(target.pk for target in targets)
    return {user.pk: user for user in get_user_model().objects.select_for_update().filter(
        pk__in=ids
    ).order_by("pk")}


def lock_api_administrator(actor, target):
    users = lock_users(actor, [target])
    current = users.get(actor.pk)
    if not current or not current.is_active or not is_admin(current):
        raise PermissionDenied("Your administrator access changed. Refresh the page and sign in again if needed.")
    return current


def protect_user_deletion(ids):
    administrators = active_administrators()
    if administrators.filter(pk__in=ids).exists() and not administrators.exclude(pk__in=ids).exists():
        raise LastAdministratorError()


def protect_user_state(user, *, active, administrator):
    if not (active and administrator):
        protect_user_deletion([user.pk])


def protect_api_update(user, changes):
    role = changes.get("role")
    protect_user_state(
        user, active=changes.get("is_active", user.is_active),
        administrator=(role == "admin") if role is not None else is_admin(user),
    )


def protect_admin_group_removal():
    administrators = active_administrators()
    if administrators.exists() and not administrators.filter(is_superuser=True).exists():
        raise LastAdministratorError()
