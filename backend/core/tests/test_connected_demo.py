from io import StringIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.management.commands.seed_connected_demo import CODE, SAMPLE
from core.models import SharedAttachment
from notebook.models import Experiment
from pipelines.models import PipelineRun
from projects.models import Project
from samples.models import Sample
from settings_app.models import SystemSettings


class ConnectedDemoTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.users = {}
        for name, roles in {"director": ["admin"], "peter": ["tech"], "maria": ["tech", "qc_reviewer"], "michael": ["tech"], "viewer": ["viewer"]}.items():
            user = get_user_model().objects.create_user(name, password="preserve-this")
            user.groups.add(*(Group.objects.get_or_create(name=r)[0] for r in roles))
            self.users[name] = user
        settings = SystemSettings.load()
        settings.notebook_enabled = True
        settings.save()

    def seed(self):
        call_command("seed_connected_demo", stdout=StringIO())

    def test_connected_records_roles_and_non_destructive_rerun(self):
        self.seed()
        sample = Sample.objects.get(sample_id=SAMPLE)
        run = PipelineRun.objects.get(sample=sample)
        self.assertEqual(run.steps.get(position=1).status, "COMPLETED")
        self.assertEqual(run.steps.get(position=2).work_item.assigned_to, self.users["peter"])
        self.assertEqual(run.steps.get(position=3).status, "AWAITING_QC")
        self.assertEqual(run.steps.get(position=3).work_item.results.get().entered_by, self.users["michael"])
        self.assertIsNone(run.steps.get(position=4).work_item_id)
        experiment = Experiment.objects.get(notebook__project=sample.project)
        self.assertEqual(experiment.current_revision.links.count(), 6)
        self.assertEqual(experiment.workflow_steps.count(), 2)
        attachments = SharedAttachment.objects.filter(project=sample.project)
        self.assertEqual(attachments.count(), 4)
        with attachments.get(display_name="DEMO-360-summary.pdf").file.open("rb") as stream:
            self.assertTrue(stream.read().startswith(b"%PDF"))
        client = APIClient()
        for name, user in self.users.items():
            client.force_authenticate(user)
            self.assertEqual(client.get(f"/api/samples/{sample.pk}/").status_code, 200, name)
            self.assertEqual(client.get(f"/api/experiments/{experiment.pk}/").status_code, 200, name)
        client.force_authenticate(self.users["viewer"])
        self.assertEqual(client.patch(f"/api/samples/{sample.pk}/", {"sample_type": "OTHER"}, format="json").status_code, 403)
        sample.sample_type = "EDITED"
        sample.save()
        sample.project.members.remove(self.users["viewer"])
        self.seed()
        sample.refresh_from_db()
        self.assertEqual(sample.sample_type, "EDITED")
        self.assertFalse(sample.project.members.filter(pk=self.users["viewer"].pk).exists())
        self.assertEqual(PipelineRun.objects.filter(sample=sample).count(), 1)
        self.assertEqual(attachments.count(), 4)
        for user in self.users.values():
            user.refresh_from_db()
            self.assertTrue(user.check_password("preserve-this"))

    def test_missing_identity_and_collision_leave_database_unchanged(self):
        self.users["michael"].is_active = False
        self.users["michael"].save()
        with self.assertRaises(CommandError):
            self.seed()
        self.assertFalse(Project.objects.filter(code=CODE).exists())
        self.users["michael"].is_active = True
        self.users["michael"].save()
        Sample.objects.create(sample_id=SAMPLE)
        with self.assertRaises(CommandError):
            self.seed()
        self.assertFalse(Project.objects.filter(code=CODE).exists())

    def test_users_can_finish_the_seeded_pipeline_through_the_api(self):
        call_command("seed_demo", connected_only=True, stdout=StringIO())
        sample = Sample.objects.get(sample_id=SAMPLE)
        run = PipelineRun.objects.get(sample=sample)
        client = APIClient()
        client.force_authenticate(self.users["maria"])
        qc = run.steps.get(position=3).work_item
        response = client.post(f"/api/work-items/{qc.pk}/qc-review/", {"qc_status": "APPROVED", "review_note": "Verified synthetic QC for the walkthrough."}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(run.steps.get(position=4).work_item_id)
        for position, username, key in [(2, "peter", "amplification_status"), (4, "michael", "interpretation")]:
            client.force_authenticate(self.users[username])
            work = run.steps.get(position=position).work_item
            self.assertIsNotNone(work)
            response = client.post("/api/results/", {"work_item": work.pk, "key": key, "value_type": "STRING", "value_string": "PASS"}, format="json")
            self.assertEqual(response.status_code, 201, response.data)
            response = client.patch(f"/api/work-items/{work.pk}/", {"status": "COMPLETED"}, format="json")
            self.assertEqual(response.status_code, 200, response.data)
        run.refresh_from_db()
        self.assertEqual(run.status, "COMPLETED")

    def test_failure_rolls_back_records_and_files(self):
        with patch("projects.models.ProjectPost.objects.create", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                self.seed()
        self.assertFalse(Project.objects.filter(code=CODE).exists())
        self.assertFalse(Sample.objects.filter(sample_id=SAMPLE).exists())
        self.assertFalse(SharedAttachment.objects.exists())
        from django.conf import settings
        from pathlib import Path
        self.assertEqual([p for p in Path(settings.MEDIA_ROOT).rglob("*") if p.is_file()], [])
