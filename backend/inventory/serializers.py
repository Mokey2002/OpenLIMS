from rest_framework import serializers
from .models import Location, Container


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ["id", "name", "kind"]


class ContainerSerializer(serializers.ModelSerializer):
    sample_count = serializers.IntegerField(source="samples.count", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)

    class Meta:
        model = Container
        fields = [
            "id",
            "container_id",
            "kind",
            "location",
            "location_name",
            "sample_count",
        ]
