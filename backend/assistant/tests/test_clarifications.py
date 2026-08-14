from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase


class AssistantClarificationTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="clarification-user"
        )
        self.client.force_authenticate(self.user)

    def chat(self, message, context=None):
        return self.client.post(
            "/api/assistant/chat/",
            {"message": message, "context": context or {}},
            format="json",
        )

    def test_ambiguous_qc_samples_offer_semantic_choices_and_keep_context(self):
        context = {
            "investigation": {
                "subject_type": "sample",
                "identifier": "S-ALPHA-003",
                "group_by": "overview",
            }
        }
        response = self.chat("Show QC samples", context=context)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["clarification"]["topic"], "qc_samples")
        self.assertEqual(response.data["context"], context)
        self.assertNotIn("chart", response.data)
        self.assertNotIn("investigation", response.data)
        self.assertEqual(
            [option["id"] for option in response.data["clarification"]["options"]],
            ["awaiting_review", "failed_qc", "workflow_qc"],
        )
        self.assertTrue(response.data["skip_llm"])
        self.assertEqual(response.data["mode"], "openlims")

    def test_ambiguous_qc_results_offer_review_failure_and_approval_choices(self):
        response = self.chat("List QC results")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["clarification"]["topic"], "qc_results")
        self.assertEqual(
            [option["message"] for option in response.data["clarification"]["options"]],
            [
                "Show results awaiting QC review",
                "Show results that failed QC",
                "Show approved results",
            ],
        )

    def test_bare_samples_results_failures_and_inventory_request_a_scope(self):
        samples = self.chat("Show samples")
        results = self.chat("List results")
        failures = self.chat("Show failures")
        inventory = self.chat("Show inventory")

        self.assertEqual(samples.data["clarification"]["topic"], "sample_scope")
        self.assertEqual(results.data["clarification"]["topic"], "result_scope")
        self.assertEqual(failures.data["clarification"]["topic"], "failure_domain")
        self.assertEqual(inventory.data["clarification"]["topic"], "inventory_scope")

    def test_precise_qc_questions_bypass_clarification(self):
        precise_questions = [
            "Show me which samples need QC",
            "Which samples failed QC?",
            "Which samples are in QC?",
            "Show results awaiting QC review",
            "Show approved results",
            "Graph QC failure rates by sample",
        ]

        for question in precise_questions:
            with self.subTest(question=question):
                response = self.chat(question)
                self.assertNotIn("clarification", response.data)
