import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.general_conversation import CONTEXT_KEY, remember_exchange
from assistant.models import AssistantAction
from assistant.provider_tools import dispatch_tool
from assistant.sample_explanations import route_sample_explanations
from events.models import Event
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample


class ExplanationWordingTests(SimpleTestCase):
    def test_negations_filters_and_compound_commands_are_not_consumed(self):
        for message in [
            "Do not explain sample EXPLAIN-1",
            "Explain sample EXPLAIN-1 and approve its results",
            "Show evidence for sample EXPLAIN-1 from yesterday",
            "What should I check first and assign the work to maria?",
            "Explain samples EXPLAIN-1 and EXPLAIN-2",
            "Explain that more simply and delete it",
            "Show the evidence except failed results",
        ]:
            with self.subTest(message=message):
                self.assertIsNone(route_sample_explanations(message, None))


class SampleExplanationTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.user = users.objects.create_user(username="explanation-tech")
        cls.user.groups.add(Group.objects.get_or_create(name="tech")[0])
        cls.viewer = users.objects.create_user(username="explanation-viewer")
        cls.other = users.objects.create_user(username="explanation-outsider")
        cls.project = Project.objects.create(code="EXPLAIN", name="Explanation project")
        cls.project.members.add(cls.user, cls.viewer)
        cls.private = Project.objects.create(code="HIDDEN", name="Private project")
        cls.private.members.add(cls.other)
        cls.sample = Sample.objects.create(sample_id="EXPLAIN-1", project=cls.project, created_by=cls.user)
        cls.second = Sample.objects.create(sample_id="EXPLAIN-2", project=cls.project, created_by=cls.user)
        cls.hidden = Sample.objects.create(sample_id="PRIVATE-EXPLANATION", project=cls.private, created_by=cls.other)
        cls.work = WorkItem.objects.create(sample=cls.sample, name="Extraction", assigned_to=cls.user)
        private_work = WorkItem.objects.create(sample=cls.hidden, name="SECRET-WORK")
        Result.objects.create(work_item=private_work, key="SECRET-ANALYTE", value_string="SECRET-VALUE")

    def setUp(self):
        self.client.force_authenticate(self.user)

    def chat(self, message, context=None):
        response = self.client.post("/api/assistant/chat/", {"message": message, "context": context or {}}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def result(self, **fields):
        return Result.objects.create(work_item=self.work, key=fields.pop("key", "concentration"), **fields)

    def test_explicit_explanations_and_followup_chain_work_without_a_provider(self):
        with patch("assistant.views.classify_route_with_llm") as classifier, patch("assistant.llm.call_openai") as model:
            data = self.chat("Summarize sample EXPLAIN-1")
            for message, focus in [
                ("Could you explain that more simply?", "summary"),
                ("Why does this sample need attention?", "evidence"),
                ("What should I check first?", "next_steps"),
                ("What don't we know?", "unknowns"),
            ]:
                data = self.chat(message, data["context"])
                self.assertEqual(data["sample_explanation"]["focus"], focus)
                self.assertEqual(data["sample_explanation"]["sample_id"], self.sample.pk)
                self.assertTrue(data["sample_explanation"]["read_only"])
                self.assertTrue(data["skip_llm"])
                self.assertEqual(data["mode"], "openlims")
                self.assertNotIn("pending_action", data)
            classifier.assert_not_called()
            model.assert_not_called()

    def test_review_priorities_explain_recorded_flags_before_assignment(self):
        self.work.assigned_to = None
        self.work.due_at = timezone.now() - timedelta(days=1)
        self.work.save()
        result = self.result(qc_passed=False, qc_status=Result.QC_REJECTED, qc_failure_reason="Control drift", qc_review_note="Review the batch")
        data = self.chat("What should I check first for sample EXPLAIN-1?")
        evidence = data["sample_explanation"]
        self.assertEqual([row["kind"] for row in evidence["signals"]], ["failed_checks", "rejected_results", "overdue_work", "unassigned_work"])
        self.assertIn("authorized QC reviewer", evidence["recommended_checks"][0])
        self.assertIn("1. Review the flagged results", data["answer"])
        details = self.chat("Show the evidence", data["context"])
        self.assertIn(f"R-{result.pk}", details["answer"])
        self.assertIn("Recorded QC reason: Control drift", details["answer"])
        self.assertIn("Recorded review note: Review the batch", details["answer"])
        self.assertIn("Counts may overlap", details["answer"])
        unknowns = self.chat("What don't we know?", details["context"])
        self.assertIn(f"Displayed work #{self.work.pk}: no assignee recorded", unknowns["answer"])

    def test_failed_check_and_approved_review_remain_distinct(self):
        self.result(qc_passed=False, qc_status=Result.QC_APPROVED)
        data = self.chat("Show evidence for sample EXPLAIN-1")
        self.assertIn("QC check: failed; review: APPROVED", data["answer"])
        self.assertIn("do not establish the scientific root cause", data["answer"])
        unknowns = self.chat("What don't we know?", data["context"])
        self.assertIn("no QC failure reason recorded", unknowns["answer"])

    def test_work_evidence_identifies_each_recorded_failure_qc_and_scheduling_flag(self):
        self.work.status = WorkItem.STATUS_FAILED
        self.work.qc_status = WorkItem.QC_RERUN_REQUIRED
        self.work.assigned_to = None
        self.work.due_at = timezone.now() - timedelta(hours=1)
        self.work.save()
        data = self.chat("Show evidence for sample EXPLAIN-1")
        self.assertIn(f"#{self.work.pk} / Extraction", data["answer"])
        self.assertIn("flags: work failed, QC RERUN_REQUIRED, overdue, unassigned", data["answer"])
        spanish = self.chat("In Spanish", data["context"])
        self.assertIn("alertas: trabajo fallido, QC RERUN_REQUIRED, vencido, sin asignar", spanish["answer"])

    def test_passed_check_does_not_grant_review_approval(self):
        self.result(qc_passed=True, qc_status=Result.QC_PENDING_REVIEW)
        data = self.chat("What should I check first for sample EXPLAIN-1?")
        self.assertEqual(data["sample_explanation"]["signals"][0]["kind"], "pending_review")
        self.assertIn("authorized reviewer", data["answer"])
        self.assertNotIn("failed QC checks:", data["answer"])

    def test_outside_range_is_evidence_without_inventing_a_failed_check_or_cause(self):
        result = self.result(value_type=Result.VALUE_TYPE_NUMBER, value_number=45, unit="ng/uL", reference_min=10, reference_max=20)
        data = self.chat("Show evidence for sample EXPLAIN-1")
        self.assertIn("45.0 ng/uL", data["answer"])
        self.assertIn("10.0 to 20.0 ng/uL; above maximum", data["answer"])
        self.assertIn("QC check: not evaluated", data["answer"])
        self.assertEqual(data["sample_briefing"]["results"]["failed_checks"], 0)
        gaps = self.chat("What don't we know?", data["context"])
        self.assertIn(f"R-{result.pk}: QC check not evaluated", gaps["answer"])

    def test_old_failures_remain_visible_outside_recent_results(self):
        older = self.result(key="old-failure", qc_passed=False)
        Result.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=10))
        for index in range(6):
            self.result(key=f"recent-{index}", qc_passed=True, qc_status=Result.QC_APPROVED)
        data = self.chat("Show evidence for sample EXPLAIN-1")
        self.assertNotIn(older.pk, [row["id"] for row in data["sample_briefing"]["recent_results"]])
        self.assertIn("old-failure", data["answer"])
        self.assertIn("Results shown: 1 of 7 recorded; 1 flagged in total", data["answer"])

    def test_completed_and_cancelled_work_flags_are_excluded_but_result_history_remains(self):
        self.work.status = WorkItem.STATUS_COMPLETED
        self.work.due_at = timezone.now() - timedelta(days=2)
        self.work.assigned_to = None
        self.work.save()
        cancelled = WorkItem.objects.create(sample=self.sample, name="Cancelled", status=WorkItem.STATUS_CANCELLED)
        self.result(qc_passed=False, qc_status=Result.QC_REJECTED)
        Result.objects.create(work_item=cancelled, key="historical", qc_status=Result.QC_REJECTED)
        data = self.chat("Explain sample EXPLAIN-1")
        self.assertEqual({row["kind"] for row in data["sample_explanation"]["signals"]}, {"failed_checks", "rejected_results"})
        self.assertIn("results may be historical", data["answer"])

    def test_no_results_or_flags_do_not_imply_readiness(self):
        data = self.chat("Explain sample EXPLAIN-2")
        self.assertEqual(data["sample_explanation"]["signals"], [])
        self.assertIn("QC outcome is unknown", data["answer"])
        self.assertIn("does not establish release readiness", data["answer"])
        unknowns = self.chat("What don't we know?", data["context"])
        self.assertIn("required sign-off", unknowns["answer"])

    def test_zero_and_false_values_are_preserved(self):
        zero = self.result(value_type=Result.VALUE_TYPE_NUMBER, value_number=0, unit="ng/uL", reference_max=1)
        false = self.result(key="detected", value_type=Result.VALUE_TYPE_BOOLEAN, value_boolean=False)
        data = self.chat("Show evidence for sample EXPLAIN-1")
        self.assertIn("0.0 ng/uL", data["answer"])
        self.assertIn("detected (Extraction): False", data["answer"])
        self.assertIn("no lower bound to 1.0 ng/uL; within limits", data["answer"])
        for row in data["sample_explanation"]["unknowns"]:
            if row.startswith((f"R-{zero.pk}:", f"R-{false.pk}:")):
                self.assertNotIn("no usable value", row)

    def test_invalid_values_limits_and_excerpted_notes_are_honest_and_json_safe(self):
        result = self.result(value_type=Result.VALUE_TYPE_NUMBER, value_number=1, qc_passed=False, qc_failure_reason="x" * 500)
        Result.objects.filter(pk=result.pk).update(value_number=float("nan"), reference_min=20, reference_max=10)
        data = self.chat("Show evidence for sample EXPLAIN-1")
        self.assertIn("invalid value", data["answer"])
        self.assertIn("limits are invalid", data["answer"])
        self.assertIn("Recorded QC reason (excerpt)", data["answer"])
        gaps = self.chat("What don't we know?", data["context"])
        self.assertIn("notes are excerpted", gaps["answer"])
        json.dumps(data, allow_nan=False)
        json.dumps(gaps, allow_nan=False)

    def test_unknowns_are_scoped_to_displayed_rows_and_not_a_complete_scan(self):
        for index in range(9):
            self.result(key=f"pending-{index}")
        data = self.chat("What is still unknown about sample EXPLAIN-1?")
        self.assertIn("only to the displayed evidence, not every result", data["answer"])
        self.assertEqual(data["sample_briefing"]["results"]["total"], 9)
        self.assertLess(len([text for text in data["sample_explanation"]["unknowns"] if text.startswith("R-")]), 9)

    def test_contextual_explanations_reload_live_counts_values_and_permissions(self):
        first = self.chat("Explain sample EXPLAIN-1")
        self.work.assigned_to = None
        self.work.save()
        self.result(value_type=Result.VALUE_TYPE_NUMBER, value_number=7, qc_passed=False)
        data = self.chat("Show the evidence", first["context"])
        self.assertEqual(data["sample_briefing"]["work"]["unassigned"], 1)
        self.assertIn("7.0", data["answer"])
        self.project.members.remove(self.user)
        denied = self.chat("Show the evidence", data["context"])
        self.assertNotIn("sample_explanation", denied)
        self.assertNotIn("sample_briefing", denied)
        self.assertNotIn("EXPLAIN-1", str(denied))
        self.assertEqual(denied["links"], [])

    def test_missing_ambiguous_conflicting_and_malformed_sample_selection_asks_one_question(self):
        for context in [{}, {"sample_ids": [self.sample.pk, self.second.pk]}, {"sample_id": True},
                        {"sample_id": "bad"}, {"sample_id": 10**100}, {"sample_ids": "bad"},
                        {"sample_id": self.sample.pk, "sample_ids": [self.second.pk]}]:
            with self.subTest(context=context):
                data = self.chat("Explain that more simply", context)
                self.assertTrue(data["clarification"]["required"])
                self.assertEqual(data["answer"].count("?"), 1)
                self.assertNotIn("sample_explanation", data)
        first = self.chat("What should I check first?")
        self.assertEqual(self.chat("EXPLAIN-1", first["context"])["sample_explanation"]["focus"], "next_steps")

    def test_inaccessible_and_missing_ids_do_not_leak_and_lookup_is_case_insensitive(self):
        for code in [self.hidden.sample_id, "DOES-NOT-EXIST"]:
            data = self.chat(f"Explain sample {code}")
            self.assertNotIn("sample_briefing", data)
            self.assertNotIn("SECRET-ANALYTE", str(data))
            self.assertNotIn("SECRET-VALUE", str(data))
            self.assertTrue(data["clarification"]["required"])
        visible = self.chat("Explain sample explain-1")
        self.assertEqual(visible["sample_explanation"]["sample_id"], self.sample.pk)

    def test_stable_id_survives_rename_and_code_reuse(self):
        first = self.chat("Explain sample EXPLAIN-1")
        self.sample.sample_id = "RENAMED-EXPLANATION"
        self.sample.save()
        Sample.objects.create(sample_id="EXPLAIN-1", project=self.project, created_by=self.user)
        data = self.chat("Show the evidence", first["context"])
        self.assertEqual(data["sample_explanation"]["sample_id"], self.sample.pk)
        self.assertTrue(data["answer"].startswith("RENAMED-EXPLANATION"))

    def test_linked_project_viewers_can_read_without_writes(self):
        linked = Project.objects.create(code="EXPLAIN-LINK", name="Linked explanation")
        linked.members.add(self.viewer)
        self.sample.linked_projects.add(linked)
        self.project.members.remove(self.viewer)
        self.client.force_authenticate(self.viewer)
        before = (AssistantAction.objects.count(), Event.objects.count(), WorkItem.objects.count(), Result.objects.count())
        for command in ["Explain sample EXPLAIN-1", "Show evidence for sample EXPLAIN-1", "What should I check first for sample EXPLAIN-1?", "What is still unknown about sample EXPLAIN-1?"]:
            self.assertTrue(self.chat(command)["sample_explanation"]["read_only"])
        self.assertEqual(before, (AssistantAction.objects.count(), Event.objects.count(), WorkItem.objects.count(), Result.objects.count()))
        self.work.refresh_from_db()
        self.assertEqual(self.work.status, WorkItem.STATUS_PENDING)

    def test_spanish_followups_and_language_switch_preserve_focus(self):
        first = self.chat("Explica la muestra EXPLAIN-1")
        self.assertIn("En palabras sencillas", first["answer"])
        second = self.chat("¿Qué no sabemos?", first["context"])
        self.assertEqual(second["sample_explanation"]["focus"], "unknowns")
        third = self.chat("In English", second["context"])
        self.assertEqual(third["sample_explanation"]["focus"], "unknowns")
        self.assertIn("What is still unknown", third["answer"])
        fourth = self.chat("Explain that in Spanish", third["context"])
        self.assertIn("Qué no sabemos", fourth["answer"])
        fifth = self.chat("same for EXPLAIN-2", fourth["context"])
        self.assertEqual(fifth["sample_explanation"]["language"], "es")
        self.assertEqual(fifth["sample_explanation"]["sample_id"], self.second.pk)

    def test_short_reply_after_spanish_clarification_retains_language(self):
        first = self.chat("¿Qué debo revisar primero?")
        invalid = self.chat("MISSING", first["context"])
        data = self.chat("EXPLAIN-1", invalid["context"])
        self.assertEqual(data["sample_explanation"]["language"], "es")
        self.assertEqual(data["sample_explanation"]["focus"], "next_steps")

    def test_same_for_and_topic_memory_replay_only_the_chosen_read(self):
        for command, focus in [("Explain sample EXPLAIN-1", "summary"), ("Show evidence for sample EXPLAIN-1", "evidence"),
                               ("What should I check first for sample EXPLAIN-1?", "next_steps"), ("What is still unknown about sample EXPLAIN-1?", "unknowns")]:
            with self.subTest(focus=focus):
                first = self.chat(command)
                second = self.chat("same for EXPLAIN-2", first["context"])
                self.assertEqual(second["sample_explanation"]["focus"], focus)
                self.assertEqual(second["sample_explanation"]["sample_id"], self.second.pk)
                back = self.chat("Back to the previous sample", second["context"])
                self.assertEqual(back["sample_explanation"]["sample_id"], self.sample.pk)
                self.assertEqual(back["sample_explanation"]["focus"], focus)

    def test_courtesy_keeps_explanation_but_reset_discards_it(self):
        first = self.chat("Explain sample EXPLAIN-1")
        thanks = self.chat("Thanks", first["context"])
        self.assertEqual(thanks["context"]["sample_id"], self.sample.pk)
        reset = self.chat("Forget this conversation", thanks["context"])
        self.assertEqual(reset["context"], {})
        self.assertTrue(self.chat("Show the evidence", reset["context"])["clarification"]["required"])

    @override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=True, OPENLIMS_ASSISTANT_LLM_PROVIDER="ollama", OLLAMA_BASE_URL="http://ollama:11434", OLLAMA_MODEL="test")
    def test_general_chat_history_stays_separate_from_sample_explanations(self):
        history = {CONTEXT_KEY: remember_exchange(self.user, [], "Explain photosynthesis", "Plants use sunlight.")}
        with patch("assistant.llm.call_ollama", return_value="A simpler general explanation.") as model:
            data = self.chat("Explain that more simply", history)
        self.assertEqual(data["response_type"], "general")
        self.assertNotIn("sample_explanation", data)
        self.assertEqual(len(model.call_args.kwargs["history"]), 2)
        lab = self.chat("Explain sample EXPLAIN-1", data["context"])
        self.assertIn("sample_explanation", lab)
        self.assertNotIn(CONTEXT_KEY, lab["context"])

    def test_both_providers_share_catalog_dispatch_and_deterministic_evidence(self):
        for provider in ["openai", "ollama"]:
            plan = {"route": "tool", "tool": "sample_explanations", "provider": provider, "confidence": .99,
                    "arguments": {"command": "Show evidence for sample EXPLAIN-1"}}
            data = dispatch_tool(plan, self.user)
            self.assertEqual(data["sample_explanation"]["focus"], "evidence")
            self.assertEqual(data["context"]["read_intent"], "sample_evidence")
            with patch("assistant.views.classify_route_with_llm", return_value=plan), patch(f"assistant.llm.call_{provider}") as model:
                api = self.chat("Help me understand the recorded evidence on EXPLAIN-1")
                self.assertEqual(api["sample_explanation"]["focus"], "evidence")
                self.assertIn("interpretation", api)
                model.assert_not_called()
