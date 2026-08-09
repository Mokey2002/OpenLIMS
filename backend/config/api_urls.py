from django.urls import path
from rest_framework.routers import DefaultRouter
from samples.views import (
    SampleBatchViewSet,
    SampleViewSet,
    SingleSampleAttachmentViewSet,
)
from inventory.views import LocationViewSet, ContainerViewSet
from events.views import EventViewSet
from custom_fields.views import FieldDefinitionViewSet, FieldValueViewSet
from results.views import WorkItemViewSet, ResultViewSet, SampleAttachmentViewSet
from projects.views import ProjectViewSet, ProjectPostViewSet
from core.views import UserLiteViewSet, UserAdminViewSet
from imports.views import InstrumentProfileViewSet,InstrumentColumnMappingViewSet,ImportJobViewSet
from notifications.views import NotificationViewSet
from sequences.views import SequenceViewSet
from alignments.views import AlignmentJobViewSet
from settings_app.views import SystemSettingsViewSet
from blast.views import BlastDatabaseViewSet, BlastJobViewSet
from mass_spec.views import MassSpecRunViewSet
from assistant.views import (
    AssistantActionCancelView,
    AssistantActionConfirmView,
    AssistantActionDetailView,
    AssistantChatView,
    AssistantStatusView,
)
from migration_toolkit.views import (
    MigrationFieldMappingViewSet,
    MigrationJobViewSet,
    MigrationProfileViewSet,
    MigrationRowRecordViewSet,
    SampleExternalIDViewSet,
)

router = DefaultRouter()
router.register(r"samples", SampleViewSet, basename="sample")
router.register(r"sample-batches", SampleBatchViewSet, basename="sample-batch")
router.register(r"locations", LocationViewSet, basename="location")
router.register(r"containers", ContainerViewSet, basename="container")
router.register(r"events", EventViewSet, basename="event")
router.register(r"field-definitions", FieldDefinitionViewSet, basename="field-definition")
router.register(r"field-values", FieldValueViewSet, basename="field-value")
router.register(r"work-items", WorkItemViewSet, basename="work-item")
router.register(r"results", ResultViewSet, basename="result")
router.register(r"attachments", SampleAttachmentViewSet, basename="attachment")
router.register(r"projects", ProjectViewSet, basename="project")
router.register(r"users", UserLiteViewSet, basename="user-lite")
router.register(r"admin-users",UserAdminViewSet,basename="admin-user")
router.register(r"project-posts", ProjectPostViewSet, basename="project-post")
router.register(r"sample-attachments", SingleSampleAttachmentViewSet, basename="sample-attachment")
router.register(r"instrument-profiles", InstrumentProfileViewSet, basename="instrument-profile")
router.register(r"instrument-mappings", InstrumentColumnMappingViewSet, basename="instrument-mapping")
router.register(r"import-jobs", ImportJobViewSet, basename="import-job")
router.register(r"notifications",NotificationViewSet, basename="notification")
router.register(r"sequences", SequenceViewSet, basename="sequence")
router.register(r"alignment-jobs", AlignmentJobViewSet, basename="alignment-job")
router.register(r"system-settings", SystemSettingsViewSet, basename="system-settings")
router.register(r"blast-databases", BlastDatabaseViewSet, basename="blast-database")
router.register(r"blast-jobs", BlastJobViewSet, basename="blast-job")
router.register(r"mass-spec-runs", MassSpecRunViewSet, basename="mass-spec-run")

router.register(r"sample-external-ids", SampleExternalIDViewSet, basename="sample-external-id")
router.register(r"migration-profiles", MigrationProfileViewSet, basename="migration-profile")
router.register(r"migration-field-mappings", MigrationFieldMappingViewSet, basename="migration-field-mapping")
router.register(r"migration-jobs", MigrationJobViewSet, basename="migration-job")
router.register(r"migration-row-records", MigrationRowRecordViewSet, basename="migration-row-record")

urlpatterns = router.urls + [
    path("assistant/chat/", AssistantChatView.as_view(), name="assistant-chat"),
    path("assistant/status/", AssistantStatusView.as_view(), name="assistant-status"),
    path(
        "assistant/actions/<uuid:token>/",
        AssistantActionDetailView.as_view(),
        name="assistant-action-detail",
    ),
    path(
        "assistant/actions/<uuid:token>/confirm/",
        AssistantActionConfirmView.as_view(),
        name="assistant-action-confirm",
    ),
    path(
        "assistant/actions/<uuid:token>/cancel/",
        AssistantActionCancelView.as_view(),
        name="assistant-action-cancel",
    ),
]
