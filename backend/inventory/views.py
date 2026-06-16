from rest_framework.permissions import SAFE_METHODS
from rest_framework.viewsets import ModelViewSet

from core.permissions import IsAdminOnly
from events.models import Event

from .models import Location, Container
from .serializers import LocationSerializer, ContainerSerializer


class InventoryAdminWritePermission(IsAdminOnly):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)

        return super().has_permission(request, view)


def location_payload(location):
    return {
        "id": location.id,
        "name": location.name,
        "kind": location.kind,
    }


def container_payload(container):
    return {
        "id": container.id,
        "container_id": container.container_id,
        "kind": container.kind,
        "location": container.location_id,
        "location_name": container.location.name if container.location else None,
    }


class LocationViewSet(ModelViewSet):
    permission_classes = [InventoryAdminWritePermission]
    queryset = Location.objects.all().order_by("name")
    serializer_class = LocationSerializer

    def perform_create(self, serializer):
        location = serializer.save()

        Event.objects.create(
            entity_type="Location",
            entity_id=str(location.id),
            action="LOCATION_CREATED",
            actor=self.request.user,
            payload=location_payload(location),
        )

    def perform_update(self, serializer):
        old_location = self.get_object()
        old_payload = location_payload(old_location)

        location = serializer.save()

        Event.objects.create(
            entity_type="Location",
            entity_id=str(location.id),
            action="LOCATION_UPDATED",
            actor=self.request.user,
            payload={
                "before": old_payload,
                "after": location_payload(location),
            },
        )

    def perform_destroy(self, instance):
        payload = location_payload(instance)
        location_id = instance.id

        instance.delete()

        Event.objects.create(
            entity_type="Location",
            entity_id=str(location_id),
            action="LOCATION_DELETED",
            actor=self.request.user,
            payload=payload,
        )


class ContainerViewSet(ModelViewSet):
    permission_classes = [InventoryAdminWritePermission]
    queryset = Container.objects.select_related("location").all().order_by("container_id")
    serializer_class = ContainerSerializer

    def perform_create(self, serializer):
        container = serializer.save()

        Event.objects.create(
            entity_type="Container",
            entity_id=str(container.id),
            action="CONTAINER_CREATED",
            actor=self.request.user,
            payload=container_payload(container),
        )

    def perform_update(self, serializer):
        old_container = self.get_object()
        old_payload = container_payload(old_container)

        container = serializer.save()

        Event.objects.create(
            entity_type="Container",
            entity_id=str(container.id),
            action="CONTAINER_UPDATED",
            actor=self.request.user,
            payload={
                "before": old_payload,
                "after": container_payload(container),
            },
        )

    def perform_destroy(self, instance):
        payload = container_payload(instance)
        container_id = instance.id

        instance.delete()

        Event.objects.create(
            entity_type="Container",
            entity_id=str(container_id),
            action="CONTAINER_DELETED",
            actor=self.request.user,
            payload=payload,
        )
