from django.shortcuts import render
from rest_framework.viewsets import ModelViewSet
from .models import Location, Container
from .serializers import LocationSerializer, ContainerSerializer

class LocationViewSet(ModelViewSet):
    queryset = Location.objects.all().order_by("name")
    serializer_class = LocationSerializer


class ContainerViewSet(ModelViewSet):
    queryset = Container.objects.select_related("location").all().order_by("container_id")
    serializer_class = ContainerSerializer

