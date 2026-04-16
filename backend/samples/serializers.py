from rest_framework import serializers
from .models import Sample, SingleSampleAttachment


class SampleSerializer(serializers.ModelSerializer):
    container_id = serializers.SerializerMethodField()
    container_code = serializers.SerializerMethodField()
    location_id = serializers.SerializerMethodField()
    location_name = serializers.SerializerMethodField()

    project_id = serializers.SerializerMethodField()
    project_name = serializers.SerializerMethodField()
    project_code = serializers.SerializerMethodField()

    class Meta:
        model = Sample
        fields = [
            "id",
            "sample_id",
            "status",
            "project",
            "project_id",
            "project_name",
            "project_code",
            "container",
            "container_id",
            "container_code",
            "location_id",
            "location_name",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "project_id",
            "project_name",
            "project_code",
            "container_id",
            "container_code",
            "location_id",
            "location_name",
            "created_at",
        ]

    def get_project_id(self, obj):
        return obj.project.id if obj.project else None

    def get_project_name(self, obj):
        return obj.project.name if obj.project else None

    def get_project_code(self, obj):
        return obj.project.code if obj.project else None

    def get_container_id(self, obj):
        return obj.container.id if obj.container else None

    def get_container_code(self, obj):
        return obj.container.container_id if obj.container else None

    def get_location_id(self, obj):
        return obj.container.location.id if obj.container and obj.container.location else None

    def get_location_name(self, obj):
        return obj.container.location.name if obj.container and obj.container.location else None
class SingleSampleAttachmentSerializer(serializers.ModelSerializer):
    filename = serializers.SerializerMethodField()
    uploaded_by_username = serializers.SerializerMethodField()

    class Meta:
        model = SingleSampleAttachment
        fields = [
            "id",
            "sample",
            "file",
            "filename",
            "uploaded_by",
            "uploaded_by_username",
            "uploaded_at",
        ]
        read_only_fields = [
            "id",
            "filename",
            "uploaded_by",
            "uploaded_by_username",
            "uploaded_at",
        ]

    def get_filename(self, obj):
        return obj.file.name.split("/")[-1]

    def get_uploaded_by_username(self, obj):
        return obj.uploaded_by.username if obj.uploaded_by else None
