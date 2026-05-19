from rest_framework import serializers
from .models import Location, Container


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ["id", "name", "kind"]


class ContainerSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source="location.name", read_only=True)
    sample_count = serializers.SerializerMethodField()
    sample_ids = serializers.SerializerMethodField()

    class Meta:
        model = Container
        fields = [
            "id",
            "container_id",
            "kind",
            "location",
            "location_name",
            "sample_count",
            "sample_ids",
        ]

    def get_sample_count(self, obj):
        return obj.samples.count()

    def get_sample_ids(self, obj):
        return list(obj.samples.values_list("sample_id", flat=True))
