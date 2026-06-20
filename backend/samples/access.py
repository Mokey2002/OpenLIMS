from django.db.models import Q
from rest_framework.exceptions import ValidationError

from core.permissions import is_admin, is_tech


def get_sample_access_queryset(queryset, user):
    """
    Project-scoped sample visibility.

    Admin:
      - all samples, including unassigned

    Tech:
      - samples in assigned projects
      - unassigned samples created by that tech

    Viewer:
      - samples in assigned projects only
      - no unassigned samples
    """
    if not user or not user.is_authenticated:
        return queryset.none()

    if is_admin(user):
        return queryset

    if is_tech(user):
        return queryset.filter(
            Q(project__members=user)
            | Q(project__isnull=True, created_by=user)
        ).distinct()

    return queryset.filter(project__members=user).distinct()


def user_can_access_sample(user, sample):
    if not user or not user.is_authenticated:
        return False

    if is_admin(user):
        return True

    if sample.project_id:
        return sample.project.members.filter(id=user.id).exists()

    return is_tech(user) and sample.created_by_id == user.id


def validate_sample_project_assignment(user, project):
    """
    Non-admin users can only create/assign samples to projects
    where they are members.

    Non-admin techs can create unassigned samples.
    Viewers are blocked by DRF permission classes before this.
    """
    if is_admin(user):
        return

    if project is None:
        return

    if not project.members.filter(id=user.id).exists():
        raise ValidationError({
            "project": (
                "You can only create or assign samples to projects where "
                "you are a project member."
            )
        })


def validate_unassign_project(user, sample):
    """
    Admin can unassign any sample.
    Tech can unassign only samples they originally created.
    """
    if is_admin(user):
        return

    if is_tech(user) and sample.created_by_id == user.id:
        return

    raise ValidationError({
        "project": (
            "Only admins can unassign this sample from a project. "
            "Tech users can only unassign samples they created."
        )
    })
