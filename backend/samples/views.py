import csv

from django.http import HttpResponse
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError

from .models import Sample, SingleSampleAttachment
from .serializers import SampleSerializer, SingleSampleAttachmentSerializer
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
        "status": sample.status,
        "project_id": sample.project_id,
        "container_id": sample.container_id,
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
            )
            .prefetch_related("linked_projects")
            .all()
            .order_by("-created_at")
        )

        search = self.request.query_params.get("search")
        status_filter = self.request.query_params.get("status")
        project = self.request.query_params.get("project")
        container = self.request.query_params.get("container")

        if search:
            queryset = queryset.filter(sample_id__icontains=search)

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        if project:
            queryset = queryset.filter(project_id=project)

        if container:
            queryset = queryset.filter(container_id=container)

        return get_sample_access_queryset(queryset, self.request.user)

    def perform_create(self, serializer):
        project = serializer.validated_data.get("project")
        linked_projects = serializer.validated_data.get("linked_projects", [])

        validate_sample_project_assignment(self.request.user, project)
        validate_linked_projects_for_user(self.request.user, linked_projects)

        serializer.save(created_by=self.request.user)

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

        updated = serializer.save()
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
        sample.save(update_fields=["status"])

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