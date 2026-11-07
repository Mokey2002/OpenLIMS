from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from assistant.lab_helpers import sample_history
from assistant.reporting_operations import _event_rows
from events.models import Event
from inventory.models import Container, Location
from pipelines.models import (
    AnalysisDefinition, PipelineRun, PipelineTemplate, PipelineTemplateStep,
    ProcedureDefinition,
)
from pipelines.services import (
    assign_analysis, cancel_pipeline, retry_pipeline_step, start_pipeline,
    sync_pipeline_step_from_work_item,
)
from projects.models import Project
from results.models import WorkItem
from samples.models import Sample


class AuditIntegrityTests(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("audit-admin", password=None)
        self.client.force_authenticate(self.admin)
        self.project = Project.objects.create(code="AUDIT", name="Audit regression")
        self.sample = Sample.objects.create(sample_id="AUDIT-001", project=self.project, created_by=self.admin)
        self.analysis = AnalysisDefinition.objects.create(code="AUDIT", name="Audit analysis", created_by=self.admin)
        self.procedure = ProcedureDefinition.objects.create(
            code="AUDIT", name="Audit procedure", analysis=self.analysis, created_by=self.admin,
        )
        self.template = PipelineTemplate.objects.create(code="AUDIT", name="Audit workflow", created_by=self.admin)

    def start(self, *, parallel=False, optional=False, requires_qc=False, count=1):
        for position in range(1, count + 1):
            PipelineTemplateStep.objects.create(
                template=self.template, position=position, procedure=self.procedure,
                dependency_positions=[] if parallel else None,
                optional=optional and position == 1, requires_qc=requires_qc,
                max_retries=2,
            )
        # Parallel roots need distinct work types to avoid a legitimate conflict.
        if parallel:
            second_analysis = AnalysisDefinition.objects.create(code="SECOND", name="Second analysis", created_by=self.admin)
            second_procedure = ProcedureDefinition.objects.create(
                code="SECOND", name="Second procedure", analysis=second_analysis, created_by=self.admin,
            )
            self.template.steps.filter(position=2).update(procedure=second_procedure)
        return start_pipeline(sample=self.sample, template=self.template, actor=self.admin)

    def test_workflow_start_and_activation_are_recorded_once_in_the_audit_api(self):
        run = self.start()
        for action in ["PIPELINE_RUN_STARTED", "PIPELINE_STEP_ACTIVATED"]:
            response = self.client.get("/api/events/", {"action": action})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 1, response.data)
            event = response.data["results"][0]
            self.assertEqual(event["entity_type"], "PipelineRun")
            self.assertEqual(event["entity_id"], str(run.pk))
            self.assertEqual(event["payload"]["sample_id"], self.sample.pk)
            summary = self.client.get("/api/events/summary/", {"action": action})
            self.assertEqual(summary.data["total_events"], 1)
            exported = self.client.get("/api/events/export-json/", {"action": action})
            self.assertEqual(len(exported.json()), 1)

    def test_analysis_assignment_is_recorded_once_and_remains_in_sample_history(self):
        work = assign_analysis(
            sample=self.sample, analysis=self.analysis, actor=self.admin,
            scope_type="SAMPLE", scope_id=self.sample.pk,
        )
        events = Event.objects.filter(action="ANALYSIS_ASSIGNED")
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.get().entity_id, str(work.pk))
        history = self.client.get(f"/api/samples/{self.sample.pk}/history/").data["results"]
        self.assertEqual([row["action"] for row in history].count("ANALYSIS_ASSIGNED"), 1)

    def test_completion_is_recorded_once_and_remains_in_sample_history(self):
        run = self.start()
        work = run.steps.get().work_item
        work.status = WorkItem.STATUS_COMPLETED
        work.save()
        self.assertEqual(Event.objects.filter(action="PIPELINE_RUN_COMPLETED").count(), 1)
        history = self.client.get(f"/api/samples/{self.sample.pk}/history/").data["results"]
        self.assertEqual([row["action"] for row in history].count("PIPELINE_RUN_COMPLETED"), 1)

    def test_cancellation_is_recorded_once_with_its_reason(self):
        run = self.start()
        cancel_pipeline(run=run, actor=self.admin, reason="Cancel after damaged sample inspection")
        events = Event.objects.filter(action="PIPELINE_RUN_CANCELLED")
        self.assertEqual(events.count(), 1)
        self.assertIn("damaged sample", events.get().payload["reason"])

    def test_retry_is_a_new_audited_attempt_without_mirrored_rows(self):
        run = self.start()
        step = run.steps.get()
        work = step.work_item
        work.status = WorkItem.STATUS_FAILED
        work.save()
        step.refresh_from_db()
        retry_pipeline_step(run=run, step=step, actor=self.admin, reason="Retry after checking reagent quality")
        self.assertEqual(Event.objects.filter(action="PIPELINE_STEP_RETRIED").count(), 1)
        activations = Event.objects.filter(action="PIPELINE_STEP_ACTIVATED")
        self.assertEqual(activations.count(), 2)
        self.assertEqual(len({row.payload["work_item_id"] for row in activations}), 2)

    def test_completed_step_resaves_do_not_repeat_completion_while_other_steps_run(self):
        run = self.start(parallel=True, count=2)
        step = run.steps.get(position=1)
        work = step.work_item
        work.status = WorkItem.STATUS_COMPLETED
        work.save()
        step.refresh_from_db()
        completed_at = step.completed_at
        work.save(update_fields=["notes"])
        sync_pipeline_step_from_work_item(work, self.admin)
        step.refresh_from_db()
        self.assertEqual(Event.objects.filter(action="PIPELINE_STEP_COMPLETED").count(), 1)
        self.assertEqual(step.completed_at, completed_at)
        self.assertEqual(run.steps.get(position=2).status, "READY")

    def test_optional_failure_resaves_do_not_repeat_skip_or_change_completion_time(self):
        run = self.start(parallel=True, optional=True, count=2)
        step = run.steps.get(position=1)
        work = step.work_item
        work.status = WorkItem.STATUS_FAILED
        work.notes = "Optional measurement could not be collected"
        work.save()
        step.refresh_from_db()
        completed_at = step.completed_at
        work.save(update_fields=["notes"])
        sync_pipeline_step_from_work_item(work, self.admin)
        step.refresh_from_db()
        self.assertEqual(Event.objects.filter(action="PIPELINE_OPTIONAL_STEP_SKIPPED").count(), 1)
        self.assertEqual(step.completed_at, completed_at)

    def test_missing_measurement_resaves_do_not_repeat_the_same_block(self):
        run = self.start()
        step = run.steps.get()
        step.required_fields = [{"key": "concentration", "required": True}]
        step.save()
        work = step.work_item
        work.status = WorkItem.STATUS_COMPLETED
        work.save()
        work.save(update_fields=["notes"])
        sync_pipeline_step_from_work_item(work, self.admin)
        self.assertEqual(Event.objects.filter(entity_type="PipelineRun", action="PIPELINE_STEP_BLOCKED").count(), 1)

    def test_qc_rejection_resaves_do_not_repeat_the_same_block(self):
        run = self.start(requires_qc=True)
        work = run.steps.get().work_item
        work.status = WorkItem.STATUS_COMPLETED
        work.qc_status = WorkItem.QC_REJECTED
        work.review_note = "Reject this measurement after quality review"
        work.save()
        work.save(update_fields=["notes"])
        sync_pipeline_step_from_work_item(work, self.admin)
        self.assertEqual(Event.objects.filter(entity_type="PipelineRun", action="PIPELINE_STEP_BLOCKED").count(), 1)

    def test_a_real_qc_change_and_new_rejection_reason_are_still_audited(self):
        run = self.start(parallel=True, requires_qc=True, count=2)
        step = run.steps.get(position=1)
        work = step.work_item
        work.status = WorkItem.STATUS_COMPLETED
        work.qc_status = WorkItem.QC_APPROVED
        work.save()
        step.refresh_from_db()
        self.assertEqual(step.status, "COMPLETED")
        work.qc_status = WorkItem.QC_REJECTED
        work.review_note = "Reject after discovering a control failure"
        work.save()
        step.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(step.status, "FAILED")
        self.assertEqual(run.status, "BLOCKED")
        work.review_note = "Updated rejection reason after reviewing instrument calibration"
        work.save()
        events = Event.objects.filter(entity_type="PipelineRun", action="PIPELINE_STEP_BLOCKED")
        self.assertEqual(events.count(), 2)
        self.assertEqual(events.latest("pk").payload["failure_reason"], work.review_note)

    def test_canonical_workflow_events_are_linked_to_history_and_assistant_by_real_ownership(self):
        run = self.start()
        canonical = Event.objects.create(
            entity_type="PipelineRun", entity_id=str(run.pk), action="CANONICAL_TEST",
            actor=self.admin, payload={"related_sample_id": self.sample.pk},
        )
        other = Sample.objects.create(sample_id="AUDIT-OTHER", project=self.project)
        other_run = PipelineRun.objects.create(sample=other, template=self.template)
        forged_relation = Event.objects.create(
            entity_type="PipelineRun", entity_id=str(other_run.pk), action="WRONG_SAMPLE",
            payload={"related_sample_id": self.sample.pk},
        )
        legacy_run_event = Event.objects.create(entity_type="PipelineRun", entity_id=str(run.pk), action="LEGACY_TEST")
        legacy_sample_event = Event.objects.create(entity_type="Sample", entity_id=str(self.sample.pk), action="LEGACY_TEST")
        response = self.client.get(f"/api/samples/{self.sample.pk}/history/")
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(canonical.pk, ids)
        self.assertIn(legacy_sample_event.pk, ids)
        self.assertNotIn(legacy_run_event.pk, ids)
        self.assertNotIn(forged_relation.pk, ids)
        assistant = sample_history(self.sample.sample_id, self.admin)
        actions = [row["action"] for row in assistant["history"]["events"]]
        self.assertEqual(actions.count("CANONICAL_TEST"), 1)
        self.assertEqual(actions.count("LEGACY_TEST"), 1)
        self.assertNotIn("WRONG_SAMPLE", actions)
        # Historical records remain intact; reads do not delete or rewrite them.
        self.assertTrue(Event.objects.filter(pk=legacy_run_event.pk).exists())

    def test_reports_keep_canonical_workflow_events_for_current_sample_collaborators(self):
        self.start()
        tech = get_user_model().objects.create_user("audit-tech")
        tech.groups.add(Group.objects.get_or_create(name="tech")[0])
        self.project.members.add(tech)
        rows = _event_rows({"project_id": self.project.pk}, tech)
        actions = [row["action"] for row in rows]
        self.assertEqual(actions.count("PIPELINE_RUN_STARTED"), 1)
        self.assertEqual(actions.count("PIPELINE_STEP_ACTIVATED"), 1)
        other = Sample.objects.create(sample_id="AUDIT-PRIVATE")
        other_run = PipelineRun.objects.create(sample=other, template=self.template)
        Event.objects.create(
            entity_type="PipelineRun", entity_id=str(other_run.pk), action="WRONG_REPORT_SAMPLE",
            actor=tech, payload={"related_sample_id": self.sample.pk, "project_id": self.project.pk},
        )
        self.assertNotIn("WRONG_REPORT_SAMPLE", [row["action"] for row in _event_rows({}, tech)])
        self.project.members.remove(tech)
        self.assertNotIn("PIPELINE_RUN_STARTED", [row["action"] for row in _event_rows({}, tech)])

    def test_storage_patch_writes_one_detailed_event_and_no_op_writes_none(self):
        location = Location.objects.create(name="Audit freezer", kind="freezer")
        container = Container.objects.create(container_id="AUDIT-BOX", kind="box", location=location)
        before = Event.objects.order_by("pk").last().pk
        response = self.client.patch(f"/api/samples/{self.sample.pk}/", {"container": container.pk}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        events = Event.objects.order_by("pk").filter(pk__gt=before)
        self.assertEqual(events.count(), 1)
        event = events.get()
        self.assertEqual(event.action, "CONTAINER_ASSIGNED")
        self.assertEqual(event.payload["before"]["container_id"], None)
        self.assertEqual(event.payload["after"]["container_id"], container.pk)
        self.assertEqual(event.payload["new_container_code"], "AUDIT-BOX")
        self.assertEqual(event.payload["location_name"], "Audit freezer")
        self.client.patch(f"/api/samples/{self.sample.pk}/", {"container": container.pk}, format="json")
        self.assertEqual(events.count(), 1)

    def test_combined_status_and_container_patch_is_one_complete_audit_entry(self):
        location = Location.objects.create(name="Audit freezer", kind="freezer")
        container = Container.objects.create(container_id="AUDIT-BOX", kind="box", location=location)
        before = Event.objects.order_by("pk").last().pk
        response = self.client.patch(f"/api/samples/{self.sample.pk}/", {
            "container": container.pk, "status": "IN_PROGRESS", "reason": "Start processing in the assigned storage container",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        events = Event.objects.filter(pk__gt=before)
        self.assertEqual(events.count(), 1)
        event = events.get()
        self.assertEqual(event.action, "UPDATED")
        self.assertCountEqual(event.payload["changed_fields"], ["status", "container_id"])
        self.assertEqual(event.payload["new_container_id"], container.pk)
        self.assertIn("Start processing", event.payload["reason"])

    def test_status_transition_rolls_back_when_its_audit_write_fails(self):
        before = Event.objects.count()
        with patch("samples.views.create_sample_event", side_effect=RuntimeError("Audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.client.post(f"/api/samples/{self.sample.pk}/transition/", {
                    "new_status": "IN_PROGRESS", "reason": "Start processing after accession review",
                }, format="json")
        self.sample.refresh_from_db()
        self.assertEqual(self.sample.status, "RECEIVED")
        self.assertEqual(Event.objects.count(), before)
