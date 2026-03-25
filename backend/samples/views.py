from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Sample
from .serializers import SampleSerializer
from .workflows_serializers import SampleTransitionSerializer
from .workflows import get_allowed_transitions

from custom_fields.models import FieldValue
from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite
from events.models import Event


class SampleViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    queryset = Sample.objects.all().order_by("-created_at")
    serializer_class = SampleSerializer

    @action(detail=True, methods=["get"], url_path="custom-fields")
    def custom_fields(self, request, pk=None):
        sample = self.get_object()

        values = (
            FieldValue.objects
            .select_related("field_definition")
            .filter(entity_type="Sample", entity_id=str(sample.id))
            .order_by("field_definition__name")
        )

        resolved = {}
        meta = []

        for fv in values:
            fd = fv.field_definition
            resolved[fd.name] = fv.value
            meta.append({
                "name": fd.name,
                "label": fd.label or fd.name,
                "data_type": fd.data_type,
                "required": fd.required,
                "rules": fd.rules or {},
                "value": fv.value,
            })

        return Response({
            "sample_id": sample.id,
            "fields": resolved,
            "fields_meta": meta,
        })

    @action(detail=True, methods=["get"], url_path="allowed-transitions")
    def allowed_transitions(self, request, pk=None):
        sample = self.get_object()
        return Response({
            "sample_id": sample.id,
            "current_status": sample.status,
            "allowed_transitions": get_allowed_transitions(sample.status),
        })

    @action(detail=True, methods=["post"], url_path="transition")
    def transition(self, request, pk=None):
        sample = self.get_object()

        serializer = SampleTransitionSerializer(
            data=request.data,
            context={"sample": sample},
        )
        serializer.is_valid(raise_exception=True)

        old_status = sample.status
        new_status = serializer.validated_data["new_status"]

        sample.status = new_status
        sample.save()

        Event.objects.create(
            entity_type="Sample",
            entity_id=str(sample.id),
            action="STATUS_CHANGED",
	    actor=request.user,
            payload={
                "sample_id": sample.id,
                "sample_code": sample.sample_id,
                "old_status": old_status,
                "new_status": new_status,
            },
        )

        return Response({
            "id": sample.id,
            "sample_id": sample.sample_id,
            "old_status": old_status,
            "new_status": new_status,
        })
