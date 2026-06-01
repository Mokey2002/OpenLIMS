from django.contrib.auth import get_user_model
from rest_framework.viewsets import ReadOnlyModelViewSet, ModelViewSet
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from events.models import Event
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import OpenLIMSTokenObtainPairSerializer
from .permissions import IsAdminOnly
from .serializers import (
    MeSerializer,
    UserAdminUpdateSerializer,
    UserCreateSerializer,
    UserLiteSerializer,
)

User = get_user_model()

class OpenLIMSTokenObtainPairView(TokenObtainPairView):
    serializer_class = OpenLIMSTokenObtainPairSerializer
    
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

        changed_fields = [
            field
            for field in before
            if before[field] != after[field]
        ]

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

    def get(self, request):
        return Response(MeSerializer(request.user).data)
