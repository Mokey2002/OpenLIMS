from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import InventoryAlert
from notifications.models import Notification
from projects.models import Project
from results.models import WorkItem
from samples.models import Sample


User = get_user_model()


class PerformanceV029Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="performance-director",
            password="test-password",
            is_staff=True,
            is_superuser=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.project = Project.objects.create(name="Performance Project", code="PERF")

    def test_my_work_response_is_bounded_while_counts_cover_all_records(self):
        for index in range(25):
            sample = Sample.objects.create(
                sample_id=f"PERF-{index:03d}",
                project=self.project,
                created_by=self.user,
            )
            WorkItem.objects.create(
                sample=sample,
                name=f"Performance work {index}",
                work_type=f"PERF-{index}",
                assigned_to=self.user,
                created_by=self.user,
                status=WorkItem.STATUS_PENDING,
            )

        for index in range(7):
            Notification.objects.create(
                user=self.user,
                title=f"Notification {index}",
                message="Performance notification",
            )

        InventoryAlert.objects.create(
            alert_type=InventoryAlert.TYPE_REORDER,
            message="Performance alert",
            status=InventoryAlert.STATUS_OPEN,
            deduplication_key="performance-v029-alert",
        )

        response = self.client.get("/api/v1/my-work/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"]["assigned"], 25)
        self.assertEqual(response.data["summary"]["unread_notifications"], 7)
        self.assertEqual(response.data["summary"]["inventory_alerts"], 1)
        self.assertEqual(len(response.data["assigned_work"]), 12)
        self.assertEqual(len(response.data["notifications"]), 5)

    def test_session_bootstrap_combines_shell_state(self):
        Notification.objects.create(
            user=self.user,
            title="Unread",
            message="Unread notification",
        )
        Notification.objects.create(
            user=self.user,
            title="Read",
            message="Read notification",
            is_read=True,
        )

        response = self.client.get("/api/v1/session/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["username"], self.user.username)
        self.assertEqual(response.data["unread_notification_count"], 1)
        self.assertIn("notebook", response.data["feature_flags"])
        self.assertIn("registry", response.data["feature_flags"])

    def test_performance_endpoints_require_authentication(self):
        anonymous = APIClient()
        self.assertEqual(anonymous.get("/api/v1/session/").status_code, 401)
        self.assertEqual(anonymous.get("/api/v1/my-work/").status_code, 401)
