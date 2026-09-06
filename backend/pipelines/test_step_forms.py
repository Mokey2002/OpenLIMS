from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from custom_fields.models import SampleForm
from samples.models import Sample
from events.models import Event
from results.models import WorkItem
from .models import AnalysisDefinition, ProcedureDefinition, PipelineTemplate, PipelineTemplateStep, PipelineRun
from .services import start_pipeline, validate_work_item_pipeline_completion, sync_pipeline_step_from_work_item, retry_pipeline_step
from .serializers import PipelineTemplateStepSerializer


class WorkflowFormTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(username="director", is_superuser=True)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.form = SampleForm.objects.create(code="MEASURE", name_en="Measurements", name_es="Mediciones", published=True,
            fields=[{"key": "concentration", "en": "Concentration", "es": "Concentración", "type": "number", "required": True, "min": 0}])
        analysis = AnalysisDefinition.objects.create(code="EXT", name="Extraction", created_by=self.admin)
        procedure = ProcedureDefinition.objects.create(code="EXT", name="Extraction", analysis=analysis, created_by=self.admin)
        self.template = PipelineTemplate.objects.create(code="FLOW", name="Flow", created_by=self.admin)
        self.template_step = PipelineTemplateStep.objects.create(template=self.template, position=1, procedure=procedure, form=self.form, max_retries=1)
        self.sample = Sample.objects.create(sample_id="S1")
        self.run = start_pipeline(sample=self.sample, template=self.template, actor=self.admin)
        self.step = self.run.steps.get()

    def save_values(self, values=None, before=None):
        return self.client.post(f"/api/pipeline-runs/{self.run.pk}/steps/{self.step.pk}/form/",
            {"values": {"concentration": 4} if values is None else values, "before": {} if before is None else before, "reason": "Measured at the bench", "work_item": self.step.work_item_id}, format="json")

    def test_missing_values_block_work_completion(self):
        with self.assertRaises(ValidationError):
            validate_work_item_pipeline_completion(self.step.work_item, WorkItem.STATUS_COMPLETED)

    def test_valid_values_allow_completion_and_are_audited(self):
        self.assertEqual(self.save_values().status_code, 200)
        validate_work_item_pipeline_completion(self.step.work_item, WorkItem.STATUS_COMPLETED)
        self.assertTrue(Event.objects.filter(action="STEP_FORM_SAVED", actor=self.admin).exists())

    def test_invalid_measurement_rejected(self):
        for values in ({}, {"concentration": -1}, {"concentration": True}, {"unknown": 4}):
            self.assertEqual(self.save_values(values).status_code, 400)

    def test_schema_survives_template_edit_and_archival(self):
        original = self.step.form_schema
        self.template_step.form = None
        self.template_step.save()
        self.form.archived = True
        self.form.save()
        self.step.refresh_from_db()
        self.assertEqual(self.step.form_schema, original)
        self.assertEqual(self.save_values().status_code, 200)

    def test_archived_form_blocks_new_run_and_rolls_back(self):
        self.form.archived = True
        self.form.save()
        sample = Sample.objects.create(sample_id="S2")
        with self.assertRaises(ValidationError):
            start_pipeline(sample=sample, template=self.template, actor=self.admin)
        self.assertFalse(PipelineRun.objects.filter(sample=sample).exists())

    def test_draft_form_cannot_be_attached(self):
        self.form.published = False
        self.form.save()
        serializer = PipelineTemplateStepSerializer(data={"position": 1, "procedure": self.template_step.procedure_id, "form": self.form.pk})
        self.assertFalse(serializer.is_valid())

    def test_stale_or_final_edit_rejected(self):
        self.assertEqual(self.save_values().status_code, 200)
        self.assertEqual(self.save_values({"concentration": 5}).status_code, 400)
        self.step.work_item.status = WorkItem.STATUS_COMPLETED
        self.step.work_item.save()
        self.assertEqual(self.save_values({"concentration": 6}, {"concentration": 4}).status_code, 400)

    def test_viewer_cannot_record(self):
        viewer = get_user_model().objects.create_user(username="viewer")
        viewer.groups.add(Group.objects.get_or_create(name="viewer")[0])
        self.client.force_authenticate(viewer)
        self.assertEqual(self.save_values().status_code, 403)

    def test_direct_completion_cannot_advance_without_form(self):
        work = self.step.work_item
        work.status = WorkItem.STATUS_COMPLETED
        work.save()
        sync_pipeline_step_from_work_item(work, self.admin)
        self.run.refresh_from_db()
        self.assertNotEqual(self.run.status, PipelineRun.STATUS_COMPLETED)

    def test_retry_clears_values_and_preserves_audit(self):
        self.save_values()
        work = self.step.work_item
        work.status = WorkItem.STATUS_FAILED
        work.save()
        sync_pipeline_step_from_work_item(work, self.admin)
        self.step.refresh_from_db()
        retry_pipeline_step(run=self.run, step=self.step, actor=self.admin, reason="Repeat measurement")
        self.step.refresh_from_db()
        self.assertEqual(self.step.form_values, {})
        self.assertEqual(self.step.form_schema["version"], self.form.pk)
        event = Event.objects.filter(entity_type="PipelineRun", action="PIPELINE_STEP_RETRIED").latest("pk")
        self.assertEqual(event.payload["previous_form_values"], {"concentration": 4})

    def test_saved_form_does_not_bypass_qc(self):
        self.step.requires_qc = True
        self.step.save()
        self.assertEqual(self.save_values().status_code, 200)
        work = self.step.work_item
        work.status = WorkItem.STATUS_COMPLETED
        work.qc_status = WorkItem.QC_PENDING_REVIEW
        work.save()
        sync_pipeline_step_from_work_item(work, self.admin)
        self.step.refresh_from_db()
        self.assertEqual(self.step.status, "AWAITING_QC")
        self.run.refresh_from_db()
        self.assertNotEqual(self.run.status, PipelineRun.STATUS_COMPLETED)

    def test_unrelated_technician_cannot_edit(self):
        from projects.models import Project
        project = Project.objects.create(code="PRIVATE", name="Private project")
        self.sample.project = project
        self.sample.save()
        tech = get_user_model().objects.create_user(username="outsider")
        tech.groups.add(Group.objects.get_or_create(name="tech")[0])
        self.client.force_authenticate(tech)
        self.assertIn(self.save_values().status_code, [403, 404])

    def test_attempt_identity_required(self):
        response = self.client.post(f"/api/pipeline-runs/{self.run.pk}/steps/{self.step.pk}/form/",
            {"values": {"concentration": 5}, "before": {}, "reason": "Recorded measurements", "work_item": -1}, format="json")
        self.assertEqual(response.status_code, 400)
