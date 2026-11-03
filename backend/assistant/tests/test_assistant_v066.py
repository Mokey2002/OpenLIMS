"""Conversational acceptance tests through the authenticated chat API."""
from unittest.mock import patch

from django.test import override_settings
from rest_framework.test import APITestCase

from assistant.models import AssistantAction, AssistantConversation
from assistant.read_plan_memory import KEY
from results.models import Result
from . import test_assistant_v065 as previous


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False, OPENLIMS_ASSISTANT_LLM_ENABLED=False,
                   TIME_ZONE="America/Los_Angeles")
class AssistantV066Tests(APITestCase):
    setUpTestData = classmethod(previous.AssistantV065Tests.setUpTestData.__func__)
    setUp = previous.AssistantV065Tests.setUp
    chat = previous.AssistantV065Tests.chat
    page = previous.AssistantV065Tests.page
    facts = previous.AssistantV065Tests.facts

    def test_polite_initial_queries_keep_all_filters_without_a_model(self):
        messages = [
            "Could you please show me the failed results for project QUALITY from yesterday?",
            "Hi, could you show me failed results for project QUALITY yesterday, please?",
            "Can I see the failed results for project QUALITY yesterday?",
            "I'd like to see the failed results for project QUALITY yesterday.",
            "Thanks! Can you show me the failed results for project QUALITY yesterday?",
        ]
        with patch("assistant.views.classify_route_with_llm") as model:
            for message in messages:
                with self.subTest(message=message):
                    facts = self.facts(self.chat(message))
                    self.assertEqual(facts["target"], "QUALITY")
                    self.assertEqual(facts["total"], 2)
                    self.assertEqual(facts["filters"]["qc"], "failed")
                    self.assertEqual(facts["filters"]["created_from"], "2026-11-01")
            model.assert_not_called()

    def test_natural_conversation_preserves_investigation_across_eight_turns(self):
        reply = self.chat("Could you show me the results for sample QUALITY-1 yesterday?")
        reply = self.chat("Just the failed ones, please", reply["context"])
        self.assertEqual(self.facts(reply)["total"], 2)
        thanks = self.chat("Thanks!", reply["context"])
        self.assertEqual(thanks["context"][KEY], reply["context"][KEY])
        compared = self.chat("Could you compare those with last week?", thanks["context"])
        focused = self.chat("Please explain the numeric differences", compared["context"])
        detail = self.chat("Can you explain the first result?", focused["context"])
        self.assertEqual(self.facts(detail)["rows"][0]["id"], self.facts(focused)["rows"][0]["id"])
        returned = self.chat("Could you go back to the comparison?", detail["context"])
        corrected = self.chat("No, I meant QUALITY-2", returned["context"])
        step = corrected["read_plan_spec"]["steps"][0]
        self.assertEqual(step["arguments"], {"sample": "QUALITY-2"})
        self.assertEqual(step["focus"], "numeric")
        self.assertEqual(step["filters"], {"period": "yesterday", "qc": "failed", "compare_period": "last_week"})
        self.assertFalse(AssistantAction.objects.exists())

    def test_short_date_followups_and_correction_forms(self):
        initial = self.chat("Show results for project QUALITY yesterday")
        for message in ["And last month?", "What about last month?", "How about last month?", "Sorry, I meant last month"]:
            with self.subTest(message=message):
                corrected = self.chat(message, initial["context"])
                self.assertEqual(self.facts(corrected)["target"], "QUALITY")
                self.assertEqual(corrected["read_plan_spec"]["steps"][0]["filters"], {"period": "last_month"})

    def test_explicit_new_request_after_actually_does_not_inherit_old_filters(self):
        initial = self.chat("Show failed results for project QUALITY yesterday")
        reply = self.chat("Actually, show me the results for sample QUALITY-2", initial["context"])
        self.assertEqual(self.facts(reply)["target"], "QUALITY-2")
        self.assertEqual(reply["read_plan_spec"]["steps"][0].get("filters", {}), {})

    def test_status_correction_does_not_get_mistaken_for_a_record_name(self):
        initial = self.chat("Show results for sample QUALITY-1 yesterday")
        for message in ["No, I meant failed ones", "Sorry, I meant failed"]:
            with self.subTest(message=message):
                reply = self.chat(message, initial["context"])
                self.assertEqual(self.facts(reply)["target"], "QUALITY-1")
                self.assertEqual(self.facts(reply)["filters"]["qc"], "failed")
                self.assertEqual(self.facts(reply)["total"], 2)
        with patch("assistant.read_plans._read") as read:
            rejected = self.chat("No, I meant 2026-02-30", initial["context"])
        self.assertTrue(rejected["clarification"])
        read.assert_not_called()

    def test_page_result_filters_survive_saving_and_refresh_permissions_and_values(self):
        reply = self.chat("Could you show me the failed results for this sample from yesterday?", page=self.page())
        self.assertEqual(self.facts(reply)["total"], 2)
        self.assertEqual(reply["page_read_reference"]["filters"], {"qc": "failed", "period": "yesterday"})
        saved = self.client.post("/api/assistant/conversations/", {"name": "Natural page read", "turn_tokens": [reply["save_turn_token"]]}, format="json")
        self.assertEqual(saved.status_code, 201, saved.data)
        conversation = AssistantConversation.objects.get(pk=saved.data["id"])
        self.assertEqual(conversation.turns[0]["reference"]["filters"]["qc"], "failed")
        Result.objects.filter(pk=self.result.pk).update(value_number=23)
        self.sample.sample_id = "RENAMED-NATURAL"
        self.sample.save()
        reopened = self.client.get(f"/api/assistant/conversations/{conversation.pk}/").data["history"][1]["reply"]
        self.assertEqual(self.facts(reopened)["total"], 2)
        self.assertEqual(self.facts(reopened)["target"], "RENAMED-NATURAL")
        self.assertIn("23.0", reopened["answer"])
        self.project.members.remove(self.user)
        denied = self.client.get(f"/api/assistant/conversations/{conversation.pk}/").data
        self.assertNotIn("23.0", str(denied))
        self.assertNotIn("RENAMED-NATURAL", str(denied))

    def test_unsupported_page_conditions_keep_previous_query_and_do_not_run_a_subset(self):
        initial = self.chat("Show results for project QUALITY yesterday")
        for message in ["Could you show results for this sample that look unusual?",
                        "Show failed results for this sample yesterday and approve them",
                        "Show results for this sample yesterday and last month",
                        "Show results for this sample from 2026-02-30 until 2026-03-02"]:
            with self.subTest(message=message), patch("assistant.page_context._read") as read:
                rejected = self.chat(message, initial["context"], self.page())
                self.assertTrue(rejected["clarification"])
                self.assertEqual(rejected["context"][KEY], initial["context"][KEY])
                read.assert_not_called()
        self.assertFalse(AssistantAction.objects.exists())

    def test_polite_negated_and_mixed_requests_never_create_actions_or_partial_reads(self):
        initial = self.chat("Show results for sample QUALITY-1")
        for message in ["Could you show results for sample QUALITY-1 and delete it?",
                        "Please don't show results for sample QUALITY-1",
                        "Just the failed ones and approve them, please",
                        "Sorry, I meant QUALITY-2 and approve it"]:
            with self.subTest(message=message), patch("assistant.read_plans._read") as read:
                reply = self.chat(message, initial["context"])
                read.assert_not_called()
                self.assertNotIn("pending_action", reply)
        self.assertFalse(AssistantAction.objects.exists())

    def test_bare_target_correction_requires_signed_context_and_rechecks_access(self):
        initial = self.chat("Show results for sample QUALITY-1")
        reply = self.chat("Sorry, I meant QUALITY-2", initial["context"])
        self.assertEqual(self.facts(reply)["target"], "QUALITY-2")
        denied = self.chat("No, I meant PRIVATE-1", initial["context"])
        self.assertNotIn("SECRET-VALUE", str(denied))
        self.assertTrue(denied["read_plan"]["partial"])
        forged = self.chat("No, I meant QUALITY-2", {KEY: initial["context"][KEY] + "broken"})
        self.assertNotIn("read_plan", forged)
        self.client.force_authenticate(self.other)
        cross_user = self.chat("No, I meant QUALITY-2", initial["context"])
        self.assertNotIn("read_plan", cross_user)
