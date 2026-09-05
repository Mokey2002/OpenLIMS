from rest_framework import serializers
from .models import (
    Sample,
    SampleBatch,
    SampleCustodyEvent,
    SampleRelationship,
    SingleSampleAttachment,
)
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
    custodian_username = serializers.CharField(
        source="custodian.username", read_only=True, allow_null=True, default=None
    )

    class Meta:
        model = Sample
        fields = [
            "id",
            "public_id",
            "sample_id",
            "sample_type",
            "form_schema",
            "form_values",
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
            "custodian",
            "custodian_username",
            "location_id",
            "location_name",
            "created_by",
            "created_by_username",
            "can_modify",
            "created_at",
            "status_changed_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "public_id", "project_id", "project_name", "project_code",
            "linked_project_summaries", "container_id", "container_code",
            "batch", "batch_code", "assigned_to", "assigned_to_username",
            "custodian", "custodian_username", "location_id", "location_name",
            "created_by", "created_by_username", "can_modify", "created_at",
            "status_changed_at", "updated_at",
            "form_schema",
        ]

    def validate(self, attrs):
        from custom_fields.forms import schema_for, validate_values
        if self.instance:
            schema = self.instance.form_schema
            if schema and attrs.get("sample_type", self.instance.sample_type) != self.instance.sample_type:
                raise serializers.ValidationError({"sample_type": "Sample type cannot change. / No se puede cambiar el tipo."})
            if not schema and attrs.get("sample_type", self.instance.sample_type) != self.instance.sample_type:
                schema = schema_for(attrs["sample_type"])
                attrs["form_schema"] = schema
        else:
            schema = schema_for(attrs.get("sample_type", "GENERAL"))
            attrs["form_schema"] = schema
        values = attrs.get("form_values", self.instance.form_values if self.instance else {})
        validate_values(schema, values)
        return attrs

    def validate_sample_type(self, value):
        normalized = str(value or "GENERAL").strip().upper()
        if not normalized:
            return "GENERAL"
        return normalized

    def get_linked_project_summaries(self, obj):
        return [
            {
                "id": project.id,
                "public_id": str(project.public_id),
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


class SampleRelationshipSerializer(serializers.ModelSerializer):
    source_sample_code = serializers.CharField(source="source_sample.sample_id", read_only=True)
    derived_sample_code = serializers.CharField(source="derived_sample.sample_id", read_only=True)
    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True, allow_null=True, default=None
    )

    class Meta:
        model = SampleRelationship
        fields = [
            "id",
            "source_sample",
            "source_sample_code",
            "derived_sample",
            "derived_sample_code",
            "relationship_type",
            "quantity",
            "unit",
            "reason",
            "created_by",
            "created_by_username",
            "created_at",
        ]
        read_only_fields = ["id", "created_by", "created_by_username", "created_at"]

    def validate_reason(self, value):
        value = str(value or "").strip()
        if len(value) < 10:
            raise serializers.ValidationError("A reason of at least 10 characters is required.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        relationship = SampleRelationship(**attrs)
        try:
            relationship.clean()
        except Exception as exc:
            detail = getattr(exc, "message_dict", None) or getattr(exc, "messages", None)
            raise serializers.ValidationError(detail or str(exc)) from exc
        if attrs.get("quantity") is not None and not str(attrs.get("unit") or "").strip():
            raise serializers.ValidationError({"unit": "Unit is required when quantity is provided."})
        return attrs


class SampleCustodyEventSerializer(serializers.ModelSerializer):
    sample_code = serializers.CharField(source="sample.sample_id", read_only=True)
    from_container_code = serializers.CharField(
        source="from_container.container_id", read_only=True, allow_null=True, default=None
    )
    to_container_code = serializers.CharField(
        source="to_container.container_id", read_only=True, allow_null=True, default=None
    )
    from_custodian_username = serializers.CharField(
        source="from_custodian.username", read_only=True, allow_null=True, default=None
    )
    to_custodian_username = serializers.CharField(
        source="to_custodian.username", read_only=True, allow_null=True, default=None
    )
    performed_by_username = serializers.CharField(source="performed_by.username", read_only=True)

    class Meta:
        model = SampleCustodyEvent
        fields = [
            "id", "sample", "sample_code", "action", "scanned_code",
            "from_container", "from_container_code", "to_container", "to_container_code",
            "from_custodian", "from_custodian_username", "to_custodian",
            "to_custodian_username", "reason", "performed_by",
            "performed_by_username", "occurred_at",
        ]
        read_only_fields = fields


class CustodyScanSerializer(serializers.Serializer):
    barcode = serializers.CharField(max_length=128)
    action = serializers.ChoiceField(choices=SampleCustodyEvent.ACTION_CHOICES)
    container = serializers.IntegerField(required=False, allow_null=True)
    custodian = serializers.IntegerField(required=False, allow_null=True)
    reason = serializers.CharField(min_length=10, max_length=2000)


class DerivedSampleCreateSerializer(serializers.Serializer):
    sample_id = serializers.CharField(max_length=64)
    sample_type = serializers.CharField(max_length=64, required=False, allow_blank=True)
    relationship_type = serializers.ChoiceField(choices=SampleRelationship.TYPE_CHOICES)
    quantity = serializers.DecimalField(
        max_digits=14, decimal_places=4, required=False, allow_null=True
    )
    unit = serializers.CharField(max_length=32, required=False, allow_blank=True)
    reason = serializers.CharField(min_length=10, max_length=2000)

    def validate_sample_id(self, value):
        value = str(value or "").strip()
        if not value:
            raise serializers.ValidationError("Sample ID is required.")
        if Sample.objects.filter(sample_id__iexact=value).exists():
            raise serializers.ValidationError("A sample with this ID already exists.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get("quantity") is not None and attrs["quantity"] <= 0:
            raise serializers.ValidationError({"quantity": "Quantity must be greater than zero."})
        if attrs.get("quantity") is not None and not str(attrs.get("unit") or "").strip():
            raise serializers.ValidationError({"unit": "Unit is required when quantity is provided."})
        return attrs


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
