from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APITestCase

from events.models import Event

from assistant.actions import EXECUTORS, propose_action
from assistant.lifecycle import finish_queued_action
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
        self.assertEqual(
            Event.objects.filter(
                entity_id=str(action.id),
                action="ASSISTANT_ACTION_CONFIRMED",
            ).count(),
            1,
        )

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
        self.assertTrue(
            Event.objects.filter(
                entity_id=str(action.id),
                action="ASSISTANT_ACTION_EXPIRED",
            ).exists()
        )

    @patch("assistant.actions.generate_assistant_report.delay")
    def test_cancelled_action_never_executes(self, delay_mock):
        action = self.create_report_action()

        first = self.client.post(
            f"/api/assistant/actions/{action.confirmation_token}/cancel/",
            {},
            format="json",
        )
        second = self.client.post(
            f"/api/assistant/actions/{action.confirmation_token}/cancel/",
            {},
            format="json",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        action.refresh_from_db()
        self.assertEqual(action.status, AssistantAction.STATUS_CANCELLED)
        delay_mock.assert_not_called()
        self.assertEqual(
            Event.objects.filter(
                entity_id=str(action.id),
                action="ASSISTANT_ACTION_CANCELLED",
            ).count(),
            1,
        )

    @patch("assistant.actions.generate_assistant_report.delay")
    def test_confirmation_requires_tech_or_admin_role(self, delay_mock):
        action = self.create_report_action()
        viewer = get_user_model().objects.create_user(
            username="assistant-viewer",
            password="test-password",
        )
        viewer_group, _ = Group.objects.get_or_create(name="viewer")
        viewer.groups.add(viewer_group)
        action.requested_by = viewer
        action.save(update_fields=["requested_by"])
        self.client.force_authenticate(viewer)

        response = self.client.post(
            f"/api/assistant/actions/{action.confirmation_token}/confirm/",
            {"confirm": True},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        action.refresh_from_db()
        self.assertEqual(action.status, AssistantAction.STATUS_PROPOSED)
        delay_mock.assert_not_called()

    def test_synchronous_completion_is_fully_audited(self):
        action = propose_action(
            user=self.user,
            action_type=AssistantAction.ACTION_CREATE_MIGRATION_MAPPINGS,
            summary="Create mappings",
            payload={"migration_job_id": 12},
        )

        def complete_executor(_action):
            return AssistantAction.STATUS_COMPLETED, {
                "migration_job_id": 12,
                "mapping_count": 4,
            }

        with patch.dict(
            EXECUTORS,
            {
                AssistantAction.ACTION_CREATE_MIGRATION_MAPPINGS: (
                    complete_executor
                )
            },
        ):
            response = self.client.post(
                f"/api/assistant/actions/{action.confirmation_token}/confirm/",
                {"confirm": True},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        action.refresh_from_db()
        self.assertEqual(action.status, AssistantAction.STATUS_COMPLETED)
        self.assertTrue(
            Event.objects.filter(
                entity_id=str(action.id),
                action="ASSISTANT_ACTION_CONFIRMED",
            ).exists()
        )
        self.assertTrue(
            Event.objects.filter(
                entity_id=str(action.id),
                action="ASSISTANT_ACTION_COMPLETED",
            ).exists()
        )

    def test_executor_failure_is_persisted_and_audited(self):
        action = propose_action(
            user=self.user,
            action_type=AssistantAction.ACTION_CREATE_MIGRATION_MAPPINGS,
            summary="Create mappings",
            payload={"migration_job_id": 12},
        )

        def failing_executor(_action):
            raise RuntimeError("Mapping generation failed")

        with patch.dict(
            EXECUTORS,
            {
                AssistantAction.ACTION_CREATE_MIGRATION_MAPPINGS: (
                    failing_executor
                )
            },
        ):
            response = self.client.post(
                f"/api/assistant/actions/{action.confirmation_token}/confirm/",
                {"confirm": True},
                format="json",
            )

        self.assertEqual(response.status_code, 400)
        action.refresh_from_db()
        self.assertEqual(action.status, AssistantAction.STATUS_FAILED)
        self.assertEqual(action.error_message, "Mapping generation failed")
        self.assertTrue(
            Event.objects.filter(
                entity_id=str(action.id),
                action="ASSISTANT_ACTION_FAILED",
            ).exists()
        )


class AssistantActionLifecycleTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="assistant-lifecycle-tech",
            password="test-password",
        )
        tech_group, _ = Group.objects.get_or_create(name="tech")
        self.user.groups.add(tech_group)

    def create_queued_action(self, *, action_type, result):
        action = propose_action(
            user=self.user,
            action_type=action_type,
            summary="Queued background action",
            payload={},
        )
        action.status = AssistantAction.STATUS_QUEUED
        action.result = result
        action.save(update_fields=["status", "result"])
        return action

    def test_background_completion_is_idempotent(self):
        action = self.create_queued_action(
            action_type=AssistantAction.ACTION_RUN_BLAST,
            result={"blast_job_id": 42, "url": "/blast"},
        )

        first = finish_queued_action(
            action_type=AssistantAction.ACTION_RUN_BLAST,
            result_key="blast_job_id",
            result_id=42,
            succeeded=True,
            result_updates={"job_status": "COMPLETED", "hits_count": 3},
        )
        second = finish_queued_action(
            action_type=AssistantAction.ACTION_RUN_BLAST,
            result_key="blast_job_id",
            result_id=42,
            succeeded=True,
            result_updates={"job_status": "COMPLETED", "hits_count": 3},
        )

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        action.refresh_from_db()
        self.assertEqual(action.status, AssistantAction.STATUS_COMPLETED)
        self.assertEqual(action.result["blast_job_id"], 42)
        self.assertEqual(action.result["hits_count"], 3)
        self.assertEqual(action.error_message, "")
        self.assertEqual(
            Event.objects.filter(
                entity_id=str(action.id),
                action="ASSISTANT_ACTION_COMPLETED",
            ).count(),
            1,
        )

    def test_background_failure_is_idempotent(self):
        action = self.create_queued_action(
            action_type=AssistantAction.ACTION_QUEUE_IMPORT,
            result={"import_job_id": 17, "url": "/imports"},
        )

        first = finish_queued_action(
            action_type=AssistantAction.ACTION_QUEUE_IMPORT,
            result_key="import_job_id",
            result_id=17,
            succeeded=False,
            error_message="CSV validation failed",
            result_updates={"job_status": "FAILED"},
        )
        second = finish_queued_action(
            action_type=AssistantAction.ACTION_QUEUE_IMPORT,
            result_key="import_job_id",
            result_id=17,
            succeeded=False,
            error_message="CSV validation failed",
            result_updates={"job_status": "FAILED"},
        )

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        action.refresh_from_db()
        self.assertEqual(action.status, AssistantAction.STATUS_FAILED)
        self.assertEqual(action.error_message, "CSV validation failed")
        self.assertEqual(
            Event.objects.filter(
                entity_id=str(action.id),
                action="ASSISTANT_ACTION_FAILED",
            ).count(),
            1,
        )
