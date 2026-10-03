"""Administrators may restrict the supported lifecycle, never bypass its gates."""
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsAuthenticatedReadOnlyAdminWrite
from events.models import Event
from samples.workflows import ALLOWED_TRANSITIONS
from .models import SampleStatusPolicy


class PolicyConflict(APIException):
    status_code = 409
    default_detail = "The status policy changed. Reload it before saving your changes."


class PolicySerializer(serializers.Serializer):
    expected_revision = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=10, max_length=2000)
    transitions = serializers.JSONField()

    def validate_transitions(self, value):
        if not isinstance(value, dict) or set(value) != set(ALLOWED_TRANSITIONS):
            raise serializers.ValidationError("Include every supported status; custom status codes are not supported.")
        for source, targets in value.items():
            if not isinstance(targets, list) or any(not isinstance(target, str) for target in targets):
                raise serializers.ValidationError("Each status requires a list of destination status codes.")
            if len(targets) != len(set(targets)) or not set(targets).issubset(ALLOWED_TRANSITIONS[source]):
                raise serializers.ValidationError(f"Unsupported or duplicate transition from {source}. QC bypasses and backward transitions are not allowed.")
            if source != "ARCHIVED" and not targets:
                raise serializers.ValidationError(f"Keep at least one destination for {source} so samples are not stranded.")
        # Normalize order for predictable UI/audit payloads.
        return {source: [target for target in allowed if target in value[source]] for source, allowed in ALLOWED_TRANSITIONS.items()}


def representation(policy):
    return {"revision": policy.revision if policy else 1,
            "transitions": policy.transitions if policy and policy.transitions else ALLOWED_TRANSITIONS,
            "supported_transitions": ALLOWED_TRANSITIONS}


class SampleStatusPolicyView(APIView):
    permission_classes = [IsAuthenticatedReadOnlyAdminWrite]

    def get(self, request):
        return Response(representation(SampleStatusPolicy.objects.filter(pk=1).first()))

    @transaction.atomic
    def patch(self, request):
        serializer = PolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        SampleStatusPolicy.objects.get_or_create(pk=1)
        policy = SampleStatusPolicy.objects.select_for_update().get(pk=1)
        values = serializer.validated_data
        if values["expected_revision"] != policy.revision:
            raise PolicyConflict()
        before = representation(policy)
        policy.transitions = values["transitions"]
        policy.revision += 1
        policy.save(update_fields=["transitions", "revision"])
        after = representation(policy)
        Event.objects.create(entity_type="SampleStatusPolicy", entity_id="1", action="SAMPLE_STATUS_POLICY_UPDATED",
                             actor=request.user, payload={"reason": values["reason"], "before": before, "after": after})
        return Response(after)
