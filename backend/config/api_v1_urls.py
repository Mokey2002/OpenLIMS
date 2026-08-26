from django.urls import include, path
from rest_framework_simplejwt.views import TokenRefreshView

from core.search_views import GlobalSearchView
from core.views import MeView, OpenLIMSTokenObtainPairView


app_name = "api-v1"

urlpatterns = [
    path("", include("config.api_urls")),
    path(
        "auth/token/",
        OpenLIMSTokenObtainPairView.as_view(),
        name="token-obtain-pair",
    ),
    path(
        "auth/token/refresh/",
        TokenRefreshView.as_view(),
        name="token-refresh",
    ),
    path("me/", MeView.as_view(), name="me"),
    path("search/", GlobalSearchView.as_view(), name="global-search"),
]
