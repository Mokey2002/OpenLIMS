import csv

from django.utils import timezone
from django.http import HttpResponse
from django.db import transaction
from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError

from .models import (
    Sample,
    SampleBatch,
    SampleCustodyEvent,
    SampleRelationship,
    SingleSampleAttachment,
)
from .serializers import (
    CustodyScanSerializer,
    DerivedSampleCreateSerializer,
    SampleBatchSerializer,
    SampleCustodyEventSerializer,
    SampleRelationshipSerializer,
    SampleSerializer,
    SingleSampleAttachmentSerializer,
)
from .workflows import get_allowed_transitions
from .access import (
    get_sample_access_queryset,
    user_can_access_sample,
    require_sample_modify_access,
    validate_sample_project_assignment,
    validate_linked_projects_for_user,
    validate_unassign_project,
)

from custom_fields.models import FieldValue
from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite
from events.models import Event


REASON_MIN_LENGTH = 10


def sample_audit_state(sample):
    return {
        "sample_type": sample.sample_type,
        "status": sample.status,
        "project_id": sample.project_id,
        "container_id": sample.container_id,
        "batch_id": sample.batch_id,
        "assigned_to_id": sample.assigned_to_id,
    }


def get_change_reason(request):
    return (
        request.data.get("reason")
        or request.data.get("status_change_reason")
        or request.data.get("change_reason")
        or ""
    )


def validate_change_reason(reason):
    normalized = str(reason or "").strip()

    if len(normalized) < REASON_MIN_LENGTH:
        raise ValidationError({
            "reason": (
                "Reason for change is required for sample status changes "
                f"and must be at least {REASON_MIN_LENGTH} characters."
            )
        })

    return normalized


def validate_status_transition(current_status, new_status):
    allowed = get_allowed_transitions(current_status)

    if new_status == current_status:
        raise ValidationError({
            "detail": f"Sample is already in status {current_status}.",
            "current_status": current_status,
        })

    if new_status not in allowed:
        raise ValidationError({
            "detail": f"Invalid transition from {current_status} to {new_status}.",
            "current_status": current_status,
            "allowed_transitions": allowed,
        })


def create_sample_event(sample, action, actor, before, after, changed_fields, extra_payload=None):
    payload = {
        "sample_id": sample.id,
        "sample_code": sample.sample_id,
        "actor_id": actor.id if actor and actor.is_authenticated else None,
        "actor_username": actor.username if actor and actor.is_authenticated else None,
        "before": before,
        "after": after,
        "changed_fields": changed_fields,
    }

    if extra_payload:
        payload.update(extra_payload)

    Event.objects.create(
        entity_type="Sample",
        entity_id=str(sample.id),
        action=action,
        actor=actor if actor and actor.is_authenticated else None,
        payload=payload,
    )


class SampleViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = SampleSerializer

    def get_queryset(self):
        queryset = (
            Sample.objects
            .select_related(
                "project",
                "container",
                "container__location",
                "created_by",
                "batch",
                "assigned_to",
                "custodian",
            )
            .prefetch_related("linked_projects")
            .all()
            .order_by("-created_at")
        )

        search = self.request.query_params.get("search")
        status_filter = self.request.query_params.get("status")
        project = self.request.query_params.get("project")
        container = self.request.query_params.get("container")
        batch = self.request.query_params.get("batch")
        assigned_to = self.request.query_params.get("assigned_to")

        if search:
            queryset = queryset.filter(sample_id__icontains=search)

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        if project:
            queryset = queryset.filter(
                Q(project_id=project) |
                Q(linked_projects__id=project)
            ).distinct()

        if container:
            queryset = queryset.filter(container_id=container)

        if batch:
            queryset = queryset.filter(batch_id=batch)

        if assigned_to:
            if str(assigned_to).lower() in {"none", "null", "unassigned"}:
                queryset = queryset.filter(assigned_to__isnull=True)
            else:
                queryset = queryset.filter(assigned_to_id=assigned_to)

        return get_sample_access_queryset(queryset, self.request.user)

    @action(detail=True, methods=["post"], url_path="derive")
    def derive(self, request, pk=None):
        source = self.get_object()
        require_sample_modify_access(request.user, source)
        input_serializer = DerivedSampleCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        with transaction.atomic():
            child = Sample.objects.create(
                sample_id=data["sample_id"],
                sample_type=str(data.get("sample_type") or source.sample_type or "GENERAL").upper(),
                status=Sample.STATUS_RECEIVED,
                project=source.project,
                batch=source.batch,
                created_by=request.user,
            )
            child.linked_projects.set(source.linked_projects.all())
            relationship = SampleRelationship(
                source_sample=source,
                derived_sample=child,
                relationship_type=data["relationship_type"],
                quantity=data.get("quantity"),
                unit=str(data.get("unit") or "").strip(),
                reason=data["reason"],
                created_by=request.user,
            )
            relationship.full_clean()
            relationship.save()

            create_sample_event(
                sample=source,
                action="SAMPLE_DERIVED",
                actor=request.user,
                before={},
                after={"derived_sample_id": child.id},
                changed_fields=["lineage"],
                extra_payload={
                    "derived_sample_code": child.sample_id,
                    "relationship_type": relationship.relationship_type,
                    "quantity": str(relationship.quantity) if relationship.quantity is not None else None,
                    "unit": relationship.unit,
                    "reason": relationship.reason,
                },
            )
            create_sample_event(
                sample=child,
                action="SAMPLE_CREATED_FROM_SOURCE",
                actor=request.user,
                before={},
                after={"source_sample_id": source.id},
                changed_fields=["lineage"],
                extra_payload={
                    "source_sample_code": source.sample_id,
                    "relationship_type": relationship.relationship_type,
                    "reason": relationship.reason,
                },
            )

            from pipelines.services import start_default_pipeline_for_sample

            start_default_pipeline_for_sample(child, request.user)

        return Response(
            {
                "sample": SampleSerializer(child, context={"request": request}).data,
                "relationship": SampleRelationshipSerializer(relationship).data,
            },
            status=status.HTTP_201_CREATED,
        )

    def perform_create(self, serializer):
        project = serializer.validated_data.get("project")
        linked_projects = serializer.validated_data.get("linked_projects", [])

        validate_sample_project_assignment(self.request.user, project)
        validate_linked_projects_for_user(self.request.user, linked_projects)

        with transaction.atomic():
            sample = serializer.save(created_by=self.request.user)

            # A configured default pipeline should make intake deterministic while
            # still allowing labs to create samples before any defaults exist.
            from pipelines.services import start_default_pipeline_for_sample

            start_default_pipeline_for_sample(sample, self.request.user)

    def perform_update(self, serializer):
        sample = self.get_object()
        require_sample_modify_access(self.request.user, sample)

        requested_project = serializer.validated_data.get("project", sample.project)
        requested_linked_projects = serializer.validated_data.get("linked_projects", None)

        if requested_project is None and sample.project_id:
            validate_unassign_project(self.request.user, sample)
        else:
            validate_sample_project_assignment(self.request.user, requested_project)

        if requested_linked_projects is not None:
            validate_linked_projects_for_user(
                self.request.user,
                requested_linked_projects,
            )

        before = sample_audit_state(sample)
        requested_status = serializer.validated_data.get("status", sample.status)
        status_changed = requested_status != sample.status
        reason = None

        if status_changed:
            reason = validate_change_reason(get_change_reason(self.request))
            validate_status_transition(sample.status, requested_status)

        save_kwargs = {}
        if status_changed:
            save_kwargs["status_changed_at"] = timezone.now()

        updated = serializer.save(**save_kwargs)
        after = sample_audit_state(updated)

        changed_fields = [
            key for key in before.keys()
            if before[key] != after[key]
        ]

        if changed_fields:
            extra_payload = {}

            if status_changed:
                extra_payload.update({
                    "reason": reason,
                    "reason_required": True,
                    "reason_type": "sample_status_change",
                })

            action = (
                "SAMPLE_STATUS_CHANGED"
                if changed_fields == ["status"]
                else "UPDATED"
            )

            create_sample_event(
                sample=updated,
                action=action,
                actor=self.request.user,
                before=before,
                after=after,
                changed_fields=changed_fields,
                extra_payload=extra_payload,
            )

    def perform_destroy(self, instance):
        require_sample_modify_access(self.request.user, instance)

        before = sample_audit_state(instance)

        create_sample_event(
            sample=instance,
            action="DELETED",
            actor=self.request.user,
            before=before,
            after={},
            changed_fields=list(before.keys()),
            extra_payload={
                "sample_code": instance.sample_id,
            },
        )

        instance.delete()

    @action(detail=True, methods=["post"], url_path="link-project")
    def link_project(self, request, pk=None):
        sample = self.get_object()
        require_sample_modify_access(request.user, sample)

        project_id = request.data.get("project") or request.data.get("project_id")

        if not project_id:
            return Response(
                {"detail": "project is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from projects.models import Project

        project = Project.objects.filter(id=project_id).first()

        if not project:
            return Response(
                {"detail": "Project not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if sample.project_id == project.id:
            return Response(
                {"detail": "This project is already the primary project."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_linked_projects_for_user(request.user, [project])
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        before = {
            "linked_project_ids": list(
                sample.linked_projects.values_list("id", flat=True)
            )
        }

        sample.linked_projects.add(project)

        after = {
            "linked_project_ids": list(
                sample.linked_projects.values_list("id", flat=True)
            )
        }

        create_sample_event(
            sample=sample,
            action="SAMPLE_PROJECT_LINKED",
            actor=request.user,
            before=before,
            after=after,
            changed_fields=["linked_projects"],
            extra_payload={
                "linked_project_id": project.id,
                "linked_project_code": project.code,
                "linked_project_name": project.name,
            },
        )

        return Response(self.get_serializer(sample).data)

    @action(detail=True, methods=["post"], url_path="unlink-project")
    def unlink_project(self, request, pk=None):
        sample = self.get_object()
        require_sample_modify_access(request.user, sample)

        project_id = request.data.get("project") or request.data.get("project_id")

        if not project_id:
            return Response(
                {"detail": "project is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from projects.models import Project

        project = Project.objects.filter(id=project_id).first()

        if not project:
            return Response(
                {"detail": "Project not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        before = {
            "linked_project_ids": list(
                sample.linked_projects.values_list("id", flat=True)
            )
        }

        sample.linked_projects.remove(project)

        after = {
            "linked_project_ids": list(
                sample.linked_projects.values_list("id", flat=True)
            )
        }

        create_sample_event(
            sample=sample,
            action="SAMPLE_PROJECT_UNLINKED",
            actor=request.user,
            before=before,
            after=after,
            changed_fields=["linked_projects"],
            extra_payload={
                "unlinked_project_id": project.id,
                "unlinked_project_code": project.code,
                "unlinked_project_name": project.name,
            },
        )

        return Response(self.get_serializer(sample).data)

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
        require_sample_modify_access(request.user, sample)

        new_status = request.data.get("new_status") or request.data.get("status")

        if not new_status:
            return Response(
                {"detail": "new_status is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            reason = validate_change_reason(get_change_reason(request))
            validate_status_transition(sample.status, new_status)
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        before = sample_audit_state(sample)

        sample.status = new_status
        sample.status_changed_at = timezone.now()
        sample.save(update_fields=["status", "status_changed_at", "updated_at"])

        after = sample_audit_state(sample)

        create_sample_event(
            sample=sample,
            action="SAMPLE_STATUS_CHANGED",
            actor=request.user,
            before=before,
            after=after,
            changed_fields=["status"],
            extra_payload={
                "reason": reason,
                "reason_required": True,
                "reason_type": "sample_status_change",
            },
        )

        serializer = self.get_serializer(sample)
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        sample = self.get_object()
        require_sample_modify_access(request.user, sample)
        old_container_id = sample.container_id
        old_container_code = (
            sample.container.container_id if sample.container else None
        )

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
                    "new_container_code": (
                        sample.container.container_id
                        if sample.container
                        else None
                    ),
                    "location_name": (
                        sample.container.location.name
                        if sample.container and sample.container.location
                        else None
                    ),
                },
            )

        return response

    @action(detail=False, methods=["post"], url_path="bulk-update")
    def bulk_update_samples(self, request):
        ids = request.data.get("ids", [])
        new_status = request.data.get("status", None)
        new_project = request.data.get("project", None)
        new_container = request.data.get("container", None)
        status_change_reason = None

        if not ids:
            return Response(
                {"detail": "No sample IDs provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_status is None and new_project is None and new_container is None:
            return Response(
                {
                    "detail": (
                        "Nothing to update. Provide status, project, "
                        "and/or container."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_status is not None:
            try:
                status_change_reason = validate_change_reason(
                    get_change_reason(request)
                )
            except ValidationError as exc:
                return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        samples = (
            Sample.objects
            .select_related(
                "project",
                "container",
                "container__location",
                "created_by",
            )
            .filter(id__in=ids)
        )
        samples = get_sample_access_queryset(samples, request.user)

        updated_count = 0
        skipped = []
        updated_ids = []

        for sample in samples:
            try:
                require_sample_modify_access(request.user, sample)
            except Exception as exc:
                skipped.append({
                    "id": sample.id,
                    "sample_id": sample.sample_id,
                    "reason": str(exc),
                })
                continue

            before = sample_audit_state(sample)

            changed_fields = []

            if new_status is not None:
                if new_status == sample.status:
                    pass
                else:
                    allowed = get_allowed_transitions(sample.status)

                    if new_status in allowed:
                        sample.status = new_status
                        sample.status_changed_at = timezone.now()
                        changed_fields.append("status")
                    else:
                        skipped.append({
                            "id": sample.id,
                            "sample_id": sample.sample_id,
                            "reason": (
                                f"Invalid workflow transition from "
                                f"{sample.status} to {new_status}"
                            ),
                        })

            if new_project is not None:
                normalized_project = new_project or None

                if normalized_project is None:
                    if sample.project_id:
                        try:
                            validate_unassign_project(request.user, sample)
                        except ValidationError as exc:
                            skipped.append({
                                "id": sample.id,
                                "sample_id": sample.sample_id,
                                "reason": exc.detail,
                            })
                            continue
                else:
                    from projects.models import Project

                    target_project = Project.objects.filter(
                        id=normalized_project
                    ).first()

                    if not target_project:
                        skipped.append({
                            "id": sample.id,
                            "sample_id": sample.sample_id,
                            "reason": "Target project does not exist.",
                        })
                        continue

                    try:
                        validate_sample_project_assignment(
                            request.user,
                            target_project,
                        )
                    except ValidationError as exc:
                        skipped.append({
                            "id": sample.id,
                            "sample_id": sample.sample_id,
                            "reason": exc.detail,
                        })
                        continue

                if sample.project_id != normalized_project:
                    sample.project_id = normalized_project
                    changed_fields.append("project_id")

            if new_container is not None:
                normalized_container = new_container or None

                if sample.container_id != normalized_container:
                    sample.container_id = normalized_container
                    changed_fields.append("container_id")

            if changed_fields:
                sample.save()

                after = sample_audit_state(sample)

                updated_count += 1
                updated_ids.append(sample.id)

                extra_payload = {
                    "bulk": True,
                }

                if "status" in changed_fields:
                    extra_payload.update({
                        "reason": status_change_reason,
                        "reason_required": True,
                        "reason_type": "bulk_sample_status_change",
                    })

                action = (
                    "BULK_SAMPLE_STATUS_CHANGED"
                    if changed_fields == ["status"]
                    else "BULK_SAMPLE_UPDATED"
                )

                create_sample_event(
                    sample=sample,
                    action=action,
                    actor=request.user,
                    before=before,
                    after=after,
                    changed_fields=changed_fields,
                    extra_payload=extra_payload,
                )

        return Response({
            "updated": updated_count,
            "updated_ids": updated_ids,
            "skipped": skipped,
        })
    @action(detail=False, methods=["post"], url_path="export-selected")
    def export_selected(self, request):
        ids = request.data.get("ids", [])

        if not ids:
            return Response(
                {"detail": "No sample IDs provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        samples = (
            Sample.objects
            .select_related(
                "project",
                "container",
                "container__location",
                "created_by",
            )
            .filter(id__in=ids)
        )
        samples = (
            get_sample_access_queryset(samples, request.user)
            .order_by("sample_id")
        )

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            'attachment; filename="openlims-selected-samples.csv"'
        )

        writer = csv.writer(response)
        writer.writerow([
            "id",
            "sample_id",
            "sample_type",
            "status",
            "project_code",
            "project_name",
            "container_code",
            "location_name",
            "created_at",
        ])

        for sample in samples:
            writer.writerow([
                sample.id,
                sample.sample_id,
                sample.sample_type,
                sample.status,
                sample.project.code if sample.project else "",
                sample.project.name if sample.project else "",
                sample.container.container_id if sample.container else "",
                (
                    sample.container.location.name
                    if sample.container and sample.container.location
                    else ""
                ),
                sample.created_at.isoformat() if sample.created_at else "",
            ])

        return response


class SampleBatchViewSet(ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = SampleBatchSerializer

    def get_queryset(self):
        queryset = (
            SampleBatch.objects.select_related("project", "created_by")
            .all()
            .order_by("code")
        )

        project = self.request.query_params.get("project")
        search = self.request.query_params.get("search")

        if project:
            queryset = queryset.filter(project_id=project)
        if search:
            queryset = queryset.filter(code__icontains=search)

        if self.request.user.is_superuser or self.request.user.groups.filter(
            name="admin"
        ).exists():
            return queryset

        return queryset.filter(project__members=self.request.user).distinct()

class SingleSampleAttachmentViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = SingleSampleAttachmentSerializer

    def get_queryset(self):
        queryset = (
            SingleSampleAttachment.objects
            .select_related(
                "sample",
                "uploaded_by",
            )
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

    def perform_create(self, serializer):
        sample = serializer.validated_data.get("sample")

        if not user_can_access_sample(self.request.user, sample):
            raise ValidationError({
                "sample": "You do not have access to attach files to this sample."
            })

        attachment = serializer.save(uploaded_by=self.request.user)

        Event.objects.create(
            entity_type="Sample",
            entity_id=str(attachment.sample.id),
            action="ATTACHMENT_UPLOADED",
            actor=self.request.user,
            payload={
                "sample_id": attachment.sample.id,
                "sample_code": attachment.sample.sample_id,
                "filename": attachment.file.name.split("/")[-1],
            },
        )


class SampleRelationshipViewSet(ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = SampleRelationshipSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        allowed = get_sample_access_queryset(Sample.objects.all(), self.request.user)
        queryset = (
            SampleRelationship.objects.select_related(
                "source_sample", "derived_sample", "created_by"
            )
            .filter(source_sample__in=allowed, derived_sample__in=allowed)
            .distinct()
        )
        sample_id = self.request.query_params.get("sample")
        if sample_id:
            queryset = queryset.filter(
                Q(source_sample_id=sample_id) | Q(derived_sample_id=sample_id)
            )
        return queryset

    def perform_create(self, serializer):
        source = serializer.validated_data["source_sample"]
        derived = serializer.validated_data["derived_sample"]
        require_sample_modify_access(self.request.user, source)
        require_sample_modify_access(self.request.user, derived)
        relationship = serializer.save(created_by=self.request.user)
        payload = {
            "source_sample_id": source.id,
            "source_sample_code": source.sample_id,
            "derived_sample_id": derived.id,
            "derived_sample_code": derived.sample_id,
            "relationship_type": relationship.relationship_type,
            "quantity": str(relationship.quantity) if relationship.quantity is not None else None,
            "unit": relationship.unit,
            "reason": relationship.reason,
        }
        for sample in [source, derived]:
            Event.objects.create(
                entity_type="Sample",
                entity_id=str(sample.id),
                action="SAMPLE_LINEAGE_LINKED",
                actor=self.request.user,
                payload={"sample_id": sample.id, "sample_code": sample.sample_id, **payload},
            )


class SampleCustodyEventViewSet(ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyOrTechAdminWrite]
    serializer_class = SampleCustodyEventSerializer

    def get_queryset(self):
        allowed = get_sample_access_queryset(Sample.objects.all(), self.request.user)
        queryset = SampleCustodyEvent.objects.select_related(
            "sample",
            "from_container",
            "to_container",
            "from_custodian",
            "to_custodian",
            "performed_by",
        ).filter(sample__in=allowed)
        sample_id = self.request.query_params.get("sample")
        if sample_id:
            queryset = queryset.filter(sample_id=sample_id)
        return queryset

    @action(detail=False, methods=["post"], url_path="scan")
    def scan(self, request):
        input_serializer = CustodyScanSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        scanned_code = data["barcode"].strip()

        from assistant.models import BarcodeLabel
        from inventory.models import Container

        label = BarcodeLabel.objects.select_related("sample").filter(
            barcode__iexact=scanned_code
        ).first()
        candidate = label.sample if label else Sample.objects.filter(
            sample_id__iexact=scanned_code
        ).first()
        if not candidate or not user_can_access_sample(request.user, candidate):
            return Response(
                {"barcode": "No accessible sample matches this barcode."},
                status=status.HTTP_404_NOT_FOUND,
            )
        require_sample_modify_access(request.user, candidate)

        container = None
        if data.get("container") is not None:
            container = Container.objects.filter(pk=data["container"]).first()
            if not container:
                raise ValidationError({"container": "Container not found."})

        custodian = None
        if data.get("custodian") is not None:
            custodian = get_user_model().objects.filter(
                pk=data["custodian"], is_active=True
            ).first()
            if not custodian:
                raise ValidationError({"custodian": "Active custodian not found."})

        action_name = data["action"]
        if action_name == SampleCustodyEvent.ACTION_MOVE and not container:
            raise ValidationError({"container": "A destination container is required for a move."})
        if action_name == SampleCustodyEvent.ACTION_TRANSFER and not custodian:
            raise ValidationError({"custodian": "A destination custodian is required for a transfer."})

        with transaction.atomic():
            sample = Sample.objects.select_for_update().select_related(
                "container", "custodian"
            ).get(pk=candidate.pk)
            from_container = sample.container
            from_custodian = sample.custodian
            to_container = sample.container
            to_custodian = sample.custodian

            if action_name in [SampleCustodyEvent.ACTION_RECEIVE, SampleCustodyEvent.ACTION_MOVE]:
                if container:
                    to_container = container
                if action_name == SampleCustodyEvent.ACTION_RECEIVE:
                    to_custodian = None
            elif action_name == SampleCustodyEvent.ACTION_CHECK_OUT:
                if sample.custodian_id and sample.custodian_id != request.user.id:
                    raise ValidationError({
                        "detail": (
                            f"Sample is already checked out to {sample.custodian.username}; "
                            "use transfer custody instead."
                        )
                    })
                to_custodian = request.user
            elif action_name == SampleCustodyEvent.ACTION_CHECK_IN:
                to_custodian = None
            elif action_name == SampleCustodyEvent.ACTION_TRANSFER:
                to_custodian = custodian
            elif action_name == SampleCustodyEvent.ACTION_PROCESS:
                to_custodian = sample.custodian or request.user
            elif action_name == SampleCustodyEvent.ACTION_DISPOSE:
                to_container = None
                to_custodian = None
                sample.status = Sample.STATUS_ARCHIVED
                sample.status_changed_at = timezone.now()

            sample.container = to_container
            sample.custodian = to_custodian
            sample.save(update_fields=[
                "container", "custodian", "status", "status_changed_at", "updated_at"
            ])
            custody_event = SampleCustodyEvent.objects.create(
                sample=sample,
                action=action_name,
                scanned_code=scanned_code,
                from_container=from_container,
                to_container=to_container,
                from_custodian=from_custodian,
                to_custodian=to_custodian,
                reason=data["reason"].strip(),
                performed_by=request.user,
            )
            Event.objects.create(
                entity_type="Sample",
                entity_id=str(sample.id),
                action=f"CUSTODY_{action_name}",
                actor=request.user,
                payload={
                    "sample_id": sample.id,
                    "sample_code": sample.sample_id,
                    "custody_event_id": custody_event.id,
                    "scanned_code": scanned_code,
                    "from_container_code": from_container.container_id if from_container else None,
                    "to_container_code": to_container.container_id if to_container else None,
                    "from_custodian": from_custodian.username if from_custodian else None,
                    "to_custodian": to_custodian.username if to_custodian else None,
                    "reason": custody_event.reason,
                },
            )

        return Response(self.get_serializer(custody_event).data, status=status.HTTP_201_CREATED)
