from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import signing
from django.db import close_old_connections, connection
from django.test import override_settings
from rest_framework.test import APITestCase, APITransactionTestCase

from assistant.actions import confirm_action
from assistant.models import AssistantAction
from assistant.provider_tools import dispatch_tool
from assistant.workflow_guide import KEY, SALT
from custom_fields.models import SampleForm
from events.models import Event
from pipelines.models import AnalysisDefinition, ProcedureDefinition, PipelineTemplate, PipelineTemplateStep
from pipelines.services import start_pipeline
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample
from settings_app.models import SystemSettings


@override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=False, OPENLIMS_ENFORCE_FEATURE_FLAGS=True)
class AssistantV069Tests(APITestCase):
    def setUp(self):
        self.tech = self.user("workflow-tech")
        self.reviewer = self.user("workflow-reviewer", "qc_reviewer")
        self.viewer = self.user("workflow-viewer", "viewer")
        self.maria = self.user("maria")
        self.outsider = self.user("outsider")
        self.project = Project.objects.create(code="PREP", name="Preparation")
        self.project.members.add(self.tech, self.reviewer, self.viewer, self.maria)
        self.sample = Sample.objects.create(sample_id="S-100", project=self.project, created_by=self.tech)
        extraction = AnalysisDefinition.objects.create(code="EXTRACTION", name="Extraction", required_fields=[{"key": "concentration", "value_type": "NUMBER", "required": True}])
        sequencing = AnalysisDefinition.objects.create(code="SEQUENCING", name="Sequencing", required_fields=[{"key": "yield", "value_type": "NUMBER", "required": True}])
        self.extract = ProcedureDefinition.objects.create(code="EXTRACT", name="Extract", analysis=extraction)
        self.seq = ProcedureDefinition.objects.create(code="SEQUENCE", name="Sequence", analysis=sequencing)
        self.template = PipelineTemplate.objects.create(code="SEQ-PREP", name="Sequencing preparation")
        self.first = PipelineTemplateStep.objects.create(template=self.template, position=1, procedure=self.extract, requires_qc=True)
        PipelineTemplateStep.objects.create(template=self.template, position=2, procedure=self.seq, dependency_positions=[1])
        self.client.force_authenticate(self.tech)

    def user(self, username, role="tech"):
        user = get_user_model().objects.create_user(username)
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        return user

    def start(self):
        self.run = start_pipeline(sample=self.sample, template=self.template, actor=self.tech)
        self.step = self.run.steps.get(position=1)
        self.work = self.step.work_item

    def chat(self, message, context=None):
        result = self.client.post("/api/assistant/chat/", {"message": message, "context": context or {}}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        return result.data

    def plan(self):
        result = self.client.get(f"/api/assistant/workflows/{self.sample.pk}/")
        self.assertEqual(result.status_code, 200, result.data)
        return result.data

    def propose(self, operation, expected=201, **fields):
        result = self.client.post(f"/api/assistant/workflows/{self.sample.pk}/actions/", {
            "operation": operation, "plan_digest": self.plan()["plan_digest"], **fields}, format="json")
        self.assertEqual(result.status_code, expected, result.data)
        return result.data

    def confirm(self, action, expected=200):
        result = self.client.post(f"/api/assistant/actions/{action['confirmation_token']}/confirm/", {"confirm": True}, format="json")
        self.assertEqual(result.status_code, expected, result.data)
        return result.data

    def result(self):
        return Result.objects.create(work_item=self.work, key="concentration", value_type="NUMBER", value_number=0, entered_by=self.tech)

    def test_full_preparation_conversation_confirmation_qc_and_next_step(self):
        initial = self.chat("Help me prepare sample S-100 for sequencing.")
        self.assertEqual(initial["workflow_plan"]["readiness"], "needs_workflow")
        self.assertFalse(self.sample.pipeline_runs.exists())
        start = self.propose("WORKFLOW_START", template_id=self.template.pk)["pending_action"]
        self.assertFalse(self.sample.pipeline_runs.exists())
        self.confirm(start)
        self.confirm(start)
        self.assertEqual(self.sample.pipeline_runs.count(), 1)
        self.run = self.sample.pipeline_runs.get()
        self.step = self.run.steps.get(position=1)
        self.work = self.step.work_item
        continued = self.chat("What should I do next?", initial["context"])
        self.assertEqual(continued["workflow_plan"]["steps"][0]["missing_fields"], ["concentration"])
        assignment = self.chat(f"Assign work item #{self.work.pk} for sample S-100 to maria", continued["context"])
        self.assertIn(KEY, assignment["context"])
        self.confirm(assignment["pending_action"])
        entered = self.chat(f"Add result concentration = 0 to work item #{self.work.pk} for sample S-100", assignment["context"])
        self.assertIn("workflow_plan", entered)
        self.confirm(entered["pending_action"])
        completion = self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk)["pending_action"]
        self.work.refresh_from_db()
        self.assertEqual(self.work.status, "PENDING")
        self.confirm(completion)
        self.assertEqual(self.run.steps.get(position=1).status, "AWAITING_QC")
        self.assertEqual(self.run.steps.get(position=2).status, "BLOCKED")
        self.client.force_authenticate(self.reviewer)
        qc = self.propose("WORKFLOW_REVIEW", step_id=self.step.pk, decision="APPROVED", reason="Reviewed the recorded extraction evidence.")["pending_action"]
        self.confirm(qc)
        self.confirm(qc)
        ready = self.chat("Am I ready for sequencing?", self.chat("Prepare sample S-100 for sequencing")["context"])
        self.assertEqual(ready["workflow_plan"]["readiness"], "available")
        self.assertEqual(self.run.steps.get(position=2).status, "READY")
        self.assertEqual(Result.objects.get().qc_status, "PENDING_REVIEW")
        self.assertEqual(Event.objects.filter(action="QC_APPROVED", entity_type="WorkItem").count(), 1)

    def test_requirements_and_dependencies_cannot_be_bypassed(self):
        self.start()
        self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk, expected=400)
        later = self.run.steps.get(position=2)
        self.propose("WORKFLOW_COMPLETE", step_id=later.pk, expected=400)
        self.propose("WORKFLOW_REVIEW", step_id=self.step.pk, decision="APPROVED", reason="Not complete", expected=400)
        self.assertEqual(WorkItem.objects.get(pk=self.work.pk).status, "PENDING")
        self.assertFalse(Result.objects.exists())

    def test_step_form_is_validated_previewed_and_audited(self):
        form = SampleForm.objects.create(code="PREP_FORM", name_en="Preparation", name_es="Preparación", published=True,
            fields=[{"key": "checked", "en": "Checked", "es": "Revisado", "type": "boolean", "required": True}])
        self.first.form = form
        self.first.save()
        self.start()
        self.result()
        self.assertIn("form:checked", self.plan()["steps"][0]["missing_fields"])
        self.propose("WORKFLOW_FORM", step_id=self.step.pk, values={"checked": "false"}, reason="Recorded actual inspection", expected=400)
        pending = self.propose("WORKFLOW_FORM", step_id=self.step.pk, values={"checked": False}, reason="Recorded actual inspection")["pending_action"]
        self.assertEqual(self.run.steps.get(pk=self.step.pk).form_values, {})
        self.confirm(pending)
        self.assertEqual(self.run.steps.get(pk=self.step.pk).form_values, {"checked": False})
        self.assertTrue(self.plan()["steps"][0]["can_complete"])
        self.assertTrue(Event.objects.filter(action="STEP_FORM_SAVED", payload__assistant_action_id=pending["id"]).exists())

    def test_frozen_result_evidence_changes_reject_confirmation(self):
        self.start()
        measured = self.result()
        action = self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk)["pending_action"]
        measured.value_number = 9
        measured.save()
        self.confirm(action, expected=400)
        self.assertEqual(WorkItem.objects.get(pk=self.work.pk).status, "PENDING")

    def test_permissions_owner_expiry_cancellation_and_context_forgery(self):
        self.start()
        self.result()
        context = self.chat("Prepare sample S-100 for sequencing")["context"]
        action = self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk)["pending_action"]
        self.client.force_authenticate(self.maria)
        self.confirm(action, expected=400)
        self.assertNotIn("workflow_plan", self.chat("Refresh preparation", context))
        forged = {KEY: signing.dumps({"sample": self.sample.pk, "user": self.tech.pk}, salt="wrong")}
        self.assertNotIn("workflow_plan", self.chat("Refresh preparation", forged))
        self.client.force_authenticate(self.tech)
        self.client.post(f"/api/assistant/actions/{action['confirmation_token']}/cancel/", {}, format="json")
        self.confirm(action, expected=400)
        self.assertNotIn(KEY, self.chat("Cancel preparation", context)["context"])
        with patch("assistant.workflow_guide.signing.loads", side_effect=signing.SignatureExpired):
            self.assertNotIn("workflow_plan", self.chat("Refresh preparation", context))

    def test_viewers_linked_members_and_revoked_membership(self):
        self.start()
        self.result()
        action = self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk)["pending_action"]
        self.client.force_authenticate(self.viewer)
        self.assertTrue(self.plan()["read_only"])
        self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk, expected=400)
        linked = Project.objects.create(code="LINKED", name="Linked")
        linked.members.add(self.outsider)
        self.sample.linked_projects.add(linked)
        self.client.force_authenticate(self.outsider)
        self.assertTrue(self.plan()["read_only"])
        self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk, expected=400)
        self.client.force_authenticate(self.tech)
        self.project.members.remove(self.tech)
        self.confirm(action, expected=400)
        self.assertEqual(self.client.get(f"/api/assistant/workflows/{self.sample.pk}/").status_code, 404)

    def test_separation_of_duties_and_reviewer_role_revocation(self):
        self.start()
        self.result()
        self.confirm(self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk)["pending_action"])
        self.tech.groups.add(Group.objects.get(name="qc_reviewer"))
        config = SystemSettings.load()
        config.qc_separation_of_duties = True
        config.save()
        self.assertFalse(self.plan()["steps"][0]["can_approve"])
        self.propose("WORKFLOW_REVIEW", step_id=self.step.pk, decision="APPROVED", reason="Self review", expected=400)
        self.client.force_authenticate(self.reviewer)
        pending = self.propose("WORKFLOW_REVIEW", step_id=self.step.pk, decision="APPROVED", reason="Independent review")["pending_action"]
        self.reviewer.groups.clear()
        self.confirm(pending, expected=400)
        self.assertEqual(WorkItem.objects.get(pk=self.work.pk).qc_status, "PENDING_REVIEW")

    def test_rejection_records_human_reason_and_does_not_unlock_sequencing(self):
        self.start()
        self.result()
        self.confirm(self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk)["pending_action"])
        self.client.force_authenticate(self.reviewer)
        pending = self.propose("WORKFLOW_REVIEW", step_id=self.step.pk, decision="RERUN_REQUIRED", reason="Recorded extraction requires a rerun.")["pending_action"]
        self.confirm(pending)
        self.assertEqual(self.run.steps.get(position=1).status, "FAILED")
        self.assertEqual(self.run.steps.get(position=2).status, "BLOCKED")
        self.assertEqual(self.plan()["readiness"], "blocked")

    def test_stale_checklist_strict_fields_wrong_step_and_template_changes(self):
        pending = self.propose("WORKFLOW_START", template_id=self.template.pk)["pending_action"]
        self.first.requires_qc = False
        self.first.save()
        self.confirm(pending, expected=400)
        self.assertFalse(self.sample.pipeline_runs.exists())
        self.start()
        old = self.plan()["plan_digest"]
        self.result()
        response = self.client.post(f"/api/assistant/workflows/{self.sample.pk}/actions/", {"operation": "WORKFLOW_COMPLETE", "plan_digest": old, "step_id": self.step.pk}, format="json")
        self.assertEqual(response.status_code, 400)
        self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk, confirm=True, expected=400)
        self.propose("WORKFLOW_COMPLETE", step_id=999999, expected=400)

    def test_provider_bridge_and_missing_sample_question_are_deterministic(self):
        self.start()
        question = self.chat("Can you help me prepare a sample for sequencing?")
        self.assertTrue(question["clarification"]["required"])
        selected = self.chat("S-100", question["context"])
        self.assertEqual(selected["workflow_plan"]["sample_code"], "S-100")
        bridged = dispatch_tool({"route": "tool", "tool": "workflow_guide", "arguments": {"command": "Help me prepare sample S-100 for sequencing"}, "confidence": .99}, self.tech)
        self.assertTrue(bridged["skip_llm"])
        self.assertEqual(bridged["workflow_plan"]["readiness"], "blocked")
        self.assertFalse(AssistantAction.objects.exists())

    def test_saved_guide_reloads_live_evidence_without_replaying_actions(self):
        self.start()
        reply = self.chat("Prepare sample S-100 for sequencing")
        saved = self.client.post("/api/assistant/conversations/", {"name": "Preparation", "turn_tokens": [reply["save_turn_token"]]}, format="json")
        self.assertEqual(saved.status_code, 201, saved.data)
        self.result()
        restored = self.client.get(f"/api/assistant/conversations/{saved.data['id']}/")
        self.assertEqual(restored.status_code, 200, restored.data)
        plan = restored.data["history"][1]["reply"]["workflow_plan"]
        self.assertEqual(plan["steps"][0]["results"][0]["value"], 0)
        self.assertEqual(plan["steps"][0]["missing_fields"], [])
        self.assertFalse(AssistantAction.objects.exists())
        self.project.members.remove(self.tech)
        denied = self.client.get(f"/api/assistant/conversations/{saved.data['id']}/")
        self.assertNotIn("workflow_plan", denied.data["history"][1]["reply"])
        self.assertEqual(denied.data["context"], {})

    def test_large_run_final_sample_and_non_sequencing_workflow_do_not_claim_readiness(self):
        for index in range(3, 52):
            PipelineTemplateStep.objects.create(template=self.template, position=index, procedure=self.extract)
        self.start()
        plan = self.plan()
        self.assertTrue(plan["truncated"])
        self.assertEqual(plan["readiness"], "unknown")
        self.assertFalse(any(row["can_record"] or row["can_review"] for row in plan["steps"]))
        self.result()
        self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk, expected=400)
        self.sample.status = "CANCELLED"
        self.sample.save()
        self.assertTrue(self.plan()["read_only"])
        self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk, expected=400)

    def test_intake_errors_are_visible_and_block_workflow_changes(self):
        self.start()
        self.result()
        schema = {"fields": [{"key": "source", "en": "Source", "es": "Origen", "type": "text", "required": True}]}
        Sample.objects.filter(pk=self.sample.pk).update(form_schema=schema, form_values={})
        self.assertTrue(self.plan()["intake_errors"])
        self.assertEqual(self.plan()["readiness"], "blocked")
        self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk, expected=400)

    def test_typed_guide_actions_obey_final_status_and_frozen_evidence(self):
        self.start()
        context = self.chat("Prepare sample S-100 for sequencing")["context"]
        pending = self.chat(f"Assign work item #{self.work.pk} for sample S-100 to maria", context)["pending_action"]
        self.result()
        self.confirm(pending, expected=400)
        self.work.refresh_from_db()
        self.assertIsNone(self.work.assigned_to_id)
        self.sample.status = "CANCELLED"
        self.sample.save()
        denied = self.chat(f"Assign work item #{self.work.pk} for sample S-100 to maria", context)
        self.assertNotIn("pending_action", denied)
        self.assertTrue(denied["workflow_plan"]["read_only"])

    def test_cross_sample_work_link_cannot_disclose_inaccessible_evidence(self):
        self.start()
        private = Project.objects.create(code="PRIVATE", name="Private")
        private_sample = Sample.objects.create(sample_id="PRIVATE-ONLY", project=private, created_by=self.outsider)
        work = WorkItem.objects.create(sample=private_sample, name="PRIVATE-WORK")
        Result.objects.create(work_item=work, key="private_measurement", value_type="STRING", value_string="PRIVATE-EVIDENCE")
        self.step.work_item = work
        self.step.save()
        plan = self.plan()
        self.assertEqual(plan["readiness"], "unknown")
        self.assertTrue(plan["steps"][0]["link_error"])
        self.assertNotIn("PRIVATE-EVIDENCE", str(plan))
        self.assertEqual(plan["steps"][0]["results"], [])
        self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk, expected=400)

    def test_late_audit_failure_rolls_back_work_and_pipeline_changes(self):
        self.start()
        self.result()
        pending = self.propose("WORKFLOW_COMPLETE", step_id=self.step.pk)["pending_action"]
        original = Event.objects.create

        def fail_final_event(**kwargs):
            if kwargs.get("action") == "WORK_ITEM_COMPLETED":
                raise ValueError("Simulated final audit failure")
            return original(**kwargs)

        with patch.object(Event.objects, "create", side_effect=fail_final_event):
            self.confirm(pending, expected=400)
        self.assertEqual(WorkItem.objects.get(pk=self.work.pk).status, "PENDING")
        self.assertEqual(self.run.steps.get(position=1).status, "READY")
        self.assertEqual(self.run.steps.get(position=2).status, "BLOCKED")

    def test_provider_assignment_keeps_the_same_workflow_and_evidence_guard(self):
        self.start()
        context = self.chat("Prepare sample S-100 for sequencing")["context"]
        result = dispatch_tool({"route": "tool", "tool": "guided_actions", "arguments": {
            "command": f"Assign work item #{self.work.pk} for sample S-100 to maria"}, "confidence": .99}, self.tech, context)
        self.assertIn(KEY, result["context"])
        self.assertEqual(result["pending_action"]["payload"]["workflow_digest"], result["workflow_plan"]["plan_digest"])
        self.assertEqual(result["workflow_plan"]["sample_id"], self.sample.pk)


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
class WorkflowActionConcurrencyTests(APITransactionTestCase):
    setUp = AssistantV069Tests.setUp
    user = AssistantV069Tests.user
    plan = AssistantV069Tests.plan
    propose = AssistantV069Tests.propose

    def test_two_confirmations_start_one_pipeline(self):
        pending = self.propose("WORKFLOW_START", template_id=self.template.pk)["pending_action"]
        barrier = Barrier(2)

        def confirm():
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.tech.pk)
                barrier.wait(timeout=10)
                return confirm_action(pending["confirmation_token"], user).status
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: confirm(), range(2)))
        self.assertEqual(results, ["COMPLETED", "COMPLETED"])
        self.assertEqual(self.sample.pipeline_runs.count(), 1)
