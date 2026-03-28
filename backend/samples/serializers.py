from rest_framework import serializers
from .models import Sample


class SampleSerializer(serializers.ModelSerializer):
    container_id = serializers.IntegerField(source="container.id", read_only=True)
    container_code = serializers.CharField(source="container.container_id", read_only=True)
    location_id = serializers.IntegerField(source="container.location.id", read_only=True)
    location_name = serializers.CharField(source="container.location.name", read_only=True)

    class Meta:
        model = Sample
        fields = [
            "id",
            "sample_id",
            "status",
            "container",
            "container_id",
            "container_code",
            "location_id",
            "location_name",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "container_id",
            "container_code",
            "location_id",
            "location_name",
            "created_at",
        ]
