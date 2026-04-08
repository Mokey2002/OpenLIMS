from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status

from .models import Sample
from .serializers import SampleSerializer
from .workflows_serializers import SampleTransitionSerializer
from .workflows import get_allowed_transitions

from custom_fields.models import FieldValue
from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite
from events.models import Event


class SampleViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = SampleSerializer

    def get_queryset(self):
        queryset = Sample.objects.select_related(
            "project",
            "container",
            "container__location",
        ).all().order_by("-created_at")

        search = self.request.query_params.get("search")
        status_filter = self.request.query_params.get("status")
        project = self.request.query_params.get("project")

        if search:
            queryset = queryset.filter(sample_id__icontains=search)

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        if project:
            queryset = queryset.filter(project_id=project)

        return queryset

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

    def partial_update(self, request, *args, **kwargs):
        sample = self.get_object()
        old_container_id = sample.container_id
        old_container_code = sample.container.container_id if sample.container else None

        response = super().partial_update(request, *args, **kwargs)

        sample.refresh_from_db()

        if old_container_id != sample.container_id:
            Event.objects.create(
                entity_type="Sample",
                entity_id=str(sample.id),
                action="CONTAINER_ASSIGNED",
                actor=request.user,
                payload={
                    "sample_id": sample.id,
                    "sample_code": sample.sample_id,
                    "old_container_id": old_container_id,
                    "old_container_code": old_container_code,
                    "new_container_id": sample.container_id,
                    "new_container_code": sample.container.container_id if sample.container else None,
                    "location_name": sample.container.location.name if sample.container and sample.container.location else None,
                },
            )

        return response

    @action(detail=False, methods=["post"], url_path="bulk-update")
    def bulk_update_samples(self, request):
        ids = request.data.get("ids", [])
        new_status = request.data.get("status", None)
        new_project = request.data.get("project", None)

        if not ids:
            return Response(
                {"detail": "No sample IDs provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_status is None and new_project is None:
            return Response(
                {"detail": "Nothing to update. Provide status and/or project."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        samples = Sample.objects.select_related("project").filter(id__in=ids)

        updated_count = 0
        skipped = []
        updated_ids = []

        for sample in samples:
            changed = False

            # workflow-aware status transition
            if new_status is not None:
                allowed = get_allowed_transitions(sample.status)
                if new_status in allowed:
                    old_status = sample.status
                    sample.status = new_status
                    changed = True

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
                            "bulk": True,
                        },
                    )
                elif sample.status != new_status:
                    skipped.append({
                        "id": sample.id,
                        "sample_id": sample.sample_id,
                        "reason": f"Invalid workflow transition from {sample.status} to {new_status}",
                    })

            # project assignment
            if new_project is not None and sample.project_id != new_project:
                old_project = sample.project.code if sample.project else None
                sample.project_id = new_project
                changed = True

                Event.objects.create(
                    entity_type="Sample",
                    entity_id=str(sample.id),
                    action="PROJECT_ASSIGNED",
                    actor=request.user,
                    payload={
                        "sample_id": sample.id,
                        "sample_code": sample.sample_id,
                        "old_project": old_project,
                        "new_project_id": new_project,
                        "bulk": True,
                    },
                )

            if changed:
                sample.save()
                updated_count += 1
                updated_ids.append(sample.id)

        return Response({
            "updated": updated_count,
            "updated_ids": updated_ids,
            "skipped": skipped,
        })
