from rest_framework.routers import DefaultRouter
from samples.views import SampleViewSet
from inventory.views import LocationViewSet, ContainerViewSet
from events.views import EventViewSet
from custom_fields.views import FieldDefinitionViewSet, FieldValueViewSet

router = DefaultRouter()
router.register(r"samples", SampleViewSet, basename="sample")
router.register(r"locations", LocationViewSet, basename="location")
router.register(r"containers", ContainerViewSet, basename="container")
router.register(r"events", EventViewSet, basename="event")
router.register(r"field-definitions", FieldDefinitionViewSet, basename="field-definition")
router.register(r"field-values", FieldValueViewSet, basename="field-value")

urlpatterns = router.urls
