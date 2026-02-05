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
def health(request):
    # DB connectivity check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
        db_ok = True
    except Exception:
        db_ok = False

    return JsonResponse({"status": "ok", "db_ok": db_ok})

def home(request):
    return JsonResponse({"app": "OpenLIMS", "health": "/health", "admin": "/admin"})


urlpatterns = [
    path("", home),
    path("admin/", admin.site.urls),
    path("health", health),
    path("api/", include("config.api_urls")),
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]
