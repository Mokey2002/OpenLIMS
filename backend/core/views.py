from rest_framework.decorators import action
from .invitations import send_invitation, InvitationSendThrottle
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import CharField, OuterRef, Subquery
from django.db.models.functions import Cast
from django.middleware.csrf import get_token
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework_simplejwt.exceptions import TokenError, AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from events.models import Event
from .authentication import enforce_csrf
from .permissions import IsAdminOnly
from .user_safety import (
    LastAdministratorConflict, LastAdministratorError, last_administrator_id,
    lock_api_administrator, protect_api_update, protect_user_deletion, user_administration,
)
from .serializers import OpenLIMSTokenObtainPairSerializer, OpenLIMSTokenRefreshSerializer
from .offboarding import OffboardingConfirmSerializer, OffboardingPreviewSerializer
from .serializers import (
    MeSerializer,
    UserAdminUpdateSerializer,
    UserCreateSerializer,
    UserLiteSerializer,
    AdminUserListSerializer,
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


class OpenLIMSTokenRefreshView(TokenRefreshView):
    serializer_class = OpenLIMSTokenRefreshSerializer


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
        enforce_csrf(request)
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
        enforce_csrf(request)
        refresh = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
        if not refresh:
            return Response({"detail": "Refresh cookie is missing."}, status=401)

        try:
            serializer = OpenLIMSTokenRefreshSerializer(data={"refresh": refresh})
            serializer.is_valid(raise_exception=True)
        except (TokenError, AuthenticationFailed):
            response = Response({"detail": "Session expired. Please sign in again."}, status=401)
            _clear_auth_cookies(response)
            return response
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
        enforce_csrf(request)
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

    @extend_schema(responses=OpenApiTypes.OBJECT)
    @action(detail=True, methods=["get"], url_path="offboarding")
    def offboarding(self, request, pk=None):
        from .offboarding import review_offboarding
        return Response(review_offboarding(self.get_object(), request.user))

    @extend_schema(request=OffboardingPreviewSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"], url_path="offboarding/preview")
    def offboarding_preview(self, request, pk=None):
        from .offboarding import prepare_offboarding
        serializer = OffboardingPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(prepare_offboarding(self.get_object(), request.user, serializer.validated_data), status=201)

    @extend_schema(request=OffboardingConfirmSerializer, responses=OpenApiTypes.OBJECT)
    @action(detail=True, methods=["post"], url_path="offboarding/confirm")
    def offboarding_confirm(self, request, pk=None):
        from .offboarding import confirm_offboarding
        serializer = OffboardingConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            return Response(confirm_offboarding(self.get_object(), request.user, serializer.validated_data["preview_id"]))
        except LastAdministratorError:
            raise LastAdministratorConflict() from None

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action in {"list", "retrieve"}:
            context["last_administrator_id"] = last_administrator_id()
        return context

    def _guarded_write(self, method, request, *args, **kwargs):
        try:
            with user_administration():
                target = self.get_object()
                request.user = lock_api_administrator(request.user, target)
                return method(request, *args, **kwargs)
        except LastAdministratorError:
            raise LastAdministratorConflict() from None

    def update(self, request, *args, **kwargs):
        return self._guarded_write(super().update, request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        return self._guarded_write(super().destroy, request, *args, **kwargs)

    def get_queryset(self):
        invitation_events = Event.objects.filter(
            entity_type="User", entity_id=Cast(OuterRef("pk"), CharField()),
            action__in=["USER_INVITATION_SENT", "USER_INVITATION_FAILED", "USER_PASSWORD_SET"],
        ).order_by("-timestamp", "-pk")
        return (
            User.objects
            .annotate(invitation_event=Subquery(invitation_events.values("action")[:1]),
                      invitation_updated_at=Subquery(invitation_events.values("timestamp")[:1]))
            .prefetch_related("groups")
            .all()
            .order_by("username")
        )

    def get_serializer_class(self):
        if self.action in ["list", "retrieve"]:
            return AdminUserListSerializer
        if self.action in ["partial_update", "update"]:
            return UserAdminUpdateSerializer

        return UserCreateSerializer

    def get_throttles(self):
        if self.action in ["create", "invite"]:
            return [InvitationSendThrottle()]
        return super().get_throttles()

    def create(self, request, *args, **kwargs):
        self.invitation_status = None
        response = super().create(request, *args, **kwargs)
        response.data["invitation_status"] = self.invitation_status
        return response

    @action(detail=True, methods=["post"])
    def invite(self, request, pk=None):
        status = send_invitation(self.get_object(), request.user)
        return Response({"invitation_status": status}, status=200 if status == "sent" else 503)

    @transaction.atomic
    def perform_create(self, serializer):
        invite = serializer.validated_data.get("send_invitation", False)
        user = serializer.save()

        from notifications.models import Notification
        Notification.objects.create(user=user, title="Welcome to OpenLIMS / Bienvenido a OpenLIMS",
                                    message="Start your first experiment with your lab's workflow. / Inicia tu primer experimento con el flujo de tu laboratorio.",
                                    link="/getting-started")

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

        if invite:
            self.invitation_status = send_invitation(user, self.request.user)

    def perform_update(self, serializer):
        user = serializer.instance
        protect_api_update(user, serializer.validated_data)

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
        protect_user_deletion([instance.pk])
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
