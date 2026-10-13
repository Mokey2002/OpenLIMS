"""Account-scoped saved workflow queries; saving never executes a query."""
from drf_spectacular.utils import extend_schema
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SavedWorkflowQuery
from .project_workflows import _recover_query
from .workflow_query import FILTERS


class WorkflowSettingsSerializer(serializers.Serializer):
    project_code = serializers.CharField(max_length=64)
    filters = serializers.ListField(child=serializers.ChoiceField(choices=sorted(FILTERS)), min_length=1, max_length=len(FILTERS))
    match = serializers.ChoiceField(choices=["all", "any"])
    scope = serializers.ChoiceField(choices=["sample", "step"])
    assignee = serializers.CharField(max_length=150, required=False, allow_blank=True)
    language = serializers.ChoiceField(choices=["en", "es"], default="en")


class SavedQuerySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    query = WorkflowSettingsSerializer()


class SavedQueryResponseSerializer(SavedQuerySerializer):
    id = serializers.IntegerField(read_only=True)


def serialize_saved(item):
    return {"id": item.pk, "name": item.name, "query": item.query}


class SavedWorkflowQueriesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=SavedQueryResponseSerializer(many=True))
    def get(self, request):
        return Response([serialize_saved(item) for item in SavedWorkflowQuery.objects.filter(owner=request.user)])

    @extend_schema(request=SavedQuerySerializer, responses={201: SavedQueryResponseSerializer})
    def post(self, request):
        serializer = SavedQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data["query"]
        # Resolve the builder's self shortcut before canonical access validation.
        if "assigned" in query["filters"] and query.get("assignee", "").casefold() in {"me", "mi", "mí"}:
            query["assignee"] = request.user.username
        validated = _recover_query(query, request.user, query["language"] == "es", "save")
        if validated is None:
            raise serializers.ValidationError({"query": "Query is invalid or its project/assignee is unavailable. / Consulta inválida o proyecto/responsable no disponible."})
        canonical = validated["context"]["project_workflows"]
        saved = {key: canonical[key] for key in ("project_code", "filters", "match", "scope", "language", "assignee") if key in canonical}
        with transaction.atomic():
            # Serialize this user's creates to enforce both the count and name cap.
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            owned = SavedWorkflowQuery.objects.filter(owner=request.user)
            name = serializer.validated_data["name"]
            if owned.filter(name=name).exists():
                raise serializers.ValidationError({"name": "Choose a different name. / Elige otro nombre."})
            if owned.count() >= 20:
                raise serializers.ValidationError({"name": "Limit: 20 saved questions. Delete one first. / Límite: 20 consultas. Elimina una primero."})
            item = SavedWorkflowQuery.objects.create(owner=request.user, name=name, query=saved)
        return Response(serialize_saved(item), status=status.HTTP_201_CREATED)


class SavedWorkflowQueryDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        item = get_object_or_404(SavedWorkflowQuery, pk=pk, owner=request.user)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
