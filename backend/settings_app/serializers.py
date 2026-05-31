from rest_framework import serializers

from .models import SystemSettings


class SystemSettingsSerializer(serializers.ModelSerializer):
    updated_by_username = serializers.CharField(
        source="updated_by.username",
        read_only=True,
    )

    class Meta:
        model = SystemSettings
        fields = [
            "id",
            "lab_name",
            "organization_name",
            "default_timezone",
            "default_sample_status",
            "max_upload_size_mb",
            "require_import_preview",
            "allowed_fasta_extensions",
            "alignments_enabled",
            "max_sequences_per_alignment",
            "max_sequence_length",
            "viewer_read_only",
            "require_audit_reason",
            "updated_by",
            "updated_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "updated_by",
            "updated_by_username",
            "created_at",
            "updated_at",
        ]

    def validate_max_upload_size_mb(self, value):
        if value < 1:
            raise serializers.ValidationError("Upload size must be at least 1 MB.")

        if value > 500:
            raise serializers.ValidationError("Upload size cannot exceed 500 MB.")

        return value

    def validate_max_sequences_per_alignment(self, value):
        if value < 2:
            raise serializers.ValidationError(
                "At least 2 sequences must be allowed per alignment."
            )

        if value > 1000:
            raise serializers.ValidationError(
                "Maximum sequences per alignment cannot exceed 1000."
            )

        return value

    def validate_max_sequence_length(self, value):
        if value < 100:
            raise serializers.ValidationError(
                "Maximum sequence length must be at least 100."
            )

        return value

    def validate_allowed_fasta_extensions(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Allowed FASTA extensions must be a list.")

        cleaned = []

        for item in value:
            extension = str(item).strip().lower()

            if not extension:
                continue

            if not extension.startswith("."):
                extension = f".{extension}"

            cleaned.append(extension)

        if not cleaned:
            raise serializers.ValidationError(
                "At least one FASTA extension is required."
            )

        return sorted(set(cleaned))

