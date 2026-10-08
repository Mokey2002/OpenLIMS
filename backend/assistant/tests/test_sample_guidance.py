from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from rest_framework.test import APITestCase
from unittest.mock import patch

from assistant.models import AssistantAction
from assistant.sample_guidance import route_sample_guidance
from events.models import Event
from pipelines.models import AnalysisDefinition, ProcedureDefinition, PipelineTemplate, PipelineTemplateStep
from pipelines.services import start_pipeline
from projects.models import Project
from results.models import Result
from samples.models import Sample


@override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=False)
class SampleGuidanceTests(APITestCase):
    def setUp(self):
        self.tech = get_user_model().objects.create_user("guide-tech")
        self.tech.groups.add(Group.objects.get_or_create(name="tech")[0])
        self.viewer = get_user_model().objects.create_user("guide-viewer")
        self.viewer.groups.add(Group.objects.get_or_create(name="viewer")[0])
        self.project = Project.objects.create(code="GUIDE", name="Guidance")
        self.project.members.add(self.tech, self.viewer)
        self.sample = Sample.objects.create(sample_id="GUIDE-001", project=self.project, created_by=self.tech)
        analysis = AnalysisDefinition.objects.create(code="GUIDE", name="Extraction", required_fields=[{"key": "concentration", "value_type": "NUMBER", "required": True}])
        procedure = ProcedureDefinition.objects.create(code="GUIDE", name="Extraction", version="1", analysis=analysis)
        template = PipelineTemplate.objects.create(code="GUIDE", name="Guidance")
        PipelineTemplateStep.objects.create(template=template, position=1, procedure=procedure, requires_qc=True)
        PipelineTemplateStep.objects.create(template=template, position=2, procedure=procedure, dependency_positions=[1])
        self.run = start_pipeline(sample=self.sample, template=template, actor=self.tech)
        self.work = self.run.steps.get(position=1).work_item
        self.client.force_authenticate(self.tech)

    def chat(self, message, context=None):
        response = self.client.post("/api/assistant/chat/", {"message": message, "context": context or {}}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_missing_fields_and_gates_are_grounded_without_writes(self):
        before = Event.objects.count()
        data = self.chat("What next for sample GUIDE-001?")
        self.assertIn("concentration", data["answer"])
        self.assertEqual(data["sample_guidance"]["steps"][1]["waiting_for"], ["1"])
        self.assertEqual(data["links"][0]["url"], f"/samples/{self.sample.pk}")
        self.assertEqual(data["context"]["sample_code"], "GUIDE-001")
        self.assertFalse(AssistantAction.objects.exists())
        self.assertEqual(Event.objects.count(), before)
        self.work.refresh_from_db()
        self.assertEqual(self.work.status, "PENDING")

    def test_followup_reloads_work_and_distinguishes_completion_from_qc(self):
        data = self.chat("What next for sample GUIDE-001?")
        Result.objects.create(work_item=self.work, key="concentration", value_type="NUMBER", value_number=43, entered_by=self.tech)
        data = self.chat("What next?", data["context"])
        self.assertIn("mark it COMPLETED", data["answer"])
        self.work.status = "COMPLETED"
        self.work.save()
        data = self.chat("What next?", data["context"])
        self.assertIn("authorized QC reviewer", data["answer"])
        self.assertEqual(data["sample_guidance"]["steps"][0]["status"], "AWAITING_QC")

    def test_revocation_and_forged_context_do_not_leak_sample_data(self):
        context = {"sample_code": "GUIDE-001", "sample_id": self.sample.pk}
        self.project.members.remove(self.tech)
        data = self.chat("What next?", context)
        self.assertNotIn("sample_guidance", data)
        self.assertEqual(data["links"], [])
        self.assertNotIn("Extraction", data["answer"])
        self.assertEqual(data["context"], {})

    def test_spanish_readonly_and_explicit_sample_override(self):
        self.client.force_authenticate(self.viewer)
        data = self.chat("¿Qué sigue para muestra GUIDE-001?")
        self.assertIn("acceso de lectura", data["answer"])
        self.assertIn("campos obligatorios", data["answer"])
        denied = self.chat("What next for sample SECRET-999?", data["context"])
        self.assertNotIn("sample_guidance", denied)

    def test_ambiguous_and_missing_references_ask_instead_of_guessing(self):
        for message in ("What next?", "What next for sample GUIDE-001 and sample GUIDE-002?"):
            data = self.chat(message)
            self.assertTrue(data["clarification"]["required"])
            self.assertEqual(data["links"], [])
        self.assertIsNone(route_sample_guidance("Approve QC for work item 1", self.tech))

    def test_completed_run_does_not_propose_work(self):
        self.run.status = "COMPLETED"
        self.run.save()
        data = self.chat("Explain the pipeline for sample GUIDE-001")
        self.assertIn("Historical run", data["answer"])
        self.assertNotIn("Enter or correct", data["answer"])

    @override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=True, OPENAI_API_KEY="test-only")
    def test_guidance_is_not_rewritten_by_external_model(self):
        with patch("assistant.llm.OpenAI") as provider:
            data = self.chat("What next for sample GUIDE-001.")
        provider.assert_not_called()
        self.assertEqual(data["sample_guidance"]["sample_id"], self.sample.pk)

    def test_clarification_accepts_bare_id_and_preserves_owner_question(self):
        data = self.chat("Who is assigned?")
        self.assertTrue(data["clarification"]["required"])
        self.work.assigned_to = self.tech
        self.work.save()
        data = self.chat("GUIDE-001", data["context"])
        self.assertIn("Recorded work assignee: guide-tech", data["answer"])
        self.assertIn("not necessarily the QC reviewer", data["answer"])

    def test_natural_followups_requery_current_records(self):
        data = self.chat("What next for sample GUIDE-001?")
        for question in ("What’s holding this up?", "What is missing?", "How can I proceed?", "And now?"):
            data = self.chat(question, data["context"])
            self.assertIn("concentration", data["answer"])
        data = self.chat("What about step 2?", data["context"])
        self.assertEqual([s["step"] for s in data["sample_guidance"]["steps"]], [2])
        data = self.chat("Who is assigned?", data["context"])
        self.assertEqual([s["step"] for s in data["sample_guidance"]["steps"]], [2])
        self.assertIn("Unassigned", data["answer"])
        self.assertFalse(AssistantAction.objects.exists())

    def test_spanish_clarification_and_followup(self):
        data = self.chat("¿Qué falta?")
        data = self.chat("GUIDE-001", data["context"])
        self.assertIn("campos obligatorios", data["answer"])
        data = self.chat("¿Y el paso 2?", data["context"])
        self.assertEqual([s["step"] for s in data["sample_guidance"]["steps"]], [2])

    def test_reset_and_access_denial_clear_context_even_for_followup_words(self):
        data = self.chat("What next for sample GUIDE-001?")
        reset = self.chat("Start over", data["context"])
        self.assertEqual(reset["context"], {})
        self.project.members.remove(self.tech)
        denied = self.chat("What is missing for this sample?", data["context"])
        self.assertEqual(denied["context"], {})
        self.assertEqual(denied["links"], [])
        self.assertNotIn("sample_guidance", denied)

    def test_unrelated_and_write_requests_are_not_swallowed(self):
        data = self.chat("What next for sample GUIDE-001?")
        for message in ("Approve QC for work item 1", "Assign step 2 to Peter", "What is DNA?", "Create a notebook for step 2", "Search notebooks mentioning step 2"):
            self.assertIsNone(route_sample_guidance(message, self.tech, data["context"]))

    def test_missing_and_ambiguous_steps_do_not_guess(self):
        data = self.chat("What next for sample GUIDE-001?")
        missing = self.chat("What about step 99?", data["context"])
        self.assertTrue(missing["clarification"]["required"])
        PipelineRun = type(self.run)
        duplicate = PipelineRun.objects.create(sample=self.sample, template=self.run.template, started_by=self.tech, status="COMPLETED")
        step = self.run.steps.get(position=1)
        step.pk = None
        step.pipeline_run = duplicate
        step.work_item = None
        step.save()
        ambiguous = self.chat("What about step 1?", data["context"])
        self.assertTrue(ambiguous["clarification"]["required"])
        self.assertNotIn("sample_guidance", ambiguous)

    def test_sample_switch_resets_step_and_never_fuzzy_matches(self):
        data = self.chat("What next for sample GUIDE-001?")
        data = self.chat("What about step 2?", data["context"])
        other = Sample.objects.create(sample_id="GUIDE-002", project=self.project, created_by=self.tech)
        switched = self.chat("What about GUIDE-002?", data["context"])
        self.assertEqual(switched["sample_guidance"]["sample_id"], other.pk)
        self.assertNotIn("step", switched["context"]["guidance"])
        missing = self.chat("What about GUIDE-003?", switched["context"])
        self.assertEqual(missing["context"], {})
        self.assertEqual(missing["links"], [])
