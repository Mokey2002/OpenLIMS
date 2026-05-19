from django.contrib.auth import get_user_model
from rest_framework import serializers
from .models import Project, ProjectPost

User = get_user_model()


class ProjectSerializer(serializers.ModelSerializer):
    sample_count = serializers.IntegerField(source="samples.count", read_only=True)
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
        ]
        read_only_fields = ["id", "created_at", "member_usernames", "sample_count"]

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
