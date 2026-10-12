from unittest.mock import patch
from datetime import timedelta
from django.utils import timezone

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from assistant.models import AssistantAction
from assistant.project_workflows import route_project_workflows
from events.models import Event
from pipelines.models import AnalysisDefinition, ProcedureDefinition, PipelineTemplate, PipelineTemplateStep
from pipelines.services import start_pipeline
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample


@override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=False)
class ProjectWorkflowTests(APITestCase):
    def setUp(self):
        self.tech = get_user_model().objects.create_user("project-tech")
        self.tech.groups.add(Group.objects.get_or_create(name="tech")[0])
        self.viewer = get_user_model().objects.create_user("project-viewer")
        self.viewer.groups.add(Group.objects.get_or_create(name="viewer")[0])
        self.project = Project.objects.create(code="DEMO-360", name="Demo project")
        self.project.members.add(self.tech, self.viewer)
        analysis = AnalysisDefinition.objects.create(code="EXTRACT", name="Extraction", required_fields=[{"key": "concentration", "value_type": "NUMBER", "required": True}])
        procedure = ProcedureDefinition.objects.create(code="EXTRACT", name="Extraction", version="1", analysis=analysis)
        self.template = PipelineTemplate.objects.create(code="FLOW", name="Workflow")
        PipelineTemplateStep.objects.create(template=self.template, position=1, procedure=procedure, requires_qc=True)
        PipelineTemplateStep.objects.create(template=self.template, position=2, procedure=procedure, dependency_positions=[1])
        self.sample, self.run, self.work = self.make_sample("SAMPLE-001")
        self.client.force_authenticate(self.tech)

    def make_sample(self, code, project=None):
        sample = Sample.objects.create(sample_id=code, project=project or self.project, created_by=self.tech)
        run = start_pipeline(sample=sample, template=self.template, actor=self.tech)
        return sample, run, run.steps.get(position=1).work_item

    def chat(self, message, context=None):
        response = self.client.post("/api/assistant/chat/", {"message": message, "context": context or {}}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def query(self, kind="blocked", context=None):
        return self.chat(f"Which samples in project DEMO-360 are {kind}?", context)

    def rows(self, data):
        return data["project_workflows"]["rows"]

    def test_project_blockers_have_exact_reasons_links_and_no_mutations(self):
        self.make_sample("SAMPLE-002")
        before = Event.objects.count()
        data = self.chat("Which samples in DEMO-360 are blocked, and why?")
        self.assertEqual(len(self.rows(data)), 2)
        reasons = self.rows(data)[0]["reasons"]
        self.assertEqual({r["kind"] for r in reasons}, {"missing", "dependency"})
        self.assertIn("concentration", data["answer"])
        self.assertEqual(data["links"][0]["url"], f"/samples/{self.sample.pk}")
        self.assertTrue(data["project_workflows"]["read_only"])
        self.assertFalse(AssistantAction.objects.exists())
        self.assertEqual(Event.objects.count(), before)

    def test_missing_then_ready_then_qc_followups_reread_records(self):
        data = self.query("missing results")
        self.assertEqual(len(self.rows(data)), 1)
        Result.objects.create(work_item=self.work, key="concentration", value_type="NUMBER", value_number=43)
        ready = self.chat("Which are ready?", data["context"])
        self.assertEqual(self.rows(ready)[0]["reasons"][0]["kind"], "ready")
        self.assertEqual(self.rows(self.query("missing results")), [])
        self.work.status = "COMPLETED"
        self.work.save()
        qc = self.chat("And QC?", ready["context"])
        self.assertEqual(self.rows(qc)[0]["reasons"][0]["qc_status"], "PENDING_REVIEW")
        self.assertEqual(self.rows(self.query("ready")), [])

    def test_qc_approval_is_not_inferred_from_work_completion(self):
        Result.objects.create(work_item=self.work, key="concentration", value_type="NUMBER", value_number=43)
        self.work.status = "COMPLETED"
        self.work.save()
        self.assertIn("PENDING_REVIEW", self.query("needing QC")["answer"])
        self.work.qc_status = "APPROVED"
        self.work.save()
        self.assertEqual(self.rows(self.query("needing QC")), [])

    def test_rejected_qc_and_failed_step_include_recorded_reason(self):
        Result.objects.create(work_item=self.work, key="concentration", value_type="NUMBER", value_number=43)
        self.work.status = "COMPLETED"
        self.work.qc_status = "REJECTED"
        self.work.review_note = "Contamination found"
        self.work.save()
        data = self.query()
        self.assertIn("Contamination found", data["answer"])
        self.assertIn("REJECTED", self.query("needing QC")["answer"])

    def test_viewer_access_linked_samples_and_private_project(self):
        private = Project.objects.create(code="SECRET", name="Secret project")
        private.members.add(self.tech)
        linked, _, _ = self.make_sample("LINKED-001", private)
        linked.linked_projects.add(self.project)
        self.make_sample("SECRET-001", private)
        self.client.force_authenticate(self.viewer)
        data = self.query()
        self.assertEqual({r["sample_code"] for r in self.rows(data)}, {"SAMPLE-001", "LINKED-001"})
        denied = self.chat("Which samples in project SECRET are blocked?")
        self.assertNotIn("project_workflows", denied)
        self.assertEqual(denied["links"], [])
        self.assertFalse(AssistantAction.objects.exists())

    def test_revocation_and_forged_context_clear_without_disclosure(self):
        data = self.query()
        self.project.members.remove(self.tech)
        for message in ("Which are ready?", "Next page"):
            denied = self.chat(message, data["context"])
            self.assertNotIn("project_workflows", denied)
            self.assertEqual(denied["context"], {})
            self.assertEqual(denied["links"], [])
        forged = {"project_workflows": {"project_code": "DEMO-360", "filter": "all", "after": 0, "has_more": True}}
        self.assertNotIn("project_workflows", self.chat("Next page", forged))

    def test_spanish_exact_codes_missing_project_and_ambiguity(self):
        data = self.chat("¿Qué muestras en proyecto DEMO-360 están bloqueadas y por qué?")
        self.assertIn("Campos obligatorios", data["answer"])
        self.assertTrue(self.chat("Which samples are blocked?")["clarification"]["required"])
        self.assertTrue(self.chat("Which samples in project DEMO-360 and project SECRET are blocked?")["clarification"]["required"])
        self.assertNotIn("project_workflows", self.chat("Which samples in project DEMO-36 are blocked?"))

    @patch("assistant.project_workflows.PAGE_SIZE", 1)
    def test_pagination_has_no_duplicates_and_keeps_filter(self):
        second, _, _ = self.make_sample("SAMPLE-002")
        first = self.query()
        self.assertTrue(first["project_workflows"]["has_more"])
        self.assertEqual(first["project_workflows"]["checked_on_page"], 1)
        self.assertEqual(first["project_workflows"]["accessible_sample_count"], 2)
        data = self.chat("Next page", first["context"])
        self.assertEqual([r["sample_id"] for r in self.rows(data)], [second.pk])
        self.assertFalse(data["project_workflows"]["has_more"])
        self.assertNotIn("project_workflows", self.chat("Next page", data["context"]))

    @patch("assistant.project_workflows.PAGE_SIZE", 1)
    def test_pagination_skips_nonmatches_to_find_useful_results(self):
        Result.objects.create(work_item=self.work, key="concentration", value_type="NUMBER", value_number=43)
        second, _, _ = self.make_sample("SAMPLE-002")
        first = self.query("missing results")
        self.assertEqual(self.rows(first)[0]["sample_id"], second.pk)
        self.assertEqual(first["project_workflows"]["checked_on_page"], 2)
        self.assertFalse(first["project_workflows"]["has_more"])
        self.assertEqual(first["project_workflows"]["matching_sample_count"], 1)

    def test_project_switch_and_reset_clear_selection(self):
        other = Project.objects.create(code="OTHER", name="Other project")
        other.members.add(self.tech)
        sample, _, _ = self.make_sample("OTHER-001", other)
        initial = self.query()
        switched = self.chat("Which samples in project OTHER are blocked?", initial["context"])
        self.assertEqual([r["sample_id"] for r in self.rows(switched)], [sample.pk])
        reset = self.chat("Start over", switched["context"])
        self.assertEqual(reset["context"], {})

    def test_invalid_cursor_fails_closed(self):
        for cursor in ("bad", -1, True, 10**30):
            with self.subTest(cursor=cursor):
                context = {"project_workflows": {"project_code": "DEMO-360", "filter": "blocked", "after": cursor, "has_more": True}}
                self.assertNotIn("project_workflows", self.chat("Next page", context))

    def test_historical_runs_final_samples_and_no_pipeline(self):
        self.run.status = "COMPLETED"
        self.run.save()
        final, _, _ = self.make_sample("FINAL-001")
        final.status = "ARCHIVED"
        final.save()
        no_pipeline = Sample.objects.create(sample_id="EMPTY-001", project=self.project)
        self.assertEqual(self.rows(self.query()), [])
        all_rows = self.rows(self.chat("Show samples in project DEMO-360 workflow overview"))
        self.assertEqual({r["sample_id"] for r in all_rows}, {self.sample.pk, no_pipeline.pk})
        self.assertTrue(all(not r["has_active_pipeline"] for r in all_rows))

    def test_single_sample_and_write_routes_are_not_swallowed(self):
        context = self.query()["context"]
        for message in ("Which samples are in QC?", "What next for sample SAMPLE-001?", "Explain pipeline for sample SAMPLE-001", "Assign step 1 for sample SAMPLE-001 to maria", "Approve QC for samples in project DEMO-360"):
            with self.subTest(message=message):
                self.assertIsNone(route_project_workflows(message, self.tech, context))

    def test_queries_are_batched_as_sample_count_grows(self):
        with CaptureQueriesContext(connection) as first:
            route_project_workflows("Which samples in project DEMO-360 are blocked?", self.tech)
        for i in range(8):
            self.make_sample(f"BATCH-{i}")
        with CaptureQueriesContext(connection) as many:
            data = route_project_workflows("Which samples in project DEMO-360 are blocked?", self.tech)
        self.assertEqual(len(data["project_workflows"]["rows"]), 9)
        self.assertLessEqual(len(many), len(first) + 1)
        self.assertLessEqual(len(many), 10)

    @override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=True, OPENAI_API_KEY="test-only")
    def test_external_provider_is_not_used(self):
        with patch("assistant.llm.OpenAI") as provider:
            data = self.query()
        provider.assert_not_called()
        self.assertTrue(data["project_workflows"]["read_only"])

    def test_failed_qc_excludes_pending_reviews(self):
        for index, status in enumerate(("PENDING_REVIEW", "REJECTED", "RERUN_REQUIRED")):
            sample, _, work = self.make_sample(f"QC-{index}")
            Result.objects.create(work_item=work, key="concentration", value_type="NUMBER", value_number=43)
            work.status = "COMPLETED"
            work.qc_status = status
            work.save()
        data = self.query("failed QC")
        self.assertEqual({row["sample_code"] for row in self.rows(data)}, {"QC-1", "QC-2"})
        self.assertEqual(data["project_workflows"]["filter"], "qc_failed")
        self.assertTrue(all(r["kind"] == "qc" for row in self.rows(data) for r in row["reasons"]))

    def test_overdue_and_unassigned_followups_refresh_current_work(self):
        self.work.due_at = timezone.now() - timedelta(days=1)
        self.work.save()
        overdue = self.query("overdue")
        self.assertEqual(len(self.rows(overdue)), 1)
        reason = self.rows(overdue)[0]["reasons"][0]
        self.assertTrue(reason["due_at"])
        self.assertIn("due date", reason["next_action"])
        self.work.due_at = timezone.now() + timedelta(days=1)
        self.work.save()
        self.assertEqual(self.rows(self.chat("Refresh results", overdue["context"])), [])
        unassigned = self.chat("Only unassigned", overdue["context"])
        self.assertEqual(len(self.rows(unassigned)), 1)
        self.work.assigned_to = self.tech
        self.work.save()
        self.assertEqual(self.rows(self.chat("Refresh results", unassigned["context"])), [])
        self.assertFalse(AssistantAction.objects.exists())

    @patch("assistant.project_workflows.MAX_SCAN", 1)
    def test_scan_cap_is_explicit_and_next_page_resumes_after_nonmatch(self):
        Result.objects.create(work_item=self.work, key="concentration", value_type="NUMBER", value_number=43)
        second, _, _ = self.make_sample("LATER-001")
        first = self.query("missing results")
        self.assertEqual(self.rows(first), [])
        self.assertTrue(first["project_workflows"]["scan_limit_reached"])
        self.assertIsNone(first["project_workflows"]["matching_sample_count"])
        self.assertEqual(first["project_workflows"]["remaining_to_check"], 1)
        data = self.chat("Next page", first["context"])
        self.assertEqual(self.rows(data)[0]["sample_id"], second.pk)
        self.assertFalse(data["project_workflows"]["complete_project_scan"])
        self.assertIsNone(data["project_workflows"]["matching_sample_count"])

    def test_spanish_filter_switches_and_refresh(self):
        data = self.chat("¿Qué muestras en proyecto DEMO-360 están bloqueadas?")
        unassigned = self.chat("Solo sin asignar", data["context"])
        self.assertEqual(unassigned["project_workflows"]["language"], "es")
        self.assertEqual(unassigned["project_workflows"]["filter"], "unassigned")
        self.assertIn("responsable", unassigned["answer"])
        failed = self.chat("Solo QC rechazado", data["context"])
        self.assertEqual(failed["project_workflows"]["filter"], "qc_failed")
        refreshed = self.chat("Actualizar resultados", unassigned["context"])
        self.assertEqual(refreshed["project_workflows"]["language"], "es")
        self.assertEqual(refreshed["project_workflows"]["matching_sample_count"], 1)

    def test_actionable_reasons_are_prioritized_before_dependencies(self):
        self.work.due_at = timezone.now() - timedelta(days=1)
        self.work.save()
        overview = self.chat("Show samples in project DEMO-360 workflow overview")
        reasons = self.rows(overview)[0]["reasons"]
        self.assertEqual(reasons[0]["kind"], "overdue")
        self.assertEqual(reasons[-1]["kind"], "dependency")
        self.assertTrue(all(r["next_action"] for r in reasons))
        blocked = self.query()
        self.assertNotIn("overdue", {r["kind"] for r in self.rows(blocked)[0]["reasons"]})

    def test_project_codes_do_not_change_the_requested_filter(self):
        project = Project.objects.create(code="OVERDUE-QC", name="Keyword project")
        project.members.add(self.tech)
        self.make_sample("KEYWORD-001", project)
        data = self.chat("Which samples in project OVERDUE-QC are blocked?")
        self.assertEqual(data["project_workflows"]["filter"], "blocked")
        self.assertEqual(len(self.rows(data)), 1)

    def test_uncreated_blocked_work_is_not_reported_as_unassigned(self):
        self.work.assigned_to = self.tech
        self.work.save()
        self.assertEqual(self.rows(self.query("unassigned")), [])
        self.assertEqual(self.rows(self.query("overdue")), [])

    def test_no_match_total_is_exact_only_after_complete_scan(self):
        data = self.query("overdue")
        self.assertTrue(data["project_workflows"]["complete_project_scan"])
        self.assertEqual(data["project_workflows"]["matching_sample_count"], 0)
        self.assertIn("Complete project scan", data["project_workflows"]["summary"])

    @patch("assistant.project_workflows.SCAN_BATCH_SIZE", 2)
    @patch("assistant.project_workflows.PAGE_SIZE", 2)
    def test_matching_pages_cross_scan_batches_without_losing_candidates(self):
        Result.objects.create(work_item=self.work, key="concentration", value_type="NUMBER", value_number=43)
        expected = []
        for index in range(4):
            sample, _, work = self.make_sample(f"SCAN-{index}")
            if index == 0:
                Result.objects.create(work_item=work, key="concentration", value_type="NUMBER", value_number=43)
            else:
                expected.append(sample.pk)
        first = self.query("missing results")
        self.assertEqual([r["sample_id"] for r in self.rows(first)], expected[:2])
        self.assertEqual(first["project_workflows"]["checked_on_page"], 4)
        second = self.chat("Next page", first["context"])
        self.assertEqual([r["sample_id"] for r in self.rows(second)], expected[2:])
        self.assertFalse(second["project_workflows"]["has_more"])

    def make_overdue(self, work, assigned=False):
        work.due_at = timezone.now() - timedelta(days=1)
        work.assigned_to = self.tech if assigned else None
        work.save()

    def test_combined_and_or_return_distinct_matching_samples_and_evidence(self):
        self.make_overdue(self.work)
        _, _, assigned = self.make_sample("OVERDUE-ASSIGNED")
        self.make_overdue(assigned, assigned=True)
        self.make_sample("UNASSIGNED-ONLY")
        both = self.query("overdue and unassigned")
        self.assertEqual([r["sample_code"] for r in self.rows(both)], ["SAMPLE-001"])
        self.assertEqual(both["project_workflows"]["filters"], ["overdue", "unassigned"])
        self.assertEqual({r["kind"] for r in self.rows(both)[0]["reasons"]}, {"overdue", "unassigned"})
        self.assertIn("different steps", both["answer"])
        either = self.query("overdue or unassigned")
        self.assertEqual(len(self.rows(either)), 3)
        self.assertEqual(either["project_workflows"]["match"], "any")
        self.assertEqual(either["project_workflows"]["matching_sample_count"], 3)
        self.assertFalse(AssistantAction.objects.exists())

    def test_refinement_replacement_and_refresh(self):
        self.make_overdue(self.work, assigned=True)
        first = self.query("overdue")
        refined = self.chat("Also unassigned", first["context"])
        self.assertEqual(self.rows(refined), [])
        self.assertEqual(refined["project_workflows"]["filters"], ["overdue", "unassigned"])
        self.work.assigned_to = None
        self.work.save()
        refreshed = self.chat("Refresh results", refined["context"])
        self.assertEqual(len(self.rows(refreshed)), 1)
        replaced = self.chat("Only unassigned", refreshed["context"])
        self.assertEqual(replaced["project_workflows"]["filters"], ["unassigned"])

    @patch("assistant.project_workflows.PAGE_SIZE", 1)
    def test_combined_pagination_and_project_switch(self):
        self.make_overdue(self.work)
        _, _, second = self.make_sample("SECOND")
        self.make_overdue(second)
        first = self.query("overdue and unassigned")
        following = self.chat("Next page", first["context"])
        self.assertEqual(self.rows(following)[0]["sample_code"], "SECOND")
        self.assertEqual(following["project_workflows"]["filters"], ["overdue", "unassigned"])
        self.assertIsNone(following["project_workflows"]["matching_sample_count"])
        other = Project.objects.create(code="OTHER", name="Other")
        other.members.add(self.tech)
        self.make_sample("OTHER-SAMPLE", other)
        switched = self.chat("Which samples in project OTHER are unassigned?", first["context"])
        self.assertEqual(self.rows(switched)[0]["sample_code"], "OTHER-SAMPLE")
        self.assertEqual(switched["project_workflows"]["filters"], ["unassigned"])

    def test_combined_filters_can_match_different_steps(self):
        # Step 1 is missing fields; step 2 has an unmet dependency. The query
        # is sample-level, not an assertion that one step meets every condition.
        data = self.query("missing results and blocked")
        self.assertEqual(len(self.rows(data)), 1)
        reasons = self.rows(data)[0]["reasons"]
        self.assertEqual(len(reasons), 2)  # missing evidence isn't duplicated
        self.assertEqual({r["step"] for r in reasons}, {1, 2})

    def test_spanish_combination_and_refinement(self):
        self.make_overdue(self.work)
        data = self.chat("¿Qué muestras en proyecto DEMO-360 están vencidas y sin asignar?")
        self.assertEqual(data["project_workflows"]["language"], "es")
        self.assertEqual(len(self.rows(data)), 1)
        refined = self.chat("También campos faltantes", data["context"])
        self.assertEqual(refined["project_workflows"]["filters"], ["overdue", "unassigned", "missing"])
        self.assertEqual(refined["project_workflows"]["language"], "es")

    def test_ambiguous_or_unsupported_queries_ask_without_actions(self):
        first = self.query("overdue or unassigned")
        for message in ("Also missing results", "Which samples in project DEMO-360 are not ready?",
                        "Which samples in project DEMO-360 are overdue and unassigned or ready?",
                        "Which samples in project DEMO-360 are overdue assigned to maria?"):
            with self.subTest(message=message):
                data = self.chat(message, first["context"])
                self.assertTrue(data["clarification"]["required"])
                self.assertNotIn("project_workflows", data)
                if message == "Also missing results":
                    self.assertTrue(data["clarification"]["previous_query_retained"])
                    self.assertEqual(data["context"]["project_workflows"]["filters"], ["overdue", "unassigned"])
                else:
                    self.assertEqual(data["context"], {})
                self.assertEqual(data["links"], [])
        self.assertFalse(AssistantAction.objects.exists())

    def test_combined_context_rechecks_permissions_and_rejects_forgery(self):
        first = self.query("overdue and unassigned")
        bad = {"project_workflows": {**first["context"]["project_workflows"], "filters": [{}]}}
        self.assertTrue(self.chat("Refresh results", bad)["clarification"]["required"])
        self.project.members.remove(self.tech)
        denied = self.chat("Refresh results", first["context"])
        self.assertNotIn("project_workflows", denied)
        self.assertEqual(denied["context"], {})

    def test_same_step_eliminates_cross_step_false_match_and_refreshes(self):
        self.make_overdue(self.work, assigned=True)
        second_work = WorkItem.objects.create(sample=self.sample, name="Parallel work", work_type="PARALLEL")
        step = self.run.steps.get(position=2)
        step.dependency_positions = []
        step.status = "READY"
        step.work_item = second_work
        step.save()
        initial = self.query("overdue and unassigned")
        self.assertEqual(len(self.rows(initial)), 1)
        narrow = self.chat("On the same step", initial["context"])
        self.assertEqual(self.rows(narrow), [])
        self.assertEqual(narrow["project_workflows"]["scope"], "step")
        self.work.assigned_to = None
        self.work.save()
        refreshed = self.chat("Refresh results", narrow["context"])
        self.assertEqual(len(self.rows(refreshed)), 1)
        self.assertEqual({r["step"] for r in self.rows(refreshed)[0]["reasons"]}, {1})
        self.assertIn("same pipeline run", refreshed["answer"])
        self.assertFalse(AssistantAction.objects.exists())

    @patch("assistant.project_workflows.PAGE_SIZE", 1)
    def test_same_step_pagination_refinement_and_replacement_keep_scope(self):
        self.make_overdue(self.work)
        _, _, work = self.make_sample("SECOND-SCOPED")
        self.make_overdue(work)
        first = self.query("overdue and unassigned on the same step")
        second = self.chat("Next page", first["context"])
        self.assertEqual(self.rows(second)[0]["sample_code"], "SECOND-SCOPED")
        self.assertEqual(second["project_workflows"]["scope"], "step")
        for message in ("Also missing results", "Only unassigned"):
            data = self.chat(message, second["context"])
            self.assertEqual(data["project_workflows"]["scope"], "step")
            self.assertEqual(self.rows(data)[0]["sample_code"], "SAMPLE-001")
        wide = self.chat("Across the sample", second["context"])
        self.assertEqual(wide["project_workflows"]["scope"], "sample")
        # A new full question uses the default scope, not an invisible old one.
        self.assertEqual(self.query("unassigned", second["context"])["project_workflows"]["scope"], "sample")

    def test_spanish_scope_and_negation(self):
        self.make_overdue(self.work)
        data = self.chat("¿Qué muestras en proyecto DEMO-360 están vencidas y sin asignar en el mismo paso?")
        self.assertEqual(data["project_workflows"]["scope"], "step")
        self.assertEqual(data["project_workflows"]["language"], "es")
        self.assertEqual(len(self.rows(data)), 1)
        wide = self.chat("En toda la muestra", data["context"])
        self.assertEqual(wide["project_workflows"]["scope"], "sample")
        self.assertEqual(wide["project_workflows"]["language"], "es")
        denied = self.query("overdue and unassigned not on the same step")
        self.assertTrue(denied["clarification"]["required"])

    def test_scope_requires_query_and_rejects_invalid_or_conflicting_context(self):
        self.assertTrue(self.chat("On the same step")["clarification"]["required"])
        data = self.query("unassigned")
        for message in ("On the same step across the sample", "Show samples in project DEMO-360 workflow overview on the same step"):
            self.assertTrue(self.chat(message, data["context"])["clarification"]["required"])
        for bad in ([], {}, True, "other"):
            context = {"project_workflows": {**data["context"]["project_workflows"], "scope": bad}}
            self.assertTrue(self.chat("Refresh results", context)["clarification"]["required"])

    def test_scoped_followup_rechecks_access_and_skips_external_provider(self):
        with patch("assistant.llm.OpenAI") as provider:
            data = self.query("unassigned on the same step")
        provider.assert_not_called()
        self.project.members.remove(self.tech)
        for message in ("On the same step", "Refresh results", "Only unassigned"):
            denied = self.chat(message, data["context"])
            self.assertNotIn("project_workflows", denied)
            self.assertEqual(denied["context"], {})


    def test_edit_match_and_remove_filter_preserve_scope_and_restart(self):
        data = self.query("overdue and unassigned on the same step")
        self.assertEqual(self.rows(data), [])
        context = data["context"]
        context["project_workflows"]["after"] = self.sample.pk
        either = self.chat("Match any condition", context)
        self.assertEqual(len(self.rows(either)), 1)
        self.assertEqual(either["project_workflows"]["scope"], "step")
        self.assertEqual(either["project_workflows"]["match"], "any")
        both = self.chat("Require all conditions", either["context"])
        self.assertEqual(self.rows(both), [])
        removed = self.chat("Remove the overdue filter", both["context"])
        self.assertEqual(removed["project_workflows"]["filters"], ["unassigned"])
        self.assertEqual(len(self.rows(removed)), 1)
        self.assertFalse(AssistantAction.objects.exists())

    def test_spanish_query_edits_and_live_permission_recheck(self):
        data = self.query("overdue and unassigned")
        either = self.chat("Cumplir cualquier condición", data["context"])
        self.assertEqual(either["project_workflows"]["language"], "es")
        self.assertEqual(len(self.rows(either)), 1)
        removed = self.chat("Quitar el filtro de vencidas", either["context"])
        self.assertEqual(removed["project_workflows"]["filters"], ["unassigned"])
        self.project.members.remove(self.tech)
        denied = self.chat("Match any condition", either["context"])
        self.assertNotIn("project_workflows", denied)
        self.assertEqual(denied["context"], {})

    def test_invalid_edits_do_not_broaden_to_all_samples(self):
        data = self.query("overdue")
        for phrase, context in [
            ("Remove the overdue filter", data["context"]),
            ("Remove the missing results filter", data["context"]),
            ("Match any condition", {}),
            ("Match any condition", {"project_workflows": {"filters": ["secret"]}}),
            ("Remove the not overdue filter", data["context"]),
        ]:
            with self.subTest(phrase=phrase, context=context):
                reply = self.chat(phrase, context)
                self.assertTrue(reply["clarification"]["required"])
                self.assertNotIn("project_workflows", reply)

    def test_unclear_followup_preserves_query_without_executing(self):
        initial = self.query("overdue or unassigned on the same step")
        initial["context"]["project_workflows"].update(after=999, has_more=True, sample_ids=[self.sample.pk])
        before = Event.objects.count()
        with patch("assistant.project_workflows._evidence") as evidence, patch("assistant.llm.OpenAI") as provider:
            reply = self.chat("Also missing results", initial["context"])
        evidence.assert_not_called()
        provider.assert_not_called()
        self.assertTrue(reply["clarification"]["previous_query_retained"])
        saved = reply["context"]["project_workflows"]
        self.assertEqual(saved["filters"], ["overdue", "unassigned"])
        self.assertEqual(saved["match"], "any")
        self.assertEqual(saved["scope"], "step")
        self.assertEqual(saved["after"], 0)
        self.assertFalse(saved["has_more"])
        self.assertNotIn("sample_ids", saved)
        self.assertNotIn("project_workflows", reply)
        self.assertEqual(reply["links"], [])
        self.assertIn("haven't applied", reply["answer"])
        self.assertIn("AND or OR", reply["answer"])
        self.assertIn("Require all conditions", reply["suggestions"])
        self.assertEqual(Event.objects.count(), before)
        self.assertFalse(AssistantAction.objects.exists())
        self.work.assigned_to = self.tech
        self.work.save()
        refreshed = self.chat("Refresh results", reply["context"])
        self.assertEqual(self.rows(refreshed), [])
        self.assertEqual(refreshed["project_workflows"]["checked_on_page"], 1)

    def test_recovery_suggestions_work_in_both_languages(self):
        for question, followup in [
            ("Which samples in project DEMO-360 are overdue or unassigned?", "Also missing results"),
            ("¿Qué muestras en proyecto DEMO-360 están vencidas o sin asignar?", "También campos faltantes"),
        ]:
            initial = self.chat(question)
            recovery = self.chat(followup, initial["context"])
            self.assertTrue(recovery["clarification"]["previous_query_retained"])
            for suggestion in recovery["suggestions"]:
                with self.subTest(suggestion=suggestion):
                    reply = self.chat(suggestion, recovery["context"])
                    if suggestion in {"Start over", "Empezar de nuevo"}:
                        self.assertEqual(reply["context"], {})
                    else:
                        self.assertIn("project_workflows", reply)
                        self.assertEqual(reply["project_workflows"]["project_code"], "DEMO-360")

    def test_recovery_drops_revoked_and_invalid_context(self):
        initial = self.query("overdue or unassigned")
        original = initial["context"]["project_workflows"]
        for field, bad in [("filters", ["private"]), ("scope", []), ("match", "none"), ("project_code", [])]:
            reply = self.chat("Also missing results", {"project_workflows": {**original, field: bad}})
            self.assertEqual(reply["context"], {})
        self.project.members.remove(self.tech)
        reply = self.chat("Also missing results", initial["context"])
        self.assertEqual(reply["context"], {})
        self.assertEqual(reply["suggestions"], [])
        self.assertNotIn("DEMO-360", reply["answer"])

    def test_recovery_choice_rechecks_permissions_again(self):
        initial = self.query("overdue or unassigned")
        recovery = self.chat("Also missing results", initial["context"])
        self.project.members.remove(self.tech)
        reply = self.chat("Refresh results", recovery["context"])
        self.assertEqual(reply["context"], {})
        self.assertNotIn("project_workflows", reply)

    def test_failed_filter_removal_keeps_previous_filter(self):
        initial = self.query("overdue on the same step")
        reply = self.chat("Remove the overdue filter", initial["context"])
        self.assertTrue(reply["clarification"]["previous_query_retained"])
        self.assertEqual(reply["context"]["project_workflows"]["filters"], ["overdue"])
        self.assertEqual(reply["context"]["project_workflows"]["scope"], "step")
        self.assertNotIn("project_workflows", reply)
        self.assertEqual(reply["suggestions"], ["Refresh results", "Start over"])
