from rest_framework.routers import DefaultRouter
from samples.views import SampleViewSet
from inventory.views import LocationViewSet, ContainerViewSet
from events.views import EventViewSet

router = DefaultRouter()
router.register(r"samples", SampleViewSet, basename="sample")
router.register(r"locations", LocationViewSet, basename="location")
router.register(r"containers", ContainerViewSet, basename="container")
router.register(r"events", EventViewSet, basename="event")

urlpatterns = router.urls
