from rest_framework import serializers
from .models import Project


class ProjectSerializer(serializers.ModelSerializer):
    sample_count = serializers.IntegerField(source="samples.count", read_only=True)

    class Meta:
        model = Project
        fields = ["id", "name", "code", "description", "created_at", "sample_count"]
        read_only_fields = ["id", "created_at", "sample_count"]
