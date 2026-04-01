from rest_framework.viewsets import ModelViewSet
from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite
from .models import Project, ProjectPost
from .serializers import ProjectSerializer, ProjectPostSerializer
from events.models import Event

class ProjectViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = ProjectSerializer
    queryset = Project.objects.all().order_by("members","samples").all().order_by("name")
class ProjectPostViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = ProjectPostSerializer

    def get_queryset(self):
        queryset = ProjectPost.objects.select_related("author", "project").all().order_by("-created_at")
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
