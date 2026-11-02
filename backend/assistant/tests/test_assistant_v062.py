import copy
import io
import json
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.answer_quality import check_answer, evaluate_cases
from assistant.models import AssistantAction, AssistantConversation, SOPDocument
from assistant.models import AssistantFeedback, AssistantInteraction
from assistant.read_plans import validate_read_plan
from assistant.result_queries import apply_filters, period_dates
from assistant.sop_operations import search_sops
from results.models import Result
from . import test_read_plans

UTC = dt_timezone.utc
NOW = datetime(2026, 11, 2, 20, tzinfo=UTC)


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False, TIME_ZONE="America/Los_Angeles")
class AssistantV062Tests(APITestCase):
    setUpTestData = classmethod(test_read_plans.ReadPlanAnswerTests.setUpTestData.__func__)
    chat = test_read_plans.ReadPlanAnswerTests.chat

    def setUp(self):
        self.client.force_authenticate(self.user)
        self.clock = patch("django.utils.timezone.now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        Result.objects.filter(pk=self.result.pk).update(created_at=datetime(2026, 11, 1, 8, 30, tzinfo=UTC))
        self.yesterday = Result.objects.create(work_item=self.work, key="second", qc_passed=False, value_number=0, value_type="NUMBER")
        Result.objects.filter(pk=self.yesterday.pk).update(created_at=datetime(2026, 11, 1, 9, 30, tzinfo=UTC))
        self.last_week = Result.objects.create(work_item=self.work, key="concentration-old", qc_passed=False, value_number=19, value_type="NUMBER")
        Result.objects.filter(pk=self.last_week.pk).update(created_at=datetime(2026, 10, 29, 12, tzinfo=UTC))
        self.before = Result.objects.create(work_item=self.work, key="boundary-before", qc_passed=False)
        Result.objects.filter(pk=self.before.pk).update(created_at=datetime(2026, 11, 1, 6, 59, tzinfo=UTC))

    def facts(self, reply):
        return reply["read_plan"]["steps"][0]["result_query"]

    def test_followup_chain_keeps_qc_scope_and_reloads_period_comparison(self):
        start = self.chat("Show failed QC results for project QUALITY")
        self.assertEqual(self.facts(start)["total"], 4)
        narrowed = self.chat("Only yesterday", start["context"])
        self.assertEqual(self.facts(narrowed)["total"], 2)
        self.assertEqual(self.facts(narrowed)["filters"]["qc"], "failed")
        comparison = self.chat("Compare those with last week", narrowed["context"])
        self.assertEqual(self.facts(comparison)["comparison_total"], 4)
        self.assertEqual(self.facts(comparison)["total"], 2)
        self.assertIn("Largest count difference", comparison["answer_overview"]["text"])
        outside_selection = self.chat("Explain the third result", comparison["context"])
        self.assertTrue(outside_selection["clarification"])
        self.assertNotIn("19.0", outside_selection["answer"])
        explained = self.chat("Explain the largest difference and link the supporting results", comparison["context"])
        self.assertEqual(self.facts(explained)["total"], 2)
        self.assertTrue(explained["citations"])
        self.assertIn("not a failure-rate comparison", explained["answer_overview"]["text"])

    def test_daylight_saving_date_boundaries_include_both_repeated_hours(self):
        self.assertEqual(period_dates("yesterday")[0].isoformat(), "2026-11-01")
        queryset, filters = apply_filters(Result.objects.filter(work_item=self.work), {"period": "yesterday"})
        self.assertEqual(set(queryset.values_list("pk", flat=True)), {self.result.pk, self.yesterday.pk})
        self.assertEqual(filters["created_before"], "2026-11-02")

    def test_exclusions_and_keys_do_not_drop_existing_date_or_qc_filters(self):
        reply = self.chat("Show failed QC results for project QUALITY yesterday")
        excluded = self.chat("Excluding key second", reply["context"])
        facts = self.facts(excluded)
        self.assertEqual(facts["total"], 1)
        self.assertEqual(facts["rows"][0]["id"], self.result.pk)
        self.assertEqual(facts["filters"]["qc"], "failed")
        self.assertIn("America/Los_Angeles", facts["window"])
        self.assertEqual(facts["rows"][0]["value"], 45)

    def test_numbered_result_reference_uses_displayed_identity_and_rechecks_access(self):
        reply = self.chat("Show failed QC results for project QUALITY yesterday")
        selected = self.facts(reply)["rows"][1]["id"]
        detail = self.chat("Explain the second result", reply["context"])
        self.assertEqual(self.facts(detail)["rows"][0]["id"], selected)
        self.project.members.remove(self.user)
        denied = self.chat("Explain the second result", reply["context"])
        self.assertTrue(denied["read_plan"]["partial"])
        self.assertEqual(denied["citations"], [])

    def test_tampered_cross_user_and_ambiguous_context_cannot_select_records(self):
        reply = self.chat("Show results for project QUALITY")
        token = reply["context"]["read_plan_memory"]
        forged = self.chat("Only yesterday", {"read_plan_memory": token + "broken"})
        self.assertNotIn("read_plan", forged)
        self.client.force_authenticate(self.other)
        cross_user = self.chat("Explain the second result", reply["context"])
        self.assertNotIn("45.0", str(cross_user))
        self.client.force_authenticate(self.user)
        multi = self.chat("Show results for sample QUALITY-1; show results for sample QUALITY-2")
        ambiguous = self.chat("Only yesterday", multi["context"])
        self.assertTrue(ambiguous["clarification"])
        self.assertIn("Which result query", ambiguous["answer"])

    def test_overview_has_grounded_sources_and_keeps_full_step_evidence(self):
        reply = self.chat("Show results for project QUALITY yesterday")
        overview = reply["answer_overview"]
        self.assertIn("2 matching results", overview["text"])
        valid_urls = {source["url"] for source in reply["citations"]}
        self.assertTrue(all(set(finding["sources"]) <= valid_urls for finding in overview["findings"]))
        self.assertIn("45.0", reply["read_plan"]["steps"][0]["answer"])
        self.assertIn("Next check", overview["text"])

    def test_local_semantic_search_matches_synonyms_without_exposing_private_or_opposite_instructions(self):
        low = SOPDocument.objects.create(document_code="LOW-DNA", title="Low concentration", version="1", section="1", approved=True,
                                        effective_at=NOW - timedelta(days=1),
                                        content="For low concentration, verify the calibration control and follow the validated repeat measurement procedure.")
        SOPDocument.objects.create(document_code="HIGH-DNA", title="High concentration", version="1", section="1", approved=True,
                                   effective_at=NOW - timedelta(days=1),
                                   content="For high concentration, review the high concentration procedure.")
        SOPDocument.objects.create(document_code="SECRET-LOW", title="Low concentration", version="1", section="1", approved=True,
                                   effective_at=NOW - timedelta(days=1),
                                   project=self.private, content="SECRET-INSTRUCTIONS")
        reply = search_sops("Which SOP covers DNA too dilute?", self.user)
        self.assertEqual(reply["citations"][0]["id"], low.pk)
        self.assertIn("low_concentration", reply["citations"][0]["semantic_matches"])
        self.assertNotIn("HIGH-DNA", str(reply))
        self.assertNotIn("SECRET-INSTRUCTIONS", str(reply))
        self.assertEqual(reply["sop_search"]["semantic_mode"], "lab-concepts-1")

    def test_saved_chat_stores_no_lab_values_and_restores_current_values_and_labels(self):
        reply = self.chat("Show results for project QUALITY yesterday")
        saved = self.client.post("/api/assistant/conversations/", {"name": "QC review", "turn_tokens": [reply["save_turn_token"]]}, format="json")
        self.assertEqual(saved.status_code, 201, saved.data)
        conversation = AssistantConversation.objects.get(pk=saved.data["id"])
        self.assertNotIn("45.0", json.dumps(conversation.turns))
        self.assertNotIn("qc_failure_reason", json.dumps(conversation.turns))
        Result.objects.filter(pk=self.result.pk).update(value_number=17)
        self.project.code = "RENAMED"
        self.project.save()
        reopened = self.client.get(f"/api/assistant/conversations/{conversation.pk}/")
        self.assertEqual(reopened.status_code, 200, reopened.data)
        fresh = reopened.data["history"][1]["reply"]
        self.assertIn("17.0", fresh["answer"])
        self.assertEqual(self.facts(fresh)["target"], "RENAMED")
        self.project.members.remove(self.user)
        denied = self.client.get(f"/api/assistant/conversations/{conversation.pk}/")
        self.assertNotIn("17.0", str(denied.data))
        self.assertNotIn("45.0", str(denied.data))
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_saved_chat_ownership_tokens_rename_delete_and_opt_in_append(self):
        initial = self.chat("Show results for project QUALITY")
        self.assertEqual(AssistantConversation.objects.count(), 0)
        saved = self.client.post("/api/assistant/conversations/", {"name": "Review", "turn_tokens": [initial["save_turn_token"]]}, format="json")
        pk = saved.data["id"]
        response = self.client.post("/api/assistant/chat/", {"message": "Show results for sample QUALITY-2", "conversation_id": pk}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(AssistantConversation.objects.get(pk=pk).turns), 2)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/assistant/conversations/{pk}/").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/assistant/conversations/{pk}/").status_code, 404)
        self.assertEqual(self.client.post("/api/assistant/conversations/", {"name": "Stolen", "turn_tokens": [initial["save_turn_token"]]}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/assistant/chat/", {"message": "Show results for sample QUALITY-2", "conversation_id": pk}, format="json").status_code, 404)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.patch(f"/api/assistant/conversations/{pk}/", {"name": "Renamed review"}, format="json").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/assistant/conversations/{pk}/").status_code, 204)
        self.assertFalse(AssistantConversation.objects.filter(pk=pk).exists())

    def test_multi_turn_quality_checks_exact_records_counts_sources_and_displayed_text(self):
        urls = [f"/samples/{self.sample.pk}#result-{self.result.pk}", f"/samples/{self.sample.pk}#result-{self.yesterday.pk}"]
        cases = [{"name": "Filtered QC conversation", "turns": [
            {"message": "Show failed QC results for project QUALITY", "expected": {"counts": {"total": 4}}},
            {"message": "Only yesterday", "expected": {"counts": {"total": 2}, "result_ids": [self.result.pk, self.yesterday.pk]}},
            {"message": "Excluding key second"},
        ], "expected": {"counts": {"total": 1, "failed": 1}, "result_ids": [self.result.pk],
                         "citation_urls": urls[:1], "overview_contains": ["1 matching results"], "operations": ["project_results"]}}]
        report = evaluate_cases(cases, self.user)
        self.assertEqual(report["passed"], 1, report)
        self.assertEqual(report["provider_requests"], 0)
        self.assertIn("latency_p95_ms", report)
        wrong = check_answer(self.chat("Show results for project QUALITY"), {"result_ids": [self.result.pk], "counts": {"total": 1}})
        self.assertFalse(wrong["exact_records"])
        self.assertFalse(wrong["exact_counts"])

    def test_feedback_exports_require_review_and_use_only_opted_in_personal_questions(self):
        reply = self.chat("Show results for project QUALITY")
        self.client.post("/api/assistant/conversations/", {"name": "Feedback review", "turn_tokens": [reply["save_turn_token"]]}, format="json")
        AssistantFeedback.objects.create(user=self.user, interaction_id=reply["interaction_id"], rating="DOWN", note="Needs clearer scope")
        another = self.chat("Show results for sample QUALITY-2")
        AssistantFeedback.objects.create(user=self.user, interaction_id=another["interaction_id"], rating="DOWN")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            call_command("export_assistant_feedback_cases", user=self.user.username, output=str(path), stdout=io.StringIO())
            report = json.loads(path.read_text())
            self.assertTrue(report["needs_review"])
            self.assertEqual(len(report["cases"]), 1)
            self.assertEqual(report["cases"][0]["review_note"], "Needs clearer scope")
            self.assertEqual(report["skipped_without_saved_question"], 1)
            self.assertIsNone(report["cases"][0]["expected"])

    def test_unsupported_filters_do_not_fall_back_to_broader_results(self):
        for message in ["Show results for project QUALITY except yesterday", "Show results for project QUALITY where sql=1"]:
            reply = self.chat(message)
            self.assertTrue(reply["clarification"])
            self.assertNotIn("read_plan", reply)
            self.assertNotIn("45.0", reply["answer"])

    def test_case_sensitive_keys_and_inline_filters_are_preserved(self):
        self.yesterday.key = "MixedCase"
        self.yesterday.save()
        reply = self.chat("Show QC failures for project QUALITY yesterday excluding key MixedCase")
        self.assertEqual(self.facts(reply)["total"], 1)
        self.assertEqual(self.facts(reply)["filters"]["exclude_keys"], ["MixedCase"])

    def test_provider_cannot_select_an_identifier_that_is_only_a_suffix_of_another_identifier(self):
        from assistant.read_plans import handle_read_plan
        payload = {"route": "read_plan", "confidence": .99, "steps": [{"operation": "project_results", "arguments": {"project": "QUALITY"}}]}
        reply = handle_read_plan("Show results for project PRIVATE-QUALITY", self.user, payload)
        self.assertTrue(reply["clarification"])
        self.assertNotIn("45.0", reply["answer"])

    def test_live_model_benchmark_reports_the_actual_configured_model_and_request_count(self):
        payload = {"route": "read_plan", "confidence": .98, "steps": [
            {"operation": "project_results", "arguments": {"project": "QUALITY"}, "filters": {"qc": "failed"}}]}
        cases = [{"name": "Natural wording", "message": "Explain recorded QC issues in project QUALITY and show those records",
                  "expected": {"counts": {"total": 4}, "operations": ["project_results"]}}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            path.write_text(json.dumps(cases))
            for provider in ["openai", "ollama"]:
                with self.subTest(provider=provider), override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=True, OPENLIMS_ASSISTANT_LLM_ROUTING_ENABLED=True,
                        OPENAI_API_KEY="test-key", OLLAMA_BASE_URL="http://ollama:11434", OLLAMA_MODEL="test"), patch(
                        f"assistant.llm.call_{provider}", return_value=json.dumps(payload)):
                    output = io.StringIO()
                    call_command("evaluate_assistant_answers", cases=str(path), user=self.user.username, live_provider=True,
                                 provider=provider, model="model-under-test", stdout=output)
                    report = json.loads(output.getvalue())
                    self.assertEqual(report["provider_requests"], 1)
                    self.assertEqual(report["configured_model"]["model"], "model-under-test")
                    self.assertEqual(report["passed"], 1)


class TypedFilterContractTests(SimpleTestCase):
    def test_invalid_dates_values_unknown_filters_and_injected_fields_fail_closed(self):
        valid = {"route": "read_plan", "confidence": .99, "steps": [{"operation": "project_results", "arguments": {"project": "QUALITY"}}]}
        for filters in [{"created_from": "2026-02-30"}, {"period": "yesterday", "created_from": "2026-01-01"},
                        {"created_from": "2026-02-01", "created_before": "2026-01-01"}, {"qc": "sql"},
                        {"keys": [True]}, {"exclude_keys": ["DROP TABLE"]}, {"owner_id": 1}, {"compare_period": "last_week"}]:
            payload = copy.deepcopy(valid)
            payload["steps"][0]["filters"] = filters
            with self.subTest(filters=filters):
                self.assertIsNone(validate_read_plan(payload))
