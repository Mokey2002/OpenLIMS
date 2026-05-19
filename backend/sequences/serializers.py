from rest_framework import serializers

from .models import Sequence, SequenceFeature


class SequenceFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = SequenceFeature
        fields = [
            "id",
            "feature_type",
            "name",
            "start",
            "end",
            "direction",
            "color",
            "metadata",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        start = attrs.get("start")
        end = attrs.get("end")

        if start is not None and end is not None and end <= start:
            raise serializers.ValidationError(
                {"end": "End must be greater than start."}
            )

        return attrs


class SequenceSerializer(serializers.ModelSerializer):
    features = SequenceFeatureSerializer(many=True, required=False)

    project_code = serializers.CharField(
        source="project.code",
        read_only=True,
    )
    project_name = serializers.CharField(
        source="project.name",
        read_only=True,
    )
    sample_code = serializers.CharField(
        source="sample.sample_id",
        read_only=True,
    )
    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    class Meta:
        model = Sequence
        fields = [
            "id",
            "name",
            "description",
            "sequence_type",
            "sequence",
            "project",
            "project_code",
            "project_name",
            "sample",
            "sample_code",
            "viewer",
            "show_complement",
            "rotate_on_scroll",
            "zoom",
            "enzymes",
            "bp_colors",
            "features",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]

    def validate_sequence(self, value):
        cleaned = "".join(value.split()).upper()

        if not cleaned:
            raise serializers.ValidationError("Sequence cannot be empty.")

        return cleaned

    def create(self, validated_data):
        features_data = validated_data.pop("features", [])

        request = self.context.get("request")

        if request and request.user and request.user.is_authenticated:
            validated_data["created_by"] = request.user

        sequence_record = Sequence.objects.create(**validated_data)

        for feature_data in features_data:
            SequenceFeature.objects.create(
                sequence_record=sequence_record,
                **feature_data,
            )

        return sequence_record

    def update(self, instance, validated_data):
        features_data = validated_data.pop("features", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        if features_data is not None:
            instance.features.all().delete()

            for feature_data in features_data:
                SequenceFeature.objects.create(
                    sequence_record=instance,
                    **feature_data,
                )

        return instance