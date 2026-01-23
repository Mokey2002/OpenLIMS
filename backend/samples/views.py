from django.shortcuts import render

from rest_framework.viewsets import ModelViewSet
from .models import Sample
from .serializers import SampleSerializer

class SampleViewSet(ModelViewSet):
    queryset = Sample.objects.all().order_by("-created_at")
    serializer_class = SampleSerializer

