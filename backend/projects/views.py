from rest_framework.viewsets import ModelViewSet
from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite
from .models import Project, ProjectPost
from .serializers import ProjectSerializer, ProjectPostSerializer
from events.models import Event
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import SAFE_METHODS
from core.permissions import IsAdminOnly
from .models import Project, ProjectPost
from core.permissions import IsAuthenticatedProjectReadAdminWrite, IsAuthenticatedReadOnlyOrTechAdminWrite

class ProjectViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedProjectReadAdminWrite]
    serializer_class = ProjectSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = Project.objects.prefetch_related("members", "samples").all().order_by("name")

        if user.is_superuser or user.groups.filter(name="admin").exists():
            return queryset

        return queryset.filter(members=user)

class ProjectPostViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = ProjectPostSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = ProjectPost.objects.select_related("author", "project").all().order_by("-created_at")

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
