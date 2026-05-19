from rest_framework import serializers
from .workflows import can_transition


class SampleTransitionSerializer(serializers.Serializer):
    new_status = serializers.CharField()

    def validate(self, attrs):
        sample = self.context["sample"]
        new_status = attrs["new_status"]

        if not can_transition(sample.status, new_status):
            raise serializers.ValidationError(
                {"new_status": f"Invalid transition from {sample.status} to {new_status}"}
            )

        return attrs
