from datetime import datetime, timezone as datetime_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from assistant.conversation import route_conversation_utility


class ConversationUtilityTests(SimpleTestCase):
    @override_settings(TIME_ZONE="UTC", USE_TZ=True)
    @patch("assistant.conversation.timezone.now")
    def test_answers_natural_time_and_date_questions_without_an_llm(
        self,
        now_mock,
    ):
        now_mock.return_value = datetime(
            2026,
            8,
            15,
            20,
            5,
            tzinfo=datetime_timezone.utc,
        )

        time_result = route_conversation_utility(
            "Could you please tell me what time it is right now?"
        )
        date_result = route_conversation_utility("What's today's date?")

        self.assertIn("8:05 PM", time_result["answer"])
        self.assertIn("Saturday, August 15, 2026", time_result["answer"])
        self.assertIn("Saturday, August 15, 2026", date_result["answer"])
        self.assertTrue(time_result["skip_llm"])
        self.assertEqual(time_result["response_type"], "utility")

    def test_handles_greetings_identity_help_and_thanks(self):
        cases = {
            "Hello there": "hello",
            "Who are you?": "openlims assistant",
            "What can you do?": "permission-filtered",
            "Thank you": "welcome",
        }

        for message, expected in cases.items():
            with self.subTest(message=message):
                result = route_conversation_utility(message)
                self.assertIsNotNone(result)
                self.assertIn(expected, result["answer"].lower())
                self.assertTrue(result["skip_llm"])

    def test_does_not_capture_a_specific_openlims_help_request(self):
        self.assertIsNone(
            route_conversation_utility("Help me find sample S-ALPHA-001")
        )


@override_settings(
    OPENLIMS_ASSISTANT_LLM_ENABLED=True,
    OPENLIMS_ASSISTANT_LLM_PROVIDER="ollama",
    OPENLIMS_ASSISTANT_LLM_ROUTING_ENABLED=True,
    OLLAMA_BASE_URL="http://ollama:11434",
    OLLAMA_MODEL="llama3.2:1b",
)
class GeneralConversationIntegrationTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="conversation-user"
        )
        self.client.force_authenticate(self.user)

    @patch("assistant.views.classify_route_with_llm")
    def test_utility_question_bypasses_the_llm_classifier(self, classifier):
        response = self.client.post(
            "/api/assistant/chat/",
            {"message": "What time is it?"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["response_type"], "utility")
        self.assertEqual(response.data["mode"], "openlims")
        self.assertTrue(response.data["skip_llm"])
        classifier.assert_not_called()

    @patch("assistant.llm.call_ollama")
    @patch("assistant.views.classify_route_with_llm")
    def test_general_question_uses_a_separate_no_database_prompt(
        self,
        classifier,
        call_ollama,
    ):
        classifier.return_value = {
            "route": "general",
            "confidence": 0.93,
            "provider": "ollama",
        }
        call_ollama.return_value = (
            "Photosynthesis converts light energy into chemical energy."
        )

        response = self.client.post(
            "/api/assistant/chat/",
            {"message": "Can you briefly explain photosynthesis?"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["response_type"], "general")
        self.assertEqual(response.data["mode"], "ollama")
        self.assertEqual(response.data["routing"]["route"], "general")
        self.assertIn("Photosynthesis", response.data["answer"])
        call_ollama.assert_called_once()
        kwargs = call_ollama.call_args.kwargs
        self.assertIn("general-conversation mode", kwargs["system_message"])
        self.assertNotIn("OpenLIMS tool result", call_ollama.call_args.args[0])

    @patch("assistant.llm.call_ollama")
    @patch("assistant.views.classify_route_with_llm")
    def test_unsupported_openlims_action_stays_unknown(
        self,
        classifier,
        call_ollama,
    ):
        classifier.return_value = {
            "route": "unknown",
            "confidence": 0.94,
            "provider": "ollama",
        }

        response = self.client.post(
            "/api/assistant/chat/",
            {"message": "Calibrate instrument ZX-9 for me"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["routing"]["route"], "unknown")
        self.assertIn("couldn't determine", response.data["answer"].lower())
        self.assertTrue(response.data["skip_llm"])
        call_ollama.assert_not_called()
