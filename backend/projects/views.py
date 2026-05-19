from rest_framework.viewsets import ModelViewSet

from core.permissions import (
    IsAuthenticatedProjectReadAdminWrite,
    IsAuthenticatedReadOnlyOrTechAdminWrite,
)
from events.models import Event
from notifications.models import Notification

from .models import Project, ProjectPost
from .serializers import ProjectSerializer, ProjectPostSerializer


class ProjectViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedProjectReadAdminWrite]
    serializer_class = ProjectSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = (
            Project.objects
            .prefetch_related("members", "samples")
            .all()
            .order_by("name")
        )

        if user.is_superuser or user.groups.filter(name="admin").exists():
            return queryset

        return queryset.filter(members=user)


class ProjectPostViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = ProjectPostSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = (
            ProjectPost.objects
            .select_related("author", "project")
            .all()
            .order_by("-created_at")
        )

        if not (user.is_superuser or user.groups.filter(name="admin").exists()):
            queryset = queryset.filter(project__members=user)

        project_id = self.request.query_params.get("project")
        if project_id:
            queryset = queryset.filter(project_id=project_id)

        return queryset

    def perform_create(self, serializer):
        post = serializer.save(author=self.request.user)

        Event.objects.create(
            entity_type="Project",
            entity_id=str(post.project.id),
            action="PROJECT_POSTED",
            actor=self.request.user,
            payload={
                "project_id": post.project.id,
                "project_code": post.project.code,
                "note": post.note,
                "has_image": bool(post.image),
            },
        )

        members = post.project.members.exclude(id=self.request.user.id)
        for member in members:
            Notification.objects.create(
                user=member,
                title="New project post",
                message=f"{self.request.user.username} posted in {post.project.code}",
                link=f"/projects/{post.project.id}",
            )
