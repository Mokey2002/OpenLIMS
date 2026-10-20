import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.models import AssistantAction
from assistant.provider_tools import dispatch_tool
from assistant.sample_briefing import ATTENTION_LIMIT, REASON_LIMIT, RECENT_RESULT_LIMIT, sample_briefing
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
        self.assertNotIn(older.pk, [row["id"] for row in briefing["recent_results"]])
        self.assertIn(older.pk, [row["id"] for row in briefing["attention"]["results"]])
        self.assertIn("old-failure", data["answer"])
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

        with self.assertNumQueries(5):
            briefing = sample_briefing(self.sample)
        self.assertEqual(len(briefing["recent_results"]), RECENT_RESULT_LIMIT)
        self.assertEqual(len(briefing["attention"]["work_items"]), ATTENTION_LIMIT)
        self.assertEqual(len(briefing["attention"]["results"]), ATTENTION_LIMIT)

    def test_work_priorities_identify_flags_owners_and_deadlines(self):
        now = timezone.now()
        failed = WorkItem.objects.create(
            sample=self.sample, name="Failed extraction", status=WorkItem.STATUS_FAILED,
            assigned_to=self.user, due_at=now + timedelta(days=1),
        )
        rerun = WorkItem.objects.create(
            sample=self.sample, name="Repeat analysis", work_type="RERUN",
            assigned_to=self.viewer, qc_status=WorkItem.QC_RERUN_REQUIRED,
        )
        overdue = WorkItem.objects.create(
            sample=self.sample, name="Overdue analysis", work_type="OVERDUE",
            assigned_to=self.user, due_at=now - timedelta(days=3),
        )
        WorkItem.objects.create(
            sample=self.sample, name="Routine assigned work", work_type="ROUTINE", assigned_to=self.user,
        )
        for status in [WorkItem.STATUS_COMPLETED, WorkItem.STATUS_CANCELLED]:
            WorkItem.objects.create(
                sample=self.sample, name=f"Closed {status}", status=status,
                qc_status=WorkItem.QC_REJECTED, due_at=now - timedelta(days=7),
            )

        data = self.chat()
        attention = data["sample_briefing"]["attention"]
        self.assertEqual(attention["work_total"], 4)
        self.assertEqual([row["id"] for row in attention["work_items"]], [failed.pk, rerun.pk, overdue.pk])
        self.assertEqual(attention["work_items"][0]["reasons"], ["work failed"])
        self.assertEqual(attention["work_items"][1]["reasons"], ["QC RERUN_REQUIRED"])
        self.assertEqual(attention["work_items"][2]["reasons"], ["overdue"])
        self.assertIn("Work needing attention (showing 3 of 4", data["answer"])
        self.assertIn("owner: briefing-viewer; due: no deadline recorded", data["answer"])
        self.assertIn(f"due: {overdue.due_at.isoformat()}", data["answer"])
        self.assertNotIn("Routine assigned work", data["answer"])
        self.assertNotIn("Closed COMPLETED", data["answer"])
        self.assertLess(data["answer"].index("Work needing attention"), data["answer"].index("Sample details:"))

    def test_results_prioritize_failures_and_rejections_before_older_pending_reviews(self):
        pending = [Result.objects.create(work_item=self.work, key=f"pending-{index}") for index in range(4)]
        Result.objects.filter(pk__in=[row.pk for row in pending]).update(created_at=timezone.now() - timedelta(days=7))
        failed = Result.objects.create(work_item=self.work, key="failed", qc_passed=False)
        rejected = Result.objects.create(
            work_item=self.work, key="rejected", qc_passed=True, qc_status=Result.QC_REJECTED,
        )
        Result.objects.filter(pk__in=[failed.pk, rejected.pk]).update(created_at=timezone.now())
        Result.objects.create(work_item=self.work, key="approved", qc_passed=True, qc_status=Result.QC_APPROVED)

        data = self.chat()
        attention = data["sample_briefing"]["attention"]
        self.assertEqual(attention["result_total"], 6)
        self.assertEqual([row["id"] for row in attention["results"]], [failed.pk, rejected.pk, pending[0].pk])
        self.assertIn("Results needing attention (showing 3 of 6", data["answer"])

    def test_reference_limits_explain_values_without_inventing_a_qc_failure_cause(self):
        result = Result.objects.create(
            work_item=self.work, key="yield", value_type=Result.VALUE_TYPE_NUMBER,
            value_number=0, unit="ng/uL", reference_min=0, reference_max=10,
            qc_passed=False, qc_failure_reason="Instrument control failed.",
        )

        data = self.chat()

        self.assertIn("Configured reference: 0.0 to 10.0 ng/uL (inclusive); within the configured limits", data["answer"])
        self.assertIn("Recorded QC reason: Instrument control failed.", data["answer"])
        self.assertIn("QC check: failed; review: PENDING_REVIEW", data["answer"])
        self.assertNotIn("below the configured minimum", data["answer"])
        self.assertEqual(data["suggestions"][:2], [
            f"Why did result R-{result.pk} fail QC?",
            f"Compare result R-{result.pk} with its reference range",
        ])
        for suggestion in data["suggestions"][:2]:
            followup = self.chat(suggestion, data["context"])
            self.assertIn("result_id", followup["context"], followup)
            self.assertEqual(followup["context"]["result_id"], result.pk)
            self.assertIn("BRIEF-001", followup["answer"])
            self.assertNotIn("pending_action", followup)

    def test_one_sided_reference_limits_and_unknown_values_are_explicit(self):
        for key, fields in [
            ("below", {"value_number": 1, "reference_min": 2}),
            ("above", {"value_number": 5, "reference_max": 4}),
            ("missing", {"reference_min": 2}),
        ]:
            Result.objects.create(
                work_item=self.work, key=key, value_type=Result.VALUE_TYPE_NUMBER, unit="mg/L", **fields,
            )

        data = self.chat()

        self.assertIn("at least 2.0 mg/L; below the configured minimum", data["answer"])
        self.assertIn("at most 4.0 mg/L; above the configured maximum", data["answer"])
        self.assertIn("at least 2.0 mg/L; no numeric value to compare", data["answer"])
        self.assertIn("QC check: not evaluated", data["answer"])

    def test_missing_reference_and_failure_reason_do_not_imply_a_known_cause(self):
        Result.objects.create(work_item=self.work, key="no-reason", qc_passed=False)

        data = self.chat()

        self.assertIn("No QC failure reason is recorded", data["answer"])
        self.assertIn("Reference range not configured", data["answer"])
        self.assertFalse(any("Compare result" in suggestion for suggestion in data["suggestions"]))

    def test_inconsistent_limits_are_not_used_for_comparison(self):
        Result.objects.create(
            work_item=self.work, key="invalid-range", value_type=Result.VALUE_TYPE_NUMBER,
            value_number=5, reference_min=10, reference_max=1,
        )

        data = self.chat()
        evidence = data["sample_briefing"]["attention"]["results"][0]

        self.assertEqual(evidence["reference_comparison"], "invalid_limits")
        self.assertIn("Configured reference limits are invalid; comparison is unavailable", data["answer"])
        self.assertNotIn("below the configured minimum", data["answer"])
        self.assertFalse(any("Compare result" in suggestion for suggestion in data["suggestions"]))

    def test_nonfinite_recorded_values_are_json_safe_and_not_compared(self):
        Result.objects.create(
            work_item=self.work, key="invalid-value", value_type=Result.VALUE_TYPE_NUMBER,
            value_number=float("inf"), reference_min=0, reference_max=10,
        )
        Result.objects.create(
            work_item=self.work, key="invalid-limit", reference_max=float("inf"),
        )

        data = self.chat()
        evidence = {row["key"]: row for row in data["sample_briefing"]["attention"]["results"]}

        json.dumps(data, allow_nan=False)
        self.assertTrue(evidence["invalid-value"]["value_invalid"])
        self.assertIsNone(evidence["invalid-value"]["value"])
        self.assertEqual(evidence["invalid-value"]["reference_comparison"], "not_numeric")
        self.assertEqual(evidence["invalid-limit"]["reference_comparison"], "invalid_limits")
        self.assertIn("invalid numeric value recorded", data["answer"])

    def test_long_qc_reasons_are_marked_as_excerpts_and_detail_can_be_opened(self):
        reason = "Recorded control failure. " * 30
        result = Result.objects.create(
            work_item=self.work, key="long-reason", qc_passed=False, qc_failure_reason=reason,
        )

        data = self.chat()
        evidence = data["sample_briefing"]["attention"]["results"][0]

        self.assertEqual(evidence["qc_failure_reason"], reason[:REASON_LIMIT])
        self.assertTrue(evidence["qc_failure_reason_truncated"])
        self.assertIn("Recorded QC reason (excerpt)", data["answer"])
        self.assertNotIn(reason, data["answer"])
        detail = self.chat(f"Why did result R-{result.pk} fail QC?", data["context"])
        self.assertIn(reason, detail["answer"])

    def test_review_decision_is_not_described_as_a_failed_check(self):
        Result.objects.create(
            work_item=self.work, key="review-rejection", qc_passed=True, qc_status=Result.QC_REJECTED,
            qc_review_note="Specimen label needs investigation.",
        )

        data = self.chat()

        self.assertIn("QC check: passed; review: REJECTED", data["answer"])
        self.assertIn("Recorded review note: Specimen label needs investigation.", data["answer"])
        self.assertNotIn("No QC failure reason", data["answer"])
        self.assertFalse(any("fail QC" in suggestion for suggestion in data["suggestions"]))

    def test_long_review_notes_are_bounded_and_distinguished_from_check_failures(self):
        note = "Recorded review evidence. " * 30
        Result.objects.create(
            work_item=self.work, key="long-review", qc_passed=True,
            qc_status=Result.QC_REJECTED, qc_review_note=note,
        )

        data = self.chat()
        evidence = data["sample_briefing"]["attention"]["results"][0]

        self.assertEqual(evidence["qc_review_note"], note[:REASON_LIMIT])
        self.assertTrue(evidence["qc_review_note_truncated"])
        self.assertIn("Recorded review note (excerpt)", data["answer"])
        self.assertNotIn(note, data["answer"])
        self.assertNotIn("No QC failure reason", data["answer"])

    def test_priority_followup_rechecks_access_after_revocation(self):
        Result.objects.create(
            work_item=self.work, key="sensitive-value", qc_passed=False,
            value_type=Result.VALUE_TYPE_NUMBER, value_number=5, reference_max=4,
            qc_failure_reason="Sensitive failure evidence",
        )
        data = self.chat()
        self.project.members.remove(self.user)

        for suggestion in data["suggestions"][:2]:
            denied = self.chat(suggestion, data["context"])
            self.assertEqual(denied["links"], [])
            self.assertNotIn("Sensitive failure evidence", str(denied))
            self.assertNotIn("sensitive-value", str(denied))

    def test_priority_evidence_refreshes_after_work_and_qc_review_change(self):
        result = Result.objects.create(work_item=self.work, key="needs-review", qc_passed=False)
        first = self.chat()
        self.assertEqual(first["sample_briefing"]["attention"]["result_total"], 1)
        result.qc_status, result.qc_passed = Result.QC_APPROVED, True
        result.save()
        self.work.status = WorkItem.STATUS_COMPLETED
        self.work.save()

        refreshed = self.chat("Summarize it", first["context"])

        self.assertEqual(refreshed["sample_briefing"]["attention"]["work_total"], 0)
        self.assertEqual(refreshed["sample_briefing"]["attention"]["result_total"], 0)
        self.assertEqual(refreshed["sample_briefing"]["attention"]["results"], [])
        self.assertFalse(any("fail QC" in suggestion for suggestion in refreshed["suggestions"]))

    @override_settings(
        OPENLIMS_ASSISTANT_LLM_ENABLED=True, OPENLIMS_ASSISTANT_LLM_ROUTING_ENABLED=True,
        OPENAI_API_KEY="test-only", OLLAMA_BASE_URL="http://ollama:11434", OLLAMA_MODEL="test",
    )
    def test_both_provider_routes_return_the_same_priority_evidence(self):
        result = Result.objects.create(work_item=self.work, key="provider-failure", qc_passed=False)
        plan = json.dumps({
            "route": "tool", "tool": "samples", "confidence": 1,
            "arguments": {"command": "Summarize sample BRIEF-001"},
        })
        for provider in ["openai", "ollama"]:
            with self.subTest(provider=provider), override_settings(OPENLIMS_ASSISTANT_LLM_PROVIDER=provider):
                with patch(f"assistant.llm.call_{provider}", return_value=plan) as model:
                    data = self.chat("Could you handle the request I described in my own words?")
                model.assert_called_once()
                self.assertEqual(data["routing"]["source"], f"{provider}_fallback")
                self.assertEqual(data["sample_briefing"]["attention"]["results"][0]["id"], result.pk)
                self.assertTrue(data["skip_llm"])

    def test_deadline_boundary_uses_one_timestamp_for_counts_and_reasons(self):
        now = timezone.now()
        self.work.due_at = now
        self.work.save()

        with patch("assistant.sample_briefing.timezone.now", return_value=now):
            data = self.chat()

        self.assertEqual(data["sample_briefing"]["work"]["overdue"], 0)
        self.assertEqual(data["sample_briefing"]["attention"]["work_items"][0]["reasons"], ["unassigned"])
