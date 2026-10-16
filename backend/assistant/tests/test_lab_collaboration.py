from django.contrib.auth.models import Group
from django.test import override_settings
from rest_framework.test import APITestCase

from assistant.models import AssistantAction
from notebook.models import ExperimentWorkflowStep, ExperimentLink, ExperimentBlock
from pipelines.models import AnalysisDefinition, ProcedureDefinition, PipelineTemplate
from inventory.models import InventoryItem, InventoryLot
from . import test_comparisons, test_lab_reviews


class CollaborationTests(APITestCase):
    setUp = test_comparisons.AssistantComparisonTests.setUp
    chat = test_comparisons.AssistantComparisonTests.chat
    experiment = test_lab_reviews.LabReviewTests.experiment

    def procedure(self, version="1", active=True):
        analysis, _ = AnalysisDefinition.objects.get_or_create(code="EX", defaults={"name": "Extraction"})
        return ProcedureDefinition.objects.create(code="EX", name="Extraction", analysis=analysis, version=version, active=active)

    def admin(self):
        self.tech.groups.add(Group.objects.get_or_create(name="admin")[0])

    def test_workflow_requires_admin_and_does_not_write(self):
        procedure = self.procedure()
        self.assertNotIn("draft", self.chat("Create a workflow with EX").data)
        self.admin()
        data = self.chat("Create a workflow with EX, and EX@1").data
        self.assertEqual([step["procedure"] for step in data["draft"]["workflow"]["steps"]], [procedure.pk, procedure.pk])
        self.assertEqual(PipelineTemplate.objects.count(), 0)
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_workflow_ambiguous_inactive_and_missing_procedures(self):
        self.admin()
        self.procedure()
        self.procedure("2")
        self.procedure("3", active=False)
        for prompt in ["EX", "EX@3", "UNKNOWN", "EX@1, UNKNOWN"]:
            with self.subTest(prompt=prompt):
                data = self.chat(f"Draft a workflow using {prompt}").data
                self.assertNotIn("draft", data)
        self.assertIn("draft", self.chat("Draft a workflow using EX@2").data)

    def test_handover_requires_shared_access_and_preserves_assignment(self):
        work = self.samples[1].work_items.first()
        work.assigned_to = self.tech
        work.status = "FAILED"
        work.save()
        prompt = "Prepare eduardo’s handover for outsider"
        self.assertNotIn("S-101", str(self.chat(prompt).data))
        self.alpha.members.add(self.outsider)
        data = self.chat(prompt).data
        self.assertIn("S-101", data["draft"]["text"])
        self.assertIn("OVERDUE", data["draft"]["text"])
        self.assertIn("REVIEW BLOCKER", data["draft"]["text"])
        self.assertNotIn("S-102", str(data))
        work.refresh_from_db()
        self.assertEqual(work.assigned_to, self.tech)
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_handover_requester_access_and_terminal_exclusion(self):
        self.alpha.members.add(self.outsider)
        work = self.samples[0].work_items.first()
        work.status = "COMPLETED"
        work.save()
        self.assertNotIn("S-100", str(self.chat("Draft eduardo's handover for outsider").data))
        self.assertNotIn("draft", self.chat("Draft eduardo's handover for missing").data)
        private_work = self.private_sample.work_items.first()
        private_work.assigned_to = self.outsider
        private_work.save()
        self.assertNotIn("S-PRIVATE", str(self.chat("Draft outsider's handover for outsider").data))

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
    def test_compare_records_unknowns_lots_and_no_causal_claims(self):
        left = self.experiment(self.tech, "Run A")
        right = self.experiment(self.tech, "Run B")
        for experiment, value in [(left, 10), (right, 12)]:
            ExperimentWorkflowStep.objects.create(experiment=experiment, position=1, definition={"name": "Incubate"}, values={"minutes": value})
        ExperimentBlock.objects.create(revision=left.current_revision, position=1, block_type="STRUCTURED_RESULT", data={"qc": "passed"})
        item = InventoryItem.objects.create(code="BUF", name="Buffer", default_unit="mL")
        lot = InventoryLot.objects.create(item=item, lot_code="L1", quantity=10, unit="mL")
        ExperimentLink.objects.create(revision=left.current_revision, entity_type="inventory_lot", entity_public_id=lot.public_id, label="Untrusted label")
        data = self.chat(f"Compare runs {left.public_id} and {right.public_id}").data
        rows = {row["field"]: row for row in data["comparison"]["rows"]}
        self.assertEqual(rows["Step 1: recorded parameters"]["finding"], "Different")
        self.assertEqual(rows["Result block 1 (recorded data)"]["finding"], "Unknown (missing record)")
        self.assertIn("L1", str(data))
        self.assertNotIn("Untrusted label", str(data))
        self.assertIn("causal", data["answer"])
        self.assertEqual(AssistantAction.objects.count(), 0)

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
    def test_compare_private_ambiguous_and_same_run(self):
        left = self.experiment(self.tech, "Shared")
        private = self.experiment(self.outsider, "Secret")
        for other in [str(private.public_id), "Missing", str(left.public_id)]:
            self.assertNotIn("comparison", self.chat(f"Compare runs {left.public_id} and {other}").data)
        self.experiment(self.tech, "Shared")
        self.assertNotIn("comparison", self.chat("Compare runs Shared and Secret").data)

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
    def test_comparison_marks_display_truncation_without_hiding_difference(self):
        left = self.experiment(self.tech, "First")
        right = self.experiment(self.tech, "Second")
        for exp, suffix in [(left, "A"), (right, "B")]:
            ExperimentWorkflowStep.objects.create(experiment=exp, position=1,
                definition={"name": "Step"}, values={"text": "x" * 4100 + suffix})
        data = self.chat("Explain differences between experiments First and Second").data
        row = next(row for row in data["comparison"]["rows"] if "parameters" in row["field"])
        self.assertEqual(row["finding"], "Different")
        self.assertEqual(len(row["left"]), 4000)
        self.assertIn("Partial comparison", str(data["comparison"]["notes"]))

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=True)
    def test_notebook_disabled(self):
        from unittest.mock import patch
        with patch("assistant.lab_collaboration.enabled", return_value=False):
            self.assertIn("disabled", self.chat("Compare runs A and B").data["answer"])
