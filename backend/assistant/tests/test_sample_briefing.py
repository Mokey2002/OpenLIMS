from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.models import AssistantAction
from assistant.provider_tools import dispatch_tool
from assistant.sample_briefing import RECENT_RESULT_LIMIT, sample_briefing
from events.models import Event
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample


class SampleBriefingTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="briefing-tech")
        cls.user.groups.add(Group.objects.get_or_create(name="tech")[0])
        cls.viewer = get_user_model().objects.create_user(username="briefing-viewer")
        cls.project = Project.objects.create(code="BRIEF", name="Briefing")
        cls.project.members.add(cls.user, cls.viewer)
        cls.sample = Sample.objects.create(
            sample_id="BRIEF-001", project=cls.project, created_by=cls.user
        )
        cls.work = WorkItem.objects.create(sample=cls.sample, name="Chemistry")

    def setUp(self):
        self.client.force_authenticate(self.user)

    def chat(self, message="Summarize sample BRIEF-001", context=None):
        result = self.client.post(
            "/api/assistant/chat/",
            {"message": message, "context": context or {}},
            format="json",
        )
        self.assertEqual(result.status_code, 200, result.data)
        return result.data

    def test_counts_distinguish_unfinished_work_checks_and_reviews(self):
        self.work.due_at = timezone.now() - timedelta(days=1)
        self.work.qc_status = WorkItem.QC_RERUN_REQUIRED
        self.work.save()
        for status in [WorkItem.STATUS_FAILED, WorkItem.STATUS_COMPLETED, WorkItem.STATUS_CANCELLED]:
            WorkItem.objects.create(
                sample=self.sample, name=status, status=status,
                due_at=self.work.due_at, qc_status=WorkItem.QC_REJECTED,
            )
        for key, passed, status in [
            ("failed", False, Result.QC_REJECTED),
            ("pending", True, Result.QC_PENDING_REVIEW),
            ("reopened", None, Result.QC_REOPENED),
        ]:
            Result.objects.create(work_item=self.work, key=key, qc_passed=passed, qc_status=status)

        data = self.chat()

        self.assertEqual(data["sample_briefing"]["work"], {
            "total": 4, "unfinished": 2, "overdue": 2,
            "unassigned": 2, "failed": 1, "qc_review": 2,
        })
        self.assertEqual(data["sample_briefing"]["results"], {
            "total": 3, "failed_checks": 1, "awaiting_review": 2, "rejected": 1,
        })
        self.assertIn("counts may overlap", data["answer"])
        self.assertIn("authorized reviewer", data["answer"])
        self.assertIn("QC check: passed; review: PENDING_REVIEW", data["answer"])

    def test_typed_values_units_and_unknown_outcomes_are_preserved(self):
        for key, fields in [
            ("concentration", {"value_type": Result.VALUE_TYPE_NUMBER, "value_number": 0, "unit": "ng/uL"}),
            ("detected", {"value_type": Result.VALUE_TYPE_BOOLEAN, "value_boolean": False}),
            ("missing", {"value_type": Result.VALUE_TYPE_NUMBER}),
            ("appearance", {"value_string": "clear"}),
        ]:
            Result.objects.create(work_item=self.work, key=key, **fields)

        data = self.chat()
        values = {row["key"]: row["value"] for row in data["sample_briefing"]["recent_results"]}
        self.assertEqual(values, {"concentration": 0, "detected": False, "missing": None, "appearance": "clear"})
        self.assertIn("0.0 ng/uL", data["answer"])
        self.assertIn("detected (Chemistry): False", data["answer"])
        self.assertIn("missing (Chemistry): not recorded", data["answer"])
        self.assertIn("QC check: not evaluated", data["answer"])

    def test_recent_results_are_bounded_but_totals_include_older_failures(self):
        older = Result.objects.create(
            work_item=self.work, key="old-failure", qc_passed=False, qc_status=Result.QC_REJECTED
        )
        Result.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=7))
        recent = [Result.objects.create(
            work_item=self.work, key=f"recent-{index}", qc_passed=True, qc_status=Result.QC_APPROVED
        ) for index in range(RECENT_RESULT_LIMIT)]
        # Resolve equal timestamps deterministically rather than dropping records.
        Result.objects.filter(pk__in=[row.pk for row in recent]).update(created_at=timezone.now())

        data = self.chat()
        briefing = data["sample_briefing"]
        self.assertEqual([row["id"] for row in briefing["recent_results"]], [row.pk for row in reversed(recent)])
        self.assertEqual(briefing["results"]["total"], RECENT_RESULT_LIMIT + 1)
        self.assertEqual(briefing["results"]["failed_checks"], 1)
        self.assertIn("showing 5 of 6", data["answer"])
        self.assertNotIn("old-failure", data["answer"])
        self.assertIn("review the recorded failures", data["answer"])

    def test_empty_records_do_not_imply_qc_pass_or_release_readiness(self):
        self.work.delete()
        data = self.chat()
        self.assertEqual(data["sample_briefing"]["results"]["total"], 0)
        self.assertEqual(data["sample_briefing"]["recent_results"], [])
        self.assertIn("QC outcome is unknown", data["answer"])
        self.assertIn("do not establish that the sample is ready for release", data["answer"])
        self.assertEqual(data["suggestions"], [
            "What next for sample BRIEF-001?", "What happened to sample BRIEF-001?",
        ])
        for suggestion in data["suggestions"]:
            followup = self.chat(suggestion, data["context"])
            self.assertFalse(followup.get("clarification", {}).get("required"))

    def test_completed_work_results_remain_visible_and_are_identified_as_historical(self):
        self.work.status = WorkItem.STATUS_COMPLETED
        self.work.save()
        Result.objects.create(work_item=self.work, key="historic", qc_passed=False)

        data = self.chat()
        self.assertEqual(data["sample_briefing"]["work"]["unfinished"], 0)
        self.assertEqual(data["sample_briefing"]["results"]["failed_checks"], 1)
        self.assertIn("may be historical", data["answer"])

    def test_private_records_and_revoked_access_never_reach_briefing(self):
        private = Project.objects.create(code="PRIVATE", name="Private")
        hidden = Sample.objects.create(sample_id="SECRET-001", project=private)
        work = WorkItem.objects.create(sample=hidden, name="Private work")
        result = Result.objects.create(work_item=work, key="private-analyte", value_string="private-value")

        visible = self.chat()
        self.assertEqual(visible["sample_briefing"]["results"]["total"], 0)
        denied = self.chat("Summarize sample SECRET-001")
        self.assertNotIn("sample_briefing", denied)
        self.assertNotIn(str(result.pk), str(denied.get("links")))
        self.assertNotIn("private-analyte", str(denied))
        self.project.members.remove(self.user)
        denied = self.chat("Summarize it", visible["context"])
        self.assertNotIn("sample_briefing", denied)
        self.assertEqual(denied["links"], [])

    def test_viewers_and_linked_project_members_can_read_without_mutation(self):
        linked = Project.objects.create(code="LINKED", name="Linked")
        linked.members.add(self.viewer)
        self.sample.linked_projects.add(linked)
        self.project.members.remove(self.viewer)
        self.client.force_authenticate(self.viewer)
        before = Event.objects.count()

        data = self.chat()

        self.assertIn("sample_briefing", data)
        self.assertNotIn("pending_action", data)
        self.assertFalse(AssistantAction.objects.exists())
        self.assertEqual(Event.objects.count(), before)
        self.work.refresh_from_db()
        self.assertEqual(self.work.status, WorkItem.STATUS_PENDING)

    def test_summary_followup_reloads_current_work_and_results(self):
        first = self.chat()
        self.work.status = WorkItem.STATUS_COMPLETED
        self.work.save()
        result = Result.objects.create(work_item=self.work, key="new-result", value_string="new value")

        updated = self.chat("Summarize it", first["context"])

        self.assertEqual(updated["sample_briefing"]["work"]["unfinished"], 0)
        self.assertEqual(updated["sample_briefing"]["recent_results"][0]["id"], result.pk)
        self.assertIn("new value", updated["answer"])

    @override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=True, OPENAI_API_KEY="test-only")
    def test_both_provider_dispatches_share_evidence_without_rewriting(self):
        for provider in ["openai", "ollama"]:
            with self.subTest(provider=provider), patch("assistant.llm.OpenAI") as model:
                data = dispatch_tool({
                    "route": "tool", "tool": "samples", "provider": provider, "confidence": 1,
                    "arguments": {"command": "Summarize sample BRIEF-001"},
                }, self.user)
                api_result = self.chat()
                self.assertEqual(data["sample_briefing"], api_result["sample_briefing"])
                self.assertTrue(data["skip_llm"])
                model.assert_not_called()

    def test_evidence_queries_are_constant_as_result_count_grows(self):
        for index in range(RECENT_RESULT_LIMIT + 2):
            work = WorkItem.objects.create(sample=self.sample, name=f"Work {index}", work_type=f"TYPE-{index}")
            Result.objects.create(work_item=work, key="result")

        with self.assertNumQueries(3):
            briefing = sample_briefing(self.sample)
        self.assertEqual(len(briefing["recent_results"]), RECENT_RESULT_LIMIT)
