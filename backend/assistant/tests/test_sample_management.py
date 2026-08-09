from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.models import AssistantAction
from custom_fields.models import FieldDefinition, FieldValue
from events.models import Event
from projects.models import Project
from samples.models import Sample, SampleBatch


class AssistantSampleManagementTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.tech = user_model.objects.create_user(
            username="eduardo-tech",
            password="test-password",
        )
        self.maria = user_model.objects.create_user(
            username="maria",
            first_name="Maria",
            password="test-password",
        )
        self.viewer = user_model.objects.create_user(
            username="sample-viewer",
            password="test-password",
        )
        self.other_tech = user_model.objects.create_user(
            username="other-tech",
            password="test-password",
        )

        tech_group, _ = Group.objects.get_or_create(name="tech")
        viewer_group, _ = Group.objects.get_or_create(name="viewer")
        self.tech.groups.add(tech_group)
        self.maria.groups.add(tech_group)
        self.other_tech.groups.add(tech_group)
        self.viewer.groups.add(viewer_group)

        self.alpha = Project.objects.create(code="ALPHA", name="Alpha")
        self.beta = Project.objects.create(code="BETA", name="Beta")
        self.alpha.members.add(self.tech, self.maria, self.viewer)
        self.beta.members.add(self.other_tech)

        self.study_field = FieldDefinition.objects.create(
            entity_type="Sample",
            name="study_id",
            label="Study ID",
            data_type="string",
            required=True,
            rules={"min_length": 3},
        )

    def make_sample(
        self,
        sample_id,
        *,
        status=Sample.STATUS_RECEIVED,
        project=None,
        with_metadata=True,
        created_by=None,
    ):
        sample = Sample.objects.create(
            sample_id=sample_id,
            status=status,
            project=project or self.alpha,
            created_by=created_by or self.tech,
        )
        if with_metadata:
            FieldValue.objects.create(
                field_definition=self.study_field,
                entity_type="Sample",
                entity_id=str(sample.id),
                value="STUDY-1",
            )
        return sample

    def chat(self, message, *, user=None, context=None):
        self.client.force_authenticate(user or self.tech)
        return self.client.post(
            "/api/assistant/chat/",
            {"message": message, "context": context or {}},
            format="json",
        )

    def confirm(self, response, *, user=None):
        token = response.data["pending_action"]["confirmation_token"]
        self.client.force_authenticate(user or self.tech)
        return self.client.post(
            f"/api/assistant/actions/{token}/confirm/",
            {"confirm": True},
            format="json",
        )

    def test_read_only_sample_commands_are_permission_filtered(self):
        sample = self.make_sample("S-1042")
        self.make_sample("S-BETA-1", project=self.beta, created_by=self.other_tech)

        found = self.chat("Find sample S-1042.")
        received = self.chat("Show samples received today.")
        awaiting = self.chat(
            "Which samples in Project Alpha are awaiting processing?"
        )
        summary = self.chat("Summarize sample S-1042.")
        hidden = self.chat("Find sample S-BETA-1.")

        self.assertEqual(found.status_code, 200)
        self.assertIn("Found sample S-1042", found.data["answer"])
        self.assertEqual(found.data["context"]["sample_ids"], [sample.id])
        self.assertIn("Samples received today", received.data["answer"])
        self.assertIn("S-1042", received.data["answer"])
        self.assertIn("S-1042", awaiting.data["answer"])
        self.assertIn("Study ID: STUDY-1", summary.data["answer"])
        self.assertIn("not found or is not accessible", hidden.data["answer"])
        self.assertEqual(hidden.data["links"], [])
        self.assertNotIn("pending_action", found.data)

    def test_create_samples_validates_required_fields_and_is_idempotent(self):
        blocked = self.chat("Create 2 samples for Project Alpha.")
        self.assertNotIn("pending_action", blocked.data)
        self.assertIn("required custom-field", blocked.data["answer"])

        proposal = self.chat(
            "Create 2 samples for Project Alpha with study_id=STUDY-2."
        )
        action = proposal.data["pending_action"]
        preview = action["preview"]
        self.assertEqual(preview["records_affected"], 2)
        self.assertEqual(preview["project"]["code"], "ALPHA")
        self.assertEqual(
            preview["requested_user"]["username"],
            self.tech.username,
        )
        self.assertEqual(
            [row["sample_id"] for row in preview["samples"]],
            ["ALPHA-S-0001", "ALPHA-S-0002"],
        )

        first = self.confirm(proposal)
        second = self.confirm(proposal)

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["result"]["succeeded_count"], 2)
        self.assertEqual(
            Sample.objects.filter(sample_id__startswith="ALPHA-S-").count(),
            2,
        )
        self.assertEqual(
            Event.objects.filter(action="SAMPLE_CREATED_BY_ASSISTANT").count(),
            2,
        )
        self.assertEqual(
            AssistantAction.objects.get(id=action["id"]).status,
            AssistantAction.STATUS_COMPLETED,
        )

    def test_sample_ids_are_case_insensitively_unique(self):
        self.make_sample("S-DUPLICATE")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Sample.objects.create(
                    sample_id="s-duplicate",
                    project=self.alpha,
                    created_by=self.tech,
                )

    def test_project_access_is_checked_before_sample_write_proposal(self):
        response = self.chat(
            "Create 1 sample for Project Beta with study_id=STUDY-2."
        )
        viewer = self.chat(
            "Create 1 sample for Project Alpha with study_id=STUDY-2.",
            user=self.viewer,
        )

        self.assertNotIn("pending_action", response.data)
        self.assertIn("do not have access", response.data["answer"])
        self.assertNotIn("pending_action", viewer.data)
        self.assertIn("Only tech or admin", viewer.data["answer"])

    def test_processing_alias_follows_workflow_and_audits_once(self):
        sample = self.make_sample("S-1042")
        proposal = self.chat("Change sample S-1042 to PROCESSING.")
        self.assertIn("pending_action", proposal.data, proposal.data)
        preview = proposal.data["pending_action"]["preview"]

        self.assertEqual(preview["current_values"]["status"], ["RECEIVED"])
        self.assertEqual(
            preview["proposed_values"]["status"],
            Sample.STATUS_IN_PROGRESS,
        )

        first = self.confirm(proposal)
        second = self.confirm(proposal)
        sample.refresh_from_db()

        self.assertEqual(first.data["result"]["succeeded_count"], 1)
        self.assertEqual(second.data["result"]["succeeded_count"], 1)
        self.assertEqual(sample.status, Sample.STATUS_IN_PROGRESS)
        self.assertEqual(
            Event.objects.filter(
                entity_type="Sample",
                entity_id=str(sample.id),
                action="SAMPLE_STATUS_CHANGED",
            ).count(),
            1,
        )

    def test_invalid_archive_is_not_proposed(self):
        self.make_sample("S-1042", status=Sample.STATUS_RECEIVED)
        response = self.chat("Archive sample S-1042.")

        self.assertNotIn("pending_action", response.data)
        self.assertEqual(response.data["preview"]["records_affected"], 0)
        self.assertIn(
            "transition from RECEIVED to ARCHIVED is not permitted",
            response.data["preview"]["excluded"][0]["reason"],
        )

    def test_bulk_status_preview_freezes_ids_and_excludes_missing_metadata(self):
        first = self.make_sample("S-100")
        second = self.make_sample("S-101")
        missing = self.make_sample("S-102", with_metadata=False)

        proposal = self.chat(
            "Move all received samples in Project Alpha to PROCESSING."
        )
        self.assertIn("pending_action", proposal.data, proposal.data)
        preview = proposal.data["pending_action"]["preview"]
        self.assertEqual(preview["records_affected"], 2)
        self.assertEqual(preview["excluded_count"], 1)
        self.assertEqual(preview["excluded"][0]["sample_id"], missing.sample_id)

        created_after_preview = self.make_sample("S-103")
        confirmed = self.confirm(proposal)

        first.refresh_from_db()
        second.refresh_from_db()
        missing.refresh_from_db()
        created_after_preview.refresh_from_db()
        self.assertEqual(confirmed.data["result"]["succeeded_count"], 2)
        self.assertEqual(first.status, Sample.STATUS_IN_PROGRESS)
        self.assertEqual(second.status, Sample.STATUS_IN_PROGRESS)
        self.assertEqual(missing.status, Sample.STATUS_RECEIVED)
        self.assertEqual(created_after_preview.status, Sample.STATUS_RECEIVED)
        self.assertNotIn(
            created_after_preview.id,
            confirmed.data["result"]["frozen_sample_ids"],
        )

    def test_bulk_execution_reports_record_drift_individually(self):
        first = self.make_sample("S-100")
        second = self.make_sample("S-101")
        proposal = self.chat(
            "Move all received samples in Project Alpha to PROCESSING."
        )
        self.assertIn("pending_action", proposal.data, proposal.data)

        second.status = Sample.STATUS_CANCELLED
        second.save(update_fields=["status", "updated_at"])
        confirmed = self.confirm(proposal)
        first.refresh_from_db()
        second.refresh_from_db()

        self.assertEqual(confirmed.data["result"]["succeeded_count"], 1)
        self.assertEqual(confirmed.data["result"]["failed_count"], 1)
        self.assertEqual(
            confirmed.data["result"]["failed"][0]["sample_id"],
            second.sample_id,
        )
        self.assertIn(
            "changed after preview",
            confirmed.data["result"]["failed"][0]["reason"],
        )
        self.assertEqual(first.status, Sample.STATUS_IN_PROGRESS)
        self.assertEqual(second.status, Sample.STATUS_CANCELLED)

    @override_settings(OPENLIMS_ASSISTANT_BULK_MAX_RECORDS=1)
    def test_configurable_bulk_maximum_blocks_large_preview(self):
        self.make_sample("S-100")
        self.make_sample("S-101")

        response = self.chat(
            "Move all received samples in Project Alpha to PROCESSING."
        )

        self.assertNotIn("pending_action", response.data)
        self.assertIn("configured assistant maximum of 1", response.data["answer"])

    def test_range_add_to_batch_and_assignment_are_confirmed_and_audited(self):
        samples = [
            self.make_sample(f"S-{value}")
            for value in range(100, 104)
        ]
        proposal = self.chat(
            "Add samples S-100 through S-103 to batch B-100."
        )
        preview = proposal.data["pending_action"]["preview"]
        self.assertEqual(preview["records_affected"], 4)
        self.assertEqual(preview["proposed_values"]["batch"], "B-100")

        added = self.confirm(proposal)
        batch = SampleBatch.objects.get(code="B-100")
        self.assertEqual(added.data["result"]["succeeded_count"], 4)
        self.assertEqual(
            Sample.objects.filter(batch=batch).count(),
            4,
        )

        assignment = self.chat(
            "Assign all unassigned samples in this batch to Maria.",
            context=added.data["result"]["context"],
        )
        assigned = self.confirm(assignment)

        self.assertEqual(assigned.data["result"]["succeeded_count"], 4)
        self.assertEqual(
            Sample.objects.filter(batch=batch, assigned_to=self.maria).count(),
            4,
        )
        self.assertEqual(
            Event.objects.filter(action="SAMPLE_BATCH_CHANGED").count(),
            4,
        )
        self.assertEqual(
            Event.objects.filter(action="SAMPLE_ASSIGNED").count(),
            4,
        )
        self.assertEqual(
            {sample.id for sample in samples},
            set(assigned.data["result"]["frozen_sample_ids"]),
        )

    def test_archive_cancelled_samples_uses_status_age(self):
        old = self.make_sample("S-OLD", status=Sample.STATUS_CANCELLED)
        recent = self.make_sample("S-RECENT", status=Sample.STATUS_CANCELLED)
        Sample.objects.filter(id=old.id).update(
            status_changed_at=timezone.now() - timedelta(days=91)
        )

        proposal = self.chat("Archive cancelled samples older than 90 days.")
        preview_codes = {
            row["sample_id"]
            for row in proposal.data["pending_action"]["preview"]["samples"]
        }
        self.assertEqual(preview_codes, {old.sample_id})

        confirmed = self.confirm(proposal)
        old.refresh_from_db()
        recent.refresh_from_db()
        self.assertEqual(confirmed.data["result"]["succeeded_count"], 1)
        self.assertEqual(old.status, Sample.STATUS_ARCHIVED)
        self.assertEqual(recent.status, Sample.STATUS_CANCELLED)
        self.assertTrue(
            Event.objects.filter(
                entity_id=str(old.id),
                action="SAMPLE_ARCHIVED",
            ).exists()
        )

    def test_permanent_deletion_is_explicitly_refused(self):
        self.make_sample("S-1042")
        response = self.chat("Permanently delete sample S-1042.")

        self.assertNotIn("pending_action", response.data)
        self.assertIn("Permanent sample deletion is not supported", response.data["answer"])
        self.assertTrue(Sample.objects.filter(sample_id="S-1042").exists())
