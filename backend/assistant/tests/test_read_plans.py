import copy
import io
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.answer_quality import check_answer, evaluate_cases
from assistant.models import AssistantAction, SOPDocument
from assistant.read_plans import handle_read_plan, parse_read_plan, validate_read_plan
from assistant.routing import validate_routing_plan
from assistant.sop_operations import search_sops
from imports.models import ImportJob, InstrumentProfile
from notebook.models import Experiment, Notebook
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample


def step(operation, **arguments):
    return {"operation": operation, "arguments": arguments}


def plan(*steps):
    return {"route": "read_plan", "steps": list(steps), "confidence": .98}


class ReadPlanValidationTests(SimpleTestCase):
    def test_complete_typed_plan_is_validated_by_the_shared_provider_contract(self):
        payload = plan(step("sample_evidence", sample="QUALITY-1"), step("sop_search", question="Show the SOP for storage"))
        self.assertEqual(validate_routing_plan(payload)["steps"], payload["steps"])

    def test_malformed_or_executable_steps_are_rejected_before_any_database_read(self):
        valid = plan(step("sample_summary", sample="QUALITY-1"), step("sample_history", sample="QUALITY-1"))
        invalid = [None, [], {**valid, "steps": []}, {**valid, "steps": valid["steps"][:1]},
                   {**valid, "steps": valid["steps"] * 3}, {**valid, "user_id": 1},
                   {**valid, "steps": [step("execute_sql", sql="select *"), valid["steps"][1]]},
                   {**valid, "steps": [step("confirmed_action", command="Approve result R-1"), valid["steps"][1]]}]
        invalid += [{**valid, "confidence": value} for value in [True, "1", float("nan"), float("inf"), .1]]
        for value in [True, [], "", "x\x00", "\ud800", "x" * 129]:
            changed = copy.deepcopy(valid)
            changed["steps"][0]["arguments"]["sample"] = value
            invalid.append(changed)
        for args in [{}, {"sample": "QUALITY-1", "user_id": 1}, {"sample": "QUALITY-1", "command": "delete"}]:
            changed = copy.deepcopy(valid)
            changed["steps"][0]["arguments"] = args
            invalid.append(changed)
        for payload in invalid:
            with self.subTest(payload=repr(payload)):
                self.assertIsNone(validate_read_plan(payload))

    def test_parser_requires_every_clause_and_preserves_quoted_identifiers(self):
        self.assertEqual(parse_read_plan('Compare runs "Run A and show results" and "Run B"; show the SOP for storage')["steps"][0]["arguments"]["left"], "Run A and show results")
        for message in ["Explain sample QUALITY-1 and show the evidence from yesterday",
                        "Explain sample QUALITY-1; calculate an unsupported statistic",
                        "Explain sample QUALITY-1 and approve its results"]:
            with self.subTest(message=message):
                self.assertIsNone(parse_read_plan(message))

    def test_invented_targets_and_sop_questions_fail_without_collecting_evidence(self):
        for payload in [plan(step("sample_summary", sample="SECRET"), step("sample_history", sample="QUALITY-1")),
                        plan(step("sample_summary", sample="QUALITY-1"), step("sop_search", question="Secret process"))]:
            with patch("assistant.read_plans._read") as read:
                reply = handle_read_plan("Explain sample QUALITY-1; show the SOP for storage", None, payload)
                self.assertTrue(reply["clarification"])
                read.assert_not_called()


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
class ReadPlanAnswerTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="quality-tech")
        cls.user.groups.add(Group.objects.get_or_create(name="tech")[0])
        cls.other = get_user_model().objects.create_user(username="quality-outsider")
        cls.project = Project.objects.create(code="QUALITY", name="Quality project")
        cls.project.members.add(cls.user)
        cls.private = Project.objects.create(code="PRIVATE-QUALITY", name="Secret project")
        cls.private.members.add(cls.other)
        cls.sample = Sample.objects.create(sample_id="QUALITY-1", project=cls.project, created_by=cls.user)
        cls.second = Sample.objects.create(sample_id="QUALITY-2", project=cls.project, created_by=cls.user)
        cls.hidden = Sample.objects.create(sample_id="PRIVATE-1", project=cls.private, created_by=cls.other)
        cls.work = WorkItem.objects.create(sample=cls.sample, name="Concentration review", assigned_to=cls.user)
        cls.result = Result.objects.create(work_item=cls.work, key="concentration", value_type=Result.VALUE_TYPE_NUMBER,
                                           value_number=45, unit="ng/uL", reference_min=10, reference_max=20,
                                           qc_passed=False, qc_status=Result.QC_APPROVED, qc_failure_reason="Control drift")
        hidden_work = WorkItem.objects.create(sample=cls.hidden, name="SECRET-WORK")
        Result.objects.create(work_item=hidden_work, key="SECRET-ANALYTE", value_string="SECRET-VALUE")
        cls.sop = SOPDocument.objects.create(document_code="SOP-CONCENTRATION", title="Concentration review",
                                             version="3", section="4.2", approved=True, uploaded_by=cls.user,
                                             content="General introductory text. " * 80 + "Concentration failures require checking the calibration control before repeating measurement.")
        cls.left = Experiment.objects.create(notebook=Notebook.objects.create(owner=cls.user, name="Run notes"),
                                            created_by=cls.user, title="Run A")
        cls.right = Experiment.objects.create(notebook=cls.left.notebook, created_by=cls.user, title="Run B")

    def setUp(self):
        self.client.force_authenticate(self.user)

    def chat(self, message, context=None):
        result = self.client.post("/api/assistant/chat/", {"message": message, "context": context or {}}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        return result.data

    def test_three_reads_combine_evidence_history_and_a_relevant_sop_passage(self):
        with patch("assistant.llm.call_openai") as llm:
            reply = self.chat("Show evidence for sample QUALITY-1; show its history; show the SOP for concentration")
        self.assertEqual([s["operation"] for s in reply["read_plan"]["steps"]], ["sample_evidence", "sample_history", "sop_search"])
        self.assertFalse(reply["read_plan"]["partial"])
        self.assertIn("45.0 ng/uL", reply["answer"])
        self.assertIn("QC check: failed; review: APPROVED", reply["answer"])
        self.assertIn("calibration control", reply["answer"])
        self.assertLess(len(reply["citations"][-1]["excerpt"]), len(self.sop.content) // 2)
        self.assertIn("calibration control", reply["citations"][-1]["excerpt"])
        self.assertIn("not a single database snapshot", reply["read_plan"]["scope"])
        self.assertEqual({c["kind"] for c in reply["citations"]}, {"sample", "result", "sop"})
        self.assertIn(f"/samples/{self.sample.pk}#result-{self.result.pk}", [c["url"] for c in reply["citations"]])
        self.assertEqual(AssistantAction.objects.count(), 0)
        llm.assert_not_called()

    def test_run_comparison_and_sample_failures_keep_tables_and_separate_scope(self):
        reply = self.chat('Compare runs "Run A" and "Run B"; show failed QC results for sample QUALITY-1; show the SOP for concentration')
        self.assertEqual(len(reply["read_plan"]["steps"]), 3)
        self.assertTrue(reply["read_plan"]["steps"][0]["comparison"]["rows"])
        self.assertIn("1 of 1 results", reply["answer"])
        self.assertNotIn("pending_action", reply)

    def test_missing_or_inaccessible_sample_produces_partial_answer_without_private_evidence(self):
        for code in ["PRIVATE-1", "DOES-NOT-EXIST"]:
            reply = self.chat(f"Explain sample QUALITY-1; show evidence for sample {code}")
            self.assertEqual([s["status"] for s in reply["read_plan"]["steps"]], ["completed", "unavailable"])
            self.assertTrue(reply["read_plan"]["partial"])
            for secret in ["SECRET-WORK", "SECRET-ANALYTE", "SECRET-VALUE", "Secret project"]:
                self.assertNotIn(secret, str(reply))
            self.assertNotIn("sample_id", reply["context"])

    def test_unsupported_condition_or_write_never_runs_a_partial_plan_or_a_single_provider_tool(self):
        for message in ["Explain sample QUALITY-1 and approve its results",
                        "Explain sample QUALITY-1; show its history except yesterday",
                        "Explain sample QUALITY-1; show its history; show the evidence; show its history; show the evidence"]:
            with patch("assistant.read_plans._read") as read, patch("assistant.views.classify_route_with_llm", return_value={
                "route": "tool", "tool": "samples", "arguments": {"command": "Archive sample QUALITY-1"}, "confidence": .99,
            }):
                reply = self.chat(message)
                self.assertTrue(reply["clarification"])
                self.assertNotIn("pending_action", reply)
                read.assert_not_called()
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_no_matching_sop_is_reported_as_unavailable_without_fabrication(self):
        reply = self.chat("Explain sample QUALITY-1; show the SOP for zirconium")
        self.assertTrue(reply["read_plan"]["partial"])
        self.assertIn("does not contain an answer", reply["answer"])
        self.assertNotIn("sop", {c["kind"] for c in reply["citations"]})

    def test_multiple_samples_clear_ambiguous_followup_context(self):
        reply = self.chat("Explain sample QUALITY-1; explain sample QUALITY-2")
        self.assertNotIn("sample_id", reply["context"])
        followup = self.chat("Show the evidence", reply["context"])
        self.assertTrue(followup["clarification"])

    def test_permissions_and_live_values_are_checked_again_on_each_request(self):
        message = "Show evidence for sample QUALITY-1; show its history"
        first = self.chat(message)
        Result.objects.filter(pk=self.result.pk).update(value_number=17)
        fresh = self.chat(message, first["context"])
        self.assertIn("17.0 ng/uL", fresh["answer"])
        self.project.members.remove(self.user)
        denied = self.chat(message, fresh["context"])
        self.assertTrue(denied["read_plan"]["partial"])
        self.assertNotIn("17.0 ng/uL", denied["answer"])
        self.assertEqual(denied["citations"], [])

    @override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=True, OPENLIMS_ASSISTANT_LLM_ROUTING_ENABLED=True,
                       OPENAI_API_KEY="test-key", OLLAMA_BASE_URL="http://ollama:11434", OLLAMA_MODEL="test")
    def test_both_providers_can_interpret_a_complete_typed_read_plan(self):
        payload = plan(step("sample_evidence", sample="QUALITY-1"), step("sop_search", question="which SOP covers concentration"))
        message = "Explain the recorded issues for sample QUALITY-1 and show which SOP covers concentration"
        for provider in ["openai", "ollama"]:
            with self.subTest(provider=provider), override_settings(OPENLIMS_ASSISTANT_LLM_PROVIDER=provider), patch(
                f"assistant.llm.call_{provider}", return_value=json.dumps(payload)
            ) as transport:
                reply = self.chat(message)
                self.assertEqual(len(reply["read_plan"]["steps"]), 2)
                self.assertEqual(reply["routing"]["source"], f"{provider}_fallback")
                transport.assert_called_once()

    def test_failure_worklist_preserves_zero_false_and_display_limits(self):
        Result.objects.filter(pk=self.result.pk).update(value_number=0)
        for i in range(22):
            Result.objects.create(work_item=self.work, key=f"failed-{i}", qc_passed=False,
                                  value_type=Result.VALUE_TYPE_BOOLEAN, value_boolean=False)
        reply = self.chat("Show failed QC results for sample QUALITY-1; show its history")
        self.assertIn("20 of 23 results", reply["answer"])
        self.assertIn("False", reply["answer"])
        self.assertEqual(len([c for c in reply["citations"] if c["kind"] == "result"]), 20)

    def test_full_text_search_matches_word_forms_and_respects_all_document_permissions(self):
        documents = []
        for code, extra in [("ARCHIVED", {"status": "ARCHIVED"}), ("DRAFT", {"approved": False}),
                            ("FUTURE", {"effective_at": timezone.now() + timedelta(days=1)}),
                            ("PROJECT", {"project": self.private}), ("GROUP", {})]:
            fields = {"document_code": code, "title": "Concentration storage", "version": "1", "section": "1",
                      "content": "SECRET-PASSAGE", "approved": True, **extra}
            document = SOPDocument.objects.create(**fields)
            documents.append(document)
        documents[-1].allowed_groups.add(Group.objects.get_or_create(name="restricted-quality")[0])
        response = search_sops("What does the SOP say about concentrations?", self.user)
        self.assertEqual(response["sop_search"]["method"], "full_text")
        self.assertEqual([c["document_code"] for c in response["citations"]], ["SOP-CONCENTRATION"])
        self.assertNotIn("SECRET-PASSAGE", str(response))

    def test_result_citations_include_linked_instrument_run_provenance(self):
        instrument = InstrumentProfile.objects.create(code="QUALITY-DEVICE", name="Quality device")
        job = ImportJob.objects.create(instrument=instrument, run_id="RUN-45", project=self.project)
        self.work.source_import_job = job
        self.work.save()
        reply = self.chat("Show evidence for sample QUALITY-1; show its history")
        citation = next(c for c in reply["citations"] if c["kind"] == "import_job")
        self.assertEqual(citation["label"], "QUALITY-DEVICE · RUN-45")
        self.assertEqual(citation["url"], f"/imports/{job.pk}")

    def test_sop_source_link_rechecks_permissions_and_displays_complete_section(self):
        response = self.client.get(f"/api/sop-documents/{self.sop.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["content"], self.sop.content)
        self.sop.allowed_groups.add(Group.objects.get_or_create(name="restricted-quality")[0])
        self.assertEqual(self.client.get(f"/api/sop-documents/{self.sop.pk}/").status_code, 404)

    def test_quality_benchmark_checks_real_facts_sources_unknowns_and_denied_reads(self):
        cases = [
            {"name": "QC evidence and SOP", "message": "Show evidence for sample QUALITY-1; show the SOP for concentration",
             "expected": {"contains": ["45.0 ng/uL", "QC check: failed; review: APPROVED", "calibration control", "do not establish the scientific root cause"],
                          "excludes": ["SECRET-VALUE"], "citation_kinds": ["result", "sop"], "operations": ["sample_evidence", "sop_search"], "partial": False}},
            {"name": "Unknown QC", "message": "Explain sample QUALITY-2",
             "expected": {"contains": ["QC outcome is unknown", "does not establish release readiness"], "citation_kinds": ["sample"]}},
            {"name": "Denied read", "message": "Explain sample QUALITY-1; show evidence for sample PRIVATE-1",
             "expected": {"contains": ["not accessible"], "excludes": ["SECRET-VALUE", "SECRET-ANALYTE"], "partial": True}},
            {"name": "Missing SOP", "message": "Explain sample QUALITY-1; show the SOP for zirconium",
             "expected": {"contains": ["does not contain an answer"], "partial": True}},
            {"name": "Project scope", "message": "Summarize project QUALITY; list samples in project QUALITY",
             "expected": {"contains": ["2 accessible samples", "2 of 2 accessible samples"],
                          "excludes": ["PRIVATE-1", "SECRET-VALUE"], "citation_kinds": ["project"],
                          "operations": ["project_summary", "project_samples"]}},
            {"name": "Run comparison", "message": 'Compare runs "Run A" and "Run B"; show the SOP for concentration',
             "expected": {"contains": ["no causal explanation is inferred", "calibration control"],
                          "citation_kinds": ["experiment", "sop"], "operations": ["compare_runs", "sop_search"]}},
            {"name": "Mixed write", "message": "Explain sample QUALITY-1 and approve its results",
             "expected": {"contains": ["not run any part"], "operations": [], "clarification": True}},
            {"name": "Unsupported filter", "message": "Explain sample QUALITY-1; show its history except yesterday",
             "expected": {"contains": ["not run any part"], "excludes": ["45.0 ng/uL"], "operations": [], "clarification": True}},
        ]
        report = evaluate_cases(cases, self.user)
        self.assertEqual(report["passed"], len(cases), report)
        wrong = check_answer({"answer": "Everything is approved", "citations": []}, cases[0]["expected"])
        self.assertFalse(wrong["required_facts"])
        self.assertFalse(wrong["sources"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            path.write_text(json.dumps(cases))
            output = io.StringIO()
            call_command("evaluate_assistant_answers", cases=str(path), user=self.user.username, stdout=output)
            self.assertEqual(json.loads(output.getvalue())["passed"], len(cases))
            cases[0]["expected"]["contains"] = ["Invented fact"]
            path.write_text(json.dumps(cases))
            with self.assertRaises(CommandError):
                call_command("evaluate_assistant_answers", cases=str(path), user=self.user.username, stdout=io.StringIO())

    def test_quality_command_rejects_mutations_without_creating_actions(self):
        with self.assertRaises(ValueError):
            evaluate_cases([{"name": "write", "message": "Archive sample QUALITY-1", "expected": {"contains": ["archived"]}}], self.user)
        self.assertEqual(AssistantAction.objects.count(), 0)
