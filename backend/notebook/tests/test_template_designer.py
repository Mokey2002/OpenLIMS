from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from notebook.models import Notebook, ExperimentTemplate, Experiment
from events.models import Event
from settings_app.models import SystemSettings


class TemplateDesignerTests(APITestCase):
    def setUp(self):
        settings = SystemSettings.load()
        settings.notebook_enabled = True
        settings.save()
        self.owner = get_user_model().objects.create_user(username="template-owner")
        self.reader = get_user_model().objects.create_user(username="template-reader")
        self.notebook = Notebook.objects.create(name="Bench", owner=self.owner, scope="USER")
        self.notebook.readers.add(self.reader)
        self.template = ExperimentTemplate.objects.create(notebook=self.notebook, name="Protocol", blocks=[{"block_type": "HEADING", "data": {"text": "Original"}}])
        self.url = f"/api/experiment-templates/{self.template.pk}/"
        self.client.force_authenticate(self.owner)

    def test_edit_changes_future_experiments_only_and_rejects_stale_editor(self):
        first = self.client.post(self.url + "instantiate/", {}, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        stamp = self.client.get(self.url).data["updated_at"]
        blocks = [{"block_type": "HEADING", "data": {"text": "New section"}}, {"block_type": "CHECKLIST", "data": {"items": []}}]
        updated = self.client.patch(self.url, {"blocks": blocks, "expected_updated_at": stamp}, format="json")
        self.assertEqual(updated.status_code, 200, updated.data)
        stale = self.client.patch(self.url, {"blocks": [], "expected_updated_at": stamp}, format="json")
        self.assertEqual(stale.status_code, 400)
        self.assertEqual(Experiment.objects.get(pk=first.data["id"]).current_revision.blocks.first().data["text"], "Original")
        second = self.client.post(self.url + "instantiate/", {}, format="json")
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(Experiment.objects.get(pk=second.data["id"]).current_revision.blocks.first().data["text"], "New section")
        self.assertTrue(Event.objects.filter(action="EXPERIMENT_TEMPLATE_UPDATED").exists())

    def test_reader_cannot_edit_delete_or_instantiate(self):
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.patch(self.url, {"blocks": []}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url + "instantiate/", {}, format="json").status_code, 403)

    def test_inactive_template_rejected_on_both_creation_paths(self):
        self.template.active = False
        self.template.save()
        self.assertEqual(self.client.post(self.url + "instantiate/", {}, format="json").status_code, 400)
        response = self.client.post("/api/experiments/", {"notebook": self.notebook.pk, "title": "Bypass", "template": self.template.pk}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Experiment.objects.exists())
