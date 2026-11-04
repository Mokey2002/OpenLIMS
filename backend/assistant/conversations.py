"""Opt-in saved chats; laboratory answers are fetched again on restoration."""
import copy

from django.contrib.auth import get_user_model
from django.db import transaction
from django.core import signing
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from .models import AssistantConversation


class ConversationNameSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)


class ConversationSerializer(ConversationNameSerializer):
    turn_tokens = serializers.ListField(child=serializers.CharField(max_length=32000), max_length=20, required=False)


class ConversationInfoSerializer(ConversationNameSerializer):
    id = serializers.UUIDField()
    updated_at = serializers.DateTimeField(required=False)


def _save_references(plan, user):
    from .sample_operations import _sample_queryset
    from .lab_reviews import _projects
    plan = copy.deepcopy(plan)
    for step in plan["steps"]:
        for kind, records, field in [("sample", _sample_queryset(user), "sample_id"), ("project", _projects(user), "code")]:
            if kind in step["arguments"]:
                matches = list(records.filter(**{field + "__iexact": step["arguments"][kind]})[:2])
                if len(matches) == 1:
                    step["saved_reference"] = {"kind": kind, "id": matches[0].pk}
    return plan


def _restore_references(plan, user):
    from .sample_operations import _sample_queryset
    from .lab_reviews import _projects
    plan = copy.deepcopy(plan)
    for step in plan["steps"]:
        reference = step.pop("saved_reference", None)
        if reference and reference["kind"] in {"sample", "project"}:
            kind = reference["kind"]
            record = (_sample_queryset(user) if kind == "sample" else _projects(user)).filter(pk=reference["id"]).first()
            if record is None:
                return None
            step["arguments"][kind] = record.sample_id if kind == "sample" else record.code
        elif reference and reference["kind"] == "experiments":
            step["arguments"] = {"left": reference["left"], "right": reference["right"]}
    return plan


def turn_descriptor(user, message, reply):
    entry = {"question": message, "kind": "unavailable", "interaction_id": reply.get("interaction_id")}
    if reply.get("response_type") == "general" and reply.get("llm_enabled"):
        entry.update(kind="general", answer=reply["answer"][:8000])
    elif reply.get("page_read_reference"):
        entry.update(kind="page_read", reference=copy.deepcopy(reply["page_read_reference"]))
    elif reply.get("workflow_plan"):
        entry.update(kind="workflow_guide", sample_id=reply["workflow_plan"]["sample_id"])
    elif reply.get("daily_work"):
        entry.update(kind="daily_work", scope=copy.deepcopy(reply["daily_work"]["scope"]))
    elif reply.get("project_investigation"):
        entry.update(kind="project_investigation", spec=copy.deepcopy(reply["project_investigation"]["spec"]))
    elif reply.get("read_plan_spec"):
        from .read_plan_memory import recall
        state = recall(reply.get("context", {}), user)
        if state:
            entry.update(kind="read", plan=copy.deepcopy(state["plan"]))
            # Store stable server-resolved target identities; never stale values.
            for step, result in zip(entry["plan"]["steps"], reply["read_plan"]["steps"]):
                step["saved_reference"] = result.get("reference")
            entry["trail"] = [_save_references(plan, user) for plan in state.get("trail", [])]
    return entry


def turn_token(user, message, reply):
    return signing.dumps({"user": user.pk, "turn": turn_descriptor(user, message, reply)},
                         salt="assistant.saved-turn.v1", compress=True)


def save_turn(conversation_id, user, message, reply):
    """Only server-produced replies reach this function; clients cannot submit turns."""
    if not conversation_id:
        return
    entry = turn_descriptor(user, message, reply)
    with transaction.atomic():
        conversation = get_object_or_404(AssistantConversation.objects.select_for_update(), pk=conversation_id, owner=user)
        conversation.turns = (conversation.turns + [entry])[-20:]
        conversation.save(update_fields=["turns", "updated_at"])


def restore(conversation, user):
    from .read_plans import handle_read_plan
    from .read_plan_memory import KEY, remember
    from .general_conversation import CONTEXT_KEY, remember_exchange
    context, history, general = {}, [], []
    for turn in conversation.turns:
        history.append({"role": "user", "content": turn["question"]})
        if turn["kind"] == "page_read":
            from .page_context import restore_page_read
            reply = restore_page_read(turn["reference"], user)
            context = reply.get("context", {})
            general = []
            reply["save_turn_token"] = turn_token(user, turn["question"], reply)
            history.append({"role": "assistant", "reply": reply})
        elif turn["kind"] == "workflow_guide":
            from .workflow_guide import guide_reply
            from .sample_operations import _sample_queryset
            sample = _sample_queryset(user).filter(pk=turn["sample_id"]).first()
            reply = guide_reply(sample, user) if sample else {"answer": "Earlier workflow records are unavailable or no longer accessible.", "context": {}}
            context, general = reply.get("context", {}), []
            reply["save_turn_token"] = turn_token(user, turn["question"], reply)
            history.append({"role": "assistant", "reply": reply})
        elif turn["kind"] in {"daily_work", "project_investigation"}:
            try:
                if turn["kind"] == "daily_work":
                    from .daily_work import daily_reply
                    reply = daily_reply(user, {**turn["scope"], "offset": 0})
                else:
                    from .project_investigations import investigation_reply
                    reply = investigation_reply(turn["spec"], user)
            except (ValueError, ValidationError):
                reply = {"answer": "Earlier work/investigation records are unavailable or no longer accessible.", "context": {}}
            context, general = reply.get("context", {}), []
            reply["save_turn_token"] = turn_token(user, turn["question"], reply)
            history.append({"role": "assistant", "reply": reply})
        elif turn["kind"] == "read":
            plan = _restore_references(turn["plan"], user)
            if plan:
                trail = [restored for candidate in turn.get("trail", []) if (restored := _restore_references(candidate, user))]
                token = remember(plan, [], user, previous={"plan": plan, "trail": trail})
                # Signed server references permit replay without relying on old labels.
                reply = handle_read_plan("refresh saved read", user, context={KEY: token}, restored_plan=True)
            else:
                reply = {"answer": "Earlier laboratory records are unavailable or no longer accessible.", "context": {}}
            context = reply.get("context", {})
            general = []
            reply["save_turn_token"] = turn_token(user, turn["question"], reply)
            history.append({"role": "assistant", "reply": reply})
        elif turn["kind"] == "general":
            general = (general + [{"role": "user", "content": turn["question"]}, {"role": "assistant", "content": turn["answer"]}])[-8:]
            context = {}
            token = remember_exchange(user, general[:-2], turn["question"], turn["answer"])
            if token:
                context[CONTEXT_KEY] = token
            history.append({"role": "assistant", "content": turn["answer"], "saveToken": signing.dumps(
                {"user": user.pk, "turn": turn}, salt="assistant.saved-turn.v1", compress=True)})
        else:
            context, general = {}, []
            history.append({"role": "assistant", "content": "Ask this question again to fetch current information or prepare a new action preview."})
    return {"id": str(conversation.pk), "name": conversation.name, "history": history, "context": context}


class ConversationsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=ConversationInfoSerializer(many=True))
    def get(self, request):
        return Response(list(AssistantConversation.objects.filter(owner=request.user).values("id", "name", "updated_at")[:50]))

    @extend_schema(request=ConversationSerializer, responses={201: ConversationInfoSerializer})
    def post(self, request):
        serializer = ConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        turns = []
        for token in serializer.validated_data.get("turn_tokens", []):
            try:
                state = signing.loads(token, salt="assistant.saved-turn.v1", max_age=86400)
                if state.get("user") != request.user.pk:
                    raise ValueError()
                turns.append(state["turn"])
            except (signing.BadSignature, ValueError, KeyError, TypeError, AttributeError):
                return Response({"detail": "An earlier message has expired. Start a new saved conversation."}, status=400)
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            owned = AssistantConversation.objects.filter(owner=request.user)
            if owned.count() >= 50:
                return Response({"detail": "You can save up to 50 conversations. Delete one to add another."}, status=400)
            if owned.filter(name=serializer.validated_data["name"]).exists():
                return Response({"detail": "Choose a different conversation name."}, status=400)
            conversation = AssistantConversation.objects.create(owner=request.user, name=serializer.validated_data["name"], turns=turns)
        return Response({"id": str(conversation.pk), "name": conversation.name}, status=status.HTTP_201_CREATED)


class ConversationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk):
        return Response(restore(get_object_or_404(AssistantConversation, pk=pk, owner=request.user), request.user))

    @extend_schema(request=ConversationNameSerializer, responses=ConversationInfoSerializer)
    def patch(self, request, pk):
        serializer = ConversationNameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            conversation = get_object_or_404(AssistantConversation.objects.select_for_update(), pk=pk, owner=request.user)
            if AssistantConversation.objects.filter(owner=request.user, name=serializer.validated_data["name"]).exclude(pk=pk).exists():
                return Response({"detail": "Choose a different conversation name."}, status=400)
            conversation.name = serializer.validated_data["name"]
            conversation.save(update_fields=["name", "updated_at"])
        return Response({"id": str(pk), "name": conversation.name})

    @extend_schema(request=None, responses={204: None})
    def delete(self, request, pk):
        conversation = get_object_or_404(AssistantConversation, pk=pk, owner=request.user)
        conversation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
