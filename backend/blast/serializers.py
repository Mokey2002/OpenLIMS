from rest_framework import serializers

from sequences.models import Sequence

from .models import BlastDatabase, BlastHit, BlastJob


class BlastDatabaseSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    class Meta:
        model = BlastDatabase
        fields = [
            "id",
            "name",
            "description",
            "database_type",
            "source_fasta",
            "db_path",
            "status",
            "error_message",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "db_path",
            "status",
            "error_message",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]


class BlastHitSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlastHit
        fields = [
            "id",
            "rank",
            "hit_id",
            "hit_def",
            "accession",
            "hit_length",
            "bit_score",
            "evalue",
            "identity_percent",
            "alignment_length",
            "query_from",
            "query_to",
            "hit_from",
            "hit_to",
            "query_aligned",
            "hit_aligned",
            "midline",
            "created_at",
        ]
        read_only_fields = fields


class BlastJobSerializer(serializers.ModelSerializer):
    hits = BlastHitSerializer(many=True, read_only=True)

    project_code = serializers.CharField(
        source="project.code",
        read_only=True,
    )
    project_name = serializers.CharField(
        source="project.name",
        read_only=True,
    )
    query_sequence_name = serializers.CharField(
        source="query_sequence.name",
        read_only=True,
    )
    query_sequence_type = serializers.CharField(
        source="query_sequence.sequence_type",
        read_only=True,
    )
    database_name = serializers.CharField(
        source="database.name",
        read_only=True,
    )
    database_type = serializers.CharField(
        source="database.database_type",
        read_only=True,
    )
    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    class Meta:
        model = BlastJob
        fields = [
            "id",
            "name",
            "project",
            "project_code",
            "project_name",
            "query_sequence",
            "query_sequence_name",
            "query_sequence_type",
            "database",
            "database_name",
            "database_type",
            "program",
            "status",
            "max_target_seqs",
            "evalue",
            "query_fasta",
            "result_json",
            "hits_count",
            "error_message",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
            "hits",
        ]
        read_only_fields = [
            "id",
            "project_code",
            "project_name",
            "query_sequence_name",
            "query_sequence_type",
            "database_name",
            "database_type",
            "status",
            "query_fasta",
            "result_json",
            "hits_count",
            "error_message",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
            "hits",
        ]

    def validate(self, attrs):
        query_sequence = attrs.get(
            "query_sequence",
            getattr(self.instance, "query_sequence", None),
        )
        database = attrs.get(
            "database",
            getattr(self.instance, "database", None),
        )
        program = attrs.get(
            "program",
            getattr(self.instance, "program", BlastJob.PROGRAM_BLASTN),
        )

        if database and database.status != BlastDatabase.STATUS_READY:
            raise serializers.ValidationError(
                {"database": "The selected BLAST database is not ready."}
            )

        if query_sequence:
            if program == BlastJob.PROGRAM_BLASTN:
                if query_sequence.sequence_type not in ["DNA", "RNA"]:
                    raise serializers.ValidationError(
                        {"program": "blastn requires a DNA or RNA query sequence."}
                    )

            if program == BlastJob.PROGRAM_BLASTP:
                if query_sequence.sequence_type != "PROTEIN":
                    raise serializers.ValidationError(
                        {"program": "blastp requires a protein query sequence."}
                    )

        if database:
            if program == BlastJob.PROGRAM_BLASTN and database.database_type != "DNA":
                raise serializers.ValidationError(
                    {"database": "blastn requires a DNA BLAST database."}
                )

            if program == BlastJob.PROGRAM_BLASTP and database.database_type != "PROTEIN":
                raise serializers.ValidationError(
                    {"database": "blastp requires a protein BLAST database."}
                )

        return attrs

    def validate_query_sequence(self, value):
        if not isinstance(value, Sequence):
            raise serializers.ValidationError("Invalid query sequence.")

        if not value.sequence:
            raise serializers.ValidationError("Query sequence cannot be empty.")

        return value
