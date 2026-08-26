from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.audit import record_audit_event
from core.entities import (
    entity_reference,
    resolve_entity,
    user_can_access_entity,
)
from core.entity_serializers import (
    EntityLinkSerializer,
    EntityReferenceSerializer,
    SharedAttachmentSerializer,
)
from core.models import EntityLink, SharedAttachment
from core.permissions import ProjectScopedEntityPermission, is_admin


def _project_visible_filter(user):
    if is_admin(user):
        return Q()
    return Q(project__members=user) | Q(project__isnull=True)


class EntityReferenceView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=EntityReferenceSerializer)
    def get(self, request, entity_type, public_id):
        try:
            obj = resolve_entity(entity_type, public_id, request.user)
        except ValueError as exc:
            raise ValidationError({"entity_type": str(exc)}) from exc
        except LookupError as exc:
            raise NotFound(str(exc)) from exc
        return Response(entity_reference(obj))


class EntityLinkViewSet(viewsets.ModelViewSet):
    queryset = EntityLink.objects.none()
    permission_classes = [ProjectScopedEntityPermission]
    serializer_class = EntityLinkSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        queryset = EntityLink.objects.select_related(
            "source_content_type",
            "target_content_type",
            "project",
            "created_by",
        ).filter(_project_visible_filter(self.request.user))

        source_type = self.request.query_params.get("source_type")
        source_public_id = self.request.query_params.get("source_public_id")
        target_type = self.request.query_params.get("target_type")
        target_public_id = self.request.query_params.get("target_public_id")
        project = self.request.query_params.get("project")

        if source_type and source_public_id:
            try:
                source = resolve_entity(source_type, source_public_id, self.request.user)
            except (ValueError, LookupError) as exc:
                raise ValidationError({"source": str(exc)}) from exc
            queryset = queryset.filter(
                source_content_type__app_label=source._meta.app_label,
                source_content_type__model=source._meta.model_name,
                source_object_id=str(source.pk),
            )
        if target_type and target_public_id:
            try:
                target = resolve_entity(target_type, target_public_id, self.request.user)
            except (ValueError, LookupError) as exc:
                raise ValidationError({"target": str(exc)}) from exc
            queryset = queryset.filter(
                target_content_type__app_label=target._meta.app_label,
                target_content_type__model=target._meta.model_name,
                target_object_id=str(target.pk),
            )
        if project:
            queryset = queryset.filter(project__public_id=project)
        return queryset.distinct()

    def perform_create(self, serializer):
        link = serializer.save()
        record_audit_event(
            entity=link.source_object,
            action="ENTITY_LINK_CREATED",
            actor=self.request.user,
            after={"link": str(link.public_id)},
            details={
                "relation_type": link.relation_type,
                "target": entity_reference(link.target_object),
            },
        )

    def destroy(self, request, *args, **kwargs):
        link = self.get_object()
        source = link.source_object
        target = link.target_object
        if not source or not target:
            raise ValidationError("The linked record no longer exists.")
        if not user_can_access_entity(request.user, source, write=True):
            raise PermissionDenied("You cannot remove this entity link.")

        link_reference = str(link.public_id)
        details = {
            "relation_type": link.relation_type,
            "target": entity_reference(target),
        }
        link.delete()
        record_audit_event(
            entity=source,
            action="ENTITY_LINK_DELETED",
            actor=request.user,
            before={"link": link_reference},
            details=details,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class SharedAttachmentViewSet(viewsets.ModelViewSet):
    queryset = SharedAttachment.objects.none()
    permission_classes = [ProjectScopedEntityPermission]
    serializer_class = SharedAttachmentSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        queryset = SharedAttachment.objects.select_related(
            "target_content_type",
            "project",
            "uploaded_by",
        ).filter(_project_visible_filter(self.request.user))
        target_type = self.request.query_params.get("target_type")
        target_public_id = self.request.query_params.get("target_public_id")
        project = self.request.query_params.get("project")
        if target_type and target_public_id:
            try:
                target = resolve_entity(target_type, target_public_id, self.request.user)
            except (ValueError, LookupError) as exc:
                raise ValidationError({"target": str(exc)}) from exc
            queryset = queryset.filter(
                target_content_type__app_label=target._meta.app_label,
                target_content_type__model=target._meta.model_name,
                target_object_id=str(target.pk),
            )
        if project:
            queryset = queryset.filter(project__public_id=project)
        return queryset.distinct()

    def perform_create(self, serializer):
        attachment = serializer.save()
        record_audit_event(
            entity=attachment.target_object,
            action="SHARED_ATTACHMENT_UPLOADED",
            actor=self.request.user,
            after={"attachment": str(attachment.public_id)},
            details={
                "filename": attachment.filename,
                "size_bytes": attachment.size_bytes,
                "sha256": attachment.sha256,
            },
        )

    def destroy(self, request, *args, **kwargs):
        attachment = self.get_object()
        target = attachment.target_object
        if not target:
            raise ValidationError("The attachment target no longer exists.")
        if not user_can_access_entity(request.user, target, write=True):
            raise PermissionDenied("You cannot remove this attachment.")

        public_id = str(attachment.public_id)
        details = {
            "filename": attachment.filename,
            "sha256": attachment.sha256,
        }
        attachment.file.delete(save=False)
        attachment.delete()
        record_audit_event(
            entity=target,
            action="SHARED_ATTACHMENT_DELETED",
            actor=request.user,
            before={"attachment": public_id},
            details=details,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
