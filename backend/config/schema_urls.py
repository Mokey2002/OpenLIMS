from django.urls import include, path


urlpatterns = [path("api/v1/", include("config.api_v1_urls"))]
