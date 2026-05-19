from django.shortcuts import render
from rest_framework.viewsets import ModelViewSet
from .models import Location, Container
from .serializers import LocationSerializer, ContainerSerializer
from core.permissions import IsAuthenticatedReadOnlyOrTechAdminWrite, IsAdminOnly, IsAuthenticatedReadOnly
from rest_framework.permissions import SAFE_METHODS

class InventoryAdminWritePermission(IsAdminOnly):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return super().has_permission(request, view)

class LocationViewSet(ModelViewSet):
    permission_classes = [InventoryAdminWritePermission]
    queryset = Location.objects.all().order_by("name")
    serializer_class = LocationSerializer


class ContainerViewSet(ModelViewSet):
    permission_classes = [InventoryAdminWritePermission]
    queryset = Container.objects.select_related("location").all().order_by("container_id")
    serializer_class = ContainerSerializer

