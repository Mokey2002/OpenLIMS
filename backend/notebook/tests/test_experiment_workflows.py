from copy import deepcopy
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from events.models import Event
from notebook.models import Experiment, ExperimentTemplate, Notebook
from notebook.workflows import workflow_checksum
from settings_app.models import SystemSettings


class ExperimentWorkflowTests(APITestCase):
    def setUp(self):
        settings = SystemSettings.load()
        settings.notebook_enabled = True
        settings.save()
        User = get_user_model()
        self.owner = User.objects.create_user(username="workflow-owner")
        self.editor = User.objects.create_user(username="workflow-editor")
        self.reader = User.objects.create_user(username="workflow-reader")
        self.outsider = User.objects.create_user(username="workflow-outsider")
        self.notebook = Notebook.objects.create(name="Workflow bench", owner=self.owner)
        self.notebook.editors.add(self.editor)
        self.notebook.readers.add(self.reader)
        self.definition = [
            {"name": "Extract DNA", "instructions": "Record concentration", "completion_criteria": "Accept concentration at least 10", "assignee": self.editor.pk,
             "fields": [{"key": "concentration", "label": "Concentration", "type": "NUMBER", "required": True, "minimum": 10, "maximum": 100}]},
            {"name": "Review result", "assignee": self.owner.pk, "fields": [
                {"key": "accepted", "label": "Accepted", "type": "BOOLEAN", "required": True, "equals": True},
                {"key": "conclusion", "label": "Conclusion", "type": "STRING", "required": True}]},
        ]
        self.client.force_authenticate(self.owner)
        result = self.client.post("/api/experiment-templates/", {"notebook": self.notebook.pk, "name": "DNA workflow", "blocks": [], "workflow_steps": self.definition}, format="json")
        self.assertEqual(result.status_code, 201, result.data)
        self.template = ExperimentTemplate.objects.get(pk=result.data["id"])
        self.template_url = f"/api/experiment-templates/{self.template.pk}/"
        result = self.client.post(self.template_url + "instantiate/", {}, format="json")
        self.assertEqual(result.status_code, 201, result.data)
        self.experiment = Experiment.objects.get(pk=result.data["id"])
        self.url = f"/api/experiments/{self.experiment.pk}/"

    def step(self, position=1, **overrides):
        current = self.experiment.workflow_steps.get(position=position)
        data = {"operation": "complete", "expected_version": current.version, "confirmed": True, "note": "Measured and checked", "values": {"concentration": 43}}
        data.update(overrides)
        return self.client.post(self.url + f"workflow-steps/{position}/", data, format="json")

    def test_full_workflow_assignees_criteria_completion_review_and_export(self):
        self.client.force_authenticate(self.editor)
        saved = self.step(operation="save", values={"concentration": 3})
        self.assertEqual(saved.status_code, 200, saved.data)  # failing measurements remain recordable
        failed = self.step(values={"concentration": 3})
        self.assertEqual(failed.status_code, 400)
        self.assertEqual(self.step().status_code, 200)
        self.assertEqual(self.step(2, values={"accepted": True, "conclusion": "Pass"}).status_code, 403)
        self.client.force_authenticate(self.owner)
        blocked = self.client.post(self.url + "transition/", {"status": "COMPLETED"}, format="json")
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(self.step(2, values={"accepted": True, "conclusion": "Pass"}).status_code, 200)
        self.assertEqual(self.client.post(self.url + "transition/", {"status": "COMPLETED"}, format="json").status_code, 200)
        reviewed = self.client.post(self.url + "review/", {"decision": "APPROVED", "signed_name": "Bench owner"}, format="json")
        self.assertEqual(reviewed.status_code, 201, reviewed.data)
        self.assertEqual(self.experiment.reviews.get().workflow_checksum, workflow_checksum(self.experiment))
        locked = self.client.post(self.url + "lock/", {"reason": "Workflow and record approved"}, format="json")
        self.assertEqual(locked.status_code, 200, locked.data)
        self.assertEqual(self.client.get(self.url + "export-pdf/").status_code, 200)
        self.assertEqual(self.step(operation="save").status_code, 400)
        self.assertEqual(Event.objects.filter(action="EXPERIMENT_WORKFLOW_COMPLETE").count(), 2)

    def test_order_missing_types_constraints_and_confirmation_are_enforced_without_writes(self):
        before_events = Event.objects.count()
        cases = [
            (2, {"values": {"accepted": True, "conclusion": "Pass"}}),
            (1, {"values": {}}), (1, {"values": {"concentration": True}}),
            (1, {"values": {"concentration": "43"}}), (1, {"values": {"concentration": 10 ** 400}}), (1, {"values": {"concentration": 101}}),
            (1, {"values": {"concentration": 43, "unknown": 1}}),
            (1, {"confirmed": False}), (1, {"note": "   "}),
        ]
        for position, data in cases:
            with self.subTest(data=data):
                self.assertEqual(self.step(position, **data).status_code, 400)
        self.assertEqual(self.experiment.workflow_steps.get(position=1).version, 1)
        self.assertEqual(Event.objects.count(), before_events)
        self.assertEqual(self.step().status_code, 200)
        self.assertEqual(self.step(2, values={"accepted": False, "conclusion": "Fail"}).status_code, 400)
        self.assertEqual(self.step(2, values={"accepted": True, "conclusion": "  "}).status_code, 400)

    def test_reader_outsider_and_revoked_assignee_cannot_change_steps(self):
        for user, expected in [(self.reader, 403), (self.outsider, 404)]:
            self.client.force_authenticate(user)
            self.assertEqual(self.step().status_code, expected)
        self.notebook.editors.remove(self.editor)
        self.client.force_authenticate(self.editor)
        self.assertEqual(self.step().status_code, 404)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.step().status_code, 400)  # revoked responsible person must be replaced
        self.assertEqual(self.step(operation="assign", assignee=self.reader.pk).status_code, 400)
        self.assertEqual(self.step(operation="assign", assignee=self.owner.pk).status_code, 200)
        self.assertEqual(self.step().status_code, 200)

    def test_assignment_required_and_changes_are_audited(self):
        self.assertEqual(self.step(operation="assign", assignee=None).status_code, 200)
        self.assertEqual(self.step().status_code, 400)
        self.assertEqual(self.step(operation="assign", assignee=self.owner.pk, note="").status_code, 400)
        self.assertEqual(self.step(operation="assign", assignee=self.owner.pk).status_code, 200)
        self.assertEqual(self.step().status_code, 200)
        self.assertEqual(Event.objects.filter(action="EXPERIMENT_WORKFLOW_ASSIGN").count(), 2)
        self.assertTrue(self.experiment.assignees.filter(pk=self.owner.pk).exists())

    def test_stale_save_and_completed_step_cannot_be_overwritten(self):
        self.assertEqual(self.step(operation="save").status_code, 200)
        self.assertEqual(self.step(operation="save", expected_version=1, values={"concentration": 55}).status_code, 400)
        self.assertEqual(self.experiment.workflow_steps.get(position=1).values, {"concentration": 43})
        self.assertEqual(self.step().status_code, 200)
        self.assertEqual(self.step(operation="save", values={"concentration": 55}).status_code, 400)
        self.assertEqual(self.step(operation="assign", assignee=self.owner.pk).status_code, 400)

    def test_template_changes_only_affect_future_runs_and_clone_resets_execution(self):
        changed = deepcopy(self.definition)
        changed[0]["name"] = "New extraction"
        self.assertEqual(self.client.patch(self.template_url, {"workflow_steps": changed}, format="json").status_code, 200)
        self.assertEqual(self.experiment.workflow_steps.get(position=1).definition["name"], "Extract DNA")
        second = self.client.post("/api/experiments/", {"notebook": self.notebook.pk, "template": self.template.pk, "title": "Second run"}, format="json")
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.data["workflow_steps"][0]["definition"]["name"], "New extraction")
        self.assertEqual(self.step().status_code, 200)
        clone = self.client.post(self.url + "clone/", {}, format="json")
        self.assertEqual(clone.status_code, 201, clone.data)
        copied = Experiment.objects.get(pk=clone.data["id"]).workflow_steps.first()
        self.assertEqual(copied.definition["name"], "Extract DNA")
        self.assertEqual(copied.values, {})
        self.assertEqual(copied.status, "PENDING")
        self.assertIsNone(copied.completed_at)
        self.assertEqual(self.client.patch(self.url, {"template": None}, format="json").status_code, 400)

    def test_failed_instantiation_and_audit_failure_roll_back(self):
        count = Experiment.objects.count()
        self.notebook.editors.remove(self.editor)
        result = self.client.post(self.template_url + "instantiate/", {}, format="json")
        self.assertEqual(result.status_code, 400)
        self.assertEqual(Experiment.objects.count(), count)
        self.notebook.editors.add(self.editor)
        with patch("notebook.workflows.record_audit_event", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.step()
        step = self.experiment.workflow_steps.get(position=1)
        self.assertEqual(step.status, "PENDING")
        self.assertEqual(step.values, {})
        self.assertEqual(step.version, 1)

    def test_invalid_definitions_rejected_and_existing_experiments_unchanged(self):
        for fields in [
            [{"key": "Bad key", "label": "Bad", "type": "NUMBER"}],
            [{"key": "n", "label": "Number", "type": "NUMBER", "minimum": 4, "maximum": 1}],
            [{"key": "b", "label": "Bool", "type": "BOOLEAN", "equals": "true"}],
            [{"key": "n", "label": "Name", "type": "STRING", "minimum": 1}],
            [{"key": "n", "label": "Name", "type": "STRING"}] * 2,
        ]:
            response = self.client.patch(self.template_url, {"workflow_steps": [{"name": "Bad", "fields": fields}]}, format="json")
            self.assertEqual(response.status_code, 400, response.data)
        plain = self.client.post("/api/experiments/", {"notebook": self.notebook.pk, "title": "No workflow"}, format="json")
        self.assertEqual(plain.status_code, 201)
        self.assertEqual(plain.data["workflow_steps"], [])
        base = f"/api/experiments/{plain.data['id']}/"
        self.assertEqual(self.client.post(base + "transition/", {"status": "COMPLETED"}, format="json").status_code, 200)
