from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite, is_qc_reviewer
from events.models import Event
from samples.access import get_sample_access_queryset
from samples.models import Sample
from settings_app.models import SystemSettings

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

    def get_permissions(self):
        if self.action == "qc_review":
            return [IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        queryset = (
            WorkItem.objects
            .select_related("sample", "sample__project", "reviewed_by")
            .prefetch_related("results")
            .all()
            .order_by("-created_at")
        )

        sample_id = self.request.query_params.get("sample")
        project_id = self.request.query_params.get("project")
        qc_status = self.request.query_params.get("qc_status")

        if sample_id:
            queryset = queryset.filter(sample_id=sample_id)

        if project_id:
            queryset = queryset.filter(sample__project_id=project_id)

        if qc_status:
            queryset = queryset.filter(qc_status=qc_status)

        allowed_samples = get_sample_access_queryset(
            Sample.objects.all(),
            self.request.user,
        )

        return queryset.filter(sample__in=allowed_samples)

    def perform_update(self, serializer):
        if "qc_status" in self.request.data:
            work_item = self.get_object()
            Event.objects.create(
                entity_type="WorkItem",
                entity_id=str(work_item.id),
                action="QC_AUTHORIZATION_DENIED",
                actor=self.request.user,
                payload={
                    "requested_status": self.request.data.get("qc_status"),
                    "reason": "QC state changes require the audited QC review endpoint.",
                },
            )
            raise PermissionDenied(
                "QC status can only be changed through the audited QC review workflow."
            )
        serializer.save()

    @action(detail=True, methods=["post"], url_path="qc-review")
    def qc_review(self, request, pk=None):
        work_item = self.get_object()

        if not is_qc_reviewer(request.user):
            Event.objects.create(
                entity_type="WorkItem",
                entity_id=str(work_item.id),
                action="QC_AUTHORIZATION_DENIED",
                actor=request.user,
                payload={
                    "requested_status": request.data.get("qc_status"),
                    "reason": "QC reviewer role is required.",
                },
            )
            raise PermissionDenied("Only QC reviewers or admins can review QC.")

        serializer = WorkItemQCReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_qc_status = serializer.validated_data["qc_status"]
        review_note = serializer.validated_data.get("review_note", "")
        if not review_note.strip():
            raise serializers.ValidationError(
                {"review_note": "An explicit QC reason or comment is required."}
            )
        if (
            new_qc_status == WorkItem.QC_APPROVED
            and SystemSettings.load().qc_separation_of_duties
            and work_item.results.filter(entered_by=request.user).exists()
        ):
            Event.objects.create(
                entity_type="WorkItem",
                entity_id=str(work_item.id),
                action="QC_AUTHORIZATION_DENIED",
                actor=request.user,
                payload={
                    "requested_status": new_qc_status,
                    "reason": "Separation of duties prevents self-approval.",
                },
            )
            raise PermissionDenied(
                "Separation of duties prevents the result entrant from approving it."
            )

        before = {
            "qc_status": work_item.qc_status,
            "review_note": work_item.review_note,
            "reviewed_by": (
                work_item.reviewed_by.username
                if work_item.reviewed_by
                else None
            ),
            "reviewed_at": (
                work_item.reviewed_at.isoformat()
                if work_item.reviewed_at
                else None
            ),
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
            "reviewed_at": (
                work_item.reviewed_at.isoformat()
                if work_item.reviewed_at
                else None
            ),
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
                "sample_code": (
                    work_item.sample.sample_id if work_item.sample else None
                ),
                "project_id": (
                    work_item.sample.project_id
                    if work_item.sample
                    else None
                ),
                "before": before,
                "after": after,
                "changed_fields": [
                    "qc_status",
                    "review_note",
                    "reviewed_by",
                    "reviewed_at",
                ],
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
                "sample_code": (
                    work_item.sample.sample_id if work_item.sample else None
                ),
                "project_id": (
                    work_item.sample.project_id
                    if work_item.sample
                    else None
                ),
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
        queryset = (
            Result.objects
            .select_related(
                "work_item",
                "work_item__sample",
                "entered_by",
                "qc_assigned_to",
                "qc_reviewed_by",
            )
            .all()
            .order_by("-created_at")
        )

        work_item_id = self.request.query_params.get("work_item")
        sample_id = self.request.query_params.get("sample")
        project_id = self.request.query_params.get("project")

        if work_item_id:
            queryset = queryset.filter(work_item_id=work_item_id)

        if sample_id:
            queryset = queryset.filter(work_item__sample_id=sample_id)

        if project_id:
            queryset = queryset.filter(work_item__sample__project_id=project_id)

        allowed_samples = get_sample_access_queryset(
            Sample.objects.all(),
            self.request.user,
        )

        return queryset.filter(work_item__sample__in=allowed_samples)

    def perform_create(self, serializer):
        serializer.save(entered_by=self.request.user)

    def perform_update(self, serializer):
        result = self.get_object()
        protected_fields = {
            "value_type",
            "value_string",
            "value_number",
            "value_boolean",
            "unit",
            "reference_min",
            "reference_max",
            "qc_rule",
            "qc_passed",
            "qc_failure_reason",
        }
        if result.qc_status == Result.QC_APPROVED:
            attempted = protected_fields.intersection(serializer.validated_data)
            if attempted:
                raise serializers.ValidationError(
                    "Approved results must be explicitly reopened before they change."
                )
        serializer.save()


class SampleAttachmentViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = SampleAttachmentSerializer

    def get_queryset(self):
        queryset = (
            SampleAttachment.objects
            .select_related("sample")
            .all()
            .order_by("-uploaded_at")
        )

        sample_id = self.request.query_params.get("sample")
        project_id = self.request.query_params.get("project")

        if sample_id:
            queryset = queryset.filter(sample_id=sample_id)

        if project_id:
            queryset = queryset.filter(sample__project_id=project_id)

        allowed_samples = get_sample_access_queryset(
            Sample.objects.all(),
            self.request.user,
        )

        return queryset.filter(sample__in=allowed_samples)
