import hashlib
import time
from datetime import timedelta

from rest_framework import serializers, status
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.http import FileResponse
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from core.permissions import IsAdminOnly, is_admin
from events.models import Event
from rest_framework.response import Response
from rest_framework.views import APIView

from .actions import (
    AssistantActionError,
    cancel_action,
    confirm_action,
    propose_action,
    serialize_action,
)
from .llm import classify_route_with_llm, configured_model_info, enhance_with_llm
from .context_state import update_conversation_context
from .models import AssistantAction, AssistantFeedback, AssistantInteraction
from .models import GeneratedArtifact, NotificationSubscription, SOPDocument
from .monitoring import build_admin_monitoring_status
from .comparisons import run_comparison_spec
from .investigations import run_investigation_spec
from .serializers import NotificationSubscriptionSerializer, SOPDocumentSerializer
from .suggestions import assistant_starter_suggestions
from .response_contracts import normalize_assistant_response
from .tools import route_assistant_message


class AssistantChatSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000)
    context = serializers.DictField(required=False, default=dict)


class AssistantFeedbackSerializer(serializers.Serializer):
    rating = serializers.ChoiceField(choices=["UP", "DOWN"])
    category = serializers.ChoiceField(
        choices=["", "WRONG_ROUTE", "WRONG_RECORDS", "MISSING_DETAIL", "UNWANTED_CHART", "OTHER"],
        required=False,
        allow_blank=True,
        default="",
    )
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)


class AssistantComparisonSerializer(serializers.Serializer):
    analysis = serializers.ChoiceField(
        choices=["compare", "trend", "outliers", "bottleneck"],
        default="compare",
    )
    kind = serializers.ChoiceField(
        choices=["sample", "project", "batch"],
        default="project",
    )
    identifiers = serializers.ListField(
        child=serializers.CharField(max_length=128),
        required=False,
        default=list,
        max_length=10,
    )
    days = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=3650,
    )
    metric = serializers.ChoiceField(
        choices=["overview", "status", "qc", "work", "turnaround", "metadata", "results"],
        default="overview",
    )
    result_key = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=128,
    )
    chart_type = serializers.ChoiceField(
        choices=["auto", "bar", "line", "scatter", "dot"],
        default="auto",
    )
    result_keys = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        default=list,
        max_length=10,
    )


class AssistantInvestigationSerializer(serializers.Serializer):
    subject_type = serializers.ChoiceField(
        choices=["sample", "result"],
        default="sample",
    )
    identifier = serializers.CharField(max_length=128)
    days = serializers.IntegerField(default=90, min_value=1, max_value=3650)
    result_key = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=128,
    )
    group_by = serializers.ChoiceField(
        choices=["overview", "operator", "workflow", "reagent", "instrument"],
        default="overview",
    )


class AssistantChatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        started_at = time.monotonic()
        serializer = AssistantChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.validated_data["message"]
        context = serializer.validated_data["context"]
        message_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()

        try:
            result = route_assistant_message(
                message=message,
                user=request.user,
                context=context,
            )
            unmatched = result.pop("route_unmatched", False)
            if unmatched:
                route_hint = classify_route_with_llm(message, context=context)
                if route_hint:
                    hinted_result = route_assistant_message(
                        message=message,
                        user=request.user,
                        context=context,
                        route_hint=route_hint,
                    )
                    hinted_result.pop("route_unmatched", None)
                    existing_routing = hinted_result.get("routing") or {}
                    hinted_result["routing"] = {
                        "source": f"{route_hint.get('provider', 'llm')}_fallback",
                        "route": route_hint.get("route", "unknown"),
                        "confidence": route_hint.get("confidence", 0),
                        "plan": existing_routing.get("plan") or {
                            key: route_hint.get(key)
                            for key in ["intent", "entities", "filters", "metrics", "chart_type"]
                            if route_hint.get(key) not in (None, [], {}, "")
                        },
                    }
                    result = hinted_result
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

            result["context"] = update_conversation_context(
                message,
                context,
                result,
            )
            result = normalize_assistant_response(message, result)
            result = enhance_with_llm(message=message, tool_result=result)
            result = normalize_assistant_response(message, result)
            routing = result.get("routing") or {}
            presentation = result.get("presentation") or {}
            interaction = AssistantInteraction.objects.create(
                user=request.user,
                message_hash=message_hash,
                route=routing.get("route", "unknown"),
                routing_source=routing.get("source", "rules"),
                confidence=float(routing.get("confidence", 0) or 0),
                response_type=presentation.get("mode", result.get("response_type", "text")),
                record_count=int(presentation.get("record_count", 0) or 0),
                clarification_requested=bool(result.get("clarification")),
                success=True,
                latency_ms=max(int((time.monotonic() - started_at) * 1000), 0),
                context_keys=sorted(result.get("context", {}).keys()),
            )
            result["interaction_id"] = str(interaction.id)
            return Response(result, status=status.HTTP_200_OK)
        except Exception as exc:
            AssistantInteraction.objects.create(
                user=request.user,
                message_hash=message_hash,
                route="error",
                routing_source="server",
                success=False,
                latency_ms=max(int((time.monotonic() - started_at) * 1000), 0),
                context_keys=sorted(context.keys()),
                error_code=type(exc).__name__[:128],
            )
            raise


class AssistantFeedbackView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, interaction_id):
        serializer = AssistantFeedbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            interaction = AssistantInteraction.objects.get(
                id=interaction_id,
                user=request.user,
            )
        except AssistantInteraction.DoesNotExist:
            return Response(
                {"detail": "Assistant interaction not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        feedback, _created = AssistantFeedback.objects.update_or_create(
            interaction=interaction,
            user=request.user,
            defaults=serializer.validated_data,
        )
        return Response(
            {
                "interaction_id": str(interaction.id),
                "rating": feedback.rating,
                "category": feedback.category,
                "note": feedback.note,
            },
            status=status.HTTP_200_OK,
        )


class AssistantMetricsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_admin(request.user):
            return Response(
                {"detail": "Admin access is required."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            days = min(max(int(request.query_params.get("days", 30)), 1), 365)
        except (TypeError, ValueError):
            days = 30
        cutoff = timezone.now() - timedelta(days=days)
        interactions = AssistantInteraction.objects.filter(created_at__gte=cutoff)
        routes = list(
            interactions.values("route").annotate(
                requests=Count("id"),
                failures=Count("id", filter=Q(success=False)),
                clarifications=Count("id", filter=Q(clarification_requested=True)),
                average_latency_ms=Avg("latency_ms"),
                average_confidence=Avg("confidence"),
            ).order_by("-requests", "route")
        )
        ratings = {
            item["rating"]: item["count"]
            for item in AssistantFeedback.objects.filter(
                interaction__created_at__gte=cutoff
            ).values("rating").annotate(count=Count("id"))
        }
        return Response(
            {
                "days": days,
                "requests": interactions.count(),
                "routes": routes,
                "feedback": {
                    "helpful": ratings.get(AssistantFeedback.RATING_UP, 0),
                    "not_helpful": ratings.get(AssistantFeedback.RATING_DOWN, 0),
                },
                "privacy": "Raw assistant questions are not stored in interaction telemetry.",
            }
        )


class AssistantComparisonView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AssistantComparisonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = run_comparison_spec(
            serializer.validated_data,
            request.user,
        )
        return Response(result, status=status.HTTP_200_OK)


class AssistantInvestigationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AssistantInvestigationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = run_investigation_spec(serializer.validated_data, request.user)
        return Response(result, status=status.HTTP_200_OK)


class AssistantStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                **configured_model_info(),
                "welcome_message": (
                    "Ask about samples, projects, QC, comparisons, inventory, "
                    "sequences, or system status. Suggestions below are based on "
                    "records you can currently access."
                ),
                "suggestions": assistant_starter_suggestions(request.user),
            },
            status=status.HTTP_200_OK,
        )


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

    @transaction.atomic
    def perform_create(self, serializer):
        save_kwargs = {"uploaded_by": self.request.user}
        if (
            serializer.validated_data.get("status")
            == SOPDocument.STATUS_ARCHIVED
            and not serializer.validated_data.get("archived_at")
        ):
            save_kwargs["archived_at"] = timezone.now()
        document = serializer.save(**save_kwargs)
        self._record_event(
            document,
            "SOP_DOCUMENT_CREATED",
            {
                "document_code": document.document_code,
                "version": document.version,
                "section": document.section,
                "status": document.status,
                "approved": document.approved,
                "project_id": document.project_id,
                "allowed_groups": list(
                    document.allowed_groups.values_list("name", flat=True)
                ),
            },
        )

    @transaction.atomic
    def perform_update(self, serializer):
        document = serializer.instance
        before = self._snapshot(document)
        next_status = serializer.validated_data.get("status", document.status)
        save_kwargs = {}

        if next_status == SOPDocument.STATUS_ARCHIVED:
            if (
                document.status != SOPDocument.STATUS_ARCHIVED
                or not document.archived_at
            ):
                save_kwargs["archived_at"] = timezone.now()
        else:
            save_kwargs["archived_at"] = None

        document = serializer.save(**save_kwargs)
        after = self._snapshot(document)
        changed_fields = [
            field
            for field in before
            if before[field] != after[field]
        ]

        if before["status"] != after["status"]:
            action = (
                "SOP_DOCUMENT_ARCHIVED"
                if after["status"] == SOPDocument.STATUS_ARCHIVED
                else "SOP_DOCUMENT_RESTORED"
            )
        else:
            action = "SOP_DOCUMENT_UPDATED"

        self._record_event(
            document,
            action,
            {
                "document_code": document.document_code,
                "version": document.version,
                "section": document.section,
                "changed_fields": changed_fields,
                "before": before,
                "after": after,
            },
        )

    @staticmethod
    def _snapshot(document):
        return {
            "document_code": document.document_code,
            "title": document.title,
            "version": document.version,
            "section": document.section,
            "status": document.status,
            "approved": document.approved,
            "project_id": document.project_id,
            "allowed_groups": sorted(
                document.allowed_groups.values_list("name", flat=True)
            ),
            "effective_at": (
                document.effective_at.isoformat()
                if document.effective_at
                else None
            ),
            "archived_at": (
                document.archived_at.isoformat()
                if document.archived_at
                else None
            ),
            "has_source_file": bool(document.source_file),
        }

    def _record_event(self, document, action, payload):
        Event.objects.create(
            entity_type="SOPDocument",
            entity_id=str(document.id),
            action=action,
            actor=self.request.user,
            payload=payload,
        )


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
