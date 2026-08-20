from rest_framework import serializers
from .models import Sample, SampleBatch, SingleSampleAttachment
from .access import user_can_modify_sample


class SampleSerializer(serializers.ModelSerializer):
    container_id = serializers.SerializerMethodField()
    container_code = serializers.SerializerMethodField()
    location_id = serializers.SerializerMethodField()
    location_name = serializers.SerializerMethodField()

    project_id = serializers.SerializerMethodField()
    project_name = serializers.SerializerMethodField()
    project_code = serializers.SerializerMethodField()
    linked_project_summaries = serializers.SerializerMethodField()
    created_by_username = serializers.SerializerMethodField()
    can_modify = serializers.SerializerMethodField()
    batch_code = serializers.SerializerMethodField()
    assigned_to_username = serializers.SerializerMethodField()

    class Meta:
        model = Sample
        fields = [
            "id",
            "sample_id",
            "sample_type",
            "status",
            "project",
            "project_id",
            "project_name",
            "project_code",
            "linked_projects",
            "linked_project_summaries",
            "container",
            "container_id",
            "container_code",
            "batch",
            "batch_code",
            "assigned_to",
            "assigned_to_username",
            "location_id",
            "location_name",
            "created_by",
            "created_by_username",
            "can_modify",
            "created_at",
            "status_changed_at",
            "updated_at",
        ]

    def validate_sample_type(self, value):
        normalized = str(value or "GENERAL").strip().upper()
        if not normalized:
            return "GENERAL"
        return normalized
        read_only_fields = [
            "id",
            "project_id",
            "project_name",
            "project_code",
            "linked_project_summaries",
            "container_id",
            "container_code",
            "batch",
            "batch_code",
            "assigned_to",
            "assigned_to_username",
            "location_id",
            "location_name",
            "created_by",
            "created_by_username",
            "can_modify",
            "created_at",
            "status_changed_at",
            "updated_at",
        ]

    def get_linked_project_summaries(self, obj):
        return [
            {
                "id": project.id,
                "code": project.code,
                "name": project.name,
            }
            for project in obj.linked_projects.all().order_by("code")
        ]

    def get_can_modify(self, obj):
        request = self.context.get("request")
        user = request.user if request else None
        return user_can_modify_sample(user, obj)

    def get_created_by_username(self, obj):
        return obj.created_by.username if obj.created_by else None

    def get_batch_code(self, obj):
        return obj.batch.code if obj.batch else None

    def get_assigned_to_username(self, obj):
        return obj.assigned_to.username if obj.assigned_to else None

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


class SampleBatchSerializer(serializers.ModelSerializer):
    project_code = serializers.CharField(source="project.code", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True)
    sample_count = serializers.IntegerField(source="samples.count", read_only=True)

    class Meta:
        model = SampleBatch
        fields = [
            "id",
            "code",
            "project",
            "project_code",
            "project_name",
            "sample_count",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "project_code",
            "project_name",
            "sample_count",
            "created_by",
            "created_at",
            "updated_at",
        ]
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
