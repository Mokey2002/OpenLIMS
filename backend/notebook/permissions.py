from django.db.models import Q

from core.permissions import is_admin, is_qc_reviewer, is_tech

from .models import Notebook


def notebooks_for_user(user, action="read"):
    queryset = Notebook.objects.all()
    if not user or not user.is_authenticated:
        return queryset.none()
    if is_admin(user):
        return queryset

    project_member = Q(scope=Notebook.SCOPE_PROJECT, project__members=user)
    team_member = Q(scope=Notebook.SCOPE_TEAM, team_members=user)
    owner = Q(owner=user)
    explicit = {
        "read": Q(readers=user) | Q(editors=user) | Q(commenters=user) | Q(reviewers=user) | Q(lockers=user),
        "write": Q(editors=user),
        "comment": Q(commenters=user) | Q(editors=user),
        "review": Q(reviewers=user),
        "lock": Q(lockers=user),
    }[action]

    scope_access = Q(pk__in=[])
    if action in {"read", "comment"}:
        scope_access = project_member | team_member
    elif action == "write" and is_tech(user):
        scope_access = project_member | team_member
    elif action in {"review", "lock"} and is_qc_reviewer(user):
        scope_access = project_member | team_member

    return queryset.filter(owner | explicit | scope_access).distinct()


def user_can_notebook(user, notebook, action="read"):
    return notebooks_for_user(user, action).filter(pk=notebook.pk).exists()
