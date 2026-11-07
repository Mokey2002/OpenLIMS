import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import SkipTest
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from events.models import Event
from samples.models import Sample
from samples.views import SampleViewSet


class SampleTransitionConcurrencyTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        if connection.vendor != "postgresql":
            if os.environ.get("REQUIRE_POSTGRES_TESTS") == "1":
                raise AssertionError("Sample transition concurrency requires PostgreSQL")
            raise SkipTest("Requires PostgreSQL row locking")
        super().setUpClass()

    def test_simultaneous_identical_transitions_record_one_change(self):
        admin = get_user_model().objects.create_superuser("transition-race-admin", password=None)
        sample = Sample.objects.create(sample_id="TRANSITION-RACE", created_by=admin)
        ready = Barrier(2, timeout=10)
        get_object = SampleViewSet.get_object

        def read_before_race(view):
            result = get_object(view)
            ready.wait()
            return result

        def transition():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '15s'")
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=admin.pk))
                response = client.post(f"/api/samples/{sample.pk}/transition/", {
                    "new_status": "IN_PROGRESS", "reason": "Start processing after accession review",
                }, format="json")
                return response.status_code
            finally:
                connection.close()

        with patch.object(SampleViewSet, "get_object", autospec=True, side_effect=read_before_race):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(transition) for _ in range(2)]
                results = [future.result(timeout=30) for future in futures]
        self.assertCountEqual(results, [200, 400])
        self.assertEqual(Event.objects.filter(action="SAMPLE_STATUS_CHANGED").count(), 1)
        sample.refresh_from_db()
        self.assertEqual(sample.status, "IN_PROGRESS")
