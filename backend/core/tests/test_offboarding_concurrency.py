from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from threading import Barrier
from unittest import SkipTest
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from core.models import UserSessionState
from core.user_safety import active_administrators, user_administration
from events.models import Event

User = get_user_model()


class OffboardingConcurrencyTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        if connection.vendor != "postgresql":
            if os.environ.get("REQUIRE_POSTGRES_TESTS") == "1":
                raise AssertionError("Offboarding concurrency requires PostgreSQL")
            raise SkipTest("Requires PostgreSQL row locking")
        super().setUpClass()

    def setUp(self):
        self.first = User.objects.create_superuser("offboarding-first", password=None)
        self.second = User.objects.create_superuser("offboarding-second", password=None)
        self.target = User.objects.create_user("offboarding-target", password=None)

    def prepare(self, actor, target):
        client = APIClient()
        client.force_authenticate(actor)
        response = client.post(f"/api/admin-users/{target.pk}/offboarding/preview/", {"reason": "Planned laboratory account departure"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["preview_id"]

    def race(self, operations):
        ready = Barrier(2, timeout=15)

        @contextmanager
        def start_together():
            ready.wait()
            with user_administration():
                yield

        def confirm(operation):
            actor_id, target_id, preview = operation
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '20s'")
                client = APIClient()
                client.force_authenticate(User.objects.get(pk=actor_id))
                return client.post(f"/api/admin-users/{target_id}/offboarding/confirm/", {"preview_id": preview, "confirmed": True}, format="json")
            finally:
                connection.close()

        with patch("core.offboarding.user_administration", start_together):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(confirm, operation) for operation in operations]
                return [future.result(timeout=40) for future in futures]

    def test_simultaneous_confirmation_returns_one_receipt_and_one_revocation(self):
        preview = self.prepare(self.first, self.target)
        operations = [(self.first.pk, self.target.pk, preview)] * 2
        responses = self.race(operations)
        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual(responses[0].data, responses[1].data)
        self.assertEqual(UserSessionState.objects.get(user=self.target).generation, 1)
        self.assertEqual(Event.objects.filter(action="USER_OFFBOARDED").count(), 1)

    def test_mutual_offboarding_cannot_remove_all_administrators(self):
        first_preview = self.prepare(self.first, self.second)
        second_preview = self.prepare(self.second, self.first)
        responses = self.race([(self.first.pk, self.second.pk, first_preview), (self.second.pk, self.first.pk, second_preview)])
        self.assertCountEqual([response.status_code for response in responses], [200, 403])
        self.assertEqual(active_administrators().count(), 1)
        self.assertEqual(Event.objects.filter(action="USER_OFFBOARDED").count(), 1)
