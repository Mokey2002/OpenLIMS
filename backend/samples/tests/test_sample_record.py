from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from rest_framework.test import APITestCase

from events.models import Event
from notebook.models import Notebook, Experiment, ExperimentRevision, ExperimentLink, ExperimentWorkflowStep
from projects.models import Project
from samples.models import Sample
from settings_app.models import SystemSettings


class SampleRecordTests(APITestCase):
    def setUp(self):
        self.reader = get_user_model().objects.create_user("sample-reader")
        self.owner = get_user_model().objects.create_user("notebook-owner")
        self.reader.groups.add(Group.objects.get_or_create(name="viewer")[0])
        self.project = Project.objects.create(code="RECORD", name="Sample record")
        self.project.members.add(self.reader)
        self.sample = Sample.objects.create(sample_id="RECORD-1", project=self.project)
        self.other = Sample.objects.create(sample_id="PRIVATE-1")
        self.notebook = Notebook.objects.create(name="Private notebook", owner=self.owner)
        self.experiment = Experiment.objects.create(notebook=self.notebook, title="Extraction", created_by=self.owner)
        self.revision = ExperimentRevision.objects.create(experiment=self.experiment, number=1, checksum="a")
        self.experiment.current_revision = self.revision
        self.experiment.save()
        ExperimentLink.objects.create(revision=self.revision, entity_type="sample", entity_public_id=self.sample.public_id, label="Source")
        self.client.force_authenticate(self.reader)

    def get(self, section, sample=None, query=""):
        return self.client.get(f"/api/samples/{(sample or self.sample).pk}/{section}/{query}")

    def test_sample_access_required_for_both_sections(self):
        for section in ("history", "experiments"):
            self.assertEqual(self.get(section, self.other).status_code, 404)

    def test_history_paginates_and_accepts_both_identifier_formats(self):
        baseline = self.get("history").data["count"]
        old = Event.objects.create(entity_type="Sample", entity_id=str(self.sample.pk), action="CREATED")
        new = Event.objects.create(entity_type="sample", entity_id=str(self.sample.public_id), action="UPDATED")
        for _ in range(55):
            Event.objects.create(entity_type="Sample", entity_id=str(self.other.pk), action="PRIVATE")
        Event.objects.create(entity_type="Experiment", entity_id=str(self.sample.pk), action="PRIVATE")
        response = self.get("history", query="?page_size=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], baseline + 2)
        self.assertEqual(response.data["results"][0]["id"], new.pk)
        page2 = self.client.get(response.data["next"])
        self.assertEqual(page2.data["results"][0]["id"], old.pk)
        seen = [new.pk, old.pk]
        while page2.data["next"]:
            page2 = self.client.get(page2.data["next"])
            seen.extend(row["id"] for row in page2.data["results"])
        self.assertEqual(len(set(seen)), baseline + 2)

    def test_private_notebook_does_not_leak_count_or_title(self):
        response = self.get("experiments")
        self.assertEqual(response.data["count"], 0)
        self.assertNotIn("Extraction", str(response.data))

    def test_explicit_reader_sees_current_link_once_and_workflow_progress(self):
        self.notebook.readers.add(self.reader)
        ExperimentLink.objects.create(revision=self.revision, entity_type="sample", entity_public_id=self.sample.public_id, label="Output", relation_type="produced")
        for position, status in enumerate(["COMPLETED", "PENDING"], 1):
            ExperimentWorkflowStep.objects.create(experiment=self.experiment, position=position, definition={"name": "Step"}, status=status)
        response = self.get("experiments", query="?page_size=1")
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["public_id"], str(self.experiment.public_id))
        self.assertEqual((row["completed_steps"], row["step_count"]), (1, 2))

    def test_removed_historical_link_not_presented_as_current(self):
        self.notebook.readers.add(self.reader)
        revision2 = ExperimentRevision.objects.create(experiment=self.experiment, number=2, checksum="b")
        self.experiment.current_revision = revision2
        self.experiment.save()
        self.assertEqual(self.get("experiments").data["count"], 0)

    def test_experiment_pagination_and_revoked_access(self):
        self.notebook.readers.add(self.reader)
        experiment = Experiment.objects.create(notebook=self.notebook, title="Second", created_by=self.owner)
        revision = ExperimentRevision.objects.create(experiment=experiment, number=1, checksum="c")
        experiment.current_revision = revision
        experiment.save()
        ExperimentLink.objects.create(revision=revision, entity_type="sample", entity_public_id=self.sample.public_id, label="Sample")
        response = self.get("experiments", query="?page_size=1")
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 1)
        second = self.client.get(response.data["next"])
        self.assertNotEqual(response.data["results"][0]["public_id"], second.data["results"][0]["public_id"])
        self.assertIsNone(second.data["next"])
        self.notebook.readers.remove(self.reader)
        self.assertEqual(self.get("experiments").data["count"], 0)

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=True)
    def test_disabled_notebook_module_does_not_leak_experiments(self):
        self.notebook.readers.add(self.reader)
        settings = SystemSettings.load()
        settings.notebook_enabled = False
        settings.save()
        self.assertEqual(self.get("experiments").data["count"], 0)

    def test_anonymous_cannot_read_sections(self):
        self.client.force_authenticate(None)
        for section in ("history", "experiments"):
            self.assertIn(self.get(section).status_code, (401, 403))
