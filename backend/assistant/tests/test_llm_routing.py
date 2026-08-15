from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from assistant.llm import classify_route_with_llm


@override_settings(
    OPENLIMS_ASSISTANT_LLM_ENABLED=True,
    OPENLIMS_ASSISTANT_LLM_PROVIDER="ollama",
    OPENLIMS_ASSISTANT_LLM_ROUTING_ENABLED=True,
    OLLAMA_BASE_URL="http://ollama:11434",
    OLLAMA_MODEL="llama3.2:1b",
)
class LLMRouteClassifierTests(SimpleTestCase):
    @patch("assistant.llm.call_ollama")
    def test_accepts_only_whitelisted_high_confidence_json(self, call_mock):
        call_mock.return_value = '{"route":"attention","confidence":0.91}'

        result = classify_route_with_llm("What should I look at first?")

        self.assertEqual(result["route"], "attention")
        self.assertEqual(result["provider"], "ollama")
        self.assertEqual(result["confidence"], 0.91)
        call_mock.assert_called_once()
        self.assertTrue(call_mock.call_args.kwargs["json_response"])

    @patch("assistant.llm.call_ollama")
    def test_rejects_unknown_or_low_confidence_routes(self, call_mock):
        call_mock.side_effect = [
            '{"route":"run_arbitrary_sql","confidence":1.0}',
            '{"route":"attention","confidence":0.2}',
        ]

        self.assertIsNone(classify_route_with_llm("Do something"))
        self.assertIsNone(classify_route_with_llm("Maybe review things"))

    @patch("assistant.llm.call_ollama")
    def test_accepts_general_questions_as_a_constrained_route(self, call_mock):
        call_mock.return_value = '{"route":"general","confidence":0.92}'

        result = classify_route_with_llm("Why is the sky blue?")

        self.assertEqual(result["route"], "general")
        self.assertEqual(result["provider"], "ollama")
        self.assertEqual(result["confidence"], 0.92)


class LLMRoutingFallbackIntegrationTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="routing-user")
        self.client.force_authenticate(self.user)

    @patch("assistant.views.classify_route_with_llm")
    def test_deterministic_match_does_not_call_llm_classifier(self, classifier):
        response = self.client.post(
            "/api/assistant/chat/",
            {"message": "What needs my attention?"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("attention", response.data)
        classifier.assert_not_called()

    @patch("assistant.views.classify_route_with_llm")
    def test_unmatched_natural_language_can_use_constrained_route_hint(
        self,
        classifier,
    ):
        classifier.return_value = {
            "route": "attention",
            "confidence": 0.88,
            "provider": "ollama",
        }
        response = self.client.post(
            "/api/assistant/chat/",
            {"message": "What are the things I ought to look at first?"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("attention", response.data)
        self.assertEqual(response.data["routing"]["route"], "attention")
        self.assertEqual(response.data["routing"]["source"], "ollama_fallback")

    @patch("assistant.views.classify_route_with_llm")
    def test_invalid_classifier_result_keeps_honest_fallback(self, classifier):
        classifier.return_value = None
        response = self.client.post(
            "/api/assistant/chat/",
            {"message": "Could you handle that thing for me?"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("couldn't determine", response.data["answer"].lower())
        self.assertEqual(response.data["mode"], "openlims")
