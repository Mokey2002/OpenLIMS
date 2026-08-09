from rest_framework import serializers, status
from django.db.models import Q
from django.http import FileResponse
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from core.permissions import IsAdminOnly, is_admin
from rest_framework.response import Response
from rest_framework.views import APIView

from .actions import (
    AssistantActionError,
    cancel_action,
    confirm_action,
    propose_action,
    serialize_action,
)
from .llm import configured_model_info, enhance_with_llm
from .models import AssistantAction
from .models import GeneratedArtifact, NotificationSubscription, SOPDocument
from .monitoring import build_admin_monitoring_status
from .serializers import NotificationSubscriptionSerializer, SOPDocumentSerializer
from .tools import route_assistant_message


class AssistantChatSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000)
    context = serializers.DictField(required=False, default=dict)


class AssistantChatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AssistantChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.validated_data["message"]
        context = serializer.validated_data["context"]

        result = route_assistant_message(
            message=message,
            user=request.user,
            context=context,
        )
        proposal = result.pop("pending_action", None)

        if proposal:
            try:
                action = propose_action(
                    user=request.user,
                    action_type=proposal["type"],
                    summary=proposal["summary"],
                    payload=proposal.get("payload") or {},
                )
                result["pending_action"] = serialize_action(action)
            except (AssistantActionError, KeyError) as exc:
                result["action_error"] = str(exc)

        result = enhance_with_llm(message=message, tool_result=result)
        return Response(result, status=status.HTTP_200_OK)


class AssistantStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(configured_model_info(), status=status.HTTP_200_OK)


class AssistantActionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, token):
        try:
            action = AssistantAction.objects.get(
                confirmation_token=token,
                requested_by=request.user,
            )
        except AssistantAction.DoesNotExist:
            return Response(
                {"detail": "Confirmation token not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(serialize_action(action), status=status.HTTP_200_OK)


class AssistantActionConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, token):
        if request.data.get("confirm") is not True:
            return Response(
                {"detail": "Set confirm to true to execute this action."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            action = confirm_action(token=token, user=request.user)
        except AssistantActionError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if action.status in [
            AssistantAction.STATUS_EXPIRED,
            AssistantAction.STATUS_FAILED,
        ]:
            return Response(
                serialize_action(action),
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_status = (
            status.HTTP_202_ACCEPTED
            if action.status == AssistantAction.STATUS_QUEUED
            else status.HTTP_200_OK
        )
        return Response(serialize_action(action), status=response_status)


class AssistantActionCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, token):
        try:
            action = cancel_action(token=token, user=request.user)
        except AssistantActionError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(serialize_action(action), status=status.HTTP_200_OK)


class AssistantArtifactDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, artifact_id):
        artifact = GeneratedArtifact.objects.select_related("project", "created_by").filter(id=artifact_id).first()
        if not artifact:
            return Response({"detail": "Artifact not found."}, status=status.HTTP_404_NOT_FOUND)
        allowed = artifact.created_by_id == request.user.id or is_admin(request.user)
        if artifact.project_id:
            allowed = allowed or artifact.project.members.filter(id=request.user.id).exists()
        if not allowed:
            return Response({"detail": "Artifact access denied."}, status=status.HTTP_403_FORBIDDEN)
        return FileResponse(artifact.file.open("rb"), content_type=artifact.content_type, as_attachment=True, filename=artifact.filename)


class SOPDocumentViewSet(ModelViewSet):
    serializer_class = SOPDocumentSerializer

    def get_permissions(self):
        if self.request.method not in ["GET", "HEAD", "OPTIONS"]:
            return [IsAdminOnly()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = SOPDocument.objects.select_related("project", "uploaded_by").prefetch_related("allowed_groups")
        if is_admin(self.request.user):
            return queryset
        return queryset.filter(
            approved=True,
            status=SOPDocument.STATUS_CURRENT,
            effective_at__lte=timezone.now(),
        ).filter(
            Q(project__isnull=True) | Q(project__members=self.request.user)
        ).filter(
            Q(allowed_groups__isnull=True) | Q(allowed_groups__in=self.request.user.groups.all())
        ).distinct()

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)


class NotificationSubscriptionViewSet(ReadOnlyModelViewSet):
    serializer_class = NotificationSubscriptionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return NotificationSubscription.objects.select_related("recipient", "created_by", "project").filter(
            Q(created_by=self.request.user) | Q(recipient=self.request.user)
        )


class AssistantSystemMonitoringView(APIView):
    permission_classes = [IsAdminOnly]

    def get(self, request):
        return Response(build_admin_monitoring_status(), status=status.HTTP_200_OK)
