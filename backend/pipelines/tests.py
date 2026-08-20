from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from events.models import Event
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample

from .models import (
    AnalysisDefinition,
    PipelineRun,
    PipelineStepRun,
    PipelineTemplate,
    PipelineTemplateStep,
    ProcedureDefinition,
)


User = get_user_model()


class PipelineWorkflowTests(APITestCase):
    def setUp(self):
        admin_group, _ = Group.objects.get_or_create(name="admin")
        tech_group, _ = Group.objects.get_or_create(name="tech")
        qc_group, _ = Group.objects.get_or_create(name="qc_reviewer")

        self.admin = User.objects.create_user(username="director", password="pass")
        self.admin.groups.add(admin_group)
        self.tech = User.objects.create_user(username="operator", password="pass")
        self.tech.groups.add(tech_group)
        self.qc = User.objects.create_user(username="reviewer", password="pass")
        self.qc.groups.add(qc_group)

        self.project = Project.objects.create(code="UNAM", name="UNAM Pilot")
        self.project.members.add(self.tech, self.qc)

    def create_definitions(self):
        extraction = AnalysisDefinition.objects.create(
            code="EXTRACTION",
            name="DNA Extraction",
            required_fields=[
                {
                    "key": "concentration",
                    "label": "Concentration",
                    "value_type": "NUMBER",
                    "required": True,
                    "unit": "ng/uL",
                }
            ],
            created_by=self.admin,
        )
        pcr = AnalysisDefinition.objects.create(
            code="PCR",
            name="PCR",
            required_fields=[],
            created_by=self.admin,
        )
        extraction_procedure = ProcedureDefinition.objects.create(
            code="DNA-EXT",
            name="DNA extraction",
            version="1",
            analysis=extraction,
            estimated_duration_minutes=30,
            created_by=self.admin,
        )
        pcr_procedure = ProcedureDefinition.objects.create(
            code="PCR-STD",
            name="Standard PCR",
            version="2",
            analysis=pcr,
            estimated_duration_minutes=90,
            created_by=self.admin,
        )
        return extraction_procedure, pcr_procedure

    def create_template(self, *, is_default=False):
        extraction, pcr = self.create_definitions()
        template = PipelineTemplate.objects.create(
            code="DNA-WORKFLOW",
            name="DNA workflow",
            active=True,
            is_default=is_default,
            default_project=self.project if is_default else None,
            default_sample_type="DNA" if is_default else "",
            created_by=self.admin,
        )
        PipelineTemplateStep.objects.create(
            template=template,
            position=1,
            procedure=extraction,
        )
        PipelineTemplateStep.objects.create(
            template=template,
            position=2,
            procedure=pcr,
            requires_qc=True,
        )
        return template

    def test_admin_can_configure_analysis_procedure_and_ordered_template(self):
        self.client.force_authenticate(self.admin)
        analysis_response = self.client.post(
            "/api/analysis-definitions/",
            {
                "code": "sequencing",
                "name": "Sequencing",
                "category": "Genomics",
                "required_fields": [
                    {
                        "key": "read_count",
                        "label": "Read count",
                        "value_type": "NUMBER",
                        "required": True,
                        "unit": "reads",
                    }
                ],
                "active": True,
            },
            format="json",
        )
        self.assertEqual(analysis_response.status_code, 201, analysis_response.data)
        self.assertEqual(analysis_response.data["code"], "SEQUENCING")

        procedure_response = self.client.post(
            "/api/procedure-definitions/",
            {
                "code": "seq-standard",
                "name": "Standard sequencing",
                "version": "1",
                "analysis": analysis_response.data["id"],
                "instructions": "Follow the approved sequencing procedure.",
                "estimated_duration_minutes": 120,
                "active": True,
            },
            format="json",
        )
        self.assertEqual(procedure_response.status_code, 201, procedure_response.data)

        template_response = self.client.post(
            "/api/pipeline-templates/",
            {
                "code": "seq-only",
                "name": "Sequencing only",
                "active": True,
                "is_default": True,
                "default_project": self.project.id,
                "default_sample_type": "DNA",
                "steps": [
                    {
                        "position": 1,
                        "procedure": procedure_response.data["id"],
                        "name": "Sequence sample",
                        "requires_qc": True,
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(template_response.status_code, 201, template_response.data)
        self.assertEqual(template_response.data["code"], "SEQ-ONLY")
        self.assertEqual(template_response.data["steps"][0]["analysis_code"], "SEQUENCING")
        self.assertTrue(
            Event.objects.filter(action="PIPELINE_TEMPLATE_CREATED").exists()
        )

    def test_tech_cannot_change_configuration(self):
        self.client.force_authenticate(self.tech)
        response = self.client.post(
            "/api/analysis-definitions/",
            {"code": "PCR", "name": "PCR", "required_fields": []},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_matching_default_pipeline_starts_when_sample_is_created(self):
        template = self.create_template(is_default=True)
        self.client.force_authenticate(self.tech)

        response = self.client.post(
            "/api/samples/",
            {
                "sample_id": "UNAM-DNA-001",
                "sample_type": "dna",
                "status": "RECEIVED",
                "project": self.project.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        sample = Sample.objects.get(sample_id="UNAM-DNA-001")
        run = PipelineRun.objects.get(sample=sample)
        self.assertEqual(run.template, template)
        self.assertEqual(run.steps.get(position=1).status, PipelineStepRun.STATUS_READY)
        self.assertEqual(run.steps.get(position=2).status, PipelineStepRun.STATUS_BLOCKED)
        self.assertEqual(WorkItem.objects.filter(sample=sample).count(), 1)

    def test_steps_advance_in_order_and_wait_for_configured_qc(self):
        template = self.create_template()
        sample = Sample.objects.create(
            sample_id="UNAM-DNA-002",
            sample_type="DNA",
            project=self.project,
            created_by=self.tech,
        )
        self.client.force_authenticate(self.tech)
        start_response = self.client.post(
            "/api/pipeline-runs/",
            {"sample": sample.id, "template": template.id},
            format="json",
        )
        self.assertEqual(start_response.status_code, 201, start_response.data)
        run = PipelineRun.objects.get(pk=start_response.data["id"])
        first = run.steps.get(position=1)

        progress_response = self.client.patch(
            f"/api/work-items/{first.work_item_id}/",
            {"status": WorkItem.STATUS_IN_PROGRESS},
            format="json",
        )
        self.assertEqual(progress_response.status_code, 200, progress_response.data)
        first.refresh_from_db()
        self.assertEqual(first.status, PipelineStepRun.STATUS_IN_PROGRESS)

        Result.objects.create(
            work_item=first.work_item,
            key="concentration",
            value_type=Result.VALUE_TYPE_NUMBER,
            value_number=18.2,
            entered_by=self.tech,
        )
        completed_response = self.client.patch(
            f"/api/work-items/{first.work_item_id}/",
            {"status": WorkItem.STATUS_COMPLETED},
            format="json",
        )
        self.assertEqual(completed_response.status_code, 200, completed_response.data)
        first.refresh_from_db()
        second = run.steps.get(position=2)
        self.assertEqual(first.status, PipelineStepRun.STATUS_COMPLETED)
        self.assertEqual(second.status, PipelineStepRun.STATUS_READY)
        self.assertIsNotNone(second.work_item_id)

        second_complete = self.client.patch(
            f"/api/work-items/{second.work_item_id}/",
            {"status": WorkItem.STATUS_COMPLETED},
            format="json",
        )
        self.assertEqual(second_complete.status_code, 200, second_complete.data)
        second.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(second.status, PipelineStepRun.STATUS_AWAITING_QC)
        self.assertEqual(run.status, PipelineRun.STATUS_ACTIVE)

        self.client.force_authenticate(self.qc)
        review_response = self.client.post(
            f"/api/work-items/{second.work_item_id}/qc-review/",
            {"qc_status": WorkItem.QC_APPROVED, "review_note": "QC metrics accepted."},
            format="json",
        )
        self.assertEqual(review_response.status_code, 200, review_response.data)
        second.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(second.status, PipelineStepRun.STATUS_COMPLETED)
        self.assertEqual(run.status, PipelineRun.STATUS_COMPLETED)
        self.assertTrue(Event.objects.filter(action="PIPELINE_RUN_COMPLETED").exists())

    def test_required_analysis_results_block_early_completion(self):
        template = self.create_template()
        sample = Sample.objects.create(
            sample_id="UNAM-DNA-003",
            sample_type="DNA",
            project=self.project,
            created_by=self.tech,
        )
        self.client.force_authenticate(self.tech)
        start_response = self.client.post(
            "/api/pipeline-runs/",
            {"sample": sample.id, "template": template.id},
            format="json",
        )
        work_item_id = start_response.data["steps"][0]["work_item"]

        response = self.client.patch(
            f"/api/work-items/{work_item_id}/",
            {"status": WorkItem.STATUS_COMPLETED},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["missing_required_fields"], ["concentration"])
        self.assertEqual(WorkItem.objects.get(pk=work_item_id).status, WorkItem.STATUS_PENDING)

    def test_failed_work_item_blocks_pipeline_and_future_steps(self):
        template = self.create_template()
        sample = Sample.objects.create(
            sample_id="UNAM-DNA-004",
            sample_type="DNA",
            project=self.project,
            created_by=self.tech,
        )
        self.client.force_authenticate(self.tech)
        start_response = self.client.post(
            "/api/pipeline-runs/",
            {"sample": sample.id, "template": template.id},
            format="json",
        )
        run = PipelineRun.objects.get(pk=start_response.data["id"])
        first = run.steps.get(position=1)

        response = self.client.patch(
            f"/api/work-items/{first.work_item_id}/",
            {"status": WorkItem.STATUS_FAILED, "notes": "Extraction instrument failed."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        run.refresh_from_db()
        first.refresh_from_db()
        second = run.steps.get(position=2)
        self.assertEqual(run.status, PipelineRun.STATUS_BLOCKED)
        self.assertEqual(first.status, PipelineStepRun.STATUS_FAILED)
        self.assertEqual(second.status, PipelineStepRun.STATUS_BLOCKED)
        self.assertIsNone(second.work_item_id)

    def test_pipeline_can_be_cancelled_with_an_audited_reason(self):
        template = self.create_template()
        sample = Sample.objects.create(
            sample_id="UNAM-DNA-005",
            sample_type="DNA",
            project=self.project,
            created_by=self.tech,
        )
        self.client.force_authenticate(self.tech)
        start_response = self.client.post(
            "/api/pipeline-runs/",
            {"sample": sample.id, "template": template.id},
            format="json",
        )
        run_id = start_response.data["id"]
        work_item_id = start_response.data["steps"][0]["work_item"]

        response = self.client.post(
            f"/api/pipeline-runs/{run_id}/cancel/",
            {"reason": "UNAM operator stopped the run after a damaged sample was found."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], PipelineRun.STATUS_CANCELLED)
        self.assertEqual(
            WorkItem.objects.get(pk=work_item_id).status,
            WorkItem.STATUS_CANCELLED,
        )
        self.assertTrue(
            Event.objects.filter(
                entity_type="Sample",
                entity_id=str(sample.id),
                action="PIPELINE_RUN_CANCELLED",
                payload__reason__icontains="damaged sample",
            ).exists()
        )
