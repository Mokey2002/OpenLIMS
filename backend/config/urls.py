"""
URL configuration for config project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework_simplejwt.views import TokenRefreshView

from core.health import build_health_status
from core.views import MeView, OpenLIMSTokenObtainPairView
from core.search_views import GlobalSearchView


def health(request):
    health_status = build_health_status()

    return JsonResponse(
        health_status,
        status=200 if health_status["status"] == "ok" else 503,
    )


def home(request):
    return JsonResponse(
        {
            "app": "OpenLIMS",
            "health": "/health/",
            "admin": "/admin/",
            "api": "/api/",
        }
    )


urlpatterns = [
    path("", home),
    path("admin/", admin.site.urls),
    path("health/", health),
    path("api/health/", health),
    path("api/", include("config.api_urls")),
    path(
        "api/auth/token/",
        OpenLIMSTokenObtainPairView.as_view(),
        name="token_obtain_pair",
    ),
    path(
        "api/auth/token/refresh/",
        TokenRefreshView.as_view(),
        name="token_refresh",
    ),
    path("api/me/", MeView.as_view(), name="me"),
    path("api/search/", GlobalSearchView.as_view(), name="global-search"),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
