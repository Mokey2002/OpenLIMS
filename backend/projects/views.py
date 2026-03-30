from rest_framework.viewsets import ModelViewSet
from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite
from .models import Project
from .serializers import ProjectSerializer


class ProjectViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = ProjectSerializer
    queryset = Project.objects.all().order_by("name")
