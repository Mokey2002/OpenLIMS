"""Exercise the actual PostgreSQL locks through concurrent HTTP requests."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import SkipTest
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from core import access_requests
from core.models import AccessRequest
from events.models import Event
from notifications.models import Notification
from projects.models import Project


class AccessRequestConcurrencyTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        if connection.vendor != "postgresql":
            if os.environ.get("REQUIRE_POSTGRES_TESTS") == "1":
                raise AssertionError("Access request concurrency requires PostgreSQL")
            raise SkipTest("Requires PostgreSQL row locking")
        super().setUpClass()

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("access-race-requester")
        self.admin = get_user_model().objects.create_superuser("access-race-admin", password=None)
        self.project = Project.objects.create(code="RACE", name="Concurrent reviews")

    def post(self, user_id, path, payload):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10s'")
                cursor.execute("SET statement_timeout = '15s'")
            client = APIClient()
            client.force_authenticate(get_user_model().objects.get(pk=user_id))
            response = client.post(path, payload, format="json")
            return response.status_code, response.data
        finally:
            connection.close()

    def parallel(self, calls, service):
        ready = Barrier(len(calls), timeout=10)
        original = getattr(access_requests, service)

        def start_together(*args, **kwargs):
            ready.wait()
            return original(*args, **kwargs)

        with patch.object(access_requests, service, side_effect=start_together):
            with ThreadPoolExecutor(max_workers=len(calls)) as pool:
                futures = [pool.submit(self.post, *call) for call in calls]
                return [future.result(timeout=30) for future in futures]

    def pending(self):
        status, data = self.post(self.user.pk, "/api/access-requests/", {
            "kind": "PROJECT", "project_code": "RACE", "reason": "Join this laboratory project",
        })
        self.assertEqual(status, 201, data)
        return data["id"]

    def decision(self, request_id, decision):
        return self.admin.pk, f"/api/access-requests/{request_id}/review/", {
            "decision": decision, "decision_reason": "Reviewed with the laboratory manager",
            "project_public_id": str(self.project.public_id),
        }

    def test_simultaneous_submissions_have_one_pending_request_and_receipt(self):
        call = (self.user.pk, "/api/access-requests/", {
            "kind": "PROJECT", "project_code": "RACE", "reason": "Join this laboratory project",
        })
        results = self.parallel([call, call], "submit")
        self.assertCountEqual([status for status, _ in results], [201, 200])
        self.assertEqual(results[0][1]["id"], results[1][1]["id"])
        self.assertEqual(AccessRequest.objects.count(), 1)
        self.assertEqual(Event.objects.filter(action="ACCESS_REQUEST_SUBMITTED").count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.admin).count(), 1)
        self.assertFalse(self.project.members.exists())

    def test_simultaneous_approvals_grant_and_notify_once(self):
        request_id = self.pending()
        call = self.decision(request_id, "APPROVED")
        results = self.parallel([call, call], "review")
        self.assertEqual([status for status, _ in results], [200, 200])
        self.assertEqual(self.project.members.count(), 1)
        self.assertEqual(Event.objects.filter(action="ACCESS_REQUEST_APPROVED").count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)

    def test_conflicting_reviews_choose_one_terminal_decision(self):
        request_id = self.pending()
        results = self.parallel([
            self.decision(request_id, "APPROVED"), self.decision(request_id, "REJECTED"),
        ], "review")
        self.assertCountEqual([status for status, _ in results], [200, 409])
        row = AccessRequest.objects.get(pk=request_id)
        self.assertEqual(self.project.members.filter(pk=self.user.pk).exists(), row.status == "APPROVED")
        self.assertEqual(Event.objects.filter(action__in=["ACCESS_REQUEST_APPROVED", "ACCESS_REQUEST_REJECTED"]).count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)
