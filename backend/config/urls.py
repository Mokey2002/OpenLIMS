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
from core.search_views import GlobalSearchView

def _check_command(command, version_arg="-version"):
    try:
        result = subprocess.run(
            [command, version_arg],
            capture_output=True,
            text=True,
            timeout=5,
        )

        output = result.stdout.strip() or result.stderr.strip()

        return {
            "ok": result.returncode == 0,
            "version": output.splitlines()[0] if output else "unknown",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
        }


def health(request):
    checks = {
        "db_ok": False,
        "redis_ok": False,
        "clustalo_ok": False,
        "blastn_ok": False,
        "blastp_ok": False,
        "makeblastdb_ok": False,
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

    clustalo = _check_command("clustalo", "--version")
    checks["clustalo_ok"] = clustalo["ok"]

    if clustalo.get("version"):
        checks["clustalo_version"] = clustalo["version"]

    if clustalo.get("error"):
        checks["clustalo_error"] = clustalo["error"]

    blastn = _check_command("blastn", "-version")
    checks["blastn_ok"] = blastn["ok"]

    if blastn.get("version"):
        checks["blastn_version"] = blastn["version"]

    if blastn.get("error"):
        checks["blastn_error"] = blastn["error"]

    blastp = _check_command("blastp", "-version")
    checks["blastp_ok"] = blastp["ok"]

    if blastp.get("version"):
        checks["blastp_version"] = blastp["version"]

    if blastp.get("error"):
        checks["blastp_error"] = blastp["error"]

    makeblastdb = _check_command("makeblastdb", "-version")
    checks["makeblastdb_ok"] = makeblastdb["ok"]

    if makeblastdb.get("version"):
        checks["makeblastdb_version"] = makeblastdb["version"]

    if makeblastdb.get("error"):
        checks["makeblastdb_error"] = makeblastdb["error"]

    all_ok = (
        checks["db_ok"]
        and checks["redis_ok"]
        and checks["clustalo_ok"]
        and checks["blastn_ok"]
        and checks["blastp_ok"]
        and checks["makeblastdb_ok"]
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
    path("api/search/", GlobalSearchView.as_view(), name="global-search"),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)