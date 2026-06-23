from django.contrib.auth import get_user_model
from rest_framework import serializers
from .models import Project, ProjectPost

User = get_user_model()


class ProjectSerializer(serializers.ModelSerializer):
    sample_count = serializers.SerializerMethodField()
    primary_sample_count = serializers.SerializerMethodField()
    linked_sample_count = serializers.SerializerMethodField()
    member_usernames = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "code",
            "description",
            "members",
            "member_usernames",
            "created_at",
            "sample_count",
            "primary_sample_count",
            "linked_sample_count",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "member_usernames",
            "sample_count",
            "primary_sample_count",
            "linked_sample_count",
        ]

    def get_sample_count(self, obj):
        primary_ids = set(obj.samples.values_list("id", flat=True))
        linked_ids = set(obj.linked_samples.values_list("id", flat=True))
        return len(primary_ids | linked_ids)

    def get_primary_sample_count(self, obj):
        return obj.samples.count()

    def get_linked_sample_count(self, obj):
        return obj.linked_samples.count()

    def get_member_usernames(self, obj):
        return list(obj.members.values_list("username", flat=True))
class ProjectPostSerializer(serializers.ModelSerializer):
    author_username = serializers.SerializerMethodField()

    class Meta:
        model = ProjectPost
        fields = [
            "id",
            "project",
            "author",
            "author_username",
            "note",
            "image",
            "created_at",
        ]
        read_only_fields = ["id", "author", "author_username", "created_at"]

    def get_author_username(self, obj):
        return obj.author.username if obj.author else None
