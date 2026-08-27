from django.db.models import Q

from core.permissions import is_admin, is_tech

from .models import WorkflowRequest


def workflow_requests_for_user(user):
    queryset = WorkflowRequest.objects.all()
    if not user or not user.is_authenticated:
        return queryset.none()
    if is_admin(user):
        return queryset
    return queryset.filter(Q(requester=user) | Q(project__members=user)).distinct()


def user_can_submit(user, project):
    return bool(user and user.is_authenticated and (is_admin(user) or project.members.filter(pk=user.pk).exists()))


def user_can_operate_request(user, request):
    return bool(
        user
        and user.is_authenticated
        and (is_admin(user) or (is_tech(user) and request.project.members.filter(pk=user.pk).exists()))
    )
