from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from events.models import Event
from notebook.models import Experiment, ExperimentOnboarding, ExperimentTemplate, Notebook
from notifications.models import Notification
from settings_app.models import SystemSettings


class OnboardingTests(APITestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("lab-owner")
        self.editor = get_user_model().objects.create_user("new-scientist")
        self.reader = get_user_model().objects.create_user("lab-reader")
        self.notebook = Notebook.objects.create(name="Our lab", owner=self.owner)
        self.notebook.editors.add(self.editor)
        self.notebook.readers.add(self.reader)
        self.template = ExperimentTemplate.objects.create(notebook=self.notebook, name="Our extraction", created_by=self.owner,
            workflow_steps=[{"name": "Measure", "fields": [{"key": "concentration", "label": "Concentration", "type": "NUMBER", "required": True, "minimum": 10}]}])
        self.client.force_authenticate(self.editor)

    def start(self, **changes):
        return self.client.post("/api/v1/onboarding/", {"template": self.template.pk, "title": "First extraction", **changes}, format="json")

    def test_first_experiment_resumes_and_tracks_real_completion(self):
        self.assertIsNone(self.client.get("/api/v1/onboarding/").data["experiment"])
        created = self.start()
        self.assertEqual(created.status_code, 201, created.data)
        experiment = Experiment.objects.get(public_id=created.data["experiment"]["public_id"])
        self.assertEqual(experiment.template, self.template)
        self.assertTrue(experiment.assignees.filter(pk=self.editor.pk).exists())
        self.assertEqual(experiment.revisions.count(), 1)
        self.assertEqual(self.start().status_code, 200)
        self.assertEqual(Experiment.objects.count(), 1)
        self.assertEqual(ExperimentOnboarding.objects.count(), 1)
        url = f"/api/experiments/{experiment.pk}/"
        self.assertEqual(experiment.status, "IN_PROGRESS")
        assigned = self.client.post(url + "workflow-steps/1/", {"operation": "assign", "expected_version": 1,
            "assignee": self.editor.pk, "note": "I am responsible for this measurement"}, format="json")
        self.assertEqual(assigned.status_code, 200, assigned.data)
        step = {"operation": "complete", "expected_version": 2, "confirmed": True, "note": "Measured in the lab", "values": {"concentration": 2}}
        self.assertEqual(self.client.post(url + "workflow-steps/1/", step, format="json").status_code, 400)
        step["values"]["concentration"] = 43
        self.assertEqual(self.client.post(url + "workflow-steps/1/", step, format="json").status_code, 200)
        self.assertEqual(self.client.post(url + "transition/", {"status": "COMPLETED"}).status_code, 200)
        resumed = self.client.get("/api/v1/onboarding/").data["experiment"]
        self.assertEqual(resumed["status"], "COMPLETED")
        self.assertEqual(resumed["steps"][0]["status"], "COMPLETED")

    def test_picker_only_includes_active_writable_workflows(self):
        ExperimentTemplate.objects.create(notebook=self.notebook, name="No steps", created_by=self.owner)
        ExperimentTemplate.objects.create(notebook=self.notebook, name="Inactive", active=False, workflow_steps=self.template.workflow_steps, created_by=self.owner)
        response = self.client.get("/api/experiment-templates/?for_onboarding=1&page_size=1")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.template.pk)
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get("/api/experiment-templates/?for_onboarding=1").data["count"], 0)
        self.assertEqual(self.start().status_code, 404)
        self.assertFalse(Experiment.objects.exists())

    def test_inactive_blank_workflow_invalid_title_and_missing_template_rejected(self):
        for changes in [{"title": " "}, {"title": "x" * 256}, {"template": -1}]:
            self.assertEqual(self.start(**changes).status_code, 400)
        self.assertEqual(self.start(template=99999).status_code, 404)
        self.template.active = False
        self.template.save()
        self.assertEqual(self.start().status_code, 404)
        self.template.active = True
        self.template.workflow_steps = []
        self.template.save()
        self.assertEqual(self.start().status_code, 404)
        self.assertFalse(ExperimentOnboarding.objects.exists())

    def test_revoked_notebook_access_does_not_leak_progress(self):
        self.start()
        self.notebook.editors.remove(self.editor)
        self.assertIsNone(self.client.get("/api/onboarding/").data["experiment"])
        self.assertEqual(self.start().status_code, 404)
        self.notebook.readers.add(self.editor)
        self.assertFalse(self.client.get("/api/onboarding/").data["experiment"]["can_write"])
        self.client.force_authenticate(self.owner)
        self.assertIsNone(self.client.get("/api/onboarding/").data["experiment"])

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=True)
    def test_disabled_module_and_anonymous_are_blocked(self):
        settings = SystemSettings.load()
        settings.notebook_enabled = False
        settings.save()
        self.assertEqual(self.client.get("/api/onboarding/").data, {"enabled": False, "experiment": None})
        self.assertEqual(self.start().status_code, 404)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get("/api/onboarding/").status_code, (401, 403))
        self.assertIn(self.start().status_code, (401, 403))

    def test_creation_failure_rolls_back_experiment_steps_audit_and_progress(self):
        before = Event.objects.count()
        with patch("notebook.services.create_revision", side_effect=RuntimeError("simulated failure")):
            with self.assertRaises(RuntimeError):
                self.start()
        self.assertFalse(Experiment.objects.exists())
        self.assertFalse(ExperimentOnboarding.objects.exists())
        self.assertFalse(Notification.objects.exists())
        self.assertEqual(Event.objects.count(), before)
