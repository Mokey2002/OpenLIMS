from rest_framework import serializers
from .models import Location, Container

class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ["id", "name", "kind"]
        read_only_fields = ["id"]


class ContainerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Container
        fields = ["id", "container_id", "kind", "location"]
        read_only_fields = ["id"]
