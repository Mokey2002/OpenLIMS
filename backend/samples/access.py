from django.db.models import Q
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.permissions import is_admin, is_tech


def get_sample_access_queryset(queryset, user, *, for_write=False):
    """
    All accounts see samples in their primary or linked projects, and samples
    with neither a primary nor any linked project. Creating or being assigned a
    sample does not bypass project visibility. Write permissions are separate.
    for_write preserves the previous work/result/attachment operation scope;
    seeing another person's unassigned sample does not permit changing its work.
    """
    if not user or not user.is_authenticated or not user.is_active:
        return queryset.none()

    access = Q(project__members=user) | Q(linked_projects__members=user)
    unassigned = Q(project__isnull=True, linked_projects__isnull=True)
    if not for_write or is_admin(user):
        access |= unassigned
    elif is_tech(user):
        access |= unassigned & Q(created_by=user)
    return queryset.filter(access).distinct()


def user_can_access_sample(user, sample, *, for_write=False):
    if not user or not user.is_authenticated or not sample.pk:
        return False
    from .models import Sample
    return get_sample_access_queryset(Sample.objects.filter(pk=sample.pk), user, for_write=for_write).exists()


def user_can_modify_sample(user, sample):
    """
    Linked-project membership gives visibility, not edit ownership.
    """
    if not user_can_access_sample(user, sample):
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


def with_sample_modify_permission(queryset, user):
    """Compute display permissions in SQL for a whole page, scoped to this user.

    Mutation authorization still uses require_sample_modify_access on fresh records.
    """
    from django.db.models import BooleanField, Case, Exists, IntegerField, OuterRef, Value, When
    from projects.models import Project

    if not user or not user.is_authenticated:
        permission = Value(False, output_field=BooleanField())
    elif is_admin(user):
        permission = Value(True, output_field=BooleanField())
    elif not is_tech(user):
        permission = Value(False, output_field=BooleanField())
    else:
        membership = Project.members.through.objects.filter(project_id=OuterRef("project_id"), user_id=user.pk)
        permission = Case(
            When(project__isnull=True, created_by_id=user.pk, then=Value(True)),
            default=Exists(membership), output_field=BooleanField(),
        )
    return queryset.annotate(_display_can_modify=permission, _display_permission_user=Value(user.pk if user else None, output_field=IntegerField()))
