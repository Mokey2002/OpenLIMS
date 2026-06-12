from rest_framework import serializers

from .models import MassSpecRun


class MassSpecRunSerializer(serializers.ModelSerializer):
    uploaded_by_username = serializers.SerializerMethodField()
    project_code = serializers.SerializerMethodField()
    sample_id_value = serializers.SerializerMethodField()

    class Meta:
        model = MassSpecRun
        fields = [
            "id",
            "name",
            "project",
            "project_code",
            "sample",
            "sample_id_value",
            "uploaded_file",
            "original_filename",
            "status",
            "error_message",
            "spectra_count",
            "ms1_count",
            "ms2_count",
            "rt_min",
            "rt_max",
            "mz_min",
            "mz_max",
            "chromatogram_data",
            "uploaded_by",
            "uploaded_by_username",
            "created_at",
            "processed_at",
        ]
        read_only_fields = [
            "id",
            "original_filename",
            "status",
            "error_message",
            "spectra_count",
            "ms1_count",
            "ms2_count",
            "rt_min",
            "rt_max",
            "mz_min",
            "mz_max",
            "chromatogram_data",
            "uploaded_by",
            "uploaded_by_username",
            "project_code",
            "sample_id_value",
            "created_at",
            "processed_at",
        ]

    def get_uploaded_by_username(self, obj):
        return obj.uploaded_by.username if obj.uploaded_by else None

    def get_project_code(self, obj):
        return obj.project.code if obj.project else None

    def get_sample_id_value(self, obj):
        return obj.sample.sample_id if obj.sample else None
