import hashlib
import json

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from events.models import Event
from notebook.models import Experiment, ExperimentRevision, Notebook
from notebook.services import create_revision, revision_payload
from samples.models import Sample


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
class RevisionAuditTests(APITestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser("revision-audit-owner", password=None)
        self.client.force_authenticate(self.actor)
        self.notebook = Notebook.objects.create(name="Protein studies", owner=self.actor)
        self.experiment = Experiment.objects.create(notebook=self.notebook, title="Protein quality", created_by=self.actor)
        self.blocks = [{"block_type": "RICH_TEXT", "data": {"text": "Initial observations"}}]
        self.path = f"/api/v1/experiments/{self.experiment.pk}/autosave/"

    def events(self):
        return Event.objects.filter(entity_type="experiment", entity_id=str(self.experiment.public_id))

    def save(self, **changes):
        return self.client.post(self.path, {"blocks": self.blocks, "links": [], **changes}, format="json")

    def test_a_replayed_save_with_the_old_base_returns_the_original_receipt(self):
        first = self.save()
        initial = first.data["revision"]["public_id"]
        blocks = [{"block_type": "RICH_TEXT", "data": {"text": "Updated observations"}}]
        changed = self.save(blocks=blocks, expected_revision_public_id=initial)
        self.assertTrue(changed.data["created"])
        retry = self.save(blocks=blocks, expected_revision_public_id=initial)
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertFalse(retry.data["created"])
        self.assertEqual(retry.data["experiment_status"], "IN_PROGRESS")
        self.assertEqual(retry.data["revision"]["public_id"], changed.data["revision"]["public_id"])
        self.assertEqual(self.experiment.revisions.count(), 2)
        self.assertEqual(self.events().count(), 2)

    def test_a_genuinely_different_stale_edit_still_cannot_overwrite_a_collaborator(self):
        initial = self.save().data["revision"]["public_id"]
        self.save(blocks=[{"block_type": "RICH_TEXT", "data": {"text": "Collaborator results"}}], expected_revision_public_id=initial)
        stale = self.save(blocks=[{"block_type": "RICH_TEXT", "data": {"text": "Outdated results"}}], expected_revision_public_id=initial)
        self.assertEqual(stale.status_code, 400, stale.data)
        self.assertEqual(self.experiment.revisions.count(), 2)
        self.assertEqual(self.events().count(), 2)

    def test_link_reordering_and_legacy_checksums_do_not_create_phantom_revisions(self):
        samples = [Sample.objects.create(sample_id=code, created_by=self.actor) for code in ["PROTEIN-Z", "PROTEIN-A"]]
        links = [{"entity_type": "sample", "entity_public_id": str(sample.public_id), "relation_type": "used"} for sample in samples]
        revision, _ = create_revision(experiment=self.experiment, actor=self.actor, blocks=self.blocks, links=links)
        original = revision_payload(revision)
        ordered = sorted(original["links"], key=lambda row: row["entity_public_id"], reverse=True)
        # Reproduce the pre-fix hashing scheme in an existing immutable row.
        legacy_hash = hashlib.sha256(json.dumps({"blocks": original["blocks"], "links": ordered},
            sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        ExperimentRevision.objects.filter(pk=revision.pk).update(checksum=legacy_hash)
        for order in [ordered, list(reversed(ordered))]:
            result = self.save(blocks=original["blocks"], links=order, expected_revision_public_id=str(revision.public_id))
            self.assertEqual(result.status_code, 200, result.data)
            self.assertFalse(result.data["created"])
            self.assertEqual(result.data["revision"]["checksum"], legacy_hash)
        self.assertEqual(self.experiment.revisions.count(), 1)
        self.assertEqual(self.events().count(), 1)

    def test_real_edits_have_revision_numbers_and_readable_change_counts(self):
        first = self.save().data["revision"]
        response = self.save(blocks=[
            {"block_type": "RICH_TEXT", "data": {"text": "Changed observations"}},
            {"block_type": "HEADING", "data": {"text": "Results"}},
        ], expected_revision_public_id=first["public_id"])
        self.assertTrue(response.data["created"])
        event = self.events().latest("pk")
        self.assertEqual(event.payload["before"]["revision"], 1)
        self.assertEqual(event.payload["after"]["revision"], 2)
        self.assertEqual(event.payload["details"]["changes"]["blocks_added"], 1)
        self.assertEqual(event.payload["details"]["changes"]["blocks_modified"], 1)
        result = self.client.get(f"/api/events/{event.pk}/")
        self.assertEqual(result.data["entity_label"], "Protein quality")
        self.assertIn("Revision 1 → 2", result.data["description"])

    def test_unchanged_retries_do_not_reopen_or_modify_a_draft(self):
        revision = self.save().data["revision"]
        Experiment.objects.filter(pk=self.experiment.pk).update(status="DRAFT")
        response = self.save(expected_revision_public_id=revision["public_id"])
        self.assertFalse(response.data["created"])
        self.assertEqual(response.data["experiment_status"], "DRAFT")
        self.experiment.refresh_from_db()
        self.assertEqual(self.experiment.status, "DRAFT")
        self.assertEqual(self.events().count(), 1)

    def test_locked_experiments_still_reject_even_an_identical_retry(self):
        revision = self.save().data["revision"]
        Experiment.objects.filter(pk=self.experiment.pk).update(status="LOCKED")
        response = self.save(expected_revision_public_id=revision["public_id"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.events().count(), 1)
