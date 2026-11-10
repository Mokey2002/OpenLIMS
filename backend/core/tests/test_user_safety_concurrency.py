import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, local
from unittest import SkipTest
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import close_old_connections, connection
from django.test import Client, TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from core.user_safety import active_administrators, user_administration
from events.models import Event


class AdministratorSafetyConcurrencyTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        if connection.vendor != "postgresql":
            if os.environ.get("REQUIRE_POSTGRES_TESTS") == "1":
                raise AssertionError("Administrator safety concurrency requires PostgreSQL")
            raise SkipTest("Requires PostgreSQL row locking")
        super().setUpClass()

    def setUp(self):
        User = get_user_model()
        self.admins = [User.objects.create_superuser(f"safety-owner-{index}", password=None) for index in range(2)]

    def race(self, method, body=None, *, target_other=False):
        ready = Barrier(2, timeout=10)

        @contextmanager
        def start_together():
            ready.wait()
            with user_administration():
                yield

        def change(index):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '15s'")
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=self.admins[index].pk))
                target = self.admins[1 - index] if target_other else self.admins[index]
                return getattr(client, method)(f"/api/admin-users/{target.pk}/", body or {}, format="json").status_code
            finally:
                connection.close()

        with patch("core.views.user_administration", start_together):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(change, index) for index in range(2)]
                results = [future.result(timeout=30) for future in futures]
        self.assertEqual(active_administrators().count(), 1)
        self.assertEqual(Event.objects.filter(entity_type="User").count(), 1)
        return results

    def test_concurrent_self_deactivation_cannot_remove_both_administrators(self):
        self.assertCountEqual(self.race("patch", {"is_active": False}), [200, 409])

    def test_concurrent_self_deletion_cannot_remove_both_administrators(self):
        self.assertCountEqual(self.race("delete"), [204, 409])

    def test_concurrent_mutual_demotion_rechecks_the_waiting_actor(self):
        self.assertCountEqual(self.race("patch", {"role": "viewer"}, target_other=True), [200, 403])

    def test_group_based_administrators_cannot_demote_themselves_concurrently(self):
        group = Group.objects.create(name="admin")
        for user in self.admins:
            user.is_superuser = user.is_staff = False
            user.save()
            user.groups.add(group)
        self.assertCountEqual(self.race("patch", {"role": "viewer"}), [200, 409])

    def test_django_admin_and_api_share_the_same_safeguard(self):
        from django.contrib.admin.models import LogEntry

        first, second = self.admins
        native = Client()
        native.force_login(second)
        ready = Barrier(2, timeout=10)
        thread = local()

        @contextmanager
        def start_together():
            if not getattr(thread, "started", False):
                thread.started = True
                ready.wait()
            with user_administration():
                yield

        def api_change():
            client = APIClient()
            client.force_authenticate(get_user_model().objects.get(pk=first.pk))
            return client.patch(f"/api/admin-users/{first.pk}/", {"is_active": False}, format="json").status_code

        def native_change():
            return native.post(reverse("admin:auth_user_change", args=[second.pk]), {
                "username": second.username, "is_active": "", "is_staff": "on", "is_superuser": "on",
                "date_joined_0": second.date_joined.strftime("%Y-%m-%d"),
                "date_joined_1": second.date_joined.strftime("%H:%M:%S"), "_save": "Save",
            }).status_code

        def run(action):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '15s'")
                return action()
            finally:
                connection.close()

        with patch("core.views.user_administration", start_together), patch("core.admin.user_administration", start_together):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(run, action) for action in [api_change, native_change]]
                results = [future.result(timeout=30) for future in futures]
        self.assertIn(results, [[200, 200], [409, 302]])
        self.assertEqual(active_administrators().count(), 1)
        self.assertEqual(Event.objects.filter(entity_type="User").count() + LogEntry.objects.count(), 1)
