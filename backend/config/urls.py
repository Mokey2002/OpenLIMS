"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.db import connection
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.conf import settings
from django.conf.urls.static import static
from core.views import MeView
import subprocess

from django.contrib import admin
from django.core.cache import cache
from django.db import connection
from django.urls import include, path
from django.http import JsonResponse
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
        checks["clustalo_version"] = (
            result.stdout.strip() or result.stderr.strip()
        ).splitlines()[0]
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
    return JsonResponse({"app": "OpenLIMS", "health": "/health", "admin": "/admin"})


urlpatterns = [
    path("", home),
    path("admin/", admin.site.urls),
    path("health/", health),
    path("api/", include("config.api_urls")),
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/me/", MeView.as_view(), name="me"),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) 
