from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite
from events.models import Event
from sequences.models import Sequence

from .models import AlignmentJob
from .serializers import AlignmentJobSerializer
from .tasks import run_alignment_job


class AlignmentJobViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = AlignmentJobSerializer

    def get_queryset(self):
        queryset = (
            AlignmentJob.objects
            .select_related("project", "created_by")
            .prefetch_related("sequences")
            .all()
            .order_by("-created_at")
        )

        project_id = self.request.query_params.get("project")
        status_value = self.request.query_params.get("status")

        if project_id:
            queryset = queryset.filter(project_id=project_id)

        if status_value:
            queryset = queryset.filter(status=status_value)

        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        sequence_ids = serializer.validated_data.pop("sequence_ids", [])

        sequences = list(
            Sequence.objects
            .select_related("sample", "project")
            .filter(id__in=sequence_ids)
            .order_by("id")
        )

        if serializer.validated_data.get("project") is None and sequences:
            project_ids = {
                sequence.project_id
                for sequence in sequences
                if sequence.project_id is not None
            }

            if len(project_ids) == 1:
                serializer.validated_data["project_id"] = list(project_ids)[0]

        actor = request.user if request.user.is_authenticated else None

        job = AlignmentJob.objects.create(
            **serializer.validated_data,
            created_by=actor,
            status="PENDING",
            input_fasta="",
            aligned_fasta="",
            summary={},
            error_message="",
        )

        job.sequences.set(sequences)

        Event.objects.create(
            entity_type="AlignmentJob",
            entity_id=str(job.id),
            action="ALIGNMENT_QUEUED",
            actor=actor,
            payload={
                "alignment_job_id": job.id,
                "name": job.name,
                "tool": job.tool,
                "project_id": job.project_id,
                "sequence_ids": [sequence.id for sequence in sequences],
            },
        )

        run_alignment_job.delay(job.id)

        output_serializer = self.get_serializer(job)
        headers = self.get_success_headers(output_serializer.data)

        return Response(
            output_serializer.data,
            status=status.HTTP_202_ACCEPTED,
            headers=headers,
        )

    @action(detail=True, methods=["get"], url_path="download-fasta")
    def download_fasta(self, request, pk=None):
        job = self.get_object()

        if not job.aligned_fasta:
            return Response(
                {"detail": "No aligned FASTA is available for this job."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "filename": f"alignment_{job.id}.fasta",
                "content": job.aligned_fasta,
            }
        )