from rest_framework.viewsets import ModelViewSet
from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite
from .models import WorkItem, Result
from .serializers import WorkItemSerializer, ResultSerializer


class WorkItemViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = WorkItemSerializer

    def get_queryset(self):
        queryset = WorkItem.objects.all().order_by("-created_at")
        sample_id = self.request.query_params.get("sample")
        if sample_id:
            queryset = queryset.filter(sample_id=sample_id)
        return queryset


class ResultViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = ResultSerializer

    def get_queryset(self):
        queryset = Result.objects.all().order_by("-created_at")
        work_item_id = self.request.query_params.get("work_item")
        if work_item_id:
            queryset = queryset.filter(work_item_id=work_item_id)
        return queryset
