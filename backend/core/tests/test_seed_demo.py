import secrets
import tempfile
from hashlib import sha256
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.demo_requester import (
    COMPLETED_REQUEST_NUMBER,
    DEMO_PROJECT_CODE,
    DEMO_REQUESTER_USERNAME,
    PENDING_REQUEST_NUMBER,
    TEST_CODE,
)
from core.management.commands.seed_demo import (
    create_demo_user,
    link_demo_import_job,
)
from core.models import EntityLink, SharedAttachment
from alignments.models import AlignmentJob
from assistant.models import AssistantAction, GeneratedArtifact, NotificationSubscription
from blast.models import BlastJob
from imports.models import ImportJob, InstrumentProfile
from inventory.models import (
    BarcodeIdentity,
    InventoryCycleCount,
    InventoryPlacement,
    InventoryReservation,
    InventoryTransaction,
)
from migration_toolkit.models import MigrationJob, MigrationMappingTemplate, MigrationProfile
from pipelines.models import PipelineRun, PipelineTemplate, PipelineTemplateStep
from projects.models import Project
from registry.models import RegistrationReview, RegistryRecord, RegistryRecordVersion, RegistrySchema
from results.models import Result, WorkItem
from samples.models import Sample, SampleBatch, SampleCustodyEvent, SampleRelationship
from sequences.models import ConstructAssemblyPlan, SequenceRevision, SequenceFeatureLibrary
from settings_app.models import SystemSettings
from notebook.models import Experiment, ExperimentComment, ExperimentReview, Notebook
from workflow_requests.models import WorkflowRequest, WorkflowRequestMessage, WorkflowRequestReport


User = get_user_model()


class DemoUserCredentialTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(name="tech")

    def create_demo_user(self):
        return create_demo_user(
            "demo-tech",
            self.group,
            email="demo-tech@example.invalid",
            first_name="Demo",
            last_name="Technician",
        )

    def test_new_demo_user_has_no_usable_default_password(self):
        user = self.create_demo_user()

        self.assertFalse(user.has_usable_password())

    def test_existing_password_is_preserved(self):
        existing_password = secrets.token_urlsafe(24)
        user = User.objects.create_user(
            username="demo-tech",
            email="old@example.invalid",
            password=existing_password,
        )

        updated_user = self.create_demo_user()

        self.assertTrue(updated_user.check_password(existing_password))

class DemoInstrumentProvenanceTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(username="instrument-tech")
        self.project = Project.objects.create(
            code="PRJ-DEMO-PROVENANCE",
            name="Demo Provenance",
        )
        self.sample = Sample.objects.create(
            sample_id="S-DEMO-PROVENANCE",
            project=self.project,
        )
        self.instrument = InstrumentProfile.objects.create(
            code="DEMO-INSTRUMENT",
            name="Demo Instrument",
            sample_id_column="sample_id",
        )
        self.import_job = ImportJob.objects.create(
            instrument=self.instrument,
            project=self.project,
            uploaded_by=self.actor,
            run_id="DEMO-PROVENANCE-RUN",
            status="COMPLETED",
        )
        self.work_item = WorkItem.objects.create(
            sample=self.sample,
            name="Demo Instrument Results",
            status=WorkItem.STATUS_COMPLETED,
        )
        Result.objects.create(
            work_item=self.work_item,
            key="concentration",
            value_type=Result.VALUE_TYPE_NUMBER,
            value_number=12.4,
        )

    def test_link_demo_import_job_adds_direct_provenance(self):
        counts = link_demo_import_job(
            self.import_job,
            [self.sample.sample_id],
            self.work_item.name,
            self.actor,
        )

        self.work_item.refresh_from_db()
        self.assertEqual(self.work_item.source_import_job, self.import_job)
        self.assertEqual(self.work_item.created_by, self.actor)
        self.assertEqual(counts["linked_sample_count"], 1)
        self.assertEqual(counts["linked_work_item_count"], 1)
        self.assertEqual(counts["linked_result_count"], 1)

    def test_link_demo_import_job_is_safe_to_rerun(self):
        for _ in range(2):
            link_demo_import_job(
                self.import_job,
                [self.sample.sample_id],
                self.work_item.name,
                self.actor,
            )

        self.assertEqual(
            WorkItem.objects.filter(source_import_job=self.import_job).count(),
            1,
        )


class DemoSeedProvenanceIntegrationTests(TestCase):
    def assert_requester_demo(self, requester, report):
        self.assertEqual(list(requester.groups.values_list("name", flat=True)), ["requester"])
        self.assertEqual(list(requester.projects.values_list("code", flat=True)), [DEMO_PROJECT_CODE])
        self.assertFalse(requester.is_staff)
        self.assertFalse(requester.is_superuser)

        portal = APIClient()
        portal.force_authenticate(requester)
        endpoint = "/api/v1/requester-requests/"
        catalog = portal.get(f"{endpoint}catalog/")
        self.assertEqual(catalog.status_code, 200)
        self.assertIn(TEST_CODE, [test["code"] for test in catalog.data["tests"]])
        requests = portal.get(endpoint)
        self.assertEqual(requests.status_code, 200)
        self.assertEqual(
            {row["request_number"]: row["status"] for row in requests.data["results"]},
            {PENDING_REQUEST_NUMBER: "SUBMITTED", COMPLETED_REQUEST_NUMBER: "COMPLETED"},
        )

        pending = requester.workflow_requests.get(request_number=PENDING_REQUEST_NUMBER)
        labels = portal.get(f"{endpoint}{pending.public_id}/labels/")
        self.assertEqual(labels.status_code, 200)
        self.assertTrue(labels.content.startswith(b"%PDF-"))
        self.assertIsNone(pending.items.get().sample_id)

        completed = report.request
        detail = portal.get(f"{endpoint}{completed.public_id}/")
        self.assertIsNotNone(detail.data["samples"][0]["received_at"])
        self.assertEqual(detail.data["reports"][0]["public_id"], str(report.public_id))
        self.assertEqual(completed.reports.count(), 1)
        download = portal.get(f"{endpoint}{completed.public_id}/reports/{report.public_id}/download/")
        self.assertEqual(download.status_code, 200)
        pdf = b"".join(download.streaming_content)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertIn(b"/Type /Page", pdf)
        self.assertEqual(sha256(pdf).hexdigest(), report.checksum_sha256)

        lab = APIClient()
        lab.force_authenticate(User.objects.get(username="peter"))
        lookup = lab.get("/api/v1/samples/accession-lookup/", {"barcode": pending.items.get().submission_barcode})
        self.assertEqual(lookup.status_code, 200)
        self.assertEqual(lookup.data["submission"]["request_number"], PENDING_REQUEST_NUMBER)
        lab_request = lab.get(f"/api/v1/workflow-requests/{completed.pk}/")
        self.assertEqual(lab_request.status_code, 200)
        self.assertEqual(lab_request.data["items"][0]["execution"]["status"], PipelineRun.STATUS_COMPLETED)
        self.assertTrue(lab_request.data["reports"][0]["approved"])

    @patch("core.management.commands.seed_demo.build_blast_database")
    def test_seed_demo_populates_all_instrument_provenance_and_can_rerun(
        self,
        _build_blast_database,
    ):
        expected_runs = {
            "DEMO-RUN-001",
            "MISEQ-RUN-2026-001",
            "MISEQ-RUN-2026-002",
            "ENDOSAFE-RUN-2026-001",
            "QPCR-RUN-2026-001",
            "NANODROP-RUN-2026-001",
            "PLATE-RUN-2026-001",
            "SANGER-RUN-2026-001",
            "BIOANALYZER-RUN-2026-001",
            "HAMILTON-RUN-2026-001",
            "META-CSV-RUN-2026-001",
        }

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                call_command("seed_demo")
                demo_requester = User.objects.get(username=DEMO_REQUESTER_USERNAME)
                self.assertFalse(demo_requester.has_usable_password())
                password = secrets.token_urlsafe(24)
                demo_requester.set_password(password)
                demo_requester.save(update_fields=["password"])
                demo_report = WorkflowRequestReport.objects.get(request__request_number=COMPLETED_REQUEST_NUMBER)
                first_work_item_count = WorkItem.objects.count()
                first_capability_counts = {
                    "links": EntityLink.objects.count(),
                    "attachments": SharedAttachment.objects.count(),
                    "lineage": SampleRelationship.objects.count(),
                    "custody": SampleCustodyEvent.objects.count(),
                    "registry_versions": RegistryRecordVersion.objects.count(),
                    "sequence_revisions": SequenceRevision.objects.count(),
                    "migration_jobs": MigrationJob.objects.count(),
                    "notebooks": Notebook.objects.count(),
                    "experiment_revisions": Experiment.objects.get(title="pOpenLIMS-GFP verification — run 2026-08").revisions.count(),
                    "inventory_transactions": InventoryTransaction.objects.count(),
                    "workflow_requests": WorkflowRequest.objects.count(),
                }
                call_command("seed_demo")
                demo_requester.refresh_from_db()
                self.assertTrue(demo_requester.check_password(password))
                self.assert_requester_demo(demo_requester, demo_report)

        self.assertEqual(WorkItem.objects.count(), first_work_item_count)
        self.assertEqual(
            {
                "links": EntityLink.objects.count(),
                "attachments": SharedAttachment.objects.count(),
                "lineage": SampleRelationship.objects.count(),
                "custody": SampleCustodyEvent.objects.count(),
                "registry_versions": RegistryRecordVersion.objects.count(),
                "sequence_revisions": SequenceRevision.objects.count(),
                "migration_jobs": MigrationJob.objects.count(),
                "notebooks": Notebook.objects.count(),
                "experiment_revisions": Experiment.objects.get(title="pOpenLIMS-GFP verification — run 2026-08").revisions.count(),
                "inventory_transactions": InventoryTransaction.objects.count(),
                "workflow_requests": WorkflowRequest.objects.count(),
            },
            first_capability_counts,
        )
        self.assertEqual(
            set(SampleBatch.objects.values_list("code", flat=True)),
            {"B-ALPHA-01", "B-ALPHA-02", "B-BETA-01", "B-GAMMA-01"},
        )
        self.assertFalse(
            Sample.objects.filter(sample_id__startswith="S-", batch__isnull=True).exists()
        )
        for sample in Sample.objects.filter(sample_id__startswith="S-"):
            keys = set(
                Result.objects.filter(work_item__sample=sample).values_list(
                    "key",
                    flat=True,
                )
            )
            self.assertIn("concentration", keys)
            self.assertIn("purity", keys)
            self.assertIn("response_percent", keys)
        self.assertEqual(
            WorkItem.objects.filter(
                status__in=[WorkItem.STATUS_PENDING, WorkItem.STATUS_IN_PROGRESS],
                work_type__in=[
                    "LIBRARY_PREP",
                    "QC_INVESTIGATION",
                    "RNA_QC_REVIEW",
                    "SEQUENCING_RERUN",
                ],
            ).count(),
            4,
        )
        jobs = ImportJob.objects.filter(run_id__in=expected_runs)
        self.assertEqual(set(jobs.values_list("run_id", flat=True)), expected_runs)
        for job in jobs:
            provenance = job.summary["provenance"]
            self.assertGreater(provenance["linked_sample_count"], 0)
            self.assertGreater(provenance["linked_work_item_count"], 0)
            self.assertGreater(provenance["linked_result_count"], 0)
            self.assertEqual(
                provenance["linked_work_item_count"],
                job.work_items.count(),
            )

        self.assertEqual(SampleRelationship.objects.count(), 4)
        self.assertEqual(SampleCustodyEvent.objects.count(), 5)
        self.assertEqual(InventoryReservation.objects.filter(lot__lot_code="GIBSON-DEMO-2026-01").count(), 3)

        template = PipelineTemplate.objects.get(code="DEMO_PARALLEL_PLASMID")
        self.assertEqual(PipelineTemplateStep.objects.filter(template=template).count(), 5)
        self.assertTrue(PipelineRun.objects.filter(template=template, sample__sample_id="PIPE-DEMO-001").exists())

        self.assertEqual(RegistrySchema.objects.count(), 12)
        self.assertEqual(
            RegistryRecord.objects.filter(
                registry_id__in=[
                    "PLS-DEMO-0001",
                    "PRM-DEMO-0001",
                    "PRO-DEMO-0001",
                    "AB-DEMO-0001",
                    "CL-DEMO-0001",
                ]
            ).count(),
            5,
        )
        self.assertGreaterEqual(RegistryRecordVersion.objects.count(), 6)
        self.assertTrue(RegistrationReview.objects.filter(decision=RegistrationReview.DECISION_APPROVED).exists())
        self.assertTrue(RegistrationReview.objects.filter(decision=RegistrationReview.DECISION_PENDING).exists())
        self.assertGreaterEqual(SequenceRevision.objects.count(), 7)
        self.assertEqual(SequenceFeatureLibrary.objects.count(), 2)
        self.assertEqual(ConstructAssemblyPlan.objects.count(), 1)

        self.assertEqual(EntityLink.objects.count(), 4)
        self.assertEqual(SharedAttachment.objects.count(), 2)
        self.assertTrue(MigrationProfile.objects.filter(name="SISBI Comprehensive Migration Demo").exists())
        self.assertTrue(MigrationMappingTemplate.objects.filter(name="SISBI Full Migration Template").exists())
        self.assertEqual(MigrationJob.objects.filter(profile__name="SISBI Comprehensive Migration Demo").count(), 2)

        self.assertTrue(AlignmentJob.objects.filter(status="COMPLETED").exists())
        self.assertTrue(BlastJob.objects.filter(status=BlastJob.STATUS_COMPLETED).exists())
        self.assertTrue(GeneratedArtifact.objects.filter(filename="openlims_comprehensive_demo_report.pdf").exists())
        self.assertTrue(GeneratedArtifact.objects.filter(filename="openlims_demo_sample_labels.pdf").exists())
        self.assertTrue(AssistantAction.objects.filter(status=AssistantAction.STATUS_PROPOSED).exists())
        self.assertTrue(NotificationSubscription.objects.filter(active=True).exists())
        self.assertTrue(SystemSettings.load().registry_enabled)
        self.assertTrue(SystemSettings.load().notebook_enabled)
        experiment = Experiment.objects.get(title="pOpenLIMS-GFP verification — run 2026-08")
        self.assertEqual(experiment.status, Experiment.STATUS_LOCKED)
        self.assertEqual(experiment.revisions.count(), 1)
        self.assertEqual(experiment.current_revision.blocks.count(), 10)
        self.assertGreaterEqual(experiment.current_revision.links.count(), 5)
        self.assertTrue(ExperimentReview.objects.filter(experiment=experiment, decision="APPROVED").exists())
        self.assertTrue(ExperimentComment.objects.filter(experiment=experiment, revision=experiment.current_revision).exists())
        self.assertEqual(BarcodeIdentity.objects.filter(active=True).count(), 5)
        self.assertEqual(InventoryPlacement.objects.filter(container__container_id="DEMO-REQUEST-PLATE-01").count(), 2)
        self.assertTrue(InventoryTransaction.objects.filter(lot__lot_code="GIBSON-DEMO-2026-01").exists())
        self.assertTrue(InventoryCycleCount.objects.filter(name="Monthly Molecular Biology Count").exists())
        workflow_request = WorkflowRequest.objects.get(request_number="REQ-DEMO-0001")
        self.assertEqual(workflow_request.status, WorkflowRequest.STATUS_APPROVED)
        self.assertTrue(workflow_request.items.filter(pipeline_run__isnull=False).exists())
        self.assertTrue(WorkflowRequestMessage.objects.filter(request=workflow_request).exists())
        self.assertTrue(WorkflowRequestReport.objects.filter(request=workflow_request, approved=True).exists())
