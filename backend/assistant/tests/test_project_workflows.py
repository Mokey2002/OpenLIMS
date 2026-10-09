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
from results.models import Result
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
