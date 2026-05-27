from rest_framework import serializers

from sequences.models import Sequence

from .models import AlignmentJob


class AlignmentJobSerializer(serializers.ModelSerializer):
    sequence_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
    )

    project_code = serializers.CharField(source="project.code", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True)
    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )
    sequence_count = serializers.SerializerMethodField()

    class Meta:
        model = AlignmentJob
        fields = [
            "id",
            "name",
            "project",
            "project_code",
            "project_name",
            "sequence_ids",
            "sequence_count",
            "tool",
            "status",
            "input_fasta",
            "aligned_fasta",
            "summary",
            "error_message",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "sequence_count",
            "status",
            "input_fasta",
            "aligned_fasta",
            "summary",
            "error_message",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]

    def get_sequence_count(self, obj):
        return obj.sequences.count()

    def validate_tool(self, value):
        if value != "CLUSTAL_OMEGA":
            raise serializers.ValidationError("Only CLUSTAL_OMEGA is supported right now.")

        return value

    def validate_sequence_ids(self, value):
        if len(value) < 2:
            raise serializers.ValidationError("Select at least 2 sequences to align.")

        unique_ids = list(dict.fromkeys(value))

        if len(unique_ids) != len(value):
            raise serializers.ValidationError("Duplicate sequence IDs are not allowed.")

        sequences = list(Sequence.objects.filter(id__in=unique_ids))

        if len(sequences) != len(unique_ids):
            found_ids = {sequence.id for sequence in sequences}
            missing = [sequence_id for sequence_id in unique_ids if sequence_id not in found_ids]
            raise serializers.ValidationError(f"Sequences not found: {missing}")

        sequence_types = {sequence.sequence_type for sequence in sequences}

        if len(sequence_types) > 1:
            raise serializers.ValidationError(
                "All selected sequences must have the same sequence type."
            )

        return unique_ids
