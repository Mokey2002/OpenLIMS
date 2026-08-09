from django.db.models import Q

from core.permissions import is_admin, is_tech


def get_project_access_queryset(
    queryset,
    user,
    *,
    project_lookup="project",
    owner_lookup=None,
):
    """Limit project-scoped records to projects visible to the user.

    Tech users may also see their own unassigned records when an owner lookup
    is supplied. Viewers and other authenticated users only see records for
    projects where they are members.
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
