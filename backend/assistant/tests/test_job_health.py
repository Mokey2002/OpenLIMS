from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from assistant.job_health import record_action_progress, scan_action_health
from assistant.lifecycle import finish_queued_action
from assistant.models import AssistantAction, AssistantActionAlert
from events.models import Event
from imports.models import ImportJob, InstrumentProfile
from notifications.models import Notification
from notifications.serializers import NotificationSerializer
from projects.models import Project

User = get_user_model()


@override_settings(ASSISTANT_QUEUE_STALL_SECONDS=600, ASSISTANT_PROGRESS_STALL_SECONDS=1800)
class AssistantJobHealthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("job-requester", password=None)
        cls.user.groups.add(Group.objects.get_or_create(name="tech")[0])
        cls.other = User.objects.create_superuser("other-director", password=None)
        cls.project = Project.objects.create(code="HEALTH", name="Protein job health")
        cls.project.members.add(cls.user)
        cls.instrument = InstrumentProfile.objects.create(code="HEALTH-SEQ", name="Protein sequencer", sample_id_column="sample_id")
        cls.job = ImportJob.objects.create(instrument=cls.instrument, project=cls.project, uploaded_by=cls.user)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def action(self, *, age=1200, **overrides):
        timestamp = timezone.now() - timedelta(seconds=age)
        defaults = {"requested_by": self.user, "action_type": "QUEUE_IMPORT", "status": "QUEUED",
                    "summary": "Import protein sequencer results", "result": {"import_job_id": self.job.pk, "url": "/imports"},
                    "expires_at": timezone.now() + timedelta(hours=1), "confirmed_at": timestamp,
                    "last_progress_at": timestamp,
                    "progress": {"current_step": "Waiting for worker", "last_completed_step": "Source mapping checked"}}
        defaults.update(overrides)
        return AssistantAction.objects.create(**defaults)

    def test_stalled_queue_notifies_only_requester_once_and_preserves_job_state(self):
        action = self.action()
        result = scan_action_health()
        self.assertEqual(result["delivered"], 1)
        notice = Notification.objects.get()
        self.assertEqual(notice.user_id, self.user.pk)
        self.assertIn("Source mapping checked", notice.message)
        self.assertIn("may still be running", notice.message)
        self.assertEqual(scan_action_health()["delivered"], 0)
        action.refresh_from_db(); self.job.refresh_from_db()
        self.assertEqual(action.status, "QUEUED")
        self.assertEqual(self.job.status, "PENDING")
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(AssistantActionAlert.objects.get().kind, "STALLED")

    def test_deleting_a_notification_does_not_recreate_the_same_alert(self):
        self.action()
        scan_action_health()
        Notification.objects.all().delete()
        self.assertEqual(scan_action_health()["delivered"], 0)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(AssistantActionAlert.objects.count(), 1)

    def test_fresh_jobs_and_recent_progress_do_not_alert(self):
        action = self.action(age=1)
        self.assertEqual(scan_action_health()["delivered"], 0)
        self.job.status = "RUNNING"; self.job.save()
        AssistantAction.objects.filter(pk=action.pk).update(last_progress_at=timezone.now() - timedelta(minutes=20))
        self.assertEqual(scan_action_health()["delivered"], 0)

    def test_running_job_metadata_updates_do_not_mask_a_real_checkpoint_stall(self):
        action = self.action(age=1900, progress={"current_step": "Importing rows", "last_completed_step": "24 rows committed"})
        self.job.status = "RUNNING"; self.job.save()
        self.assertEqual(scan_action_health()["delivered"], 1)
        action.refresh_from_db()
        self.assertEqual(action.progress["last_completed_step"], "24 rows committed")

    def test_checkpoint_recovery_resolves_the_old_stall_without_marking_the_job_complete(self):
        action = self.action()
        scan_action_health()
        record_action_progress(action_type="QUEUE_IMPORT", result_key="import_job_id", result_id=self.job.pk,
            current_step="Importing rows", last_completed_step="25 rows committed", current=25, total=100)
        action.refresh_from_db()
        self.assertEqual(action.status, "QUEUED")
        self.assertEqual(action.progress["current"], 25)
        self.assertIsNotNone(AssistantActionAlert.objects.get().resolved_at)
        self.assertEqual(scan_action_health()["delivered"], 0)

    def test_failure_and_worker_redelivery_create_one_failure_notice_and_audit_event(self):
        action = self.action()
        for _ in range(2):
            finish_queued_action(action_type="QUEUE_IMPORT", result_key="import_job_id", result_id=self.job.pk,
                                 succeeded=False, error_message="CSV mapping is invalid")
        action.refresh_from_db()
        self.assertEqual(action.status, "FAILED")
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(AssistantActionAlert.objects.get().kind, "FAILED")
        self.assertEqual(Event.objects.filter(action="ASSISTANT_ACTION_FAILED").count(), 1)
        notice = self.client.get("/api/notifications/").data["results"][0]
        self.assertEqual(notice["assistant_alert"]["snapshot"]["last_completed_step"], "Source mapping checked")
        self.assertIn("Repair rejected rows", notice["assistant_alert"]["snapshot"]["recovery_hint"])

    def test_worker_import_failure_is_not_duplicated_by_the_native_import_notice(self):
        from imports.tasks import process_import_job
        self.action()
        with patch("imports.tasks.broadcast_job_update"):
            with self.assertRaises(Exception):
                process_import_job.run(self.job.pk)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(Notification.objects.get().title, "Assistant task failed")

    def test_unmanaged_imports_keep_their_existing_failure_notice(self):
        from imports.tasks import process_import_job
        with patch("imports.tasks.broadcast_job_update"):
            with self.assertRaises(Exception):
                process_import_job.run(self.job.pk)
        self.assertEqual(Notification.objects.get().title, "Import failed")
        self.assertEqual(AssistantActionAlert.objects.count(), 0)

    def test_native_completion_reconciles_a_missed_callback_and_resolves_stall(self):
        action = self.action()
        scan_action_health()
        self.job.status = "COMPLETED"; self.job.save()
        scan_action_health()
        action.refresh_from_db()
        self.assertEqual(action.status, "COMPLETED")
        self.assertEqual(action.progress["last_completed_step"], "Results saved")
        self.assertIsNotNone(AssistantActionAlert.objects.get().resolved_at)
        self.assertEqual(Notification.objects.count(), 1)

    def test_failure_after_a_stall_sends_one_distinct_failure_notice(self):
        action = self.action()
        scan_action_health()
        finish_queued_action(action_type="QUEUE_IMPORT", action_id=action.pk, succeeded=False, error_message="Invalid file")
        self.assertEqual(Notification.objects.count(), 2)
        self.assertCountEqual(AssistantActionAlert.objects.values_list("kind", flat=True), ["STALLED", "FAILED"])
        self.assertIsNotNone(AssistantActionAlert.objects.get(kind="STALLED").resolved_at)

    def test_offboarded_or_revoked_users_do_not_receive_private_job_progress(self):
        action = self.action()
        self.project.members.remove(self.user)
        self.assertEqual(scan_action_health()["delivered"], 0)
        health = self.client.get(f"/api/assistant/jobs/{action.pk}/").data["health"]
        self.assertFalse(health["accessible"])
        self.assertNotIn("Source mapping checked", str(health))
        self.user.is_active = False; self.user.save()
        self.assertEqual(scan_action_health()["delivered"], 0)

    def test_task_status_and_alert_notifications_are_requester_only_even_for_another_admin(self):
        action = self.action()
        scan_action_health()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/assistant/jobs/{action.pk}/").status_code, 404)
        self.assertEqual(self.client.get("/api/notifications/").data["count"], 0)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(f"/api/v1/assistant/jobs/{action.pk}/").status_code, 200)

    def test_management_command_needs_no_celery_worker_or_redis_connection(self):
        self.action()
        output = StringIO()
        with patch("celery.app.base.Celery.send_task", side_effect=AssertionError("Monitor must not use Celery")), \
             patch("redis.Redis.execute_command", side_effect=AssertionError("Monitor must not require Redis")), \
             patch("redis.asyncio.Redis.execute_command", side_effect=AssertionError("Monitor must not require Redis")):
            call_command("monitor_assistant_actions", stdout=output)
        self.assertIn("1 alerts delivered", output.getvalue())

    def test_bounded_monitor_cursor_advances_past_previously_alerted_jobs(self):
        actions = [self.action() for _ in range(3)]
        first = scan_action_health(limit=1)
        second = scan_action_health(limit=1, after_id=first["cursor"])
        third = scan_action_health(limit=1, after_id=second["cursor"])
        self.assertEqual([first["delivered"], second["delivered"], third["delivered"]], [1, 1, 1])
        self.assertEqual(Notification.objects.count(), len(actions))

    def test_alert_serialization_has_no_per_row_job_or_actor_lookups(self):
        for _ in range(3): self.action()
        scan_action_health()
        rows = Notification.objects.select_related("assistant_alert__action")
        with self.assertNumQueries(1):
            data = NotificationSerializer(rows, many=True).data
        self.assertEqual(len(data), 3)

    def test_report_task_replays_do_not_create_duplicate_completion_events(self):
        from assistant.tasks import generate_assistant_report
        action = self.action(action_type="QUEUE_REPORT", requested_by=self.other, result={})
        generate_assistant_report.run(str(action.pk))
        generate_assistant_report.run(str(action.pk))
        action.refresh_from_db()
        self.assertEqual(action.status, "COMPLETED")
        self.assertIn("report", action.result)
        self.assertEqual(Event.objects.filter(action="ASSISTANT_ACTION_COMPLETED").count(), 1)

    def test_running_atomic_import_uses_progress_timeout_even_before_its_job_transaction_commits(self):
        self.action(age=1200, progress={"current_step": "Validating and importing in one transaction", "last_completed_step": "Worker received confirmed import"})
        self.assertEqual(self.job.status, "PENDING")
        self.assertEqual(scan_action_health()["delivered"], 0)

    def test_report_worker_rechecks_revoked_administrator_access(self):
        from assistant.tasks import generate_assistant_report
        action = self.action(action_type="QUEUE_REPORT", result={})
        with self.assertRaises(PermissionError):
            generate_assistant_report.run(str(action.pk))
        action.refresh_from_db()
        self.assertEqual(action.status, "FAILED")
        self.assertNotIn("report", action.result)
        self.assertEqual(Notification.objects.get().title, "Assistant task failed")

    def test_recent_native_failure_is_found_without_waiting_for_stall_timeout(self):
        action = self.action(age=1)
        self.job.status = "FAILED"; self.job.save()
        self.assertEqual(scan_action_health()["delivered"], 1)
        action.refresh_from_db()
        self.assertEqual(action.status, "FAILED")
        self.assertEqual(Notification.objects.count(), 1)

    def test_blast_worker_redelivery_does_not_duplicate_failure_notifications(self):
        from blast.models import BlastDatabase, BlastJob
        from blast.tasks import run_blast_job_task
        from sequences.models import Sequence
        sequence = Sequence.objects.create(name="Protein query", sequence="ATGC", created_by=self.user, project=self.project)
        database = BlastDatabase.objects.create(name="Health database", created_by=self.user)
        job = BlastJob.objects.create(name="Health BLAST", query_sequence=sequence, database=database, project=self.project, created_by=self.user)
        self.action(action_type="RUN_BLAST", result={"blast_job_id": job.pk})
        with patch("blast.tasks.run_blast_job", side_effect=RuntimeError("Tool unavailable")), patch("blast.tasks.broadcast_blast_job_update"):
            for _ in range(2):
                with self.assertRaises(RuntimeError): run_blast_job_task.run(job.pk)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(Notification.objects.get().title, "Assistant task failed")

    def test_alignment_worker_redelivery_does_not_duplicate_failure_notifications(self):
        from alignments.models import AlignmentJob
        from alignments.tasks import run_alignment_job
        job = AlignmentJob.objects.create(name="Health alignment", project=self.project, created_by=self.user)
        self.action(action_type="RUN_ALIGNMENT", result={"alignment_job_id": job.pk})
        with patch("alignments.tasks.run_clustal_omega_alignment", side_effect=RuntimeError("Tool unavailable")), patch("alignments.tasks.broadcast_alignment_job_update"):
            for _ in range(2):
                with self.assertRaises(RuntimeError): run_alignment_job.run(job.pk)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(Notification.objects.get().title, "Assistant task failed")

    def test_failure_after_source_access_revocation_returns_only_a_generic_owner_notice(self):
        action = self.action()
        self.project.members.remove(self.user)
        finish_queued_action(action_type="QUEUE_IMPORT", action_id=action.pk, succeeded=False, error_message="Private source failure detail")
        notice = Notification.objects.get()
        self.assertNotIn("Source mapping checked", notice.message)
        self.assertNotIn("Private source failure detail", str(notice.assistant_alert.snapshot))
        response = self.client.get(f"/api/assistant/jobs/{action.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["result"], {})
        self.assertEqual(response.data["preview"], {})
        self.assertEqual(response.data["error_message"], "")

    def test_malformed_legacy_progress_does_not_break_monitoring_or_status_rendering(self):
        action = self.action(progress={"current_step": {}, "last_completed_step": ["old"], "current": {}}, result=[])
        self.assertEqual(scan_action_health()["delivered"], 1)
        health = self.client.get(f"/api/assistant/jobs/{action.pk}/").data["health"]
        self.assertIsInstance(health["current_step"], str)
        self.assertIsInstance(health["last_completed_step"], str)
        self.assertIsNone(health["progress_current"])

    def test_live_job_details_require_a_current_application_read_role(self):
        action = self.action()
        self.user.groups.clear()
        self.assertTrue(self.project.members.filter(pk=self.user.pk).exists())
        self.assertEqual(scan_action_health()["delivered"], 0)
        response = self.client.get(f"/api/assistant/jobs/{action.pk}/")
        self.assertFalse(response.data["health"]["accessible"])
        self.assertEqual(response.data["result"], {})
