from django.urls import path

from core.consumers import JobStatusConsumer


websocket_urlpatterns = [
    path("ws/jobs/", JobStatusConsumer.as_asgi()),
]
