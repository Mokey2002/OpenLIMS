import json
from datetime import timedelta
from unittest.mock import patch

from django.core import signing
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from assistant.answer_quality import check_answer, evaluate_cases, validate_cases
from assistant.models import AssistantAction, AssistantConversation, SOPDocument
from assistant.read_plan_memory import KEY, MAX_TOKEN, SALT, recall
from assistant.read_plans import handle_read_plan, validate_read_plan
from assistant.result_filter_language import parse_filters
from assistant.sop_embeddings import chunks, _document_vectors
from assistant.sop_operations import search_sops
from imports.models import InstrumentProfile, ImportJob
from results.models import Result, WorkItem
from . import test_assistant_v062 as previous

NOW = previous.NOW


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False, TIME_ZONE="America/Los_Angeles")
class AssistantV063Tests(APITestCase):
    setUpTestData = classmethod(previous.AssistantV062Tests.setUpTestData.__func__)
    setUp = previous.AssistantV062Tests.setUp
    chat = previous.AssistantV062Tests.chat
    facts = previous.AssistantV062Tests.facts

    def test_result_explanation_displays_values_ranges_reasons_review_and_provenance(self):
        instrument = InstrumentProfile.objects.create(code="SEQ-1", name="Sequencer")
        job = ImportJob.objects.create(instrument=instrument, run_id="RUN-42", project=self.project)
        self.work.source_import_job = job
        self.work.save()
        reply = self.chat("Show results for project QUALITY yesterday only key concentration")
        detail = self.chat("Explain the first result", reply["context"])
        overview = detail["answer_overview"]["text"]
        for text in ["45.0 ng/uL", "10.0 to 20.0", "above the configured maximum", "QC check: failed", "review: APPROVED", "Control drift", "SEQ-1", "RUN-42"]:
            self.assertIn(text, overview)
        self.assertIn("not independent proof", overview)
        self.assertEqual(detail["answer_overview"]["findings"][0]["sources"], [f"/samples/{self.sample.pk}#result-{self.result.pk}"])
        Result.objects.filter(pk=self.result.pk).update(value_number=float("nan"), qc_failure_reason="", reference_min=30, reference_max=20)
        refreshed = self.chat("Explain the first result", reply["context"])
        self.assertIn("invalid numeric value", refreshed["answer_overview"]["text"])
        self.assertIn("limits are invalid", refreshed["answer_overview"]["text"])
        self.assertIn("No QC failure reason", refreshed["answer_overview"]["text"])
        json.dumps(refreshed, allow_nan=False)

    def test_investigation_back_and_target_correction_keep_filters_and_recheck_records(self):
        start = self.chat("Show failed QC results for project QUALITY yesterday excluding key second")
        compared = self.chat("Compare those with last week", start["context"])
        detail = self.chat("Explain the first result", compared["context"])
        self.assertTrue(detail["context"]["investigation_navigation"]["comparison"])
        Result.objects.filter(pk=self.result.pk).update(value_number=47)
        returned = self.chat("Back to comparison", detail["context"])
        self.assertIn("47.0", returned["answer"])
        self.assertEqual(returned["read_plan_spec"]["steps"], compared["read_plan_spec"]["steps"])
        corrected = self.chat("Apply the same filters to sample QUALITY-2", detail["context"])
        self.assertEqual(corrected["read_plan_spec"]["steps"][0]["operation"], "sample_results_compare")
        self.assertEqual(self.facts(corrected)["filters"]["exclude_keys"], ["second"])
        self.assertEqual(self.facts(corrected)["filters"]["qc"], "failed")
        denied = self.chat("Apply same filters to project PRIVATE-QUALITY", returned["context"])
        self.assertTrue(denied["read_plan"]["partial"])
        self.assertNotIn("SECRET-VALUE", str(denied))
        self.project.members.remove(self.user)
        denied = self.chat("Back to comparison", detail["context"])
        self.assertTrue(denied["read_plan"]["partial"])
        self.assertNotIn("47.0", str(denied))
        self.assertFalse(AssistantAction.objects.exists())

    def test_filters_support_weekdays_instruments_operators_edits_and_fail_closed(self):
        instrument = InstrumentProfile.objects.create(code="SEQ-1", name="Sequencer")
        job = ImportJob.objects.create(instrument=instrument, run_id="RUN-42")
        self.work.source_import_job = job
        self.work.save()
        Result.objects.filter(pk=self.result.pk).update(entered_by=self.user)
        initial = self.chat("Show results for project QUALITY since Friday from instrument SEQ-1 by operator quality-tech")
        facts = self.facts(initial)
        self.assertEqual(facts["total"], 1)
        self.assertEqual(facts["filters"]["created_from"], "2026-10-30")
        self.assertEqual(facts["filters"]["created_before"], "2026-11-03")
        self.assertEqual(initial["context"]["result_query_context"]["filters"]["operator"], "quality-tech")
        broadened = self.chat("Clear operator filter", initial["context"])
        self.assertEqual(self.facts(broadened)["total"], 3)
        self.assertEqual(self.facts(broadened)["filters"]["instrument"], "SEQ-1")
        edited = self.chat("Only yesterday", broadened["context"])
        self.assertEqual(self.facts(edited)["total"], 2)
        self.assertNotIn("created_from", edited["read_plan_spec"]["steps"][0]["filters"])
        for message in ["Only instrument SEQ-1 with no missing values", "Since Friday except yesterday", "Since 2026-02-30", "From 2026-11-03 until 2026-11-01"]:
            with self.subTest(message=message):
                rejected = self.chat(message, initial["context"])
                self.assertTrue(rejected["clarification"])
                self.assertNotIn("read_plan", rejected)
                self.assertNotIn("45.0", str(rejected))
                self.assertEqual(rejected["context"][KEY], initial["context"][KEY])

    def test_memory_is_bounded_signed_and_does_not_retain_result_values(self):
        reply = self.chat("Show results for project QUALITY yesterday")
        for index in range(8):
            reply = self.chat("Only passed" if index % 2 else "Only failed", reply["context"])
        state = recall(reply["context"], self.user)
        self.assertLessEqual(len(state["trail"]), 4)
        self.assertLessEqual(len(reply["context"][KEY]), MAX_TOKEN)
        self.assertNotIn("45.0", str(state))
        bad = {**state, "trail": [{"route": "execute_sql"}]}
        self.assertIsNone(recall({KEY: signing.dumps(bad, salt=SALT)}, self.user))
        self.client.force_authenticate(self.other)
        denied = self.chat("Back to results", reply["context"])
        self.assertNotIn("45.0", str(denied))

    def test_saved_drilldown_restores_parent_by_stable_identity_after_project_rename(self):
        initial = self.chat("Show results for project QUALITY yesterday")
        compared = self.chat("Compare those with last week", initial["context"])
        detail = self.chat("Explain the first result", compared["context"])
        saved = self.client.post("/api/assistant/conversations/", {"name": "Investigation", "turn_tokens": [detail["save_turn_token"]]}, format="json")
        self.assertEqual(saved.status_code, 201, saved.data)
        stored = AssistantConversation.objects.get(pk=saved.data["id"])
        self.assertNotIn("value_number", json.dumps(stored.turns))
        self.assertNotIn("Control drift", json.dumps(stored.turns))
        self.project.code = "RENAMED"
        self.project.save()
        reopened = self.client.get(f"/api/assistant/conversations/{stored.pk}/")
        returned = self.chat("Back to comparison", reopened.data["context"])
        self.assertEqual(self.facts(returned)["target"], "RENAMED")
        self.assertEqual(self.facts(returned)["total"], 2)

    def add_numeric(self, key, value, unit, *, when=None, passed=None, analysis="DNA", work_type="ASSAY"):
        work = WorkItem.objects.create(sample=self.sample, name="Measurement", status=WorkItem.STATUS_COMPLETED,
                                       analysis_code=analysis, work_type=work_type)
        result = Result.objects.create(work_item=work, key=key, value_type=Result.VALUE_TYPE_NUMBER,
                                      value_number=value, unit=unit, qc_passed=passed)
        Result.objects.filter(pk=result.pk).update(created_at=when or NOW - timedelta(days=1))
        return result

    def test_statistics_keep_qc_denominators_units_and_analysis_scopes_correct(self):
        self.add_numeric("dna", 10, "ng/uL", passed=False)
        self.add_numeric("dna", 20, "ug/mL", passed=True)
        self.add_numeric("dna", 20000, "ng/mL", passed=None)
        self.add_numeric("dna", 7, "mM", passed=True)
        self.add_numeric("dna", 9, "ng/uL", passed=False, analysis="RNA")
        self.add_numeric("dna", float("nan"), "ng/uL", passed=None)
        self.add_numeric("dna", None, "ng/uL", passed=None)
        self.add_numeric("dna", 5, "ng/uL", when=NOW - timedelta(days=6), passed=True)
        initial = self.chat("Show results for project QUALITY yesterday only key dna")
        compared = self.chat("Compare those with last week", initial["context"])
        statistics = self.facts(compared)["statistics"]
        rate = next(row for row in statistics["rates"] if row["group"] == "DNA / ASSAY / dna")
        self.assertEqual(rate["selected"], {"total": 6, "assessed": 3, "failed": 1, "unassessed": 3, "failure_rate": 33.33})
        # Last week includes yesterday in this fixed Monday clock: disclose overlap.
        self.assertEqual(rate["comparison"]["assessed"], 4)
        numeric = next(row for row in statistics["numeric"] if row["group"] == "DNA / ASSAY / dna" and row["unit"] == "ng/µL")
        self.assertEqual(numeric["selected_n"], 3)
        self.assertAlmostEqual(float(numeric["selected_mean"]), 50 / 3, places=5)
        self.assertEqual(float(numeric["selected_min"]), 10)
        self.assertEqual(float(numeric["selected_max"]), 20)
        self.assertEqual(len(statistics["numeric"]), 3)
        failed = self.chat("Only failed", compared["context"])
        rate_after = next(row for row in self.facts(failed)["statistics"]["rates"] if row["group"] == rate["group"])
        self.assertEqual(rate_after["selected"], rate["selected"])
        numeric_after = next(row for row in self.facts(failed)["statistics"]["numeric"] if row["group"] == rate["group"])
        self.assertEqual(numeric_after["selected_n"], 1)
        self.assertEqual(float(numeric_after["selected_mean"]), 10)
        json.dumps(compared, allow_nan=False)

    def test_zero_denominator_does_not_become_zero_percent_and_huge_finite_values_work(self):
        self.add_numeric("unassessed", 1e308, "M")
        self.add_numeric("unassessed", 1e308, "M")
        self.add_numeric("unassessed", 10, "m")
        self.add_numeric("unassessed", float("inf"), "M")
        self.add_numeric("unassessed", -float("inf"), "M")
        self.add_numeric("unassessed", 50, "")
        reply = self.chat("Show results for project QUALITY yesterday only key unassessed")
        reply = self.chat("Compare those with last week", reply["context"])
        stats = self.facts(reply)["statistics"]
        self.assertIsNone(stats["rates"][0]["selected_rate"])
        self.assertEqual(len(stats["numeric"]), 3)
        missing_unit = next(row for row in stats["numeric"] if row["unit"] == "(unit not recorded)")
        self.assertEqual(missing_unit["selected_n"], 1)
        self.assertIsNone(missing_unit["selected_mean"])
        numeric = next(row for row in stats["numeric"] if row["unit"] == "M")
        self.assertEqual(numeric["selected_n"], 2)
        self.assertEqual(float(numeric["selected_mean"]), 1e308)
        json.dumps(reply, allow_nan=False)

    def test_forced_model_evaluation_requires_provider_calls_and_checks_computed_facts(self):
        payload = {"route": "read_plan", "confidence": .99, "steps": [{"operation": "project_results", "arguments": {"project": "QUALITY"}, "filters": {"period": "yesterday"}}]}
        cases = [{"name": "Real routing contract", "message": "Show results for project QUALITY yesterday", "expected": {"counts": {"total": 2}, "facts": {"filters.created_from": "2026-11-01"}}}]
        with override_settings(OPENLIMS_ASSISTANT_LLM_PROVIDER="openai", OPENLIMS_ASSISTANT_LLM_ENABLED=True, OPENLIMS_ASSISTANT_LLM_ROUTING_ENABLED=True, OPENAI_API_KEY="test-key"), patch("assistant.llm.call_openai", return_value=json.dumps(payload)) as call:
            report = evaluate_cases(cases, self.user, live_provider=True, force_provider=True, require_provider=True)
            self.assertEqual(report["passed"], 1, report)
            self.assertEqual(report["provider_requests"], 1)
            call.assert_called_once()
        with override_settings(OPENLIMS_ASSISTANT_LLM_PROVIDER="openai", OPENLIMS_ASSISTANT_LLM_ENABLED=True, OPENAI_API_KEY="test-key"), patch("assistant.llm.call_openai", return_value="invalid JSON"):
            report = evaluate_cases(cases, self.user, live_provider=True, force_provider=True, require_provider=True)
            self.assertEqual(report["passed"], 0)
            self.assertFalse(report["results"][0]["checks"]["provider_used"])
        with self.assertRaises(ValueError):
            evaluate_cases(cases, self.user, force_provider=True)
        self.assertFalse(check_answer({}, {"facts": {"statistics.rates.0.selected.assessed": 3}})["computed_facts"])

    def test_forced_provider_followups_must_match_signed_server_continuation_for_both_providers(self):
        first = {"route": "read_plan", "confidence": .99, "steps": [{"operation": "project_results", "arguments": {"project": "QUALITY"}, "filters": {"period": "yesterday"}}]}
        second = {"route": "read_plan", "confidence": .99, "steps": [{"operation": "project_results", "arguments": {"project": "QUALITY"}, "filters": {"period": "yesterday", "exclude_keys": ["second"]}}]}
        cases = [{"name": "Natural correction", "turns": [{"message": "Show results for project QUALITY yesterday"}, {"message": "Excluding key second"}],
                  "expected": {"counts": {"total": 1}, "result_ids": [self.result.pk], "overview_contains": ["1 matching results"]}}]
        for provider in ["openai", "ollama"]:
            with self.subTest(provider=provider), override_settings(OPENLIMS_ASSISTANT_LLM_PROVIDER=provider, OPENLIMS_ASSISTANT_LLM_ENABLED=True,
                    OPENLIMS_ASSISTANT_LLM_ROUTING_ENABLED=True, OPENAI_API_KEY="test-key"), patch(
                    f"assistant.llm.call_{provider}", side_effect=[json.dumps(first), json.dumps(second)]) as call:
                report = evaluate_cases(cases, self.user, live_provider=True, force_provider=True, require_provider=True)
                self.assertEqual(report["passed"], 1, report)
                self.assertEqual(report["provider_requests"], 2)
                self.assertIn("verified", call.call_args[0][0].lower())
                self.assertIn("QUALITY", call.call_args[0][0])

    def test_long_quality_dialogue_keeps_latest_scope_and_has_per_turn_expectations(self):
        turns = [{"message": "Show results for project QUALITY yesterday"}]
        turns += [{"message": "Only failed" if index % 2 == 0 else "Only all QC results", "expected": {"counts": {"total": 2}}} for index in range(29)]
        report = evaluate_cases([{"name": "Thirty-turn investigation", "turns": turns, "expected": {"counts": {"total": 2}}}], self.user)
        self.assertEqual(report["passed"], 1, report)


class FilterGrammarTests(SimpleTestCase):
    def test_malformed_provider_plans_never_read_or_raise_in_filter_clarification(self):
        for payload in [[1], {"steps": True}, {"steps": [{"operation": []}]}, {"steps": [False]}]:
            with self.subTest(payload=payload), patch("assistant.read_plans._read") as read:
                reply = handle_read_plan("Show results for project ALPHA; show results for sample S-1", None, payload)
                self.assertTrue(reply["clarification"])
                read.assert_not_called()

    def test_filters_reject_unsupported_or_conflicting_conditions(self):
        for text in ["yesterday with value > 10", "only key DNA only key RNA", "from instrument A and", "sql=1"]:
            self.assertIsNone(parse_filters(text))
        self.assertEqual(parse_filters("from instrument A by operator Bob+lab only key MixedCase"), {"instrument": "A", "operator": "Bob+lab", "keys": ["MixedCase"]})
        payload = {"route": "read_plan", "confidence": 1, "steps": [{"operation": "project_results", "arguments": {"project": "ALPHA"}, "filters": {"operator": "x;DROP TABLE"}}]}
        self.assertIsNone(validate_read_plan(payload))

    def test_quality_case_schema_handles_long_dialogues_and_finite_fact_expectations(self):
        case = {"name": "Long", "turns": [{"message": "Only yesterday"}] * 30, "expected": {"facts": {"total": 1}}}
        validate_cases([case])
        for value in [float("nan"), {}, []]:
            case["expected"]["facts"]["total"] = value
            with self.assertRaises(ValueError):
                validate_cases([case])


class FakeArray(list):
    def tolist(self):
        return list(self)


class FakeEncoder:
    def __init__(self):
        self.texts = []

    def encode(self, texts, **kwargs):
        self.texts.extend(texts)
        return FakeArray([[1., 0.] if any(term in text.casefold() for term in ["photometer", "optical detector", "secret"]) else [0., 1.] for text in texts])


@override_settings(OPENLIMS_SOP_EMBEDDING_MODEL_PATH="/models/test-offline", OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
class OfflineSOPTests(APITestCase):
    setUpTestData = classmethod(previous.AssistantV062Tests.setUpTestData.__func__)

    def setUp(self):
        _document_vectors.cache_clear()
        self.encoder = FakeEncoder()
        self.model = patch("assistant.sop_embeddings._model", return_value=self.encoder)
        self.model.start()
        self.addCleanup(self.model.stop)
        self.addCleanup(_document_vectors.cache_clear)

    def test_unfamiliar_paraphrase_retrieves_chunk_and_never_embeds_inaccessible_text(self):
        target = SOPDocument.objects.create(document_code="OPTICAL", title="Detector maintenance", version="1", section="1", approved=True,
            content="Routine generic introduction. " * 80 + "Clean the optical detector following the validated optical detector procedure. " * 10)
        private = SOPDocument.objects.create(document_code="PRIVATE", title="SECRET optical detector", version="1", section="1", approved=True, project=self.private, content="SECRET INSTRUCTION")
        pending = SOPDocument.objects.create(document_code="DRAFT", title="Photometer", version="1", section="1", approved=False, content="SECRET DRAFT")
        reply = search_sops("Which SOP covers servicing the photometer?", self.user)
        self.assertEqual(reply["sop_search"]["semantic_mode"], "local-embeddings-1")
        self.assertEqual(reply["citations"][0]["id"], target.pk)
        self.assertIn("optical detector", reply["citations"][0]["excerpt"])
        self.assertGreater(reply["citations"][0]["matched_chunk"]["start"], 0)
        self.assertNotIn("SECRET", " ".join(self.encoder.texts))
        # Cached vectors must not bypass changed access or content.
        target.project = self.private
        target.save()
        denied = search_sops("Which SOP covers servicing the photometer?", self.user)
        self.assertNotIn(target.pk, [citation["id"] for citation in denied["citations"]])
        self.assertNotIn("SECRET", str(denied))

    def test_unavailable_or_malformed_model_falls_back_to_approved_lexical_search(self):
        self.encoder.encode = lambda *args, **kwargs: FakeArray([[float("nan")]])
        reply = search_sops("Show the SOP for concentration", self.user)
        self.assertTrue(reply["sop_search"]["embedding_fallback"])
        self.assertEqual(reply["citations"][0]["id"], self.sop.pk)
        self.assertEqual(reply["sop_search"]["semantic_mode"], "lab-concepts-1")

    def test_semantic_matching_keeps_opposite_concentration_instructions_out(self):
        low = SOPDocument.objects.create(document_code="LOW", title="Low concentration", version="1", section="1", approved=True, content="Follow the validated measurement procedure.")
        high = SOPDocument.objects.create(document_code="HIGH", title="High concentration", version="1", section="1", approved=True, content="Follow the validated measurement procedure.")
        reply = search_sops("Which SOP covers DNA too dilute?", self.user)
        ids = [citation["id"] for citation in reply["citations"]]
        self.assertIn(low.pk, ids)
        self.assertNotIn(high.pk, ids)

    def test_chunk_bounds_and_edited_content_invalidation(self):
        content = " ".join(f"word{index}" for index in range(4000))
        pieces = chunks(content)
        self.assertEqual(len(pieces), 32)
        self.assertLess(pieces[-1]["end"], len(content))
        self.assertEqual(pieces[0]["text"].split()[-20:], pieces[1]["text"].split()[:20])
        target = SOPDocument.objects.create(document_code="EDIT", title="Maintenance", version="1", section="1", approved=True, content="Clean the optical detector.")
        self.assertTrue(search_sops("Which SOP covers a photometer?", self.user)["citations"])
        target.content = "General procedure without the matching text."
        target.save()
        reply = search_sops("Which SOP covers a photometer?", self.user)
        self.assertNotIn(target.pk, [citation["id"] for citation in reply["citations"]])

    def test_bounded_semantic_no_match_does_not_claim_no_answer_exists_in_whole_library(self):
        SOPDocument.objects.create(document_code="LONG", title="Routine", version="1", section="1", approved=True, content="Generic routine text. " * 2000)
        with patch("assistant.sop_embeddings.DOCUMENT_LIMIT", 1):
            reply = search_sops("Which SOP covers a photometer?", self.user)
        self.assertEqual(reply["citations"], [])
        self.assertTrue(reply["sop_search"]["candidate_limit_reached"])
        self.assertTrue(reply["sop_search"]["section_chunk_limit_reached"])
        self.assertIn("inspected", reply["answer"])
        self.assertIn("Older sections", reply["answer"])
        self.assertNotIn("does not contain an answer", reply["answer"])
