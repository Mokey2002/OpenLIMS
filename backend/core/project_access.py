from django.core.exceptions import PermissionDenied
from django.db.models import Q

from core.permissions import is_admin, is_tech


def get_project_access_queryset(
    queryset,
    user,
    *,
    project_lookup="project",
    owner_lookup=None,
):
    """Return project-scoped records visible to a user.

    New modules should use this helper so project membership and optional
    ownership behave consistently. Existing imports continue through
    ``projects.access`` for compatibility.
    """
    if not user or not user.is_authenticated:
        return queryset.none()

    if is_admin(user):
        return queryset

    access_filter = Q(**{f"{project_lookup}__members": user})

    if owner_lookup and is_tech(user):
        access_filter |= Q(
            **{
                f"{project_lookup}__isnull": True,
                owner_lookup: user,
            }
        )

    return queryset.filter(access_filter).distinct()


def user_can_access_project(user, project, *, write=False):
    if not user or not user.is_authenticated or project is None:
        return False
    if is_admin(user):
        return True
    if write and not is_tech(user):
        return False
    return project.members.filter(pk=user.pk).exists()


def require_project_access(user, project, *, write=False):
    if not user_can_access_project(user, project, write=write):
        raise PermissionDenied("You do not have access to this project.")
    return project
