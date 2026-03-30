from rest_framework.routers import DefaultRouter
from samples.views import SampleViewSet
from inventory.views import LocationViewSet, ContainerViewSet
from events.views import EventViewSet
from custom_fields.views import FieldDefinitionViewSet, FieldValueViewSet
from results.views import WorkItemViewSet, ResultViewSet, SampleAttachmentViewSet
from projects.views import ProjectViewSet

router = DefaultRouter()
router.register(r"samples", SampleViewSet, basename="sample")
router.register(r"locations", LocationViewSet, basename="location")
router.register(r"containers", ContainerViewSet, basename="container")
router.register(r"events", EventViewSet, basename="event")
router.register(r"field-definitions", FieldDefinitionViewSet, basename="field-definition")
router.register(r"field-values", FieldValueViewSet, basename="field-value")
router.register(r"work-items", WorkItemViewSet, basename="work-item")
router.register(r"results", ResultViewSet, basename="result")
router.register(r"attachments", SampleAttachmentViewSet, basename="attachment")
router.register(r"projects", ProjectViewSet, basename="project")
urlpatterns = router.urls
