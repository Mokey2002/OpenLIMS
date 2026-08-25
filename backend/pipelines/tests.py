from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from events.models import Event
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample, SampleBatch

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

    def test_dependency_graph_activates_parallel_root_steps(self):
        extraction, pcr = self.create_definitions()
        template = PipelineTemplate.objects.create(
            code="PARALLEL", name="Parallel preparation", created_by=self.admin
        )
        PipelineTemplateStep.objects.create(
            template=template,
            position=1,
            procedure=extraction,
            dependency_positions=[],
        )
        PipelineTemplateStep.objects.create(
            template=template,
            position=2,
            procedure=pcr,
            dependency_positions=[],
        )
        sample = Sample.objects.create(
            sample_id="PARALLEL-001", project=self.project, created_by=self.tech
        )
        self.client.force_authenticate(self.tech)
        response = self.client.post(
            "/api/pipeline-runs/", {"sample": sample.id, "template": template.id}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        statuses = {step["position"]: step["status"] for step in response.data["steps"]}
        self.assertEqual(statuses, {1: "READY", 2: "READY"})
        self.assertEqual(WorkItem.objects.filter(sample=sample).count(), 2)

    def test_result_condition_skips_branch_and_completes_run(self):
        extraction, pcr = self.create_definitions()
        template = PipelineTemplate.objects.create(
            code="CONDITIONAL", name="Conditional amplification", created_by=self.admin
        )
        PipelineTemplateStep.objects.create(
            template=template,
            position=1,
            procedure=extraction,
            dependency_positions=[],
        )
        PipelineTemplateStep.objects.create(
            template=template,
            position=2,
            procedure=pcr,
            dependency_positions=[1],
            activation_condition={
                "source_position": 1,
                "result_key": "concentration",
                "operator": "GTE",
                "value": 10,
            },
        )
        sample = Sample.objects.create(
            sample_id="CONDITIONAL-001", project=self.project, created_by=self.tech
        )
        self.client.force_authenticate(self.tech)
        start = self.client.post(
            "/api/pipeline-runs/", {"sample": sample.id, "template": template.id}, format="json"
        )
        run = PipelineRun.objects.get(pk=start.data["id"])
        first = run.steps.get(position=1)
        Result.objects.create(
            work_item=first.work_item,
            key="concentration",
            value_type=Result.VALUE_TYPE_NUMBER,
            value_number=4.5,
            entered_by=self.tech,
        )
        completed = self.client.patch(
            f"/api/work-items/{first.work_item_id}/",
            {"status": WorkItem.STATUS_COMPLETED},
            format="json",
        )
        self.assertEqual(completed.status_code, 200, completed.data)
        run.refresh_from_db()
        second = run.steps.get(position=2)
        self.assertEqual(second.status, PipelineStepRun.STATUS_SKIPPED)
        self.assertEqual(run.status, PipelineRun.STATUS_COMPLETED)

    def test_failed_step_can_be_retried_within_configured_limit(self):
        extraction, _ = self.create_definitions()
        template = PipelineTemplate.objects.create(
            code="RETRYABLE", name="Retryable extraction", created_by=self.admin
        )
        PipelineTemplateStep.objects.create(
            template=template,
            position=1,
            procedure=extraction,
            dependency_positions=[],
            max_retries=1,
        )
        sample = Sample.objects.create(
            sample_id="RETRY-001", project=self.project, created_by=self.tech
        )
        self.client.force_authenticate(self.tech)
        start = self.client.post(
            "/api/pipeline-runs/", {"sample": sample.id, "template": template.id}, format="json"
        )
        run = PipelineRun.objects.get(pk=start.data["id"])
        step = run.steps.get(position=1)
        old_work_item_id = step.work_item_id
        self.client.patch(
            f"/api/work-items/{old_work_item_id}/",
            {"status": WorkItem.STATUS_FAILED, "notes": "Instrument stopped during extraction."},
            format="json",
        )
        retry = self.client.post(
            f"/api/pipeline-runs/{run.id}/steps/{step.id}/retry/",
            {"reason": "Instrument recovered; repeat the extraction."},
            format="json",
        )
        self.assertEqual(retry.status_code, 200, retry.data)
        step.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(step.retry_count, 1)
        self.assertEqual(step.status, PipelineStepRun.STATUS_READY)
        self.assertNotEqual(step.work_item_id, old_work_item_id)
        self.assertEqual(run.status, PipelineRun.STATUS_ACTIVE)

    def test_optional_failure_skips_step_and_releases_dependents(self):
        extraction, pcr = self.create_definitions()
        template = PipelineTemplate.objects.create(
            code="OPTIONAL", name="Optional preparation", created_by=self.admin
        )
        PipelineTemplateStep.objects.create(
            template=template,
            position=1,
            procedure=extraction,
            dependency_positions=[],
            optional=True,
        )
        PipelineTemplateStep.objects.create(
            template=template,
            position=2,
            procedure=pcr,
            dependency_positions=[1],
        )
        sample = Sample.objects.create(
            sample_id="OPTIONAL-001", project=self.project, created_by=self.tech
        )
        self.client.force_authenticate(self.tech)
        start = self.client.post(
            "/api/pipeline-runs/", {"sample": sample.id, "template": template.id}, format="json"
        )
        run = PipelineRun.objects.get(pk=start.data["id"])
        first = run.steps.get(position=1)
        failed = self.client.patch(
            f"/api/work-items/{first.work_item_id}/",
            {"status": WorkItem.STATUS_FAILED, "notes": "Optional preparation unavailable."},
            format="json",
        )
        self.assertEqual(failed.status_code, 200, failed.data)
        first.refresh_from_db()
        second = run.steps.get(position=2)
        run.refresh_from_db()
        self.assertEqual(first.status, PipelineStepRun.STATUS_SKIPPED)
        self.assertEqual(second.status, PipelineStepRun.STATUS_READY)
        self.assertEqual(run.status, PipelineRun.STATUS_ACTIVE)

    def test_analysis_can_be_assigned_to_one_sample_with_required_results(self):
        analysis = AnalysisDefinition.objects.create(
            code="PH",
            name="pH analysis",
            required_fields=[
                {
                    "key": "ph",
                    "label": "pH",
                    "value_type": "NUMBER",
                    "required": True,
                    "unit": "",
                }
            ],
            created_by=self.admin,
        )
        sample = Sample.objects.create(
            sample_id="SCOPE-SAMPLE-001",
            project=self.project,
            created_by=self.tech,
        )
        self.client.force_authenticate(self.tech)

        response = self.client.post(
            "/api/pipeline-runs/assign/",
            {
                "scope_type": "SAMPLE",
                "sample": sample.id,
                "assignment_type": "ANALYSIS",
                "analysis": analysis.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["assigned_count"], 1)
        work_item = WorkItem.objects.get(sample=sample)
        self.assertEqual(work_item.analysis_code, "PH")
        self.assertEqual(work_item.required_fields, analysis.required_fields)

        completion = self.client.patch(
            f"/api/work-items/{work_item.id}/",
            {"status": WorkItem.STATUS_COMPLETED},
            format="json",
        )
        self.assertEqual(completion.status_code, 400, completion.data)
        self.assertEqual(completion.data["missing_required_fields"], ["ph"])

        Result.objects.create(
            work_item=work_item,
            key="ph",
            value_type=Result.VALUE_TYPE_NUMBER,
            value_number=7.2,
            entered_by=self.tech,
        )
        completion = self.client.patch(
            f"/api/work-items/{work_item.id}/",
            {"status": WorkItem.STATUS_COMPLETED},
            format="json",
        )
        self.assertEqual(completion.status_code, 200, completion.data)

    def test_analysis_can_be_assigned_to_every_sample_in_a_batch(self):
        analysis = AnalysisDefinition.objects.create(
            code="MICRO",
            name="Microbiology screen",
            required_fields=[],
            created_by=self.admin,
        )
        batch = SampleBatch.objects.create(
            code="BATCH-001",
            project=self.project,
            created_by=self.tech,
        )
        samples = [
            Sample.objects.create(
                sample_id=f"BATCH-SAMPLE-{index}",
                project=self.project,
                batch=batch,
                created_by=self.tech,
            )
            for index in range(1, 3)
        ]
        self.client.force_authenticate(self.tech)

        response = self.client.post(
            "/api/pipeline-runs/assign/",
            {
                "scope_type": "BATCH",
                "batch": batch.id,
                "assignment_type": "ANALYSIS",
                "analysis": analysis.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["assigned_count"], 2)
        self.assertEqual(
            WorkItem.objects.filter(
                sample__in=samples,
                analysis_code="MICRO",
            ).count(),
            2,
        )

        duplicate = self.client.post(
            "/api/pipeline-runs/assign/",
            {
                "scope_type": "BATCH",
                "batch": batch.id,
                "assignment_type": "ANALYSIS",
                "analysis": analysis.id,
            },
            format="json",
        )
        self.assertEqual(duplicate.status_code, 200, duplicate.data)
        self.assertEqual(duplicate.data["assigned_count"], 0)
        self.assertEqual(duplicate.data["skipped_count"], 2)

    def test_pipeline_project_assignment_reports_assigned_and_skipped_samples(self):
        template = self.create_template()
        first = Sample.objects.create(
            sample_id="PROJECT-SAMPLE-001",
            project=self.project,
            created_by=self.tech,
        )
        second = Sample.objects.create(
            sample_id="PROJECT-SAMPLE-002",
            project=self.project,
            created_by=self.tech,
        )
        Sample.objects.create(
            sample_id="PROJECT-SAMPLE-ARCHIVED",
            project=self.project,
            status=Sample.STATUS_ARCHIVED,
            created_by=self.tech,
        )
        self.client.force_authenticate(self.tech)
        existing = self.client.post(
            "/api/pipeline-runs/",
            {"sample": first.id, "template": template.id},
            format="json",
        )
        self.assertEqual(existing.status_code, 201, existing.data)

        response = self.client.post(
            "/api/pipeline-runs/assign/",
            {
                "scope_type": "PROJECT",
                "project": self.project.id,
                "assignment_type": "PIPELINE",
                "pipeline_template": template.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["assigned_count"], 1)
        self.assertEqual(response.data["skipped_count"], 2)
        self.assertEqual(response.data["assigned"][0]["sample"], second.id)
        self.assertEqual(PipelineRun.objects.filter(sample=second).count(), 1)
        self.assertTrue(
            Event.objects.filter(
                entity_type="Project",
                entity_id=str(self.project.id),
                action="WORKFLOW_ASSIGNMENT_COMPLETED",
                payload__assigned_count=1,
                payload__skipped_count=2,
            ).exists()
        )

    def test_viewer_cannot_assign_project_workflows(self):
        viewer_group, _ = Group.objects.get_or_create(name="viewer")
        viewer = User.objects.create_user(username="project-viewer", password="pass")
        viewer.groups.add(viewer_group)
        self.project.members.add(viewer)
        analysis = AnalysisDefinition.objects.create(
            code="VIEW-ONLY",
            name="View only analysis",
            created_by=self.admin,
        )
        Sample.objects.create(
            sample_id="VIEWER-SAMPLE-001",
            project=self.project,
            created_by=self.tech,
        )
        self.client.force_authenticate(viewer)

        response = self.client.post(
            "/api/pipeline-runs/assign/",
            {
                "scope_type": "PROJECT",
                "project": self.project.id,
                "assignment_type": "ANALYSIS",
                "analysis": analysis.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.data)
