import json
from importlib import import_module
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase
from assistant.llm import classify_route_with_llm, build_route_classifier_prompt
from assistant.provider_tools import COMMAND_TOOLS, DIRECT_TOOLS, dispatch_tool, validate_tool_plan
from assistant.models import AssistantAction
from pipelines.models import AnalysisDefinition, ProcedureDefinition, PipelineTemplate
from results.models import Result, WorkItem
from . import test_comparisons, test_lab_reviews


def plan(tool, **args):
    return {"route": "tool", "tool": tool, "arguments": args, "confidence": .98}


SETTINGS = dict(OPENLIMS_ASSISTANT_LLM_ENABLED=True, OPENLIMS_ASSISTANT_LLM_ROUTING_ENABLED=True,
                OPENAI_API_KEY="test-key", OLLAMA_BASE_URL="http://ollama:11434", OLLAMA_MODEL="test",
                OPENLIMS_ENFORCE_FEATURE_FLAGS=False)


@override_settings(**SETTINGS)
class ProviderContractTests(SimpleTestCase):
    def test_every_assistant_router_has_a_connection_or_explicit_internal_role(self):
        import ast
        from pathlib import Path
        routers = {node.name for path in Path(__file__).parents[1].glob("*.py")
                   for node in ast.parse(path.read_text()).body
                   if isinstance(node, ast.FunctionDef) and node.name.startswith("route_")}
        connected = {entry[1] for entry in COMMAND_TOOLS.values()}
        # These are orchestration/clarification or wrappers whose individual
        # features are registered as direct tools above, not executable actions.
        internal = {"route_assistant_message", "route_assistant_clarification", "route_conversation_utility",
                    "route_lab_helpers", "route_lab_reviews", "route_lab_collaboration"}
        self.assertEqual(routers - connected - internal, set())

    def test_both_providers_expose_every_registered_feature(self):
        prompt = build_route_classifier_prompt("Help me")
        for provider in ["openai", "ollama"]:
            for tool in {*DIRECT_TOOLS, *COMMAND_TOOLS}:
                with self.subTest(provider=provider, tool=tool), override_settings(OPENLIMS_ASSISTANT_LLM_PROVIDER=provider), patch(f"assistant.llm.call_{provider}", return_value=json.dumps(plan(tool))) as transport:
                    result = classify_route_with_llm("Help me")
                    self.assertEqual(result["tool"], tool)
                    self.assertEqual(result["provider"], provider)
                    self.assertIn(f"- {tool}:", prompt)
                    transport.assert_called_once()

    def test_untrusted_model_payloads_fail_closed(self):
        bad = [plan("execute_sql", command="DROP TABLE samples"), plan("handover", source=["peter"]),
               plan("handover", source="peter", user_id=1), plan("reagent_plan", count=True),
               plan("reagent_plan", count=0), plan("handover", source="x\x00"),
               plan("handover", source="x" * 1001), plan("handover", source="\ud800")]
        bad += [{**plan("handover"), "confidence": value} for value in [False, float("nan"), float("inf"), .1, "1"]]
        for value in bad:
            with self.subTest(value=repr(value)):
                self.assertIsNone(validate_tool_plan(value))

    def test_catalog_names_resolve_to_real_functions(self):
        for tool, (module, name, _) in {**COMMAND_TOOLS, **DIRECT_TOOLS}.items():
            with self.subTest(tool=tool):
                self.assertTrue(callable(getattr(import_module(f"assistant.{module}"), name)))

    def test_provider_failure_and_invalid_json_do_not_dispatch(self):
        for provider in ["openai", "ollama"]:
            for raw in ["not json", json.dumps(plan("execute_sql")), json.dumps({**plan("handover"), "confidence": .1})]:
                with self.subTest(provider=provider, raw=raw), override_settings(OPENLIMS_ASSISTANT_LLM_PROVIDER=provider), patch(f"assistant.llm.call_{provider}", return_value=raw):
                    self.assertIsNone(classify_route_with_llm("Help me"))
            with override_settings(OPENLIMS_ASSISTANT_LLM_PROVIDER=provider), patch(f"assistant.llm.call_{provider}", side_effect=TimeoutError("offline")):
                self.assertIsNone(classify_route_with_llm("Help me"))


@override_settings(**SETTINGS)
class ProviderIntegrationTests(APITestCase):
    setUp = test_comparisons.AssistantComparisonTests.setUp
    chat = test_comparisons.AssistantComparisonTests.chat
    experiment = test_lab_reviews.LabReviewTests.experiment
    lot = test_lab_reviews.LabReviewTests.lot

    def via_provider(self, provider, payload, message="Could you handle the request I described in my own words?"):
        with override_settings(OPENLIMS_ASSISTANT_LLM_PROVIDER=provider), patch(f"assistant.llm.call_{provider}", return_value=json.dumps(payload)) as call:
            reply = self.chat(message)
            self.assertEqual(reply.status_code, 200, reply.data)
            call.assert_called_once()
            self.assertEqual(reply.data["routing"]["source"], f"{provider}_fallback")
            return reply.data

    def test_all_new_features_through_both_provider_transports(self):
        self.tech.is_superuser = True
        self.tech.save()
        analysis = AnalysisDefinition.objects.create(code="EX", name="Extraction")
        ProcedureDefinition.objects.create(code="EX", name="Extraction", version="1", analysis=analysis)
        left, right = self.experiment(self.tech, "Run A"), self.experiment(self.tech, "Run B")
        self.lot()
        messages = {
            "sample_history": "Tell me the story of S-100",
            "similar_experiments": "Locate earlier experiments resembling Run",
            "reagent_plan": "Estimate material requirements for 5 specimens with EX version 1",
            "project_update": "Write a team progress note about ALPHA",
            "quarantine_impact": "If LOT-12 were quarantined, what would be impacted?",
            "data_quality": "Look for suspicious records under ALPHA",
            "workflow_draft": "Sketch an ordered pipeline based on EX@1",
            "handover": "Help eduardo take over eduardo's unfinished work",
            "compare_runs": f"Explain how {left.public_id} differs from {right.public_id}",
        }
        cases = [
            (plan("sample_history", sample="S-100"), "history"),
            (plan("similar_experiments", topic="Run"), "links"),
            (plan("reagent_plan", count=5, procedure="EX", version="1"), "answer"),
            (plan("project_update", project="ALPHA"), "draft"),
            (plan("quarantine_impact", lot="LOT-12"), "impact_preview"),
            (plan("data_quality", project="ALPHA"), "comparison"),
            (plan("workflow_draft", procedures="EX@1"), "draft"),
            (plan("handover", source="eduardo", recipient="eduardo"), "draft"),
            (plan("compare_runs", left=str(left.public_id), right=str(right.public_id)), "comparison"),
        ]
        for provider in ["openai", "ollama"]:
            for payload, key in cases:
                with self.subTest(provider=provider, tool=payload["tool"]):
                    data = self.via_provider(provider, payload, messages[payload["tool"]])
                    self.assertIn(key, data)
                    self.assertEqual(data["interpretation"]["tool"], payload["tool"])
                    self.assertNotIn("pending_action", data)
        self.assertEqual(PipelineTemplate.objects.count(), 0)
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_every_command_adapter_passes_authenticated_user_and_context(self):
        self.tech.is_superuser = True
        self.tech.save()
        for tool, (module, name, _) in COMMAND_TOOLS.items():
            with self.subTest(tool=tool), patch(f"assistant.{module}.{name}", autospec=True, return_value={"answer": "Evidence"}) as handler:
                data = dispatch_tool(plan(tool, command="example"), self.tech, {"sample_code": "S-100"})
                self.assertEqual(data["answer"], "Evidence")
                handler.assert_called_once()
                if tool != "migration":
                    self.assertIn(self.tech, handler.call_args.args)

    def test_permission_checks_and_missing_arguments_apply_to_both_providers(self):
        private = self.experiment(self.outsider, "Secret run")
        for provider in ["openai", "ollama"]:
            for payload, absent in [
                (plan("sample_history", sample="S-PRIVATE"), "history"),
                (plan("data_quality", project="PRIVATE"), "comparison"),
                (plan("workflow_draft", procedures="EX@1"), "draft"),
                (plan("compare_runs", left=str(private.public_id), right="other"), "comparison"),
                (plan("migration", command="Show failed migration jobs"), "migration"),
            ]:
                with self.subTest(provider=provider, tool=payload["tool"]):
                    data = self.via_provider(provider, payload)
                    self.assertNotIn(absent, data)
                    self.assertNotIn("Secret run", str(data))
            data = self.via_provider(provider, plan("handover", recipient="eduardo"))
            self.assertEqual(data["clarification"]["fields"], ["source"])

    def test_model_can_only_propose_writes_and_cannot_confirm(self):
        for provider in ["openai", "ollama"]:
            before = WorkItem.objects.count()
            data = self.via_provider(provider, plan("work_items", command="Create sequencing work for samples in batch B-100"))
            self.assertIn("pending_action", data)
            self.assertEqual(WorkItem.objects.count(), before)
            action = AssistantAction.objects.get(confirmation_token=data["pending_action"]["confirmation_token"])
            self.assertEqual(action.requested_by, self.tech)
            self.assertIsNone(validate_tool_plan(plan("confirm", token=str(action.confirmation_token))))

    def test_viewer_cannot_propose_guided_result_write(self):
        self.alpha.members.add(self.outsider)
        self.client.force_authenticate(self.outsider)
        work = self.samples[0].work_items.first()
        before = Result.objects.count()
        data = self.via_provider("ollama", plan("guided_actions", command=f"Add result glucose = 43 to work item {work.pk}"))
        self.assertNotIn("pending_action", data)
        self.assertEqual(Result.objects.count(), before)
