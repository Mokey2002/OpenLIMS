from django.urls import path
from rest_framework.routers import DefaultRouter
from samples.views import (
    SampleBatchViewSet,
    SampleCustodyEventViewSet,
    SampleRelationshipViewSet,
    SampleViewSet,
    SingleSampleAttachmentViewSet,
)
from inventory.views import (
    ContainerViewSet,
    InventoryItemViewSet,
    InventoryLotViewSet,
    InventoryReservationViewSet,
    LocationViewSet,
)
from events.views import EventViewSet
from custom_fields.views import FieldDefinitionViewSet, FieldValueViewSet
from results.views import WorkItemViewSet, ResultViewSet, SampleAttachmentViewSet
from projects.views import ProjectViewSet, ProjectPostViewSet
from core.views import UserLiteViewSet, UserAdminViewSet
from imports.views import InstrumentProfileViewSet,InstrumentColumnMappingViewSet,ImportJobViewSet
from notifications.views import NotificationViewSet
from sequences.views import SequenceViewSet
from alignments.views import AlignmentJobViewSet
from settings_app.views import PublicUISettingsView, SystemSettingsViewSet
from settings_app.views import FeatureFlagsView
from core.entity_views import (
    EntityLinkViewSet,
    EntityReferenceView,
    SharedAttachmentViewSet,
)
from blast.views import BlastDatabaseViewSet, BlastJobViewSet
from mass_spec.views import MassSpecRunViewSet
from assistant.views import (
    AssistantActionCancelView,
    AssistantActionConfirmView,
    AssistantActionDetailView,
    AssistantChatView,
    AssistantFeedbackView,
    AssistantMetricsView,
    AssistantComparisonView,
    AssistantInvestigationView,
    AssistantStatusView,
    AssistantArtifactDownloadView,
    AssistantSystemMonitoringView,
    NotificationSubscriptionViewSet,
    SOPDocumentViewSet,
)
from migration_toolkit.views import (
    MigrationDatabaseConnectionViewSet,
    MigrationDatasetViewSet,
    MigrationFieldMappingViewSet,
    MigrationJobViewSet,
    MigrationMappingTemplateViewSet,
    MigrationProfileViewSet,
    MigrationRowRecordViewSet,
    SampleExternalIDViewSet,
)
from pipelines.views import (
    AnalysisDefinitionViewSet,
    PipelineRunViewSet,
    PipelineTemplateViewSet,
    ProcedureDefinitionViewSet,
)

router = DefaultRouter()
router.register(r"samples", SampleViewSet, basename="sample")
router.register(r"sample-batches", SampleBatchViewSet, basename="sample-batch")
router.register(r"sample-relationships", SampleRelationshipViewSet, basename="sample-relationship")
router.register(r"sample-custody-events", SampleCustodyEventViewSet, basename="sample-custody-event")
router.register(r"locations", LocationViewSet, basename="location")
router.register(r"containers", ContainerViewSet, basename="container")
router.register(r"inventory-items", InventoryItemViewSet, basename="inventory-item")
router.register(r"inventory-lots", InventoryLotViewSet, basename="inventory-lot")
router.register(
    r"inventory-reservations",
    InventoryReservationViewSet,
    basename="inventory-reservation",
)
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
router.register(r"sop-documents", SOPDocumentViewSet, basename="sop-document")
router.register(r"notification-subscriptions", NotificationSubscriptionViewSet, basename="notification-subscription")

router.register(r"sample-external-ids", SampleExternalIDViewSet, basename="sample-external-id")
router.register(
    r"migration-database-connections",
    MigrationDatabaseConnectionViewSet,
    basename="migration-database-connection",
)
router.register(r"migration-datasets", MigrationDatasetViewSet, basename="migration-dataset")
router.register(r"migration-profiles", MigrationProfileViewSet, basename="migration-profile")
router.register(
    r"migration-mapping-templates",
    MigrationMappingTemplateViewSet,
    basename="migration-mapping-template",
)
router.register(r"migration-field-mappings", MigrationFieldMappingViewSet, basename="migration-field-mapping")
router.register(r"migration-jobs", MigrationJobViewSet, basename="migration-job")
router.register(r"migration-row-records", MigrationRowRecordViewSet, basename="migration-row-record")
router.register(r"analysis-definitions", AnalysisDefinitionViewSet, basename="analysis-definition")
router.register(r"procedure-definitions", ProcedureDefinitionViewSet, basename="procedure-definition")
router.register(r"pipeline-templates", PipelineTemplateViewSet, basename="pipeline-template")
router.register(r"pipeline-runs", PipelineRunViewSet, basename="pipeline-run")
router.register(r"entity-links", EntityLinkViewSet, basename="entity-link")
router.register(
    r"shared-attachments",
    SharedAttachmentViewSet,
    basename="shared-attachment",
)

urlpatterns = router.urls + [
    path("ui-settings/", PublicUISettingsView.as_view(), name="public-ui-settings"),
    path("feature-flags/", FeatureFlagsView.as_view(), name="feature-flags"),
    path(
        "entity-references/<str:entity_type>/<uuid:public_id>/",
        EntityReferenceView.as_view(),
        name="entity-reference",
    ),
    path("assistant/chat/", AssistantChatView.as_view(), name="assistant-chat"),
    path(
        "assistant/interactions/<uuid:interaction_id>/feedback/",
        AssistantFeedbackView.as_view(),
        name="assistant-feedback",
    ),
    path("assistant/metrics/", AssistantMetricsView.as_view(), name="assistant-metrics"),
    path(
        "assistant/comparisons/",
        AssistantComparisonView.as_view(),
        name="assistant-comparisons",
    ),
    path(
        "assistant/investigations/",
        AssistantInvestigationView.as_view(),
        name="assistant-investigations",
    ),
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
    path(
        "assistant/artifacts/<uuid:artifact_id>/download/",
        AssistantArtifactDownloadView.as_view(),
        name="assistant-artifact-download",
    ),
    path(
        "assistant/system-monitoring/",
        AssistantSystemMonitoringView.as_view(),
        name="assistant-system-monitoring",
    ),
]
