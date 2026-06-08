from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite

from .models import BlastDatabase, BlastJob
from .serializers import BlastDatabaseSerializer, BlastJobSerializer
from .tasks import build_blast_database_task, run_blast_job_task


class BlastDatabaseViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = BlastDatabaseSerializer

    def get_queryset(self):
        queryset = (
            BlastDatabase.objects
            .select_related("created_by")
            .all()
            .order_by("name")
        )

        database_type = self.request.query_params.get("database_type")
        status_value = self.request.query_params.get("status")

        if database_type:
            queryset = queryset.filter(database_type=database_type)

        if status_value:
            queryset = queryset.filter(status=status_value)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"], url_path="build")
    def build(self, request, pk=None):
        database = self.get_object()

        database.status = BlastDatabase.STATUS_BUILDING
        database.error_message = ""
        database.save(update_fields=["status", "error_message", "updated_at"])

        build_blast_database_task.delay(database.id)

        serializer = self.get_serializer(database)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)


class BlastJobViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = BlastJobSerializer

    def get_queryset(self):
        queryset = (
            BlastJob.objects
            .select_related(
                "project",
                "query_sequence",
                "database",
                "created_by",
            )
            .prefetch_related("hits")
            .all()
            .order_by("-created_at")
        )

        project_id = self.request.query_params.get("project")
        sequence_id = self.request.query_params.get("sequence")
        database_id = self.request.query_params.get("database")
        status_value = self.request.query_params.get("status")

        if project_id:
            queryset = queryset.filter(project_id=project_id)

        if sequence_id:
            queryset = queryset.filter(query_sequence_id=sequence_id)

        if database_id:
            queryset = queryset.filter(database_id=database_id)

        if status_value:
            queryset = queryset.filter(status=status_value)

        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        query_sequence = serializer.validated_data["query_sequence"]

        if serializer.validated_data.get("project") is None:
            serializer.validated_data["project"] = query_sequence.project

        job = BlastJob.objects.create(
            **serializer.validated_data,
            created_by=request.user if request.user.is_authenticated else None,
            status=BlastJob.STATUS_PENDING,
        )

        run_blast_job_task.delay(job.id)

        output_serializer = self.get_serializer(job)

        return Response(
            output_serializer.data,
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["get"], url_path="hits")
    def hits(self, request, pk=None):
        job = self.get_object()
        serializer = self.get_serializer(job)
        return Response(serializer.data)
