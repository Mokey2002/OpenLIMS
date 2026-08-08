from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APITestCase

from events.models import Event

from assistant.actions import propose_action
from assistant.models import AssistantAction


class AssistantActionConfirmationTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="assistant-tech",
            password="test-password",
        )
        tech_group, _ = Group.objects.get_or_create(name="tech")
        self.user.groups.add(tech_group)
        self.client.force_authenticate(self.user)

    def create_report_action(self):
        return propose_action(
            user=self.user,
            action_type=AssistantAction.ACTION_QUEUE_REPORT,
            summary="Queue operations report",
            payload={
                "report_type": "OPERATIONS_SUMMARY",
                "filters": {},
            },
        )

    @patch("assistant.actions.generate_assistant_report.delay")
    def test_proposal_never_executes_without_confirmation(self, delay_mock):
        action = self.create_report_action()

        delay_mock.assert_not_called()
        self.assertEqual(action.status, AssistantAction.STATUS_PROPOSED)
        self.assertTrue(
            Event.objects.filter(
                entity_id=str(action.id),
                action="ASSISTANT_ACTION_PROPOSED",
            ).exists()
        )

    @patch("assistant.actions.generate_assistant_report.delay")
    def test_confirmation_queues_once_and_is_idempotent(self, delay_mock):
        action = self.create_report_action()
        url = f"/api/assistant/actions/{action.confirmation_token}/confirm/"

        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.post(url, {"confirm": True}, format="json")

        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.data["status"], AssistantAction.STATUS_QUEUED)
        delay_mock.assert_called_once_with(str(action.id))

        with self.captureOnCommitCallbacks(execute=True):
            second = self.client.post(url, {"confirm": True}, format="json")

        self.assertEqual(second.status_code, 202)
        delay_mock.assert_called_once()

    def test_confirmation_requires_explicit_true(self):
        action = self.create_report_action()
        url = f"/api/assistant/actions/{action.confirmation_token}/confirm/"

        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, 400)
        action.refresh_from_db()
        self.assertEqual(action.status, AssistantAction.STATUS_PROPOSED)

    def test_confirmation_token_is_bound_to_requesting_user(self):
        action = self.create_report_action()
        other = get_user_model().objects.create_user(
            username="other-user",
            password="test-password",
        )
        other.groups.add(Group.objects.get(name="tech"))
        self.client.force_authenticate(other)

        response = self.client.post(
            f"/api/assistant/actions/{action.confirmation_token}/confirm/",
            {"confirm": True},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        action.refresh_from_db()
        self.assertEqual(action.status, AssistantAction.STATUS_PROPOSED)

    def test_expired_action_cannot_execute(self):
        action = self.create_report_action()
        action.expires_at = timezone.now() - timedelta(seconds=1)
        action.save(update_fields=["expires_at"])

        response = self.client.post(
            f"/api/assistant/actions/{action.confirmation_token}/confirm/",
            {"confirm": True},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        action.refresh_from_db()
        self.assertEqual(action.status, AssistantAction.STATUS_EXPIRED)
