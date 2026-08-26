import secrets
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.management.commands.seed_demo import (
    create_demo_user,
    link_demo_import_job,
)
from core.models import EntityLink, SharedAttachment
from alignments.models import AlignmentJob
from assistant.models import AssistantAction, GeneratedArtifact, NotificationSubscription
from blast.models import BlastJob
from imports.models import ImportJob, InstrumentProfile
from inventory.models import InventoryReservation
from migration_toolkit.models import MigrationJob, MigrationMappingTemplate, MigrationProfile
from pipelines.models import PipelineRun, PipelineTemplate, PipelineTemplateStep
from projects.models import Project
from registry.models import RegistrationReview, RegistryRecord, RegistryRecordVersion, RegistrySchema
from results.models import Result, WorkItem
from samples.models import Sample, SampleBatch, SampleCustodyEvent, SampleRelationship
from sequences.models import ConstructAssemblyPlan, SequenceRevision, SequenceFeatureLibrary
from settings_app.models import SystemSettings


User = get_user_model()


class DemoUserCredentialTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(name="tech")

    def create_demo_user(self, *, password=None):
        return create_demo_user(
            "demo-tech",
            self.group,
            email="demo-tech@example.invalid",
            first_name="Demo",
            last_name="Technician",
            password=password,
        )

    def test_new_demo_user_has_no_usable_default_password(self):
        user = self.create_demo_user()

        self.assertFalse(user.has_usable_password())

    def test_existing_password_is_preserved_without_environment_password(self):
        existing_password = secrets.token_urlsafe(24)
        user = User.objects.create_user(
            username="demo-tech",
            email="old@example.invalid",
            password=existing_password,
        )

        updated_user = self.create_demo_user()

        self.assertTrue(updated_user.check_password(existing_password))

    def test_environment_password_replaces_existing_password(self):
        old_password = secrets.token_urlsafe(24)
        new_password = secrets.token_urlsafe(24)
        User.objects.create_user(
            username="demo-tech",
            email="old@example.invalid",
            password=old_password,
        )

        updated_user = self.create_demo_user(password=new_password)

        self.assertFalse(updated_user.check_password(old_password))
        self.assertTrue(updated_user.check_password(new_password))


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
                first_work_item_count = WorkItem.objects.count()
                first_capability_counts = {
                    "links": EntityLink.objects.count(),
                    "attachments": SharedAttachment.objects.count(),
                    "lineage": SampleRelationship.objects.count(),
                    "custody": SampleCustodyEvent.objects.count(),
                    "registry_versions": RegistryRecordVersion.objects.count(),
                    "sequence_revisions": SequenceRevision.objects.count(),
                    "migration_jobs": MigrationJob.objects.count(),
                }
                call_command("seed_demo")

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
        self.assertEqual(SampleCustodyEvent.objects.count(), 4)
        self.assertEqual(InventoryReservation.objects.filter(lot__lot_code="GIBSON-DEMO-2026-01").count(), 2)

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
        self.assertEqual(SharedAttachment.objects.count(), 1)
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
