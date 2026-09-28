"""Failure-path tests: assert both the response and absence of side effects."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from notebook.models import Experiment, Notebook
from notebook.services import create_revision, notify_experiment
from notifications.models import Notification


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
class NotebookSafetyTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="safety-owner")
        self.reader = User.objects.create_user(username="safety-reader")
        self.outsider = User.objects.create_user(username="safety-outsider")
        self.book = Notebook.objects.create(name="Private", scope="USER", owner=self.owner)
        self.book.readers.add(self.reader)
        self.experiment = Experiment.objects.create(notebook=self.book, title="Original", created_by=self.owner)
        self.client = APIClient()
        self.url = f"/api/v1/experiments/{self.experiment.pk}/"
        self.blocks = [{"block_type": "RICH_TEXT", "data": {"text": "Original results"}}]

    def snapshot(self):
        self.experiment.refresh_from_db()
        return (self.experiment.title, self.experiment.status, self.experiment.current_revision_id,
                self.experiment.revisions.count(), Notification.objects.count())

    def test_readers_and_outsiders_cannot_mutate_via_any_write_endpoint(self):
        for user, expected in [(self.reader, 403), (self.outsider, 404)]:
            self.client.force_authenticate(user)
            for method, suffix, payload in [
                ("patch", "", {"title": "Unauthorized"}),
                ("post", "autosave/", {"blocks": self.blocks, "links": []}),
                ("post", "transition/", {"status": "IN_PROGRESS"}),
                ("post", "review/", {"decision": "APPROVED"}),
                ("post", "lock/", {}),
            ]:
                with self.subTest(user=user.username, endpoint=suffix):
                    before = self.snapshot()
                    response = getattr(self.client, method)(self.url + suffix, payload, format="json")
                    self.assertEqual(response.status_code, expected, response.data)
                    self.assertEqual(self.snapshot(), before)

    def test_invalid_transition_does_not_create_notifications_or_change_state(self):
        self.client.force_authenticate(self.owner)
        before = self.snapshot()
        for target in ["COMPLETED", "LOCKED", "REVIEWED", "UNKNOWN"]:
            response = self.client.post(self.url + "transition/", {"status": target}, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.snapshot(), before)

    def test_reviewed_and_locked_records_reject_metadata_edits(self):
        self.client.force_authenticate(self.owner)
        for state in [Experiment.STATUS_REVIEWED, Experiment.STATUS_LOCKED]:
            Experiment.objects.filter(pk=self.experiment.pk).update(status=state)
            before = self.snapshot()
            response = self.client.patch(self.url, {"title": "Changed"}, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.snapshot(), before)

    def test_notification_failure_rolls_back_assignment_and_metadata(self):
        self.client.force_authenticate(self.owner)
        before = self.snapshot()
        with patch("notebook.views.notify_experiment", side_effect=RuntimeError("notification failure")):
            with self.assertRaisesRegex(RuntimeError, "notification failure"):
                self.client.patch(self.url, {"title": "Changed", "assignees": [self.reader.pk]}, format="json")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.experiment.assignees.exists())

    def test_revision_and_notification_roll_back_together(self):
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, "abort"):
            with transaction.atomic():
                create_revision(experiment=self.experiment, actor=self.owner, blocks=self.blocks, links=[])
                notify_experiment(self.experiment, self.owner, [self.reader], "Update", "Results")
                raise RuntimeError("abort")
        self.assertEqual(self.snapshot(), before)

    def test_inactive_or_revoked_recipient_is_not_notified(self):
        self.reader.is_active = False
        self.reader.save(update_fields=["is_active"])
        notify_experiment(self.experiment, self.owner, [self.reader, self.outsider, None], "Update", "Results")
        self.assertFalse(Notification.objects.exists())
        self.reader.is_active = True
        self.reader.save(update_fields=["is_active"])
        self.book.readers.clear()
        notify_experiment(self.experiment, self.owner, [self.reader], "Update", "Results")
        self.assertFalse(Notification.objects.exists())

    def test_tied_timestamps_paginate_without_missing_or_duplicate_records(self):
        self.client.force_authenticate(self.owner)
        for index in range(5):
            Experiment.objects.create(notebook=self.book, title=f"Trial {index}", created_by=self.owner)
        Experiment.objects.update(updated_at=timezone.now())
        expected = list(Experiment.objects.order_by("-pk").values_list("pk", flat=True))
        for variant in ["", "&summary=1"]:
            actual = []
            for page in range(1, 4):
                response = self.client.get(f"/api/v1/experiments/?page_size=2&page={page}{variant}")
                self.assertEqual(response.status_code, 200)
                actual.extend(row["id"] for row in response.data["results"])
            self.assertEqual(actual, expected)
