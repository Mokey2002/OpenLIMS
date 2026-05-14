from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework import serializers

User = get_user_model()


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    role = serializers.ChoiceField(
        choices=["admin", "tech", "viewer"],
        write_only=True,
    )
    roles = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "password",
            "role",
            "roles",
            "is_active",
            "is_staff",
            "is_superuser",
        ]
        read_only_fields = [
            "id",
            "roles",
            "is_active",
            "is_staff",
            "is_superuser",
        ]

    def create(self, validated_data):
        role = validated_data.pop("role")
        password = validated_data.pop("password")

        user = User.objects.create(**validated_data)
        user.set_password(password)

        if role == "admin":
            user.is_staff = True

        user.save()

        group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(group)

        return user

    def get_roles(self, obj):
        return list(obj.groups.values_list("name", flat=True))


class UserListSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "roles",
            "is_active",
            "is_staff",
            "is_superuser",
        ]

    def get_roles(self, obj):
        return list(obj.groups.values_list("name", flat=True))


class MeSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "roles",
            "is_staff",
            "is_superuser",
        ]

    def get_roles(self, obj):
        return list(obj.groups.values_list("name", flat=True))
