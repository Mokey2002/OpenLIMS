from django.db.models import Q
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.permissions import is_admin, is_tech


def get_sample_access_queryset(queryset, user):
    """
    Admin:
      - all samples

    Tech:
      - samples in assigned primary projects
      - samples linked to assigned projects
      - unassigned samples created by that tech

    Viewer:
      - samples in assigned primary projects
      - samples linked to assigned projects
      - no unassigned samples
    """
    if not user or not user.is_authenticated:
        return queryset.none()

    if is_admin(user):
        return queryset

    if is_tech(user):
        return queryset.filter(
            Q(project__members=user)
            | Q(linked_projects__members=user)
            | Q(project__isnull=True, created_by=user)
        ).distinct()

    return queryset.filter(
        Q(project__members=user)
        | Q(linked_projects__members=user)
    ).distinct()


def user_can_access_sample(user, sample):
    if not user or not user.is_authenticated:
        return False

    if is_admin(user):
        return True

    if sample.project_id and sample.project.members.filter(id=user.id).exists():
        return True

    if sample.linked_projects.filter(members=user).exists():
        return True

    return is_tech(user) and sample.project_id is None and sample.created_by_id == user.id


def user_can_modify_sample(user, sample):
    """
    Linked-project membership gives visibility, not edit ownership.
    """
    if not user or not user.is_authenticated:
        return False

    if is_admin(user):
        return True

    if not is_tech(user):
        return False

    if sample.project_id:
        return sample.project.members.filter(id=user.id).exists()

    return sample.created_by_id == user.id


def require_sample_modify_access(user, sample):
    if not user_can_modify_sample(user, sample):
        raise PermissionDenied(
            "You can view this sample, but you do not have permission to modify it."
        )


def validate_sample_project_assignment(user, project):
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


def validate_linked_projects_for_user(user, projects):
    if is_admin(user):
        return

    for project in projects:
        if not project.members.filter(id=user.id).exists():
            raise ValidationError({
                "linked_projects": (
                    "You can only link samples to projects where "
                    "you are a project member."
                )
            })


def validate_unassign_project(user, sample):
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
