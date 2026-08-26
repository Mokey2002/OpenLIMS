from django.db import transaction
from rest_framework import serializers

from core.project_access import user_can_access_project
from registry.models import RegistryRecord
from registry.services import registry_records_for_user, user_can_write_record

from .molecular import gc_content, molecular_weight, validate_alphabet
from .models import (
    AssemblyFragment,
    ConstructAssemblyPlan,
    Sequence,
    SequenceFeature,
    SequenceFeatureLibrary,
    SequenceRevision,
    SequenceRevisionFeature,
)
from .services import create_sequence_revision


class SequenceFeatureSerializer(serializers.ModelSerializer):
    library_feature_public_id = serializers.UUIDField(
        source="library_feature.public_id", read_only=True, allow_null=True
    )

    class Meta:
        model = SequenceFeature
        fields = [
            "id", "feature_type", "name", "start", "end", "direction", "color",
            "metadata", "library_feature", "library_feature_public_id",
            "primer_sequence", "melting_temperature", "gc_content", "created_at",
        ]
        read_only_fields = [
            "id", "library_feature_public_id", "primer_sequence",
            "melting_temperature", "gc_content", "created_at",
        ]

    def validate(self, attrs):
        start = attrs.get("start", getattr(self.instance, "start", None))
        end = attrs.get("end", getattr(self.instance, "end", None))
        if start is not None and end is not None and end <= start:
            raise serializers.ValidationError({"end": "End must be greater than start."})
        direction = attrs.get("direction", getattr(self.instance, "direction", 1))
        if direction not in {-1, 1}:
            raise serializers.ValidationError({"direction": "Choose 1 or -1."})
        return attrs


class SequenceRevisionFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = SequenceRevisionFeature
        fields = [
            "public_id", "feature_type", "name", "start", "end", "direction",
            "color", "metadata", "library_feature", "primer_sequence",
            "melting_temperature", "gc_content",
        ]
        read_only_fields = fields


class SequenceRevisionSerializer(serializers.ModelSerializer):
    features = SequenceRevisionFeatureSerializer(many=True, read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    registry_record_public_id = serializers.UUIDField(
        source="registry_record.public_id", read_only=True, allow_null=True
    )
    registry_id = serializers.CharField(
        source="registry_record.registry_id", read_only=True, allow_null=True
    )
    length = serializers.SerializerMethodField()
    gc_content = serializers.SerializerMethodField()
    molecular_weight = serializers.SerializerMethodField()

    class Meta:
        model = SequenceRevision
        fields = [
            "id", "public_id", "revision", "sequence_type", "topology", "sequence",
            "checksum", "change_summary", "registry_record", "registry_record_public_id",
            "registry_id", "source_metadata", "features", "length", "gc_content",
            "molecular_weight", "created_by", "created_by_username", "created_at",
        ]
        read_only_fields = fields

    def get_length(self, obj):
        return len(obj.sequence)

    def get_gc_content(self, obj):
        return gc_content(obj.sequence) if obj.sequence_type in {"DNA", "RNA"} else None

    def get_molecular_weight(self, obj):
        return molecular_weight(obj.sequence, obj.sequence_type)


class SequenceSerializer(serializers.ModelSerializer):
    features = SequenceFeatureSerializer(many=True, required=False)
    revisions = SequenceRevisionSerializer(many=True, read_only=True)
    registry_record = serializers.PrimaryKeyRelatedField(
        queryset=RegistryRecord.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    change_summary = serializers.CharField(write_only=True, required=False, allow_blank=True)
    project_code = serializers.CharField(source="project.code", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True)
    sample_code = serializers.CharField(source="sample.sample_id", read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    current_revision_public_id = serializers.UUIDField(
        source="current_revision.public_id", read_only=True, allow_null=True
    )
    checksum = serializers.CharField(source="current_revision.checksum", read_only=True)
    gc_content = serializers.SerializerMethodField()
    molecular_weight = serializers.SerializerMethodField()

    class Meta:
        model = Sequence
        fields = [
            "id", "public_id", "name", "description", "sequence_type", "topology",
            "sequence", "project", "project_code", "project_name", "sample", "sample_code",
            "import_job", "source_type", "source_metadata", "viewer", "show_complement",
            "rotate_on_scroll", "zoom", "enzymes", "bp_colors", "features", "revisions",
            "current_revision", "current_revision_public_id", "checksum", "registry_record",
            "change_summary", "gc_content", "molecular_weight", "created_by",
            "created_by_username", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "public_id", "created_by", "created_by_username", "import_job",
            "source_type", "source_metadata", "current_revision", "current_revision_public_id",
            "checksum", "revisions", "gc_content", "molecular_weight", "created_at", "updated_at",
        ]

    def get_gc_content(self, obj):
        return gc_content(obj.sequence) if obj.sequence_type in {"DNA", "RNA"} else None

    def get_molecular_weight(self, obj):
        return molecular_weight(obj.sequence, obj.sequence_type)

    def validate_project(self, project):
        if project and not user_can_access_project(self.context["request"].user, project, write=True):
            raise serializers.ValidationError("You cannot write sequences in this project.")
        return project

    def validate(self, attrs):
        sequence_type = attrs.get("sequence_type", getattr(self.instance, "sequence_type", "DNA"))
        raw_sequence = attrs.get("sequence", getattr(self.instance, "sequence", ""))
        try:
            attrs["sequence"] = validate_alphabet(raw_sequence, sequence_type)
        except ValueError as exc:
            raise serializers.ValidationError({"sequence": str(exc)}) from exc
        features = attrs.get("features")
        if features is not None:
            length = len(attrs["sequence"])
            for index, feature in enumerate(features):
                if feature["end"] > length:
                    raise serializers.ValidationError(
                        {"features": {index: {"end": "Feature exceeds sequence length."}}}
                    )
        registry_record = attrs.get("registry_record")
        project = attrs.get("project", getattr(self.instance, "project", None))
        if registry_record and registry_record.project_id and project and registry_record.project_id != project.id:
            raise serializers.ValidationError(
                {"registry_record": "The registry record and sequence must share a project."}
            )
        if registry_record and (
            not registry_records_for_user(self.context["request"].user).filter(pk=registry_record.pk).exists()
            or not user_can_write_record(self.context["request"].user, registry_record)
        ):
            raise serializers.ValidationError(
                {"registry_record": "You cannot link revisions to this registry record."}
            )
        return attrs

    def _replace_features(self, sequence_record, features_data):
        sequence_record.features.all().delete()
        for feature_data in features_data:
            SequenceFeature.objects.create(sequence_record=sequence_record, **feature_data)

    @transaction.atomic
    def create(self, validated_data):
        features_data = validated_data.pop("features", [])
        registry_record = validated_data.pop("registry_record", None)
        change_summary = validated_data.pop("change_summary", "Initial revision")
        request = self.context.get("request")
        # File import provenance is supplied by the trusted import endpoint. Keep
        # these fields read-only for ordinary API clients while snapshotting the
        # original GenBank/FASTA metadata in revision 1.
        if "import_source_metadata" in self.context:
            validated_data["source_metadata"] = self.context["import_source_metadata"]
            validated_data["source_type"] = self.context.get("import_source_type", "MANUAL")
        if request and request.user.is_authenticated:
            validated_data["created_by"] = request.user
        sequence_record = Sequence.objects.create(**validated_data)
        self._replace_features(sequence_record, features_data)
        create_sequence_revision(
            sequence_record,
            actor=request.user,
            change_summary=change_summary or "Initial revision",
            registry_record=registry_record,
            audit_action="SEQUENCE_WORKSPACE_CREATED",
        )
        return sequence_record

    @transaction.atomic
    def update(self, instance, validated_data):
        features_data = validated_data.pop("features", None)
        registry_marker = object()
        registry_record = validated_data.pop("registry_record", registry_marker)
        change_summary = validated_data.pop("change_summary", "")
        before = (instance.sequence_type, instance.topology, instance.sequence)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if features_data is not None:
            self._replace_features(instance, features_data)
        molecular_changed = before != (instance.sequence_type, instance.topology, instance.sequence)
        if features_data is not None or molecular_changed or registry_record is not registry_marker:
            linked_record = (
                registry_record
                if registry_record is not registry_marker
                else (instance.current_revision.registry_record if instance.current_revision else None)
            )
            create_sequence_revision(
                instance,
                actor=self.context["request"].user,
                change_summary=change_summary or "Molecular workspace updated",
                registry_record=linked_record,
            )
        return instance


class SequenceFeatureLibrarySerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = SequenceFeatureLibrary
        fields = [
            "id", "public_id", "name", "feature_type", "sequence_type", "motif",
            "color", "qualifiers", "project", "created_by", "created_by_username", "created_at",
        ]
        read_only_fields = ["id", "public_id", "created_by", "created_by_username", "created_at"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class AssemblyFragmentSerializer(serializers.ModelSerializer):
    source_revision_public_id = serializers.UUIDField(source="source_revision.public_id", read_only=True)

    class Meta:
        model = AssemblyFragment
        fields = [
            "id", "public_id", "source_revision", "source_revision_public_id", "order",
            "start", "end", "reverse_complement", "left_overhang", "right_overhang",
        ]
        read_only_fields = ["id", "public_id", "source_revision_public_id"]

    def validate(self, attrs):
        revision = attrs.get("source_revision")
        start = attrs.get("start", 0)
        end = attrs.get("end") or len(revision.sequence)
        if revision.sequence_type != "DNA":
            raise serializers.ValidationError({"source_revision": "Assembly currently supports DNA fragments."})
        if start >= end or end > len(revision.sequence):
            raise serializers.ValidationError("Choose a valid source revision range.")
        attrs["end"] = end
        return attrs


class ConstructAssemblyPlanSerializer(serializers.ModelSerializer):
    fragments = AssemblyFragmentSerializer(many=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = ConstructAssemblyPlan
        fields = [
            "id", "public_id", "name", "target_sequence", "method", "cloning_notes",
            "status", "fragments", "created_by", "created_by_username", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "public_id", "status", "created_by", "created_by_username", "created_at", "updated_at",
        ]

    @transaction.atomic
    def create(self, validated_data):
        fragments = validated_data.pop("fragments")
        validated_data["created_by"] = self.context["request"].user
        plan = ConstructAssemblyPlan.objects.create(**validated_data)
        for fragment in fragments:
            AssemblyFragment.objects.create(plan=plan, **fragment)
        return plan
