from django.conf import settings
from django.contrib.auth import get_user_model
from django.middleware.csrf import get_token
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from events.models import Event
from .permissions import IsAdminOnly
from .serializers import OpenLIMSTokenObtainPairSerializer
from .serializers import (
    MeSerializer,
    UserAdminUpdateSerializer,
    UserCreateSerializer,
    UserLiteSerializer,
)

User = get_user_model()


def _set_auth_cookies(response, access, refresh=None):
    response.set_cookie(
        settings.JWT_ACCESS_COOKIE_NAME,
        access,
        max_age=settings.JWT_ACCESS_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.JWT_COOKIE_SECURE,
        samesite=settings.JWT_COOKIE_SAMESITE,
        path="/",
    )
    if refresh:
        response.set_cookie(
            settings.JWT_REFRESH_COOKIE_NAME,
            refresh,
            max_age=settings.JWT_REFRESH_COOKIE_MAX_AGE,
            httponly=True,
            secure=settings.JWT_COOKIE_SECURE,
            samesite=settings.JWT_COOKIE_SAMESITE,
            path="/",
        )


def _clear_auth_cookies(response):
    response.delete_cookie(
        settings.JWT_ACCESS_COOKIE_NAME,
        path="/",
        samesite=settings.JWT_COOKIE_SAMESITE,
    )
    response.delete_cookie(
        settings.JWT_REFRESH_COOKIE_NAME,
        path="/",
        samesite=settings.JWT_COOKIE_SAMESITE,
    )


class OpenLIMSTokenObtainPairView(TokenObtainPairView):
    serializer_class = OpenLIMSTokenObtainPairSerializer


class CSRFTokenView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        get_token(request)
        return Response({"detail": "CSRF cookie set."})


class CookieLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = OpenLIMSTokenObtainPairSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tokens = serializer.validated_data

        response = Response({"user": MeSerializer(serializer.user).data})
        _set_auth_cookies(response, tokens["access"], tokens["refresh"])
        get_token(request)
        return response


class CookieRefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        refresh = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
        if not refresh:
            return Response({"detail": "Refresh cookie is missing."}, status=401)

        serializer = TokenRefreshSerializer(data={"refresh": refresh})
        serializer.is_valid(raise_exception=True)
        tokens = serializer.validated_data

        response = Response({"detail": "Session refreshed."})
        _set_auth_cookies(
            response,
            tokens["access"],
            tokens.get("refresh"),
        )
        return response


class CookieLogoutView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        refresh = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
        if refresh:
            try:
                RefreshToken(refresh).blacklist()
            except TokenError:
                pass

        response = Response({"detail": "Logged out."})
        _clear_auth_cookies(response)
        return response


class UserLiteViewSet(ReadOnlyModelViewSet):
    permission_classes = [IsAdminOnly]
    serializer_class = UserLiteSerializer

    def get_queryset(self):
        return (
            User.objects
            .prefetch_related("groups")
            .all()
            .order_by("username")
        )


class UserAdminViewSet(ModelViewSet):
    permission_classes = [IsAdminOnly]

    def get_queryset(self):
        return (
            User.objects
            .prefetch_related("groups")
            .all()
            .order_by("username")
        )

    def get_serializer_class(self):
        if self.action in ["partial_update", "update"]:
            return UserAdminUpdateSerializer

        return UserCreateSerializer

    def perform_create(self, serializer):
        user = serializer.save()

        Event.objects.create(
            entity_type="User",
            entity_id=str(user.id),
            action="USER_CREATED",
            actor=self.request.user if self.request.user.is_authenticated else None,
            payload={
                "user_id": user.id,
                "username": user.username,
                "email": user.email,
                "roles": list(user.groups.values_list("name", flat=True)),
                "is_active": user.is_active,
            },
        )

    def perform_update(self, serializer):
        user = self.get_object()

        before = {
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "roles": list(user.groups.values_list("name", flat=True)),
            "is_active": user.is_active,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
        }

        updated_user = serializer.save()

        after = {
            "email": updated_user.email,
            "first_name": updated_user.first_name,
            "last_name": updated_user.last_name,
            "roles": list(updated_user.groups.values_list("name", flat=True)),
            "is_active": updated_user.is_active,
            "is_staff": updated_user.is_staff,
            "is_superuser": updated_user.is_superuser,
        }

        changed_fields = [field for field in before if before[field] != after[field]]

        if changed_fields:
            action = "USER_UPDATED"

            if before["roles"] != after["roles"]:
                action = "USER_ROLE_UPDATED"

            if before["is_active"] != after["is_active"]:
                action = "USER_STATUS_UPDATED"

            Event.objects.create(
                entity_type="User",
                entity_id=str(updated_user.id),
                action=action,
                actor=self.request.user if self.request.user.is_authenticated else None,
                payload={
                    "user_id": updated_user.id,
                    "username": updated_user.username,
                    "before": before,
                    "after": after,
                    "changed_fields": changed_fields,
                },
            )

    def perform_destroy(self, instance):
        Event.objects.create(
            entity_type="User",
            entity_id=str(instance.id),
            action="USER_DELETED",
            actor=self.request.user if self.request.user.is_authenticated else None,
            payload={
                "user_id": instance.id,
                "username": instance.username,
                "email": instance.email,
                "roles": list(instance.groups.values_list("name", flat=True)),
            },
        )

        instance.delete()


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        return Response(MeSerializer(request.user).data)
