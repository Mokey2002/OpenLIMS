from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite

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