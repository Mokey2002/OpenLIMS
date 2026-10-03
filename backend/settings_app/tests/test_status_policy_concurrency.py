import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import SkipTest

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from events.models import Event
from samples.workflows import ALLOWED_TRANSITIONS
from settings_app.models import SampleStatusPolicy


class StatusPolicyConcurrencyTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        if connection.vendor != "postgresql":
            if os.environ.get("REQUIRE_POSTGRES_TESTS") == "1":
                raise AssertionError("Policy concurrency requires PostgreSQL")
            raise SkipTest("Requires PostgreSQL row locking")
        super().setUpClass()

    def test_competing_first_saves_cannot_overwrite_each_other(self):
        admin = get_user_model().objects.create_superuser("policy-race-admin", "admin@example.org", None)
        ready = Barrier(2, timeout=10)

        def save():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '15s'")
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=admin.pk))
                ready.wait()
                response = client.patch("/api/sample-status-policy/", {
                    "expected_revision": 1, "transitions": ALLOWED_TRANSITIONS,
                    "reason": "Concurrent administrator policy update",
                }, format="json")
                return response.status_code
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(save), pool.submit(save)]
            results = [future.result(timeout=30) for future in futures]
        self.assertCountEqual(results, [200, 409])
        self.assertEqual(SampleStatusPolicy.objects.get(pk=1).revision, 2)
        self.assertEqual(Event.objects.filter(action="SAMPLE_STATUS_POLICY_UPDATED").count(), 1)
