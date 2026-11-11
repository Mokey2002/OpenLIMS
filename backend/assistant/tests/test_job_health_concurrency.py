from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
from threading import Barrier
from unittest import SkipTest

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from assistant.actions import confirm_action
from assistant.job_health import scan_action_health
from assistant.lifecycle import finish_queued_action
from assistant.models import AssistantAction, AssistantActionAlert
from imports.models import ImportJob, InstrumentProfile
from notifications.models import Notification
from projects.models import Project


@override_settings(ASSISTANT_QUEUE_STALL_SECONDS=600, ASSISTANT_PROGRESS_STALL_SECONDS=1800)
class JobHealthConcurrencyTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        if connection.vendor != "postgresql":
            if os.environ.get("REQUIRE_POSTGRES_TESTS") == "1": raise AssertionError("Job alert races require PostgreSQL")
            raise SkipTest("Requires PostgreSQL locks")
        super().setUpClass()

    def setUp(self):
        self.user = get_user_model().objects.create_user("concurrent-job-owner", password=None)
        self.user.groups.add(Group.objects.get_or_create(name="tech")[0])
        project = Project.objects.create(code="RACE", name="Concurrent alerts")
        project.members.add(self.user)
        instrument = InstrumentProfile.objects.create(code="RACE-SEQ", name="Sequencer", sample_id_column="sample_id")
        self.job = ImportJob.objects.create(project=project, instrument=instrument, uploaded_by=self.user)
        self.action = AssistantAction.objects.create(requested_by=self.user, action_type="QUEUE_IMPORT", status="QUEUED", summary="Concurrent import",
            result={"import_job_id": self.job.pk}, progress={"current_step": "Waiting for worker", "last_completed_step": "Confirmation saved"},
            last_progress_at=timezone.now() - timedelta(hours=1), expires_at=timezone.now())

    def race(self, operations):
        ready = Barrier(2, timeout=15)
        def run(operation):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '20s'")
                ready.wait()
                return operation()
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, operation) for operation in operations]
            return [future.result(timeout=35) for future in futures]

    def test_two_monitors_deliver_exactly_one_stall_notice(self):
        results = self.race([scan_action_health, scan_action_health])
        self.assertEqual(sum(result["delivered"] for result in results), 1)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(AssistantActionAlert.objects.count(), 1)

    def test_completion_and_monitor_never_leave_a_live_stall_after_success(self):
        def complete():
            return finish_queued_action(action_type="QUEUE_IMPORT", action_id=self.action.pk, succeeded=True)
        self.race([scan_action_health, complete])
        self.action.refresh_from_db()
        self.assertEqual(self.action.status, "COMPLETED")
        self.assertEqual(AssistantActionAlert.objects.filter(kind="STALLED", resolved_at__isnull=True).count(), 0)
        self.assertEqual(AssistantActionAlert.objects.filter(kind="FAILED").count(), 0)

    def test_monitor_and_confirmation_retry_share_the_owner_first_lock_order(self):
        def repeat():
            with transaction.atomic():
                return confirm_action(self.action.confirmation_token, self.user).status
        self.race([scan_action_health, repeat])
        self.assertEqual(Notification.objects.count(), 1)
        self.action.refresh_from_db()
        self.assertEqual(self.action.status, "QUEUED")
