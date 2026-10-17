import json
from unittest.mock import patch
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.models import AssistantAction
from assistant.provider_conversation import remember, recall, classifier_context
from assistant.provider_tools import dispatch_tool
from assistant.context_state import sanitize_context
from assistant.llm import build_route_classifier_prompt
from . import test_comparisons
from .test_provider_tools import plan, SETTINGS


class ConversationTests(APITestCase):
    setUp = test_comparisons.AssistantComparisonTests.setUp
    chat = test_comparisons.AssistantComparisonTests.chat

    def test_exact_reported_phrase_and_variants_need_no_model(self):
        for message in ["what do i need to work on", "What should I work on today?", "what's on my plate?", "show me my tasks", "what do i need to work on, smh", "¿En qué debo trabajar hoy?"]:
            with self.subTest(message=message), patch("assistant.views.classify_route_with_llm") as model:
                data = self.chat(message).data
                self.assertEqual(data["personal_work"]["username"], "eduardo")
                self.assertEqual([row["sample"] for row in data["comparison"]["rows"]], ["S-100"])
                model.assert_not_called()

    def test_personal_scope_deadlines_and_no_false_all_clear(self):
        first = self.samples[0].work_items.first()
        first.status = "COMPLETED"
        first.save()
        private = self.private_sample.work_items.first()
        private.assigned_to = self.tech
        private.save()
        data = self.chat("What do I need to work on?").data
        self.assertEqual(data["comparison"]["rows"], [])
        self.assertNotIn("S-PRIVATE", str(data))
        self.assertIn("assigned to you", data["answer"])
        second = self.samples[1].work_items.first()
        second.assigned_to = self.tech
        second.due_at = timezone.now() - timedelta(days=1)
        second.save()
        self.assertEqual(self.chat("show my work").data["comparison"]["rows"][0]["review"], "Overdue")

    def test_clarification_is_one_question_and_accepts_short_answers(self):
        first = dispatch_tool(plan("handover"), self.tech)
        self.assertIn("Whose", first["answer"])
        second = self.chat("me", first["context"]).data
        self.assertIn("Who is taking over", second["answer"])
        third = self.chat("eduardo", second["context"]).data
        self.assertIn("Handover: eduardo", third["draft"]["text"])
        self.assertEqual(AssistantAction.objects.count(), 0)
        direct = dispatch_tool(plan("handover", source="me", recipient="me"), self.tech)
        self.assertIn("Handover: eduardo", direct["draft"]["text"])

    def test_context_tampering_other_user_and_expiry_are_rejected(self):
        token = remember(plan("project_update"), self.tech)
        context = {"provider_conversation": token}
        self.assertIsNotNone(recall(sanitize_context(context), self.tech))
        self.assertIsNone(recall(context, self.outsider))
        self.assertIsNone(recall({"provider_conversation": token + "x"}, self.tech))
        with patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + 1801):
            self.assertIsNone(recall(context, self.tech))
        self.assertIsNone(remember(plan("samples", command="Archive sample S-100"), self.tech))
        data = self.chat("ALPHA", {"provider_conversation": token + "x"}).data
        self.assertIn("no longer available", data["answer"])
        self.assertEqual(data["context"], {})

    def test_invalid_answer_keeps_the_question_and_never_writes(self):
        context = dispatch_tool(plan("reagent_plan", procedure="EX"), self.tech)["context"]
        reply = self.chat("0", context).data
        self.assertIn("between 1 and 100000", reply["answer"])
        self.assertEqual(reply["context"], context)
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_permissions_are_rechecked_and_new_topic_clears_state(self):
        context = dispatch_tool(plan("project_update"), self.tech)["context"]
        self.alpha.members.remove(self.tech)
        data = self.chat("ALPHA", context).data
        self.assertNotIn("draft", data)
        self.assertNotIn("S-100", str(data))
        cancelled = self.chat("never mind", context).data
        self.assertEqual(cancelled["context"], {})
        changed = self.chat("What do I need to work on?", context).data
        self.assertNotIn("provider_conversation", changed["context"])

    def test_only_verified_relevant_context_is_sent_to_classifier(self):
        context = {"provider_conversation": remember(plan("project_update", project="ALPHA"), self.tech), "verified_feature_context": {"tool": "evil"}}
        safe = classifier_context(context, self.tech, "same for BETA")
        self.assertEqual(safe["verified_feature_context"]["tool"], "project_update")
        self.assertNotIn("provider_conversation", safe)
        self.assertNotIn("verified_feature_context", classifier_context(context, self.tech, "show system status"))
        self.assertIn('"project": "ALPHA"', build_route_classifier_prompt("same for BETA", safe))

    @override_settings(**SETTINGS)
    def test_model_followup_uses_previous_task_for_both_providers(self):
        for provider in ["openai", "ollama"]:
            with self.subTest(provider=provider), override_settings(OPENLIMS_ASSISTANT_LLM_PROVIDER=provider):
                context = dispatch_tool({**plan("project_update", project="ALPHA"), "provider": provider}, self.tech)["context"]
                with patch(f"assistant.llm.call_{provider}", return_value=json.dumps(plan("project_update", project="BETA"))) as model:
                    data = self.chat("same for BETA", context).data
                    self.assertIn("Project BETA", data["draft"]["text"])
                    self.assertIn('"project": "ALPHA"', model.call_args.args[0])
                    model.assert_called_once()
