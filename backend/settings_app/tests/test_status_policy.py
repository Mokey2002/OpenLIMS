from copy import deepcopy
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from events.models import Event
from samples.models import Sample
from samples.workflows import ALLOWED_TRANSITIONS, get_allowed_transitions
from settings_app.models import SampleStatusPolicy


class StatusPolicyTests(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("policy-admin", "admin@example.org", "secret")
        self.tech = get_user_model().objects.create_user("policy-tech")
        self.tech.groups.add(Group.objects.get_or_create(name="tech")[0])
        self.client.force_authenticate(self.admin)
        self.url = "/api/sample-status-policy/"

    def save(self, transitions=None, revision=1, reason="Lab requires processing before cancellation"):
        return self.client.patch(self.url, {"transitions": transitions if transitions is not None else deepcopy(ALLOWED_TRANSITIONS),
            "expected_revision": revision, "reason": reason}, format="json")

    def test_default_get_does_not_create_policy(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["transitions"], ALLOWED_TRANSITIONS)
        self.assertEqual(response.data["revision"], 1)
        self.assertFalse(SampleStatusPolicy.objects.exists())

    def test_save_audit_enforcement_and_restore(self):
        sample = Sample.objects.create(sample_id="CONFIG-1", created_by=self.admin)
        transitions = deepcopy(ALLOWED_TRANSITIONS)
        transitions["RECEIVED"] = ["IN_PROGRESS"]
        response = self.save(transitions)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["revision"], 2)
        sample.refresh_from_db()
        self.assertEqual(sample.status, "RECEIVED")
        self.assertEqual(get_allowed_transitions("RECEIVED"), ["IN_PROGRESS"])
        allowed = self.client.get(f"/api/samples/{sample.pk}/allowed-transitions/")
        self.assertEqual(allowed.data["allowed_transitions"], ["IN_PROGRESS"])
        event = Event.objects.get(action="SAMPLE_STATUS_POLICY_UPDATED")
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.payload["after"]["transitions"], transitions)
        self.assertEqual(self.client.patch(f"/api/samples/{sample.pk}/", {"status": "CANCELLED", "reason": "Testing a blocked transition"}, format="json").status_code, 400)
        self.assertEqual(self.save(revision=2).status_code, 200)
        self.assertEqual(get_allowed_transitions("RECEIVED"), ALLOWED_TRANSITIONS["RECEIVED"])

    def test_direct_transition_and_bulk_respect_policy(self):
        sample = Sample.objects.create(sample_id="BULK-1", created_by=self.admin)
        transitions = deepcopy(ALLOWED_TRANSITIONS)
        transitions["RECEIVED"] = ["IN_PROGRESS"]
        self.save(transitions)
        response = self.client.post(f"/api/samples/{sample.pk}/transition/", {"status": "CANCELLED", "reason": "Test blocked cancellation"}, format="json")
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/samples/bulk-update/", {"ids": [sample.pk], "status": "CANCELLED", "reason": "Test blocked cancellation"}, format="json")
        sample.refresh_from_db()
        self.assertEqual(sample.status, "RECEIVED")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["updated"], 0)
        self.assertEqual(len(response.data["skipped"]), 1)

    def test_stale_revision_cannot_overwrite(self):
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(self.save().status_code, 409)
        self.assertEqual(SampleStatusPolicy.objects.get(pk=1).revision, 2)
        self.assertEqual(Event.objects.filter(action="SAMPLE_STATUS_POLICY_UPDATED").count(), 1)

    def test_validation_rejects_bypasses_dead_ends_and_unknown_codes(self):
        for source, targets in [("RECEIVED", ["REPORTED"]), ("QC", ["RECEIVED"]), ("ARCHIVED", ["RECEIVED"]),
                                ("IN_PROGRESS", []), ("QC", ["REPORTED", "REPORTED"]), ("QC", "REPORTED")]:
            with self.subTest(source=source, targets=targets):
                transitions = deepcopy(ALLOWED_TRANSITIONS)
                transitions[source] = targets
                self.assertEqual(self.save(transitions).status_code, 400)
        self.assertEqual(self.save({}).status_code, 400)
        self.assertEqual(self.save(reason=" ").status_code, 400)
        self.assertFalse(SampleStatusPolicy.objects.exists())

    def test_permissions(self):
        self.client.force_authenticate(self.tech)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.save().status_code, 403)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(self.url).status_code, (401, 403))
        self.assertIn(self.save().status_code, (401, 403))

    def test_audit_failure_rolls_back_policy(self):
        with patch("settings_app.status_policy.Event.objects.create", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.save()
        self.assertFalse(SampleStatusPolicy.objects.exists())
