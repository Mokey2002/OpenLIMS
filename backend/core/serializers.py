from django.db import transaction
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework import serializers
from django.contrib.auth.models import update_last_login
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from .permissions import application_roles

User = get_user_model()


VALID_ROLES = ["admin", "tech", "viewer", "qc_reviewer"]


class UserLiteSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "roles",
            "is_active",
            "is_staff",
            "is_superuser",
            "last_login",
            "date_joined",
        ]

    def get_roles(self, obj):
        return application_roles(obj)

    def get_full_name(self, obj):
        return obj.get_full_name()


class UserListSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "roles",
            "is_active",
            "is_staff",
            "is_superuser",
            "last_login",
            "date_joined",
        ]

    def get_roles(self, obj):
        return application_roles(obj)

    def get_full_name(self, obj):
        return obj.get_full_name()


class AdminUserListSerializer(UserListSerializer):
    invitation_event = serializers.CharField(read_only=True, allow_null=True)
    invitation_updated_at = serializers.DateTimeField(read_only=True, allow_null=True)
    password_ready = serializers.SerializerMethodField()
    is_last_active_admin = serializers.SerializerMethodField()

    class Meta(UserListSerializer.Meta):
        fields = UserListSerializer.Meta.fields + ["invitation_event", "invitation_updated_at", "password_ready", "is_last_active_admin"]

    def get_is_last_active_admin(self, obj) -> bool:
        return obj.pk == self.context.get("last_administrator_id")

    def get_password_ready(self, obj):
        return obj.has_usable_password()


class UserCreateSerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(default=True)
    password = serializers.CharField(write_only=True, required=False, trim_whitespace=False)
    send_invitation = serializers.BooleanField(write_only=True, required=False)
    role = serializers.ChoiceField(
        choices=VALID_ROLES,
        write_only=True,
    )
    roles = serializers.SerializerMethodField(read_only=True)
    full_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "password",
            "send_invitation",
            "role",
            "roles",
            "is_active",
            "is_staff",
            "is_superuser",
            "last_login",
            "date_joined",
        ]
        read_only_fields = [
            "id",
            "roles",
            "full_name",
            "is_staff",
            "is_superuser",
            "last_login",
            "date_joined",
        ]

    def validate(self, attrs):
        from .invitations import invitation_origin
        invite = attrs.get("send_invitation", False)
        attrs["send_invitation"] = invite
        if invite:
            invitation_origin()
            if not attrs.get("email") or not attrs.get("is_active", True):
                raise serializers.ValidationError({"email": "Invitation requires an active user and email address."})
        elif not attrs.get("password"):
            raise serializers.ValidationError({"password": "A password is required without an invitation."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        role = validated_data.pop("role")
        password = validated_data.pop("password", None)
        invite = validated_data.pop("send_invitation", False)

        user = User.objects.create(**validated_data)
        user.set_password(None if invite else password)

        if role == "admin":
            user.is_staff = True
            user.is_superuser = True
        else:
            user.is_staff = False
            user.is_superuser = False

        user.save()

        group, _ = Group.objects.get_or_create(name=role)
        user.groups.set([group])

        return user

    def get_roles(self, obj):
        return application_roles(obj)

    def get_full_name(self, obj):
        return obj.get_full_name()


class UserAdminUpdateSerializer(serializers.ModelSerializer):
    role = serializers.ChoiceField(
        choices=VALID_ROLES,
        write_only=True,
        required=False,
    )
    roles = serializers.SerializerMethodField(read_only=True)
    full_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "roles",
            "is_active",
            "is_staff",
            "is_superuser",
            "last_login",
            "date_joined",
        ]
        read_only_fields = [
            "id",
            "username",
            "roles",
            "full_name",
            "is_staff",
            "is_superuser",
            "last_login",
            "date_joined",
        ]

    def update(self, instance, validated_data):
        role = validated_data.pop("role", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if role:
            group, _ = Group.objects.get_or_create(name=role)
            instance.groups.set([group])

            if role == "admin":
                instance.is_staff = True
                instance.is_superuser = True
            else:
                instance.is_staff = False
                instance.is_superuser = False

        instance.save()
        return instance

    def get_roles(self, obj):
        return application_roles(obj)

    def get_full_name(self, obj):
        return obj.get_full_name()


class MeSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "roles",
            "is_active",
            "is_staff",
            "is_superuser",
            "last_login",
        ]

    def get_roles(self, obj):
        return application_roles(obj)

    def get_full_name(self, obj):
        return obj.get_full_name()
    
class OpenLIMSTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        from .session_revocation import GENERATION_CLAIM, session_generation
        token = super().get_token(user)
        token[GENERATION_CLAIM] = session_generation(user)
        return token

    @transaction.atomic
    def validate(self, attrs):
        # Serialize token issuance with offboarding. Otherwise a login that
        # began before deactivation could mint the new generation afterwards.
        User.objects.select_for_update().filter(**{self.username_field: attrs.get(self.username_field)}).first()
        data = super().validate(attrs)

        update_last_login(None, self.user)

        return data


class OpenLIMSTokenRefreshSerializer(TokenRefreshSerializer):
    @transaction.atomic
    def validate(self, attrs):
        from .authentication import CookieJWTAuthentication
        refresh = self.token_class(attrs["refresh"])
        User.objects.select_for_update().filter(pk=refresh.get("user_id")).first()
        CookieJWTAuthentication().get_user(refresh)
        return super().validate(attrs)
