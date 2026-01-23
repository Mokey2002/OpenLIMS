from rest_framework import serializers
from .models import Sample

class SampleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sample
        fields = ["id", "sample_id", "status", "created_at"]
        read_only_fields = ["id", "created_at"]
