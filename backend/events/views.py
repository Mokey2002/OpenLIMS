from django.shortcuts import render

from rest_framework.viewsets import ReadOnlyModelViewSet
from .models import Event
from .serializers import EventSerializer
from core.permissions import IsAuthenticatedReadOnly

class EventViewSet(ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticatedReadOnly]
    queryset = Event.objects.all().order_by("-timestamp")
    serializer_class = EventSerializer
