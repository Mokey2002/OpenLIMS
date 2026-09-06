from django.test import TestCase
from rest_framework.exceptions import ValidationError
from .test_step_forms import WorkflowFormTests
from .models import PipelineTemplateStep
from .serializers import PipelineTemplateSerializer
from .services import start_pipeline, sync_pipeline_step_from_work_item, _condition_matches
from .rules import normalize_expected, matches
from samples.models import Sample
from results.models import WorkItem
from events.models import Event


class MeasurementRuleTests(TestCase):
    setUp = WorkflowFormTests.setUp

    def condition(self, **changes):
        return {"source_kind": "measurement", "source_position": 1, "result_key": "concentration", "operator": "LT", "value": 10, **changes}

    def make_run(self, **condition_changes):
        child = PipelineTemplateStep.objects.create(template=self.template, position=2, procedure=self.template_step.procedure,
            dependency_positions=[1], activation_condition=self.condition(**condition_changes))
        run = start_pipeline(sample=Sample.objects.create(sample_id="S2"), template=self.template, actor=self.admin)
        return run, child

    def test_branch_activation_and_audit(self):
        run, child = self.make_run()
        source = run.steps.get(position=1)
        source.form_values = {"concentration": 4}
        source.save()
        source.work_item.status = WorkItem.STATUS_COMPLETED
        source.work_item.save()
        sync_pipeline_step_from_work_item(source.work_item, self.admin)
        target = run.steps.get(position=2)
        self.assertEqual(target.status, "READY")
        event = Event.objects.filter(entity_type="PipelineRun", entity_id=str(run.pk), action="WORKFLOW_RULE_EVALUATED").latest("pk")
        self.assertTrue(event.payload["matched"])
        self.assertEqual(event.payload["actual"], 4)

    def test_nonmatching_branch_skipped(self):
        run, child = self.make_run()
        source = run.steps.get(position=1)
        source.form_values = {"concentration": 12}
        source.save()
        source.work_item.status = WorkItem.STATUS_COMPLETED
        source.work_item.save()
        sync_pipeline_step_from_work_item(source.work_item, self.admin)
        self.assertEqual(run.steps.get(position=2).status, "SKIPPED")

    def test_missing_measurement_never_matches_not_equal(self):
        run, child = self.make_run(operator="NE")
        self.assertFalse(_condition_matches(run.steps.get(position=2)))

    def test_template_changes_do_not_change_running_rule(self):
        run, child = self.make_run()
        child.activation_condition = self.condition(value=100)
        child.save()
        self.assertEqual(run.steps.get(position=2).activation_condition["value"], 10)

    def test_serializer_validates_source_and_normalizes_threshold(self):
        payload = {"code": "NEW", "name": "New", "steps": [
            {"position": 1, "procedure": self.template_step.procedure_id, "form": self.form.pk},
            {"position": 2, "procedure": self.template_step.procedure_id, "dependency_positions": [1], "activation_condition": self.condition(value="10")}]}
        serializer = PipelineTemplateSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["steps"][1]["activation_condition"]["value"], 10)
        payload["steps"][1]["activation_condition"]["result_key"] = "unknown"
        self.assertFalse(PipelineTemplateSerializer(data=payload).is_valid())

    def test_preview_matches_runtime_and_writes_nothing(self):
        before = Event.objects.count()
        response = self.client.post("/api/pipeline-templates/preview-rule/", {"form": self.form.pk, "field": "concentration", "operator": "LT", "value": "10", "actual": "4"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["matches"])
        self.assertEqual(Event.objects.count(), before)

    def test_invalid_thresholds_and_types(self):
        field = {"type": "number"}
        for value in (True, "bad", float("nan"), float("inf")):
            with self.assertRaises(ValidationError):
                normalize_expected(field, "LT", value)
        with self.assertRaises(ValidationError):
            normalize_expected({"type": "boolean"}, "GT", True)
        self.assertEqual(normalize_expected(field, "IN", "1,2"), [1, 2])
        self.assertTrue(matches(2, "IN", [1, 2]))
