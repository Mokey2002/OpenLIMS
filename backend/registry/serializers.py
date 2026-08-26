from django.db import transaction
from rest_framework import serializers

from core.project_access import user_can_access_project
from core.entities import user_can_access_entity
from sequences.models import SequenceRevision

from .models import (
    RegistrationReview,
    RegistryAlias,
    RegistryRecord,
    RegistryRecordVersion,
    RegistryRelationship,
    RegistrySchema,
)
from .services import create_record_version, generate_registry_id, validate_schema_data


class RegistrySchemaSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = RegistrySchema
        fields = [
            "id", "public_id", "code", "name", "entity_type", "version",
            "id_prefix", "description", "schema", "matching_fields", "active",
            "created_by", "created_by_username", "created_at",
        ]
        read_only_fields = ["id", "public_id", "created_by", "created_by_username", "created_at"]

    def validate_schema(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Schema must be a JSON object.")
        if value.get("type", "object") != "object":
            raise serializers.ValidationError("Registry schemas must describe an object.")
        if not isinstance(value.get("properties", {}), dict):
            raise serializers.ValidationError("properties must be an object.")
        return value

    def validate_matching_fields(self, value):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise serializers.ValidationError("matching_fields must be a list of field names.")
        return list(dict.fromkeys(value))

    def validate(self, attrs):
        definition = attrs.get("schema", getattr(self.instance, "schema", {}))
        fields = attrs.get("matching_fields", getattr(self.instance, "matching_fields", []))
        unknown = [field for field in fields if field not in definition.get("properties", {})]
        if unknown:
            raise serializers.ValidationError({"matching_fields": f"Unknown fields: {', '.join(unknown)}"})
        if self.instance and self.instance.records.exists():
            mutable = {"active"}
            changed = {
                field for field, value in attrs.items()
                if field not in mutable and value != getattr(self.instance, field)
            }
            if changed:
                raise serializers.ValidationError(
                    "A schema used by records is immutable. Create a new schema version."
                )
        return attrs

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class RegistryAliasSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegistryAlias
        fields = ["id", "public_id", "alias", "alias_type", "created_at"]
        read_only_fields = ["id", "public_id", "created_at"]


class RegistryRecordVersionSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    sequence_revision_public_id = serializers.UUIDField(
        source="sequence_revision.public_id", read_only=True, allow_null=True
    )

    class Meta:
        model = RegistryRecordVersion
        fields = [
            "id", "public_id", "version", "schema", "data", "sequence_revision",
            "sequence_revision_public_id", "sequence_checksum", "change_summary",
            "created_by", "created_by_username", "created_at",
        ]
        read_only_fields = fields


class RegistrationReviewSerializer(serializers.ModelSerializer):
    requested_by_username = serializers.CharField(source="requested_by.username", read_only=True)
    reviewer_username = serializers.CharField(source="reviewer.username", read_only=True, allow_null=True)

    class Meta:
        model = RegistrationReview
        fields = [
            "id", "public_id", "record", "version", "requested_by",
            "requested_by_username", "reviewer", "reviewer_username", "decision",
            "comments", "requested_at", "reviewed_at",
        ]
        read_only_fields = fields


class RegistryRecordSerializer(serializers.ModelSerializer):
    aliases = RegistryAliasSerializer(many=True, required=False)
    versions = RegistryRecordVersionSerializer(many=True, read_only=True)
    reviews = RegistrationReviewSerializer(many=True, read_only=True)
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    project_code = serializers.CharField(source="project.code", read_only=True, allow_null=True)
    entity_type = serializers.CharField(source="schema.entity_type", read_only=True)
    schema_version = serializers.IntegerField(source="schema.version", read_only=True)
    data = serializers.JSONField(write_only=True, required=False, default=dict)
    sequence_revision = serializers.PrimaryKeyRelatedField(
        queryset=SequenceRevision.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = RegistryRecord
        fields = [
            "id", "public_id", "registry_id", "schema", "schema_version", "entity_type",
            "name", "description", "catalog_number", "external_identifiers", "tags",
            "project", "project_code", "owner", "owner_username", "visibility",
            "lifecycle_status", "current_version", "data", "sequence_revision",
            "aliases", "versions", "reviews", "registered_at", "retired_at",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "public_id", "schema_version", "entity_type", "owner",
            "owner_username", "lifecycle_status", "current_version", "versions",
            "reviews", "registered_at", "retired_at", "created_at", "updated_at",
        ]
        extra_kwargs = {"registry_id": {"required": False, "allow_blank": True}}

    def validate_project(self, project):
        if project and not user_can_access_project(
            self.context["request"].user, project, write=True
        ):
            raise serializers.ValidationError("You cannot write registry records in this project.")
        return project

    def validate(self, attrs):
        schema = attrs.get("schema", getattr(self.instance, "schema", None))
        data = attrs.get("data", None)
        if schema and not schema.active and not self.instance:
            raise serializers.ValidationError({"schema": "Choose an active registry schema."})
        if data is not None and schema:
            try:
                validate_schema_data(schema.schema, data)
            except ValueError as exc:
                detail = exc.args[0] if exc.args else str(exc)
                raise serializers.ValidationError({"data": detail}) from exc
        visibility = attrs.get("visibility", getattr(self.instance, "visibility", None))
        project = attrs.get("project", getattr(self.instance, "project", None))
        if visibility == RegistryRecord.VISIBILITY_PROJECT and not project:
            raise serializers.ValidationError({"project": "Project visibility requires a project."})
        aliases = attrs.get("aliases")
        if aliases is not None:
            normalized = [item.get("alias", "").strip().casefold() for item in aliases]
            if any(not item for item in normalized) or len(normalized) != len(set(normalized)):
                raise serializers.ValidationError({"aliases": "Aliases must be non-empty and unique."})
        revision = attrs.get("sequence_revision")
        if revision and not user_can_access_entity(
            self.context["request"].user,
            revision.sequence_record,
            write=True,
        ):
            raise serializers.ValidationError(
                {"sequence_revision": "You cannot link this sequence revision."}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        aliases = validated_data.pop("aliases", [])
        data = validated_data.pop("data", {})
        sequence_revision = validated_data.pop("sequence_revision", None)
        schema = validated_data["schema"]
        validated_data["owner"] = self.context["request"].user
        validated_data["registry_id"] = validated_data.get("registry_id") or generate_registry_id(schema)
        record = RegistryRecord.objects.create(**validated_data)
        for alias in aliases:
            RegistryAlias.objects.create(record=record, **alias)
        create_record_version(
            record,
            data=data,
            actor=self.context["request"].user,
            sequence_revision=sequence_revision,
            change_summary="Initial version",
            audit_action="REGISTRY_RECORD_CREATED",
        )
        return record

    @transaction.atomic
    def update(self, instance, validated_data):
        aliases = validated_data.pop("aliases", None)
        data = validated_data.pop("data", None)
        sequence_revision = validated_data.pop("sequence_revision", None)
        previous_schema = instance.schema
        previous_version = instance.current_version
        schema = validated_data.get("schema", instance.schema)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if aliases is not None:
            instance.aliases.all().delete()
            for alias in aliases:
                RegistryAlias.objects.create(record=instance, **alias)
        if data is not None or sequence_revision is not None or schema != previous_schema:
            create_record_version(
                instance,
                data=data if data is not None else (previous_version.data if previous_version else {}),
                actor=self.context["request"].user,
                schema=schema,
                sequence_revision=sequence_revision or (
                    previous_version.sequence_revision if previous_version else None
                ),
                change_summary="Updated through record API",
            )
        return instance


class RegistryRelationshipSerializer(serializers.ModelSerializer):
    source_registry_id = serializers.CharField(source="source.registry_id", read_only=True)
    target_registry_id = serializers.CharField(source="target.registry_id", read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = RegistryRelationship
        fields = [
            "id", "public_id", "source", "source_registry_id", "target",
            "target_registry_id", "relationship_type", "custom_type", "metadata",
            "created_by", "created_by_username", "created_at",
        ]
        read_only_fields = ["id", "public_id", "created_by", "created_by_username", "created_at"]

    def validate(self, attrs):
        source = attrs.get("source")
        target = attrs.get("target")
        if source == target:
            raise serializers.ValidationError("A registry record cannot relate to itself.")
        if source.project_id and target.project_id and source.project_id != target.project_id:
            raise serializers.ValidationError("Cross-project registry relationships are not allowed.")
        if attrs.get("relationship_type") == RegistryRelationship.RELATION_CUSTOM and not attrs.get("custom_type"):
            raise serializers.ValidationError({"custom_type": "This field is required."})
        return attrs

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)
