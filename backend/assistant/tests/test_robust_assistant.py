import secrets

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from assistant.context_state import update_conversation_context
from assistant.entity_resolution import resolve_entities
from assistant.evaluation_cases import (
    LLM_FALLBACK_EVALUATION_CASES,
    iter_routing_evaluation_cases,
)
from assistant.models import AssistantFeedback, AssistantInteraction
from assistant.response_contracts import normalize_assistant_response
from assistant.routing import classify_route_with_rules, validate_routing_plan
from imports.models import ImportJob, InstrumentProfile
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample, SampleBatch


class RoutingEvaluationCorpusTests(SimpleTestCase):
    def test_corpus_contains_at_least_one_hundred_realistic_questions(self):
        cases = list(iter_routing_evaluation_cases())

        self.assertGreaterEqual(len(cases), 100)
        self.assertTrue(any("¿" in case["message"] for case in cases))

    def test_high_confidence_rule_routes_match_the_corpus(self):
        failures = []
        for case in iter_routing_evaluation_cases():
            plan = classify_route_with_rules(case["message"])
            actual = plan.get("route") if plan else None
            if actual != case["expected_route"]:
                failures.append((case["message"], case["expected_route"], actual))

        self.assertEqual(failures, [])

    def test_vague_general_and_typo_cases_are_left_for_utility_or_llm_fallback(self):
        for message in LLM_FALLBACK_EVALUATION_CASES:
            self.assertIsNone(classify_route_with_rules(message), message)

    def test_structured_llm_plan_is_allow_listed_and_confidence_gated(self):
        plan = validate_routing_plan(
            {
                "route": "comparison",
                "intent": "compare_samples",
                "entities": [
                    {"kind": "sample", "identifier": "S-1"},
                    {"kind": "database", "identifier": "secret"},
                ],
                "filters": {"days": 30, "sql": "DROP TABLE samples"},
                "metrics": ["purity"],
                "chart_type": "dot",
                "confidence": 0.91,
            }
        )

        self.assertTrue(plan["accepted"])
        self.assertEqual(plan["entities"], [{"kind": "sample", "identifier": "S-1"}])
        self.assertEqual(plan["filters"], {"days": 30})
        self.assertNotIn("sql", plan["filters"])

    def test_response_contract_hides_unrequested_chart(self):
        result = normalize_assistant_response(
            "Which samples need QC?",
            {
                "answer": "One sample needs QC.",
                "chart": {"chartType": "bar", "data": [{"name": "S-1", "count": 1}]},
                "comparison": {"rows": [{"sample": "S-1"}]},
            },
        )

        self.assertIsNone(result["chart"])
        self.assertEqual(result["presentation"]["mode"], "table")
        self.assertFalse(result["presentation"]["chart_requested"])

    def test_response_contract_keeps_explicit_chart(self):
        result = normalize_assistant_response(
            "Plot these samples as dots",
            {"answer": "Done.", "chart": {"chartType": "dot", "data": []}},
        )

        self.assertEqual(result["chart"]["chartType"], "dot")
        self.assertEqual(result["presentation"]["mode"], "chart")

    def test_context_retains_follow_up_and_resets_on_new_topic(self):
        previous = {"comparison": {"kind": "sample", "identifiers": ["S-1", "S-2"]}}

        self.assertEqual(
            update_conversation_context("Make it a dot plot", previous, {}),
            previous,
        )
        self.assertEqual(update_conversation_context("What time is it?", previous, {}), {})


class RobustAssistantIntegrationTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="robust-user",
            password=secrets.token_urlsafe(24),
        )
        self.other_user = get_user_model().objects.create_user(username="other-user")
        self.project = Project.objects.create(code="PRJ-ALPHA", name="Alpha")
        self.project.members.add(self.user)
        self.hidden_project = Project.objects.create(code="PRJ-HIDDEN", name="Hidden")
        self.hidden_project.members.add(self.other_user)
        self.batch = SampleBatch.objects.create(code="B-ALPHA-01", project=self.project)
        self.sample_one = Sample.objects.create(
            sample_id="S-ALPHA-001",
            project=self.project,
            batch=self.batch,
            created_by=self.user,
        )
        self.sample_two = Sample.objects.create(
            sample_id="S-ALPHA-002",
            project=self.project,
            batch=self.batch,
            created_by=self.user,
        )
        Sample.objects.create(
            sample_id="S-HIDDEN-001",
            project=self.hidden_project,
            created_by=self.other_user,
        )
        self.instrument = InstrumentProfile.objects.create(
            name="Demo instrument",
            code="DEMO-INSTRUMENT",
            sample_id_column="sample_id",
        )
        self.import_job = ImportJob.objects.create(
            instrument=self.instrument,
            project=self.project,
            uploaded_by=self.user,
            status="COMPLETED",
        )
        for index, sample in enumerate([self.sample_one, self.sample_two]):
            work_item = WorkItem.objects.create(
                sample=sample,
                name="QC panel",
                work_type=f"QC_{index}",
                source_import_job=self.import_job,
                created_by=self.user,
            )
            Result.objects.create(
                work_item=work_item,
                key="purity",
                value_type=Result.VALUE_TYPE_NUMBER,
                value_number=95 - index * 10,
                qc_passed=index == 0,
                qc_status=Result.QC_APPROVED if index == 0 else Result.QC_REJECTED,
            )
        self.client.force_authenticate(self.user)

    def test_entity_resolution_corrects_unique_typo_and_filters_permissions(self):
        corrected = resolve_entities("sample", ["S-ALPXA-001"], self.user)
        hidden = resolve_entities("sample", ["S-HIDDEN-001"], self.user)

        self.assertEqual(corrected["entities"][0].sample_id, "S-ALPHA-001")
        self.assertEqual(corrected["corrected"]["S-ALPXA-001"], "S-ALPHA-001")
        self.assertEqual(hidden["entities"], [])
        self.assertEqual(hidden["missing"], ["S-HIDDEN-001"])

    def test_safe_analytics_returns_table_without_unrequested_graph(self):
        response = self.client.post(
            "/api/assistant/chat/",
            {"message": "Which instrument has the highest QC failure rate?"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["routing"]["route"], "analytics")
        self.assertEqual(response.data["presentation"]["mode"], "table")
        self.assertIsNone(response.data.get("chart"))
        self.assertEqual(response.data["comparison"]["rows"][0]["group"], "DEMO-INSTRUMENT")

    def test_safe_analytics_keeps_requested_bar_chart(self):
        response = self.client.post(
            "/api/assistant/chat/",
            {"message": "Graph QC failure rate by instrument as a bar chart"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["presentation"]["mode"], "chart")
        self.assertEqual(response.data["chart"]["chartType"], "bar")

    def test_comparison_context_supports_identifier_free_chart_follow_up(self):
        first = self.client.post(
            "/api/assistant/chat/",
            {"message": "Compare samples S-ALPHA-001 and S-ALPHA-002"},
            format="json",
        )
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data["presentation"]["mode"], "table")

        follow_up = self.client.post(
            "/api/assistant/chat/",
            {
                "message": "Make it a dot plot using purity",
                "context": first.data["context"],
            },
            format="json",
        )

        self.assertEqual(follow_up.status_code, 200, follow_up.data)
        self.assertEqual(follow_up.data["routing"]["route"], "comparison")
        self.assertEqual(follow_up.data["presentation"]["mode"], "chart")
        self.assertEqual(follow_up.data["chart"]["chartType"], "dot")

    def test_chat_logs_metadata_without_raw_message_and_accepts_feedback(self):
        message = "What needs my attention?"
        response = self.client.post(
            "/api/assistant/chat/",
            {"message": message},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        interaction = AssistantInteraction.objects.get(id=response.data["interaction_id"])
        self.assertNotEqual(interaction.message_hash, message)
        self.assertEqual(len(interaction.message_hash), 64)
        self.assertEqual(interaction.route, "attention")

        feedback_response = self.client.post(
            f"/api/assistant/interactions/{interaction.id}/feedback/",
            {"rating": "DOWN", "category": "WRONG_ROUTE", "note": "Expected QC."},
            format="json",
        )

        self.assertEqual(feedback_response.status_code, 200, feedback_response.data)
        feedback = AssistantFeedback.objects.get(interaction=interaction, user=self.user)
        self.assertEqual(feedback.rating, "DOWN")
        self.assertEqual(feedback.category, "WRONG_ROUTE")

    def test_user_cannot_submit_feedback_for_another_users_interaction(self):
        interaction = AssistantInteraction.objects.create(
            user=self.other_user,
            message_hash="0" * 64,
        )

        response = self.client.post(
            f"/api/assistant/interactions/{interaction.id}/feedback/",
            {"rating": "UP"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
