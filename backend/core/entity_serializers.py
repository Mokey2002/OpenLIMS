import hashlib
import os

from django.contrib.contenttypes.models import ContentType
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.entities import (
    entity_is_globally_scoped,
    entity_reference,
    get_entity_project,
    resolve_entity,
    supported_entity_types,
)
from core.models import EntityLink, SharedAttachment
from core.upload_validators import validate_uploaded_file
from settings_app.models import SystemSettings


SHARED_ATTACHMENT_EXTENSIONS = {
    ".csv",
    ".docx",
    ".fa",
    ".fasta",
    ".fna",
    ".gb",
    ".gbk",
    ".jpeg",
    ".jpg",
    ".json",
    ".pdf",
    ".png",
    ".svg",
    ".txt",
    ".xlsx",
}


class ProjectReferenceSerializer(serializers.Serializer):
    public_id = serializers.UUIDField()
    code = serializers.CharField()
    name = serializers.CharField()


class EntityReferenceSerializer(serializers.Serializer):
    type = serializers.CharField()
    public_id = serializers.UUIDField()
    label = serializers.CharField()
    project = ProjectReferenceSerializer(allow_null=True)


def _resolve_for_request(entity_type, public_id, request, *, write=False):
    try:
        return resolve_entity(entity_type, public_id, request.user, write=write)
    except ValueError as exc:
        raise serializers.ValidationError(str(exc)) from exc
    except LookupError as exc:
        raise serializers.ValidationError(str(exc)) from exc
    except PermissionError as exc:
        raise serializers.ValidationError(str(exc)) from exc


class EntityLinkSerializer(serializers.ModelSerializer):
    source_type = serializers.ChoiceField(
        choices=[(item, item) for item in supported_entity_types()],
        write_only=True,
    )
    source_public_id = serializers.UUIDField(write_only=True)
    target_type = serializers.ChoiceField(
        choices=[(item, item) for item in supported_entity_types()],
        write_only=True,
    )
    target_public_id = serializers.UUIDField(write_only=True)
    source = serializers.SerializerMethodField()
    target = serializers.SerializerMethodField()
    project_public_id = serializers.UUIDField(source="project.public_id", read_only=True)
    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
        allow_null=True,
        default=None,
    )

    class Meta:
        model = EntityLink
        fields = [
            "id",
            "public_id",
            "source_type",
            "source_public_id",
            "target_type",
            "target_public_id",
            "source",
            "target",
            "relation_type",
            "label",
            "metadata",
            "project_public_id",
            "created_by",
            "created_by_username",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "source",
            "target",
            "project_public_id",
            "created_by",
            "created_by_username",
            "created_at",
        ]

    def validate_relation_type(self, value):
        return str(value).strip().lower()

    def validate(self, attrs):
        request = self.context["request"]
        source = _resolve_for_request(
            attrs["source_type"],
            attrs["source_public_id"],
            request,
            write=True,
        )
        target = _resolve_for_request(
            attrs["target_type"],
            attrs["target_public_id"],
            request,
            write=True,
        )
        if source == target:
            raise serializers.ValidationError("An entity cannot link to itself.")

        source_project = get_entity_project(source)
        target_project = get_entity_project(target)
        for field, obj, project in [
            ("source", source, source_project),
            ("target", target, target_project),
        ]:
            if project is None and not entity_is_globally_scoped(obj):
                raise serializers.ValidationError(
                    {
                        field: (
                            "Project-scoped records must be assigned to a project "
                            "before they can use shared links."
                        )
                    }
                )
        if (
            source_project is not None
            and target_project is not None
            and source_project.pk != target_project.pk
        ):
            raise serializers.ValidationError(
                "Cross-project links require both records to share a primary project."
            )

        source_content_type = ContentType.objects.get_for_model(source)
        target_content_type = ContentType.objects.get_for_model(target)
        relation_type = attrs.get("relation_type", "")
        if EntityLink.objects.filter(
            source_content_type=source_content_type,
            source_object_id=str(source.pk),
            target_content_type=target_content_type,
            target_object_id=str(target.pk),
            relation_type=relation_type,
        ).exists():
            raise serializers.ValidationError(
                "This relationship already exists between these records."
            )

        self._source = source
        self._target = target
        self._project = source_project or target_project
        return attrs

    def create(self, validated_data):
        for key in [
            "source_type",
            "source_public_id",
            "target_type",
            "target_public_id",
        ]:
            validated_data.pop(key, None)
        return EntityLink.objects.create(
            source_content_type=ContentType.objects.get_for_model(self._source),
            source_object_id=str(self._source.pk),
            target_content_type=ContentType.objects.get_for_model(self._target),
            target_object_id=str(self._target.pk),
            project=self._project,
            created_by=self.context["request"].user,
            **validated_data,
        )

    @extend_schema_field(EntityReferenceSerializer)
    def get_source(self, obj):
        return entity_reference(obj.source_object) if obj.source_object else None

    @extend_schema_field(EntityReferenceSerializer)
    def get_target(self, obj):
        return entity_reference(obj.target_object) if obj.target_object else None


class SharedAttachmentSerializer(serializers.ModelSerializer):
    target_type = serializers.ChoiceField(
        choices=[(item, item) for item in supported_entity_types()],
        write_only=True,
    )
    target_public_id = serializers.UUIDField(write_only=True)
    target = serializers.SerializerMethodField()
    filename = serializers.CharField(read_only=True)
    project_public_id = serializers.UUIDField(source="project.public_id", read_only=True)
    uploaded_by_username = serializers.CharField(
        source="uploaded_by.username",
        read_only=True,
        allow_null=True,
        default=None,
    )

    class Meta:
        model = SharedAttachment
        fields = [
            "id",
            "public_id",
            "target_type",
            "target_public_id",
            "target",
            "file",
            "filename",
            "display_name",
            "description",
            "media_type",
            "size_bytes",
            "sha256",
            "project_public_id",
            "uploaded_by",
            "uploaded_by_username",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "target",
            "filename",
            "media_type",
            "size_bytes",
            "sha256",
            "project_public_id",
            "uploaded_by",
            "uploaded_by_username",
            "created_at",
        ]

    def validate_file(self, uploaded_file):
        max_size = SystemSettings.load().max_upload_size_mb * 1024 * 1024
        validate_uploaded_file(
            uploaded_file,
            sorted(SHARED_ATTACHMENT_EXTENSIONS),
            max_size_bytes=max_size,
        )
        return uploaded_file

    def validate(self, attrs):
        request = self.context["request"]
        self._target = _resolve_for_request(
            attrs["target_type"],
            attrs["target_public_id"],
            request,
            write=True,
        )
        if (
            get_entity_project(self._target) is None
            and not entity_is_globally_scoped(self._target)
        ):
            raise serializers.ValidationError(
                {
                    "target": (
                        "Project-scoped records must be assigned to a project "
                        "before they can use shared attachments."
                    )
                }
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop("target_type", None)
        validated_data.pop("target_public_id", None)
        uploaded_file = validated_data["file"]
        digest = hashlib.sha256()
        for chunk in uploaded_file.chunks():
            digest.update(chunk)
        uploaded_file.seek(0)

        if not validated_data.get("display_name"):
            validated_data["display_name"] = os.path.basename(uploaded_file.name)

        return SharedAttachment.objects.create(
            target_content_type=ContentType.objects.get_for_model(self._target),
            target_object_id=str(self._target.pk),
            project=get_entity_project(self._target),
            media_type=getattr(uploaded_file, "content_type", "") or "",
            size_bytes=uploaded_file.size,
            sha256=digest.hexdigest(),
            uploaded_by=self.context["request"].user,
            **validated_data,
        )

    @extend_schema_field(EntityReferenceSerializer)
    def get_target(self, obj):
        return entity_reference(obj.target_object) if obj.target_object else None
