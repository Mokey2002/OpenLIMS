from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.permissions import IsAuthenticatedReadOnlyAdminWrite
from events.models import Event

from .models import SystemSettings
from .serializers import SystemSettingsSerializer


class SystemSettingsViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticatedReadOnlyAdminWrite]
    serializer_class = SystemSettingsSerializer

    def get_queryset(self):
        SystemSettings.load()
        return SystemSettings.objects.all()

    def list(self, request, *args, **kwargs):
        settings_obj = SystemSettings.load()
        serializer = self.get_serializer(settings_obj)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        settings_obj = SystemSettings.load()
        serializer = self.get_serializer(settings_obj)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "System settings already exist. Use PATCH or PUT."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def update(self, request, *args, **kwargs):
        settings_obj = SystemSettings.load()
        partial = kwargs.pop("partial", False)

        before = SystemSettingsSerializer(settings_obj).data

        serializer = self.get_serializer(
            settings_obj,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)

        after = serializer.data

        Event.objects.create(
            entity_type="SystemSettings",
            entity_id=str(settings_obj.id),
            action="SETTINGS_UPDATED",
            actor=request.user if request.user.is_authenticated else None,
            payload={
                "before": before,
                "after": after,
            },
        )

        return Response(after)

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"detail": "System settings cannot be deleted."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=False, methods=["post"], url_path="reset-defaults")
    def reset_defaults(self, request):
        settings_obj = SystemSettings.load()

        settings_obj.lab_name = "OpenLIMS Demo Lab"
        settings_obj.organization_name = "OpenLIMS"
        settings_obj.default_timezone = "UTC"
        settings_obj.default_sample_status = "RECEIVED"
        settings_obj.max_upload_size_mb = 10
        settings_obj.require_import_preview = True
        settings_obj.allowed_fasta_extensions = [".fasta", ".fa", ".fna", ".txt"]
        settings_obj.alignments_enabled = True
        settings_obj.max_sequences_per_alignment = 25
        settings_obj.max_sequence_length = 100000
        settings_obj.viewer_read_only = True
        settings_obj.require_audit_reason = False
        settings_obj.updated_by = request.user
        settings_obj.save()

        Event.objects.create(
            entity_type="SystemSettings",
            entity_id=str(settings_obj.id),
            action="SETTINGS_RESET_DEFAULTS",
            actor=request.user if request.user.is_authenticated else None,
            payload={
                "settings_id": settings_obj.id,
            },
        )

        serializer = self.get_serializer(settings_obj)
        return Response(serializer.data)
