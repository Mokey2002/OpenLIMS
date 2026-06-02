from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite
from events.models import Event

from .models import WorkItem, Result, SampleAttachment
from .serializers import (
    WorkItemQCReviewSerializer,
    WorkItemSerializer,
    ResultSerializer,
    SampleAttachmentSerializer,
)


class WorkItemViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = WorkItemSerializer

    def get_queryset(self):
        queryset = (
            WorkItem.objects
            .select_related("sample", "reviewed_by")
            .prefetch_related("results")
            .all()
            .order_by("-created_at")
        )

        sample_id = self.request.query_params.get("sample")
        qc_status = self.request.query_params.get("qc_status")

        if sample_id:
            queryset = queryset.filter(sample_id=sample_id)

        if qc_status:
            queryset = queryset.filter(qc_status=qc_status)

        return queryset

    @action(detail=True, methods=["post"], url_path="qc-review")
    def qc_review(self, request, pk=None):
        work_item = self.get_object()

        serializer = WorkItemQCReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_qc_status = serializer.validated_data["qc_status"]
        review_note = serializer.validated_data.get("review_note", "")

        before = {
            "qc_status": work_item.qc_status,
            "review_note": work_item.review_note,
            "reviewed_by": work_item.reviewed_by.username if work_item.reviewed_by else None,
            "reviewed_at": work_item.reviewed_at.isoformat() if work_item.reviewed_at else None,
        }

        work_item.qc_status = new_qc_status
        work_item.review_note = review_note
        work_item.reviewed_by = request.user
        work_item.reviewed_at = timezone.now()
        work_item.save(
            update_fields=[
                "qc_status",
                "review_note",
                "reviewed_by",
                "reviewed_at",
            ]
        )

        after = {
            "qc_status": work_item.qc_status,
            "review_note": work_item.review_note,
            "reviewed_by": request.user.username,
            "reviewed_at": work_item.reviewed_at.isoformat() if work_item.reviewed_at else None,
        }

        action_name = "QC_REVIEW_UPDATED"

        if new_qc_status == WorkItem.QC_APPROVED:
            action_name = "QC_APPROVED"
        elif new_qc_status == WorkItem.QC_REJECTED:
            action_name = "QC_REJECTED"
        elif new_qc_status == WorkItem.QC_RERUN_REQUIRED:
            action_name = "QC_RERUN_REQUIRED"
        elif new_qc_status == WorkItem.QC_PENDING_REVIEW:
            action_name = "QC_PENDING_REVIEW"

        Event.objects.create(
            entity_type="WorkItem",
            entity_id=str(work_item.id),
            action=action_name,
            actor=request.user if request.user.is_authenticated else None,
            payload={
                "work_item_id": work_item.id,
                "work_item_name": work_item.name,
                "sample_id": work_item.sample_id,
                "sample_code": work_item.sample.sample_id if work_item.sample else None,
                "before": before,
                "after": after,
                "changed_fields": ["qc_status", "review_note", "reviewed_by", "reviewed_at"],
            },
        )

        Event.objects.create(
            entity_type="Sample",
            entity_id=str(work_item.sample_id),
            action=action_name,
            actor=request.user if request.user.is_authenticated else None,
            payload={
                "work_item_id": work_item.id,
                "work_item_name": work_item.name,
                "sample_id": work_item.sample_id,
                "sample_code": work_item.sample.sample_id if work_item.sample else None,
                "qc_status": new_qc_status,
                "review_note": review_note,
            },
        )

        output_serializer = self.get_serializer(work_item)
        return Response(output_serializer.data, status=status.HTTP_200_OK)


class ResultViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = ResultSerializer

    def get_queryset(self):
        queryset = Result.objects.all().order_by("-created_at")
        work_item_id = self.request.query_params.get("work_item")

        if work_item_id:
            queryset = queryset.filter(work_item_id=work_item_id)

        return queryset


class SampleAttachmentViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = SampleAttachmentSerializer

    def get_queryset(self):
        queryset = SampleAttachment.objects.all().order_by("-uploaded_at")
        sample_id = self.request.query_params.get("sample")

        if sample_id:
            queryset = queryset.filter(sample_id=sample_id)

        return queryset