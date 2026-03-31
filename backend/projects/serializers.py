from django.contrib.auth import get_user_model
from rest_framework import serializers
from .models import Project

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
