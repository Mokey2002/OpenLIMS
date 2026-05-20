from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite
from events.models import Event

from .models import Sequence
from .serializers import SequenceSerializer


class SequenceViewSet(viewsets.ModelViewSet):
    serializer_class = SequenceSerializer
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]

    def get_queryset(self):
        queryset = (
            Sequence.objects
            .select_related("project", "sample", "created_by")
            .prefetch_related("features")
            .all()
        )

        project_id = self.request.query_params.get("project")
        sample_id = self.request.query_params.get("sample")

        if project_id:
            queryset = queryset.filter(project_id=project_id)

        if sample_id:
            queryset = queryset.filter(sample_id=sample_id)

        return queryset

    def perform_create(self, serializer):
        sequence_record = serializer.save()

        self._create_sequence_event(
            sequence_record=sequence_record,
            action="SEQUENCE_WORKSPACE_CREATED",
        )

    def perform_update(self, serializer):
        sequence_record = serializer.save()

        self._create_sequence_event(
            sequence_record=sequence_record,
            action="SEQUENCE_WORKSPACE_UPDATED",
        )

    def perform_destroy(self, instance):
        sequence_id = instance.id
        sequence_name = instance.name
        project_id = instance.project_id
        sample_id = instance.sample_id
        features_count = instance.features.count()

        actor = None
        if self.request.user and self.request.user.is_authenticated:
            actor = self.request.user

        instance.delete()

        Event.objects.create(
            entity_type="Sequence",
            entity_id=str(sequence_id),
            action="SEQUENCE_WORKSPACE_DELETED",
            actor=actor,
            payload={
                "sequence_id": sequence_id,
                "name": sequence_name,
                "project_id": project_id,
                "sample_id": sample_id,
                "features_count": features_count,
            },
        )

    @action(detail=True, methods=["get"], url_path="workspace")
    def workspace(self, request, pk=None):
        sequence_record = self.get_object()
        serializer = self.get_serializer(sequence_record)

        data = serializer.data
        features = data.get("features", [])

        data["annotations"] = [
            self._to_seqviz_feature(feature)
            for feature in features
            if feature["feature_type"] == "ANNOTATION"
        ]

        data["primers"] = [
            self._to_seqviz_feature(feature)
            for feature in features
            if feature["feature_type"] == "PRIMER"
        ]

        data["translations"] = [
            self._to_seqviz_feature(feature)
            for feature in features
            if feature["feature_type"] == "TRANSLATION"
        ]

        data["highlights"] = [
            self._to_seqviz_feature(feature)
            for feature in features
            if feature["feature_type"] == "HIGHLIGHT"
        ]

        return Response(data)

    def _to_seqviz_feature(self, feature):
        return {
            "id": feature["id"],
            "name": feature.get("name") or "",
            "start": feature["start"],
            "end": feature["end"],
            "direction": feature["direction"],
            "color": feature["color"],
            **(feature.get("metadata") or {}),
        }

    def _create_sequence_event(self, sequence_record, action):
        actor = None

        if self.request.user and self.request.user.is_authenticated:
            actor = self.request.user

        Event.objects.create(
            entity_type="Sequence",
            entity_id=str(sequence_record.id),
            action=action,
            actor=actor,
            payload={
                "sequence_id": sequence_record.id,
                "name": sequence_record.name,
                "sequence_type": sequence_record.sequence_type,
                "sequence_length": len(sequence_record.sequence or ""),
                "project_id": sequence_record.project_id,
                "sample_id": sequence_record.sample_id,
                "features_count": sequence_record.features.count(),
            },
        )