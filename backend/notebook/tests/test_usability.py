from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from notebook.models import Notebook, Experiment
from notebook.services import notify_experiment
from notifications.models import Notification


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
class UsabilityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner")
        self.reader = User.objects.create_user(username="reader")
        self.outsider = User.objects.create_user(username="outsider")
        self.notebook = Notebook.objects.create(name="Aurora private notebook", scope="USER", owner=self.owner)
        self.experiment = Experiment.objects.create(notebook=self.notebook, title="Aurora trial", created_by=self.owner)
        self.client = APIClient()

    def test_search_respects_explicit_access_and_links(self):
        self.client.force_authenticate(self.outsider)
        result = self.client.get("/api/search/?q=Aurora").data
        self.assertEqual(result["results"]["notebooks"], [])
        self.assertEqual(result["results"]["experiments"], [])
        self.notebook.readers.add(self.reader)
        self.client.force_authenticate(self.reader)
        result = self.client.get("/api/search/?q=Aurora").data
        self.assertEqual(result["results"]["notebooks"][0]["url"], f"/notebook?notebook={self.notebook.pk}")
        self.assertEqual(result["results"]["experiments"][0]["url"], f"/notebook?experiment={self.experiment.public_id}")
        self.notebook.readers.clear()
        self.assertEqual(self.client.get("/api/search/?q=Aurora").data["results"]["experiments"], [])

    def test_notification_excludes_actor_duplicates_and_inaccessible_users(self):
        self.notebook.readers.add(self.reader)
        notify_experiment(self.experiment, self.owner, [self.owner, self.reader, self.reader, self.outsider], "Assigned", "Open experiment")
        self.assertEqual(list(Notification.objects.values_list("user_id", flat=True)), [self.reader.pk])

    def test_assignment_notifies_only_new_assignee(self):
        self.notebook.readers.add(self.reader)
        self.client.force_authenticate(self.owner)
        url = f"/api/experiments/{self.experiment.pk}/"
        response = self.client.patch(url, {"assignees": [self.reader.pk]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Notification.objects.filter(user=self.reader).count(), 1)
        self.client.patch(url, {"title": "Aurora renamed", "assignees": [self.reader.pk]}, format="json")
        self.assertEqual(Notification.objects.filter(user=self.reader).count(), 1)

    def test_completion_notifies_reviewer_once(self):
        from notebook.services import create_revision
        self.notebook.reviewers.add(self.reader)
        create_revision(experiment=self.experiment, actor=self.owner,
                        blocks=[{"block_type": "RICH_TEXT", "data": {"text": "Trial results"}}], links=[], reason="Test")
        self.client.force_authenticate(self.owner)
        url = f"/api/experiments/{self.experiment.pk}/transition/"
        response = self.client.post(url, {"status": "COMPLETED"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Notification.objects.filter(user=self.reader).count(), 1)
        self.assertEqual(self.client.post(url, {"status": "COMPLETED"}, format="json").status_code, 400)
        self.assertEqual(Notification.objects.filter(user=self.reader).count(), 1)

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=True)
    def test_disabled_notebook_module_is_not_searchable(self):
        from settings_app.models import SystemSettings
        settings = SystemSettings.load()
        settings.notebook_enabled = False
        settings.save()
        self.client.force_authenticate(self.owner)
        result = self.client.get("/api/search/?q=Aurora").data
        self.assertEqual(result["results"]["notebooks"], [])
        self.assertEqual(result["results"]["experiments"], [])
