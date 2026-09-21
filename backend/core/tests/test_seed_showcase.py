from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase

from alignments.models import AlignmentJob
from core.management.commands.seed_showcase import CODE
from mass_spec.models import MassSpecRun
from notebook.models import Experiment
from projects.models import Project
from results.models import WorkItem, Result
from samples.models import Sample


class ShowcaseTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="presenter", password="test-only")

    def test_connected_demo_and_preserved_rerun(self):
        call_command("seed_demo", showcase_only=True, owner=self.owner.username)
        project = Project.objects.get(code=CODE)
        self.assertEqual(project.samples.count(), 6)
        experiment = Experiment.objects.get(notebook__project=project)
        self.assertEqual(experiment.status, "COMPLETED")
        self.assertEqual(experiment.current_revision.links.count(), 6)
        self.assertEqual(Result.objects.filter(work_item__sample__project=project).count(), 12)
        self.assertEqual(WorkItem.objects.filter(sample__project=project, status="PENDING").count(), 1)
        self.assertEqual(Sample.objects.filter(project=project, status="QC").get().sample_id, "AUR-006")
        self.assertEqual(MassSpecRun.objects.filter(project=project, status="COMPLETED").count(), 3)
        alignment = AlignmentJob.objects.get(project=project)
        strings = [line for line in alignment.aligned_fasta.splitlines() if not line.startswith(">")]
        self.assertEqual(len(set(map(len, strings))), 1)
        self.assertEqual(sum(len(set(column)) > 1 for column in zip(*strings)), 1)
        sample = Sample.objects.get(sample_id="AUR-001")
        sample.status = "IN_PROGRESS"
        sample.save()
        call_command("seed_showcase", owner=self.owner.username)
        sample.refresh_from_db()
        self.assertEqual(sample.status, "IN_PROGRESS")
        self.assertEqual(project.samples.count(), 6)
        self.assertEqual(experiment.revisions.count(), 1)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password("test-only"))
        self.assertFalse(self.owner.is_superuser)
        self.assertEqual(self.owner.groups.count(), 0)

    def test_missing_owner_and_collision_do_not_write(self):
        with self.assertRaises(CommandError):
            call_command("seed_showcase", owner="missing")
        self.assertFalse(Project.objects.exists())
        Sample.objects.create(sample_id="AUR-001")
        with self.assertRaises(CommandError):
            call_command("seed_showcase", owner=self.owner.username)
        self.assertFalse(Project.objects.exists())
        self.assertEqual(Sample.objects.count(), 1)

    def test_failure_rolls_back(self):
        from unittest.mock import patch
        with patch("core.management.commands.seed_showcase.create_revision", side_effect=ValueError("failure")):
            with self.assertRaises(ValueError):
                call_command("seed_showcase", owner=self.owner.username)
        self.assertFalse(Project.objects.exists())
        self.assertFalse(Sample.objects.exists())
        self.assertFalse(MassSpecRun.objects.exists())
