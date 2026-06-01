"""
URL configuration for config project.
"""

import subprocess

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path
from rest_framework_simplejwt.views import TokenRefreshView

from core.views import MeView, OpenLIMSTokenObtainPairView


def health(request):
    checks = {
        "db_ok": False,
        "redis_ok": False,
        "clustalo_ok": False,
    }

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

        checks["db_ok"] = True
    except Exception as e:
        checks["db_error"] = str(e)

    try:
        cache.set("health_check", "ok", timeout=10)
        checks["redis_ok"] = cache.get("health_check") == "ok"
    except Exception as e:
        checks["redis_error"] = str(e)

    try:
        result = subprocess.run(
            ["clustalo", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        checks["clustalo_ok"] = result.returncode == 0

        version_output = result.stdout.strip() or result.stderr.strip()
        checks["clustalo_version"] = (
            version_output.splitlines()[0] if version_output else "unknown"
        )
    except Exception as e:
        checks["clustalo_error"] = str(e)

    all_ok = (
        checks["db_ok"]
        and checks["redis_ok"]
        and checks["clustalo_ok"]
    )

    return JsonResponse(
        {
            "status": "ok" if all_ok else "degraded",
            **checks,
        },
        status=200 if all_ok else 503,
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
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)