from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APITestCase

from alignments.models import AlignmentJob
from assistant.models import AssistantAction
from blast.models import BlastDatabase, BlastJob
from custom_fields.models import FieldDefinition, FieldValue
from events.models import Event
from imports.models import ImportJob, InstrumentProfile
from inventory.models import Container, Location
from projects.models import Project
from results.models import WorkItem
from samples.models import Sample
from sequences.models import Sequence


class AssistantAttentionTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.tech = user_model.objects.create_user(
            username="attention-tech",
            password="test-password",
        )
        self.admin = user_model.objects.create_user(
            username="attention-admin",
            password="test-password",
        )
        tech_group, _ = Group.objects.get_or_create(name="tech")
        admin_group, _ = Group.objects.get_or_create(name="admin")
        self.tech.groups.add(tech_group)
        self.admin.groups.add(admin_group)

        self.visible_project = Project.objects.create(
            code="PRJ-ATTN-VISIBLE",
            name="Visible Attention Project",
        )
        self.hidden_project = Project.objects.create(
            code="PRJ-ATTN-HIDDEN",
            name="Hidden Attention Project",
        )
        self.visible_project.members.add(self.tech)

        location = Location.objects.create(name="Freezer A", kind="freezer")
        container = Container.objects.create(
            container_id="ATTN-BOX-1",
            kind="box",
            location=location,
        )

        self.required_field = FieldDefinition.objects.create(
            entity_type="Sample",
            name="study_id",
            label="Study ID",
            data_type="string",
            required=True,
        )

        self.stuck_sample = Sample.objects.create(
            sample_id="S-ATTN-STUCK",
            status=Sample.STATUS_RECEIVED,
            project=self.visible_project,
            container=container,
            created_by=self.tech,
        )
        self.recent_sample = Sample.objects.create(
            sample_id="S-ATTN-RECENT",
            status=Sample.STATUS_IN_PROGRESS,
            project=self.visible_project,
            container=container,
            created_by=self.tech,
        )
        self.recent_transition_sample = Sample.objects.create(
            sample_id="S-ATTN-RECENT-TRANSITION",
            status=Sample.STATUS_IN_PROGRESS,
            project=self.visible_project,
            container=container,
            created_by=self.tech,
        )
        self.missing_sample = Sample.objects.create(
            sample_id="S-ATTN-MISSING",
            status=Sample.STATUS_RECEIVED,
            project=None,
            container=None,
            created_by=self.tech,
        )
        self.hidden_sample = Sample.objects.create(
            sample_id="S-ATTN-HIDDEN",
            status=Sample.STATUS_RECEIVED,
            project=self.hidden_project,
            container=None,
            created_by=self.admin,
        )

        old_timestamp = timezone.now() - timedelta(days=5)
        Sample.objects.filter(
            id__in=[
                self.stuck_sample.id,
                self.recent_transition_sample.id,
                self.hidden_sample.id,
            ]
        ).update(created_at=old_timestamp)

        for sample in [
            self.stuck_sample,
            self.recent_sample,
            self.recent_transition_sample,
        ]:
            FieldValue.objects.create(
                field_definition=self.required_field,
                entity_type="Sample",
                entity_id=str(sample.id),
                value="STUDY-1",
            )

        Event.objects.create(
            entity_type="Sample",
            entity_id=str(self.recent_transition_sample.id),
            action="SAMPLE_STATUS_CHANGED",
            actor=self.tech,
            payload={"changed_fields": ["status"]},
        )

        self.pending_qc = WorkItem.objects.create(
            sample=self.recent_sample,
            name="Pending QC review",
            status=WorkItem.STATUS_COMPLETED,
            qc_status=WorkItem.QC_PENDING_REVIEW,
        )
        self.failed_qc = WorkItem.objects.create(
            sample=self.stuck_sample,
            name="Rejected QC review",
            status=WorkItem.STATUS_COMPLETED,
            qc_status=WorkItem.QC_REJECTED,
        )
        self.old_work_item = WorkItem.objects.create(
            sample=self.stuck_sample,
            name="Old open work",
            status=WorkItem.STATUS_IN_PROGRESS,
        )
        self.hidden_work_item = WorkItem.objects.create(
            sample=self.hidden_sample,
            name="Hidden old work",
            status=WorkItem.STATUS_PENDING,
        )
        WorkItem.objects.filter(
            id__in=[self.old_work_item.id, self.hidden_work_item.id]
        ).update(created_at=old_timestamp)

        self.instrument = InstrumentProfile.objects.create(
            name="Attention Instrument",
            code="ATTN-INST",
            sample_id_column="sample_id",
        )
        self.visible_import = ImportJob.objects.create(
            instrument=self.instrument,
            project=self.visible_project,
            uploaded_by=self.tech,
            status="FAILED",
        )
        self.hidden_import = ImportJob.objects.create(
            instrument=self.instrument,
            project=self.hidden_project,
            uploaded_by=self.admin,
            status="FAILED",
        )

        self.visible_sequence = Sequence.objects.create(
            name="Visible attention sequence",
            sequence="ATGCGT",
            project=self.visible_project,
            sample=self.stuck_sample,
            created_by=self.tech,
        )
        self.hidden_sequence = Sequence.objects.create(
            name="Hidden attention sequence",
            sequence="ATGCGC",
            project=self.hidden_project,
            sample=self.hidden_sample,
            created_by=self.admin,
        )
        self.blast_database = BlastDatabase.objects.create(
            name="Attention BLAST database",
            status=BlastDatabase.STATUS_READY,
            db_path="/tmp/attention-blast-db",
            created_by=self.admin,
        )
        self.visible_blast = BlastJob.objects.create(
            name="Visible failed BLAST",
            project=self.visible_project,
            query_sequence=self.visible_sequence,
            database=self.blast_database,
            status=BlastJob.STATUS_FAILED,
            created_by=self.tech,
        )
        self.hidden_blast = BlastJob.objects.create(
            name="Hidden failed BLAST",
            project=self.hidden_project,
            query_sequence=self.hidden_sequence,
            database=self.blast_database,
            status=BlastJob.STATUS_FAILED,
            created_by=self.admin,
        )

        self.visible_alignment = AlignmentJob.objects.create(
            name="Visible failed alignment",
            project=self.visible_project,
            status="FAILED",
            created_by=self.tech,
        )
        self.hidden_alignment = AlignmentJob.objects.create(
            name="Hidden failed alignment",
            project=self.hidden_project,
            status="FAILED",
            created_by=self.admin,
        )

    def post_attention_question(self, user, message="What needs attention?"):
        self.client.force_authenticate(user)
        return self.client.post(
            "/api/assistant/chat/",
            {"message": message, "context": {}},
            format="json",
        )

    def response_ids(self, response):
        data = response.data
        rows = data.get("results", data)
        return {row["id"] for row in rows}

    @patch("assistant.attention.build_health_status")
    def test_attention_summary_is_exact_permission_filtered_and_read_only(
        self,
        health_mock,
    ):
        events_before = Event.objects.count()
        actions_before = AssistantAction.objects.count()

        response = self.post_attention_question(self.tech)

        self.assertEqual(response.status_code, 200)
        health_mock.assert_not_called()

        attention = response.data["attention"]
        self.assertEqual(attention["total"], 8)
        self.assertEqual(attention["counts"]["stuck_samples"], 1)
        self.assertEqual(
            attention["counts"]["missing_sample_information"],
            1,
        )
        self.assertEqual(attention["counts"]["pending_qc_reviews"], 1)
        self.assertEqual(attention["counts"]["failed_qc_reviews"], 1)
        self.assertEqual(attention["counts"]["overdue_work_items"], 1)
        self.assertEqual(attention["counts"]["failed_imports"], 1)
        self.assertEqual(attention["counts"]["failed_blast_jobs"], 1)
        self.assertEqual(attention["counts"]["failed_alignments"], 1)
        self.assertEqual(attention["counts"]["system_warnings"], 0)
        self.assertTrue(attention["system_health_restricted"])
        self.assertFalse(attention["inventory_checks_available"])
        self.assertNotIn(
            self.recent_transition_sample.id,
            attention["details"]["stuck_sample_ids"],
        )
        self.assertNotIn(
            self.hidden_sample.id,
            attention["details"]["stuck_sample_ids"],
        )
        self.assertNotIn("Hidden", response.data["answer"])
        self.assertNotIn("pending_action", response.data)
        self.assertEqual(Event.objects.count(), events_before)
        self.assertEqual(AssistantAction.objects.count(), actions_before)

    @patch("assistant.attention.build_health_status")
    def test_admin_can_read_scoped_system_health_warnings(self, health_mock):
        health_mock.return_value = {
            "status": "degraded",
            "db_ok": True,
            "redis_ok": False,
            "redis_error": "Redis unavailable",
            "clustalo_ok": True,
            "blastn_ok": True,
            "blastp_ok": True,
            "makeblastdb_ok": True,
            "pyopenms_ok": False,
            "pyopenms_error": "pyOpenMS missing",
        }

        response = self.post_attention_question(
            self.admin,
            "Show system health warnings",
        )

        self.assertEqual(response.status_code, 200)
        health_mock.assert_called_once_with()
        attention = response.data["attention"]
        self.assertEqual(attention["scope"], "system_health")
        self.assertEqual(attention["total"], 2)
        self.assertEqual(attention["counts"]["system_warnings"], 2)
        self.assertFalse(attention["system_health_restricted"])
        self.assertTrue(
            any(link["url"] == "/system-status" for link in response.data["links"])
        )

    def test_follow_up_prompt_returns_only_failed_jobs(self):
        response = self.post_attention_question(self.tech, "Show failed jobs")

        self.assertEqual(response.status_code, 200)
        attention = response.data["attention"]
        self.assertEqual(attention["scope"], "failed_jobs")
        self.assertEqual(attention["total"], 3)
        self.assertNotIn("Samples in the same", response.data["answer"])
        self.assertIn("Failed BLAST jobs: 1", response.data["answer"])

    def test_inventory_scope_explains_current_coverage(self):
        response = self.post_attention_question(
            self.tech,
            "Show inventory warnings",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["attention"]["scope"], "inventory")
        self.assertEqual(response.data["attention"]["total"], 0)
        self.assertIn("not quantities or expiration dates", response.data["answer"])

    def test_project_scoped_pages_match_attention_visibility(self):
        self.client.force_authenticate(self.tech)

        work_items = self.client.get("/api/work-items/")
        imports = self.client.get("/api/import-jobs/")
        blast_jobs = self.client.get("/api/blast-jobs/")
        alignments = self.client.get("/api/alignment-jobs/")

        self.assertNotIn(self.hidden_work_item.id, self.response_ids(work_items))
        self.assertEqual(self.response_ids(imports), {self.visible_import.id})
        self.assertEqual(self.response_ids(blast_jobs), {self.visible_blast.id})
        self.assertEqual(
            self.response_ids(alignments),
            {self.visible_alignment.id},
        )
