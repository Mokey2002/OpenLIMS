import json
from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from assistant.models import AssistantAction, AssistantConversation
from assistant.page_context import route_page_read
from assistant.read_plan_memory import KEY, recall, remember
from assistant.read_plans import validate_read_plan
from assistant.result_queries import period_dates
from assistant.result_corrections import parse_correction
from results.models import Result
from events.models import Event
from . import test_assistant_v063 as previous
from . import test_sample_guidance as guidance

NOW = previous.NOW


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False, OPENLIMS_ASSISTANT_LLM_ENABLED=False, TIME_ZONE="America/Los_Angeles")
class AssistantV065Tests(APITestCase):
    setUpTestData = classmethod(previous.AssistantV063Tests.setUpTestData.__func__)
    setUp = previous.AssistantV063Tests.setUp
    facts = previous.AssistantV063Tests.facts

    def chat(self, message, context=None, page=None):
        payload = {"message": message, "context": context or {}}
        if page is not None:
            payload["page_context"] = page
        result = self.client.post("/api/assistant/chat/", payload, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        return result.data

    def page(self, kind="sample", record=None):
        record = record or (self.sample if kind == "sample" else self.project)
        return {"kind": kind, "record_id": str(record.public_id)}

    def test_page_reads_use_loaded_identity_override_old_context_and_do_not_create_actions(self):
        stale = self.chat("Explain sample QUALITY-2")["context"]
        reply = self.chat("Summarize this sample", stale, self.page())
        self.assertIn("QUALITY-1", reply["answer"])
        self.assertEqual(reply["context"]["sample_id"], self.sample.pk)
        self.assertEqual(reply["page_context_used"]["label"], "QUALITY-1")
        self.assertEqual(reply["citations"][0]["url"], f"/samples/{self.sample.pk}")
        project = self.chat("Summarize this project", page=self.page("project"))
        self.assertIn("Quality project", project["answer"])
        self.assertEqual(project["context"]["project_id"], self.project.pk)
        samples = self.chat("Show samples in this project", page=self.page("project"))
        self.assertIn("QUALITY-2", str(samples))
        evidence = self.chat("Show evidence for this sample", page=self.page())
        self.assertIn("45.0", evidence["answer"])
        self.assertFalse(AssistantAction.objects.exists())

    def test_polite_page_requests_work_and_extra_conditions_are_not_silently_discarded(self):
        reply = self.chat("Could you please summarize this sample?", page=self.page())
        self.assertEqual(reply["page_context_used"]["label"], "QUALITY-1")
        with patch("assistant.page_context._read") as read:
            rejected = self.chat("Show results for this sample that look unusual", page=self.page())
        self.assertTrue(rejected["clarification"])
        self.assertNotIn("read_plan", rejected)
        read.assert_not_called()

    def test_page_results_create_signed_query_state_for_atomic_natural_corrections(self):
        reply = self.chat("Show results for this sample", page=self.page())
        self.assertEqual(self.facts(reply)["target"], "QUALITY-1")
        self.assertIsNotNone(recall(reply["context"], self.user))
        corrected = self.chat("No, use last month and exclude key second", reply["context"])
        facts = self.facts(corrected)
        self.assertEqual(facts["filters"]["created_from"], "2026-10-01")
        self.assertEqual(facts["filters"]["created_before"], "2026-11-01")
        self.assertEqual(facts["filters"]["exclude_keys"], ["second"])
        self.assertEqual(facts["total"], 2)

    def test_atomic_corrections_preserve_scope_focus_qc_and_existing_exclusions(self):
        reply = self.chat("Show failed results for project QUALITY yesterday excluding key old-control")
        compared = self.chat("Compare those with this month", reply["context"])
        focused = self.chat("Explain numeric differences", compared["context"])
        corrected = self.chat("Actually, use last month and exclude key second", focused["context"])
        step = corrected["read_plan_spec"]["steps"][0]
        self.assertEqual(step["focus"], "numeric")
        self.assertEqual(step["filters"], {"qc": "failed", "period": "last_month", "compare_period": "this_month", "exclude_keys": ["old-control", "second"]})
        switched = self.chat("No, use sample QUALITY-2 and this month", corrected["context"])
        step = switched["read_plan_spec"]["steps"][0]
        self.assertEqual(step["operation"], "sample_results_compare")
        self.assertEqual(step["arguments"], {"sample": "QUALITY-2"})
        self.assertEqual(step["filters"]["exclude_keys"], ["old-control", "second"])
        self.assertEqual(step["focus"], "numeric")

    def test_unsupported_conflicting_or_write_corrections_do_not_run_a_partial_read(self):
        reply = self.chat("Show failed results for project QUALITY yesterday")
        for message in ["No, use last month and exclude controls", "Actually, use last month and approve them", "No, use last month and yesterday",
                        "Use last month and where sql=1", "No, use project QUALITY and project PRIVATE-QUALITY", "No, use 2026-02-30"]:
            with self.subTest(message=message), patch("assistant.read_plans._read") as read:
                rejected = self.chat(message, reply["context"])
            self.assertTrue(rejected["clarification"])
            self.assertNotIn("read_plan", rejected)
            self.assertEqual(rejected["context"][KEY], reply["context"][KEY])
            read.assert_not_called()
        self.assertFalse(AssistantAction.objects.exists())

    def test_page_permissions_are_rechecked_for_pk_uuid_history_and_saved_reads(self):
        reply = self.chat("Summarize this sample", page=self.page())
        saved = self.client.post("/api/assistant/conversations/", {"name": "Page summary", "turn_tokens": [reply["save_turn_token"]]}, format="json")
        self.assertEqual(saved.status_code, 201, saved.data)
        stored = AssistantConversation.objects.get(pk=saved.data["id"])
        self.assertEqual(stored.turns[0]["kind"], "page_read")
        self.assertNotIn("45.0", json.dumps(stored.turns))
        Result.objects.filter(pk=self.result.pk).update(value_number=17)
        self.sample.sample_id = "RENAMED-SAMPLE"
        self.sample.save()
        opened = self.client.get(f"/api/assistant/conversations/{stored.pk}/")
        self.assertIn("RENAMED-SAMPLE", opened.data["history"][1]["reply"]["answer"])
        self.project.members.remove(self.user)
        for page in [self.page(), {"kind": "sample", "record_id": str(self.sample.pk)}, self.page("project")]:
            denied = self.chat("Show history for this" if page["kind"] == "sample" else "Summarize this project", page=page)
            self.assertTrue(denied["clarification"])
            self.assertNotIn("17.0", str(denied))
            self.assertNotIn("RENAMED-SAMPLE", str(denied))
            self.assertNotIn("page_read_reference", denied)
        denied = self.client.get(f"/api/assistant/conversations/{stored.pk}/")
        self.assertNotIn("17.0", str(denied.data))
        self.assertNotIn("RENAMED-SAMPLE", str(denied.data))

    def test_invalid_page_metadata_is_rejected_before_any_read(self):
        for page in [{"kind": "user", "record_id": "1"}, {"kind": "sample", "record_id": "../private"},
                     {"kind": "sample", "record_id": "1", "user_id": self.other.pk}, {"kind": "sample", "record_id": True},
                     {"kind": "sample", "record_id": "0"}, {"kind": "sample"}, []]:
            with self.subTest(page=page), patch("assistant.page_context._read") as read:
                result = self.client.post("/api/assistant/chat/", {"message": "Summarize this sample", "page_context": page}, format="json")
            self.assertEqual(result.status_code, 400, result.data)
            read.assert_not_called()

    def test_page_does_not_retarget_explicit_records_general_questions_or_writes(self):
        explicit = self.chat("Explain sample QUALITY-2", page=self.page())
        self.assertEqual(explicit["context"]["sample_id"], self.second.pk)
        self.assertNotIn("page_context_used", explicit)
        general = self.chat("What is DNA?", page=self.page())
        self.assertNotIn("page_context_used", general)
        for text in ["Approve this sample", "Summarize this sample and approve it"]:
            result = self.chat(text, explicit["context"], self.page())
            self.assertTrue(result["clarification"])
            self.assertNotIn("pending_action", result)
            self.assertNotIn("page_context_used", result)
        mismatch = self.chat("Summarize the current sample", page=self.page("project"))
        self.assertTrue(mismatch["clarification"])
        self.assertNotIn("Quality project", mismatch["answer"])

    def test_malicious_display_context_tampered_and_cross_user_tokens_cannot_change_queries(self):
        reply = self.chat("Show results for this project", page=self.page("project"))
        forged = {**reply["context"], "result_query_context": {"kind": "project", "target": "PRIVATE-QUALITY", "filters": {}}}
        corrected = self.chat("Use last month", forged)
        self.assertEqual(self.facts(corrected)["target"], "QUALITY")
        self.client.force_authenticate(self.other)
        denied = self.chat("Use last month", reply["context"])
        self.assertNotIn("read_plan", denied)
        self.assertNotIn("45.0", str(denied))
        denied = self.chat("Show results for this sample", page=self.page())
        self.assertNotIn("45.0", str(denied))
        self.assertTrue(denied["clarification"])

    def test_page_history_uses_stable_identity_after_sample_rename(self):
        other = self.second
        other.sample_id = "RENAMED-SECOND"
        other.save()
        Event.objects.create(entity_type="Sample", entity_id=str(other.pk), action="PAGE-SECOND-HISTORY", actor=self.user)
        reply = self.chat("Show history for this sample", page=self.page(record=other))
        self.assertIn("PAGE-SECOND-HISTORY", reply["answer"])
        self.assertIn("RENAMED-SECOND", reply["answer"])
        self.assertEqual(reply["context"]["sample_id"], other.pk)

    def test_month_comparison_and_multiple_query_corrections_are_bounded(self):
        reply = self.chat("Show results for project QUALITY last month")
        compared = self.chat("Compare those with previous month", reply["context"])
        self.assertEqual(self.facts(compared)["comparison_scope"]["selected_days"], 31)
        self.assertTrue(self.facts(compared)["comparison_scope"]["overlap"])
        plan = validate_read_plan({"route": "read_plan", "confidence": 1, "steps": [
            {"operation": "project_results", "arguments": {"project": "QUALITY"}},
            {"operation": "sample_results", "arguments": {"sample": "QUALITY-1"}}]})
        with patch("assistant.read_plans._read") as read:
            rejected = self.chat("No, use last month", {KEY: remember(plan, [], self.user)})
        self.assertTrue(rejected["clarification"])
        read.assert_not_called()


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False, OPENLIMS_ASSISTANT_LLM_ENABLED=False)
class PageGuidanceTests(APITestCase):
    setUp = guidance.SampleGuidanceTests.setUp
    def test_page_question_explains_actual_workflow_dependencies_without_writes(self):
        before = Event.objects.count()
        result = self.client.post("/api/assistant/chat/", {"message": "Why is this blocked?", "page_context": {"kind": "sample", "record_id": str(self.sample.public_id)}}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["sample_guidance"]["steps"][1]["waiting_for"], ["1"])
        self.assertIn("concentration", result.data["answer"])
        self.assertFalse(AssistantAction.objects.exists())
        self.assertEqual(Event.objects.count(), before)


class CorrectionGrammarTests(SimpleTestCase):
    def test_explicit_action_targets_are_not_mistaken_for_page_references_in_reasons(self):
        page = {"kind": "sample", "record_id": "1"}
        for message in ["Approve result R-42 because the current control passed", "Approve result R-42 because this control passed"]:
            self.assertIsNone(route_page_read(message, None, page))

    def test_month_boundaries_include_year_and_leap_year_transitions(self):
        for instant, start, end in [(datetime(2026, 1, 15, tzinfo=dt_timezone.utc), "2025-12-01", "2026-01-01"),
                                    (datetime(2024, 3, 15, tzinfo=dt_timezone.utc), "2024-02-01", "2024-03-01")]:
            with patch("django.utils.timezone.now", return_value=instant):
                dates = period_dates("last_month")
                self.assertEqual([day.isoformat() for day in dates], [start, end])

    def test_quoted_targets_and_atomic_conflicts(self):
        patch_value, question = parse_correction('No, use project "DNA and RNA" and last month and exclude key MixedCase')
        self.assertIsNone(question)
        self.assertEqual(patch_value["target"]["identifier"], "DNA and RNA")
        self.assertEqual(patch_value["filters"], {"period": "last_month", "exclude_keys": ["MixedCase"]})
        self.assertEqual(parse_correction("Notify the project owner"), (None, None))
        self.assertIsNotNone(parse_correction("No, use last month and yesterday")[1])
