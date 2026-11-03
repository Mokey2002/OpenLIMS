import copy
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from assistant.answer_quality import evaluate_cases
from assistant.models import AssistantAction, AssistantConversation
from assistant.read_plan_memory import KEY, recall, remember
from assistant.read_plans import handle_read_plan, validate_read_plan
from assistant.result_statistics import _rate_difference
from assistant.comparison_explanations import _rate_line, window_scope
from imports.models import ImportJob, InstrumentProfile
from results.models import Result, WorkItem
from . import test_read_plans as baseline
from . import test_assistant_v062 as previous

NOW = previous.NOW


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False, TIME_ZONE="America/Los_Angeles")
class AssistantV064Tests(APITestCase):
    setUpTestData = classmethod(baseline.ReadPlanAnswerTests.setUpTestData.__func__)
    chat = baseline.ReadPlanAnswerTests.chat
    facts = previous.AssistantV062Tests.facts

    def setUp(self):
        self.client.force_authenticate(self.user)
        Result.objects.filter(work_item__sample__in=[self.sample, self.second]).delete()
        self.clock = patch("django.utils.timezone.now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def measurement(self, value, passed, *, comparison=False, key="concentration", unit="ng/uL", sample=None, analysis="DNA", operator=None, job=None):
        work = WorkItem.objects.create(sample=sample or self.sample, status=WorkItem.STATUS_COMPLETED, name="Measured concentration",
                                       analysis_code=analysis, work_type="ASSAY", source_import_job=job)
        result = Result.objects.create(work_item=work, key=key, value_type=Result.VALUE_TYPE_NUMBER, value_number=value,
                                      unit=unit, qc_passed=passed, entered_by=operator)
        Result.objects.filter(pk=result.pk).update(created_at=NOW if comparison else NOW - timedelta(days=1))
        return result

    def seed_cohorts(self):
        for value, passed in [(10, False), (20, False), (30, True), (40, True), (None, None)]:
            self.measurement(value, passed)
        for passed in [False, True, True, True, True]:
            self.measurement(10, passed, comparison=True, unit="ug/mL")

    def compare(self, suffix="", qc=""):
        reply = self.chat(f"Show {qc + ' ' if qc else ''}results for project QUALITY yesterday{(' ' + suffix) if suffix else ''}")
        return self.chat("Compare those with this week", reply["context"])

    def test_main_answer_explains_actual_denominators_measurements_and_aggregate_scope(self):
        self.seed_cohorts()
        reply = self.compare()
        overview = reply["answer_overview"]["text"]
        for text in ["50.00% (2/4 failed/assessed)", "20.00% (1/5 failed/assessed)", "increase of 30.00 percentage points",
                     "Unassessed results: selected 1; comparison 0", "selected 25", "comparison 10", "difference 15", "ng/µL", "statistical significance"]:
            self.assertIn(text, overview)
        self.assertFalse(self.facts(reply)["comparison_scope"]["overlap"])
        self.assertIn("repeated measurements of the same sample", overview)
        self.assertEqual(self.facts(reply)["statistics"]["numeric"][0]["selected_n"], 4)
        aggregate = next(c for c in reply["citations"] if c["kind"] == "project")
        self.assertEqual(aggregate["url"], f"/projects/{self.project.pk}")
        self.assertIn("all currently accessible matching records", aggregate["scope"])
        self.assertIn("not just the displayed result examples", aggregate["scope"])
        source_urls = {source["url"] for source in reply["citations"]}
        self.assertTrue(all(set(finding["sources"]) <= source_urls for finding in reply["answer_overview"]["findings"]))
        json.dumps(reply, allow_nan=False)
        self.assertFalse(AssistantAction.objects.exists())

    def test_combined_comparisons_keep_distinct_aggregate_source_scopes(self):
        self.seed_cohorts()
        plan = {"route": "read_plan", "confidence": 1, "steps": [
            {"operation": "project_results_compare", "arguments": {"project": "QUALITY"}, "filters": {"period": "yesterday", "compare_period": "this_week", "qc": status}}
            for status in ["failed", "passed"]]}
        reply = handle_read_plan("Compare failed results for project QUALITY yesterday with this week; compare passed results for project QUALITY yesterday with this week", self.user, plan)
        sources = [source for source in reply["citations"] if source["kind"] == "project"]
        self.assertEqual(len(sources), 2)
        self.assertTrue(any("QC: failed" in source["scope"] for source in sources))
        self.assertTrue(any("QC: passed" in source["scope"] for source in sources))

    def test_each_focus_is_signed_preserves_filters_and_changes_main_answer(self):
        self.seed_cohorts()
        compared = self.compare("excluding key control", qc="failed")
        rate = self.chat("Explain failure-rate differences", compared["context"])
        self.assertEqual(rate["read_plan_spec"]["steps"][0]["focus"], "qc_rates")
        text = rate["answer_overview"]["text"]
        self.assertIn("50.00% (2/4", text)
        self.assertNotIn("Largest count difference", text)
        self.assertNotIn("Mean comparison", text)
        self.assertEqual(self.facts(rate)["filters"]["qc"], "failed")
        self.assertEqual(self.facts(rate)["filters"]["exclude_keys"], ["control"])
        self.assertEqual(rate["context"]["result_query_context"]["focus"], "qc_rates")
        numeric = self.chat("Explain measurement differences", rate["context"])
        text = numeric["answer_overview"]["text"]
        self.assertIn("selected 15", text)
        self.assertIn("comparison 10", text)
        self.assertIn("difference 5", text)
        self.assertNotIn("Largest QC failure-rate", text)
        counts = self.chat("Explain count differences", numeric["context"])
        self.assertIn("Largest count difference", counts["answer_overview"]["text"])
        self.assertNotIn("Mean comparison", counts["answer_overview"]["text"])
        full = self.chat("Show comparison overview", counts["context"])
        self.assertIn("Largest QC failure-rate", full["answer_overview"]["text"])
        self.assertIn("Mean comparison", full["answer_overview"]["text"])
        self.assertEqual(recall(full["context"], self.user)["plan"]["steps"][0]["focus"], "overview")

    def test_focus_retains_instrument_operator_and_key_filters_in_rate_denominators(self):
        instrument = InstrumentProfile.objects.create(code="SEQ-64", name="Comparison sequencer")
        job = ImportJob.objects.create(instrument=instrument, run_id="RUN-64")
        for comparison in [False, True]:
            self.measurement(20, False, comparison=comparison, operator=self.user, job=job)
            self.measurement(30, True, comparison=comparison, operator=self.user, job=job)
            self.measurement(900, False, comparison=comparison)  # excluded by instrument/operator
        start = self.chat("Show failed results for project QUALITY yesterday from instrument SEQ-64 by operator quality-tech only key concentration")
        compared = self.chat("Compare those with this week", start["context"])
        rate = self.chat("Show QC failure rates", compared["context"])
        self.assertIn("50.00% (1/2", rate["answer_overview"]["text"])
        self.assertEqual(self.facts(rate)["statistics"]["rates"][0]["selected"]["total"], 2)
        self.assertNotIn("900", rate["answer"])

    def test_invalid_focus_extensions_do_not_drop_new_conditions_or_execute_a_read(self):
        self.seed_cohorts()
        reply = self.compare()
        for message in ["Explain numeric differences excluding key concentration", "Explain failure-rate differences for a different project",
                        "Explain failure rates excluding key concentration", "Show comparison overview only passed"]:
            with self.subTest(message=message), patch("assistant.read_plans._read") as read:
                rejected = self.chat(message, reply["context"])
                self.assertTrue(rejected["clarification"])
                self.assertNotIn("read_plan", rejected)
                self.assertEqual(rejected["context"][KEY], reply["context"][KEY])
                read.assert_not_called()
        start = self.chat("Show results for project QUALITY yesterday")
        rejected = self.chat("Explain failure-rate differences", start["context"])
        self.assertTrue(rejected["clarification"])
        self.assertIn("Choose one", rejected["answer"])

    def test_multiple_comparisons_require_a_target_before_focusing(self):
        plan = validate_read_plan({"route": "read_plan", "confidence": 1, "steps": [
            {"operation": "project_results_compare", "arguments": {"project": "QUALITY"}, "filters": {"compare_period": "this_week"}},
            {"operation": "sample_results_compare", "arguments": {"sample": "QUALITY-1"}, "filters": {"compare_period": "this_week"}}]})
        context = {KEY: remember(plan, [], self.user)}
        with patch("assistant.read_plans._read") as read:
            reply = self.chat("Explain failure-rate differences", context)
        self.assertTrue(reply["clarification"])
        self.assertNotIn("read_plan", reply)
        read.assert_not_called()

    def test_rate_differences_use_unrounded_proportions(self):
        for comparison, statuses in [(False, [False, True, True]), (True, [False, True, True, True, True, True])]:
            for passed in statuses:
                self.measurement(10, passed, comparison=comparison)
        reply = self.compare()
        row = self.facts(reply)["statistics"]["rates"][0]
        self.assertEqual(row["selected_rate"], 33.33)
        self.assertEqual(row["comparison_rate"], 16.67)
        self.assertEqual(row["difference_pp"], 16.67)  # subtracting rounded rates gives 16.66
        self.assertIn("increase of 16.67", reply["answer_overview"]["text"])

    def test_largest_qc_change_is_ranked_before_the_forty_group_display_limit(self):
        for index in range(41):
            for comparison in [False, True]:
                self.measurement(10, True, key=f"A-{index:02d}", comparison=comparison)
        self.measurement(10, False, key="Z-important")
        self.measurement(10, True, key="Z-important", comparison=True)
        reply = self.compare()
        statistics = self.facts(reply)["statistics"]
        self.assertEqual(statistics["rate_groups"], 42)
        self.assertEqual(len(statistics["rates"]), 40)
        self.assertIn("Z-important", statistics["rates"][0]["group"])
        self.assertIn("Z-important", reply["answer_overview"]["text"])
        self.assertEqual(statistics["rates"][0]["difference_pp"], 100)
        self.assertIn("42 paired numeric groups", reply["answer_overview"]["text"])

    def test_mean_differences_keep_precision_before_display_rounding_and_are_json_finite(self):
        self.measurement(1.00000004, True)
        self.measurement(1.00000003, True, comparison=True)
        self.measurement(1e308, True, key="extreme", unit="M")
        self.measurement(-1e308, True, key="extreme", unit="M", comparison=True)
        reply = self.compare()
        rows = self.facts(reply)["statistics"]["numeric"]
        row = next(row for row in rows if row["group"].endswith(" / concentration"))
        self.assertEqual(row["selected_mean"], row["comparison_mean"])
        self.assertGreater(Decimal(row["mean_difference"]), 0)
        self.assertEqual(row["direction"], "increase")
        extreme = next(row for row in rows if row["group"].endswith(" / extreme"))
        self.assertEqual(Decimal(extreme["mean_difference"]), Decimal("2e308"))
        self.assertIn("before display rounding", reply["answer_overview"]["text"])
        json.dumps(reply, allow_nan=False)

    def test_missing_assessments_units_and_one_sided_cohorts_never_become_zero_changes(self):
        self.measurement(10, None, key="unassessed")
        self.measurement(20, None, key="unassessed", comparison=True)
        self.measurement(10, None, key="no-unit", unit="")
        self.measurement(20, None, key="no-unit", unit="", comparison=True)
        self.measurement(10, None, key="incompatible", unit="ng/uL")
        self.measurement(20, None, key="incompatible", unit="mM", comparison=True)
        self.measurement(10, True, key="one-sided")
        reply = self.compare("excluding key unassessed")
        rate = self.chat("Explain failure-rate differences", reply["context"])
        self.assertIn("no group has assessed checks in both windows", rate["answer_overview"]["text"])
        self.assertIn("Missing rates are not zero", rate["answer_overview"]["text"])
        numeric = self.chat("Explain numeric differences", rate["context"])
        self.assertIn("difference is unavailable", numeric["answer_overview"]["text"])
        self.assertNotIn("Mean comparison", numeric["answer_overview"]["text"])
        self.assertTrue(all(row["mean_difference"] is None for row in self.facts(numeric)["statistics"]["numeric"]))

    def test_exact_zero_negative_differences_and_window_overlap_are_explained(self):
        for value, comparison in [(10, False), (10, True)]:
            self.measurement(value, False, comparison=comparison)
        reply = self.compare()
        self.assertIn("unchanged (0.00 percentage points)", reply["answer_overview"]["text"])
        self.assertEqual(self.facts(reply)["statistics"]["numeric"][0]["mean_difference"], "0")
        Result.objects.filter(created_at__lt=NOW).update(value_number=5, qc_passed=True)
        reply = self.compare()
        self.assertIn("decrease of 100.00 percentage points", reply["answer_overview"]["text"])
        self.assertEqual(Decimal(self.facts(reply)["statistics"]["numeric"][0]["mean_difference"]), -5)
        overlapping = self.chat("Compare those with last week", reply["context"])
        self.assertTrue(self.facts(overlapping)["comparison_scope"]["overlap"])
        self.assertIn("not independent cohorts", overlapping["answer_overview"]["text"])
        self.assertIn("different numbers of calendar days", overlapping["answer_overview"]["text"])

    def test_saved_focus_refreshes_values_and_rechecks_access_and_cross_user_context(self):
        self.seed_cohorts()
        reply = self.chat("Explain numeric differences", self.compare()["context"])
        saved = self.client.post("/api/assistant/conversations/", {"name": "Mean investigation", "turn_tokens": [reply["save_turn_token"]]}, format="json")
        self.assertEqual(saved.status_code, 201, saved.data)
        stored = AssistantConversation.objects.get(pk=saved.data["id"])
        self.assertEqual(stored.turns[0]["plan"]["steps"][0]["focus"], "numeric")
        self.assertNotIn("mean_difference", json.dumps(stored.turns))
        Result.objects.filter(created_at__lt=NOW, work_item__sample=self.sample).update(value_number=60)
        opened = self.client.get(f"/api/assistant/conversations/{stored.pk}/")
        self.assertIn("selected 60", opened.data["history"][1]["reply"]["answer_overview"]["text"])
        self.client.force_authenticate(self.other)
        denied = self.chat("Explain failure-rate differences", reply["context"])
        self.assertNotIn("read_plan", denied)
        self.assertNotIn("2/4", str(denied))
        self.client.force_authenticate(self.user)
        self.project.members.remove(self.user)
        denied = self.chat("Explain failure-rate differences", reply["context"])
        self.assertTrue(denied["read_plan"]["partial"])
        self.assertEqual(denied["citations"], [])
        self.assertNotIn("2/4", str(denied))

    def test_clear_comparison_drops_presentation_focus_and_detail_return_restores_it(self):
        self.seed_cohorts()
        reply = self.chat("Explain numeric differences", self.compare()["context"])
        detail = self.chat("Explain the first result", reply["context"])
        restored = self.chat("Back to comparison", detail["context"])
        self.assertEqual(restored["read_plan_spec"]["steps"][0]["focus"], "numeric")
        cleared = self.chat("Clear comparison filter", restored["context"])
        self.assertEqual(cleared["read_plan_spec"]["steps"][0]["operation"], "project_results")
        self.assertNotIn("focus", cleared["read_plan_spec"]["steps"][0])

    def test_quality_evaluation_asserts_actual_displayed_differences_and_computed_metrics(self):
        self.seed_cohorts()
        report = evaluate_cases([{"name": "Rate explanation", "turns": [
            {"message": "Show failed results for project QUALITY yesterday"}, {"message": "Compare those with this week"},
            {"message": "Explain failure-rate differences"}], "expected": {
                "overview_contains": ["50.00% (2/4", "20.00% (1/5", "30.00 percentage points"],
                "overview_excludes": ["Largest count difference"], "facts": {"statistics.rates.0.difference_pp": 30,
                "comparison_explanation.focus": "qc_rates"}, "citation_kinds": ["project"]}}], self.user)
        self.assertEqual(report["passed"], 1, report)


class ComparisonContractTests(SimpleTestCase):
    def test_focus_is_allowlisted_and_only_accepted_on_period_comparisons(self):
        payload = {"route": "read_plan", "confidence": .99, "steps": [{"operation": "project_results_compare", "arguments": {"project": "ALPHA"}, "filters": {"compare_period": "last_week"}, "focus": "numeric"}]}
        self.assertEqual(validate_read_plan(payload)["steps"][0]["focus"], "numeric")
        for focus in [[], True, "execute_sql", "", None]:
            changed = copy.deepcopy(payload)
            changed["steps"][0]["focus"] = focus
            self.assertIsNone(validate_read_plan(changed))
        changed = copy.deepcopy(payload)
        changed["steps"][0].update(operation="project_results", filters={})
        self.assertIsNone(validate_read_plan(changed))
        changed = copy.deepcopy(payload)
        changed["steps"][0]["operation"] = []
        self.assertIsNone(validate_read_plan(changed))

    def test_small_real_rate_change_is_not_described_as_unchanged_after_rounding(self):
        left = {"assessed": 50000, "failed": 1, "failure_rate": 0}
        right = {"assessed": 50000, "failed": 0, "failure_rate": 0}
        difference = _rate_difference(left, right)
        self.assertGreater(difference, 0)
        line = _rate_line({"selected": left, "comparison": right, "direction": "increase", "difference_pp": 0, "group": "DNA"})
        self.assertIn("increase of less than 0.01 percentage points", line)
        self.assertNotIn("unchanged", line)

    def test_adjacent_windows_do_not_overlap_and_open_bounds_are_disclosed(self):
        adjacent = window_scope({"created_from": "2026-11-01", "created_before": "2026-11-02"}, {"created_from": "2026-11-02", "created_before": "2026-11-03"})
        self.assertFalse(adjacent["overlap"])
        self.assertFalse(adjacent["unequal_duration"])
        opened = window_scope({}, {"created_from": "2026-11-02", "created_before": "2026-11-03"})
        self.assertTrue(opened["overlap"])
        self.assertIsNone(opened["selected_days"])
