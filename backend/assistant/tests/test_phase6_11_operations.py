import shutil
import tempfile
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.models import (
    BarcodeLabel,
    GeneratedArtifact,
    NotificationDelivery,
    NotificationSubscription,
    SOPDocument,
)
from assistant.notification_operations import dispatch_subscription
from events.models import Event
from inventory.models import InventoryItem, InventoryLot
from notifications.models import Notification
from projects.models import Project
from results.models import WorkItem
from samples.models import Sample, SampleBatch


class AssistantPhaseSixToElevenTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_dir = tempfile.mkdtemp(prefix="openlims-phase611-test-")
        cls.settings_override = override_settings(MEDIA_ROOT=cls.media_dir)
        cls.settings_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.settings_override.disable()
        shutil.rmtree(cls.media_dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        user_model = get_user_model()
        self.tech = user_model.objects.create_user(username="eduardo", first_name="Eduardo")
        self.maria = user_model.objects.create_user(username="maria", first_name="Maria")
        self.outsider = user_model.objects.create_user(username="outsider")
        self.admin = user_model.objects.create_superuser(username="admin", email="admin@example.com", password="password")
        tech_group, _ = Group.objects.get_or_create(name="tech")
        viewer_group, _ = Group.objects.get_or_create(name="viewer")
        self.tech.groups.add(tech_group)
        self.maria.groups.add(tech_group)
        self.outsider.groups.add(viewer_group)
        self.project = Project.objects.create(code="ALPHA", name="Alpha")
        self.project.members.add(self.tech, self.maria)
        self.batch = SampleBatch.objects.create(code="B-100", project=self.project, created_by=self.tech)
        self.samples = [
            Sample.objects.create(sample_id=f"S-{number}", project=self.project, batch=self.batch, created_by=self.tech)
            for number in range(100, 103)
        ]
        self.client.force_authenticate(self.tech)

    def chat(self, message, context=None):
        return self.client.post(
            "/api/assistant/chat/",
            {"message": message, "context": context or {}},
            format="json",
        )

    def confirm(self, response):
        token = response.data["pending_action"]["confirmation_token"]
        return self.client.post(
            f"/api/assistant/actions/{token}/confirm/",
            {"confirm": True},
            format="json",
        )

    def test_phase6_read_only_overdue_work_is_project_filtered(self):
        WorkItem.objects.create(
            sample=self.samples[0],
            name="Sequencing work",
            work_type="SEQUENCING",
            due_at=timezone.now() - timedelta(hours=2),
            created_by=self.tech,
        )
        other_project = Project.objects.create(code="PRIVATE", name="Private")
        private_sample = Sample.objects.create(sample_id="S-PRIVATE", project=other_project)
        WorkItem.objects.create(
            sample=private_sample,
            name="Sequencing work",
            work_type="SEQUENCING",
            due_at=timezone.now() - timedelta(hours=2),
        )

        response = self.chat("Show overdue sequencing work")

        self.assertEqual(response.status_code, 200)
        self.assertIn("S-100", response.data["answer"])
        self.assertNotIn("S-PRIVATE", response.data["answer"])
        self.assertNotIn("pending_action", response.data)

    def test_pending_blast_context_yields_to_explicit_non_sequence_request(self):
        response = self.chat(
            "Count samples by status",
            context={
                "intent": "RUN_BLAST",
                "request_text": "Prepare BLAST",
                "program": "blastn",
            },
        )

        self.assertIn("RECEIVED", response.data["answer"])
        self.assertNotIn("BLAST", response.data["answer"])
        self.assertNotIn("pending_action", response.data)

    def test_bare_tell_me_is_not_treated_as_notification_subscription(self):
        response = self.chat("Tell me count samples by status")

        self.assertIn("RECEIVED", response.data["answer"])
        self.assertNotIn("notification trigger", response.data["answer"])

    def test_phase6_create_work_uses_frozen_samples_detects_duplicates_and_replays_once(self):
        WorkItem.objects.create(
            sample=self.samples[0],
            name="Sequencing work",
            work_type="SEQUENCING",
            created_by=self.tech,
        )

        proposal = self.chat("Create sequencing work for samples in batch B-100")

        self.assertEqual(proposal.status_code, 200)
        preview = proposal.data["pending_action"]["preview"]
        self.assertEqual(preview["records_affected"], 2)
        self.assertEqual(preview["excluded_count"], 1)

        new_sample = Sample.objects.create(
            sample_id="S-NEW",
            project=self.project,
            batch=self.batch,
            created_by=self.tech,
        )
        first = self.confirm(proposal)
        second = self.confirm(proposal)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(WorkItem.objects.filter(work_type="SEQUENCING").count(), 3)
        self.assertFalse(WorkItem.objects.filter(sample=new_sample, work_type="SEQUENCING").exists())
        self.assertEqual(Event.objects.filter(action="WORK_ITEM_CREATED").count(), 2)

    def test_phase6_create_reports_concurrent_duplicate_and_continues_batch(self):
        proposal = self.chat("Create sequencing work for samples in batch B-100")
        WorkItem.objects.create(
            sample=self.samples[0],
            name="Concurrent sequencing work",
            work_type="SEQUENCING",
            created_by=self.maria,
        )

        result = self.confirm(proposal)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["result"]["succeeded_count"], 2)
        self.assertEqual(result.data["result"]["failed_count"], 1)
        self.assertEqual(
            result.data["result"]["failed"][0]["reason"],
            "duplicate active work exists",
        )

    def test_phase6_assignment_rechecks_status_and_reports_partial_failure(self):
        due = timezone.make_aware(datetime.combine(timezone.localdate(), time(hour=12)))
        items = [
            WorkItem.objects.create(sample=sample, name="Sequencing work", work_type="SEQUENCING", due_at=due, created_by=self.tech)
            for sample in self.samples[:2]
        ]
        proposal = self.chat("Assign today's sequencing work to Maria")
        self.assertEqual(proposal.data["pending_action"]["preview"]["records_affected"], 2)

        items[0].status = WorkItem.STATUS_COMPLETED
        items[0].save(update_fields=["status"])
        result = self.confirm(proposal)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["result"]["succeeded_count"], 1)
        self.assertEqual(result.data["result"]["failed_count"], 1)
        items[1].refresh_from_db()
        self.assertEqual(items[1].assigned_to, self.maria)

    def test_phase7_generates_downloadable_pdf_and_unique_resolvable_barcodes(self):
        proposal = self.chat("Create barcode labels for batch B-100")
        self.assertEqual(proposal.status_code, 200)
        preview = proposal.data["pending_action"]["preview"]
        self.assertEqual(preview["proposed_values"]["output"], "Downloadable PDF")
        self.assertEqual(preview["records_affected"], 3)

        result = self.confirm(proposal)

        self.assertEqual(result.status_code, 200)
        artifact = GeneratedArtifact.objects.get(id=result.data["result"]["artifact_id"])
        self.assertEqual(artifact.kind, GeneratedArtifact.KIND_LABEL_PDF)
        with artifact.file.open("rb") as stream:
            self.assertEqual(stream.read(4), b"%PDF")
        self.assertEqual(BarcodeLabel.objects.count(), 3)
        self.assertEqual(BarcodeLabel.objects.values("barcode").distinct().count(), 3)
        self.assertEqual(Event.objects.filter(action="LABEL_GENERATED").count(), 3)

        download = self.client.get(result.data["result"]["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download["Content-Type"], "application/pdf")

    def test_phase7_reprint_is_explicit_and_audited(self):
        first = self.chat("Create barcode labels for sample S-100")
        self.confirm(first)
        second = self.chat("Regenerate the damaged label for sample S-100")

        self.assertEqual(second.data["pending_action"]["preview"]["current_values"]["previously_generated"], 1)
        result = self.confirm(second)

        self.assertEqual(result.data["result"]["reprint_count"], 1)
        self.assertTrue(Event.objects.filter(action="LABEL_REPRINTED").exists())

    def test_phase8_csv_filters_are_previewed_stored_and_reproducible(self):
        event = Event.objects.create(
            entity_type="Sample",
            entity_id=str(self.samples[0].id),
            action="STATUS_CHANGED",
            actor=self.tech,
            payload={"sample_code": self.samples[0].sample_id, "project_id": self.project.id},
        )
        Event.objects.filter(pk=event.pk).update(
            timestamp=timezone.make_aware(datetime(timezone.localdate().year, 8, 15, 12))
        )
        proposal = self.chat("Export sample status changes from August as CSV")
        filters = proposal.data["pending_action"]["preview"]["current_values"]
        self.assertEqual(filters["report_type"], "SAMPLE_STATUS_CHANGES")
        self.assertEqual(filters["output_format"], "CSV")
        self.assertEqual(filters["timezone"], "UTC")

        result = self.confirm(proposal)
        artifact = GeneratedArtifact.objects.get(id=result.data["result"]["artifact_id"])

        self.assertEqual(artifact.parameters, result.data["result"]["stored_filters"])
        self.assertEqual(artifact.kind, GeneratedArtifact.KIND_REPORT_CSV)
        self.assertTrue(Event.objects.filter(action="REPORT_GENERATED", entity_id=str(artifact.id)).exists())
        with artifact.file.open("rb") as stream:
            content = stream.read().decode("utf-8")
        self.assertIn("Stored filters", content)
        self.assertIn("STATUS_CHANGED", content)

    def test_phase8_pdf_report_respects_project_access(self):
        proposal = self.chat("Generate a PDF report for Project Alpha")
        self.assertEqual(proposal.status_code, 200)
        result = self.confirm(proposal)
        self.assertEqual(result.status_code, 200)
        artifact = GeneratedArtifact.objects.get(id=result.data["result"]["artifact_id"])
        self.assertEqual(artifact.project, self.project)

        self.client.force_authenticate(self.outsider)
        denied = self.chat("Generate a PDF report for Project Alpha")
        self.assertNotIn("pending_action", denied.data)
        self.assertIn("not accessible", denied.data["answer"])
        self.assertEqual(self.client.get(result.data["result"]["download_url"]).status_code, 403)

    def test_phase8_unscoped_report_does_not_leak_other_users_unscoped_events(self):
        Event.objects.create(
            entity_type="AssistantAction",
            entity_id="private-other-action",
            action="ASSISTANT_ACTION_COMPLETED",
            actor=self.outsider,
            payload={"detail": "PRIVATE OTHER USER EVENT"},
        )

        proposal = self.chat("Export assistant action history as CSV")
        result = self.confirm(proposal)
        artifact = GeneratedArtifact.objects.get(id=result.data["result"]["artifact_id"])
        with artifact.file.open("rb") as stream:
            content = stream.read().decode("utf-8")

        self.assertNotIn("PRIVATE OTHER USER EVENT", content)
        self.assertIn("eduardo", content)

    def test_phase9_answers_only_from_current_approved_accessible_sops_with_citations(self):
        SOPDocument.objects.create(
            document_code="SOP-SAMPLE-001",
            title="Sample receipt",
            version="3",
            section="4.2 Receive a sample",
            content="Verify the identifier, record the received time, and place the sample in its validated location.",
            approved=True,
            status=SOPDocument.STATUS_CURRENT,
            uploaded_by=self.admin,
        )
        SOPDocument.objects.create(
            document_code="SOP-SAMPLE-OLD",
            title="Old sample receipt",
            version="1",
            section="2",
            content="Use the archived process.",
            approved=True,
            status=SOPDocument.STATUS_ARCHIVED,
            uploaded_by=self.admin,
        )

        response = self.chat("How do I receive a sample?")

        self.assertIn("SOP-SAMPLE-001 version 3, section 4.2 Receive a sample", response.data["answer"])
        self.assertNotIn("archived process", response.data["answer"])
        self.assertEqual(response.data["citations"][0]["version"], "3")
        self.assertNotIn("pending_action", response.data)

    def test_phase9_restricted_sop_and_missing_answer_are_not_exposed(self):
        qc_group, _ = Group.objects.get_or_create(name="qc_reviewer")
        document = SOPDocument.objects.create(
            document_code="SOP-SECRET-001",
            title="Restricted sequencing import",
            version="1",
            section="1",
            content="Restricted sequencing import instruction.",
            approved=True,
            uploaded_by=self.admin,
        )
        document.allowed_groups.add(qc_group)

        response = self.chat("Which SOP applies to sequencing imports?")

        self.assertIn("does not contain an answer", response.data["answer"])
        self.assertNotIn("Restricted", response.data["answer"])

    def test_phase10_duplicate_subscription_is_prevented_and_can_be_listed_cancelled(self):
        proposal = self.chat("Alert me when reagent R-100 falls below 10 units")
        self.assertIn("not found", proposal.data["answer"])
        item = InventoryItem.objects.create(code="R-100", name="Reagent", category=InventoryItem.CATEGORY_REAGENT, default_unit="mL")

        proposal = self.chat("Alert me when reagent R-100 falls below 10 units")
        created = self.confirm(proposal)
        subscription_id = created.data["result"]["subscription_id"]
        duplicate = self.chat("Alert me when reagent R-100 falls below 10 units")
        self.assertIn("identical active notification", duplicate.data["answer"])

        listed = self.chat("List my notification subscriptions")
        self.assertIn(f"#{subscription_id}", listed.data["answer"])

        cancel = self.chat(f"Cancel notification {subscription_id}")
        self.confirm(cancel)
        self.assertFalse(NotificationSubscription.objects.get(id=subscription_id).active)
        self.assertTrue(Event.objects.filter(action="NOTIFICATION_CANCELLED").exists())
        recreated = self.confirm(self.chat("Alert me when reagent R-100 falls below 10 units"))
        self.assertNotEqual(recreated.data["result"]["subscription_id"], subscription_id)
        self.assertEqual(item.code, "R-100")

    def test_phase10_delivery_rechecks_permissions_and_prevents_duplicate_delivery(self):
        item = InventoryItem.objects.create(code="R-100", name="Reagent", category=InventoryItem.CATEGORY_REAGENT, default_unit="mL")
        InventoryLot.objects.create(item=item, lot_code="L-1", quantity=Decimal("5"), unit="mL")
        subscription = NotificationSubscription.objects.create(
            trigger="INVENTORY_BELOW",
            recipient=self.tech,
            delivery_channel=NotificationSubscription.CHANNEL_IN_APP,
            frequency=NotificationSubscription.FREQUENCY_DAILY,
            expires_at=timezone.now() + timedelta(days=2),
            target_type="InventoryItem",
            target_id=str(item.id),
            threshold=Decimal("10"),
            deduplication_key="inventory-test",
            next_run_at=timezone.now() - timedelta(minutes=1),
            created_by=self.tech,
        )

        first = dispatch_subscription(subscription)
        subscription.refresh_from_db()
        subscription.next_run_at = timezone.now() - timedelta(minutes=1)
        subscription.save(update_fields=["next_run_at"])
        second = dispatch_subscription(subscription)

        self.assertEqual(first.id, second.id)
        self.assertTrue(first.permission_rechecked)
        self.assertEqual(NotificationDelivery.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.tech).count(), 1)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_phase10_email_channel_delivers_to_configured_recipient(self):
        self.tech.email = "eduardo@example.com"
        self.tech.save(update_fields=["email"])
        item = InventoryItem.objects.create(code="R-EMAIL", name="Email reagent", category=InventoryItem.CATEGORY_REAGENT, default_unit="mL")
        InventoryLot.objects.create(item=item, lot_code="L-EMAIL", quantity=Decimal("1"), unit="mL")
        subscription = NotificationSubscription.objects.create(
            trigger="INVENTORY_BELOW",
            recipient=self.tech,
            delivery_channel=NotificationSubscription.CHANNEL_EMAIL,
            frequency=NotificationSubscription.FREQUENCY_ONCE,
            target_type="InventoryItem",
            target_id=str(item.id),
            threshold=Decimal("2"),
            deduplication_key="email-test",
            next_run_at=timezone.now() - timedelta(minutes=1),
            created_by=self.tech,
        )

        delivery = dispatch_subscription(subscription)

        self.assertEqual(delivery.status, NotificationDelivery.STATUS_DELIVERED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["eduardo@example.com"])
        self.assertEqual(Notification.objects.filter(user=self.tech).count(), 0)

    def test_phase10_delivery_is_skipped_and_audited_when_project_access_is_removed(self):
        subscription = NotificationSubscription.objects.create(
            trigger="SAMPLE_APPROVED",
            recipient=self.maria,
            delivery_channel=NotificationSubscription.CHANNEL_IN_APP,
            frequency=NotificationSubscription.FREQUENCY_ONCE,
            expires_at=timezone.now() + timedelta(days=2),
            project=self.project,
            target_type="Sample",
            target_id=str(self.samples[0].id),
            deduplication_key="permission-test",
            next_run_at=timezone.now() - timedelta(minutes=1),
            created_by=self.tech,
        )
        self.project.members.remove(self.maria)

        delivery = dispatch_subscription(subscription)

        self.assertEqual(delivery.status, NotificationDelivery.STATUS_SKIPPED)
        self.assertTrue(delivery.permission_rechecked)
        subscription.refresh_from_db()
        self.assertFalse(subscription.active)
        self.assertTrue(Event.objects.filter(action="NOTIFICATION_SKIPPED").exists())

    @patch("assistant.monitoring._backup_status", return_value={"status": "stale", "latest_age_hours": 48, "link": "/system-status?check=backups"})
    @patch("assistant.monitoring._storage_status", return_value={"status": "warning", "used_percent": 91, "free_bytes": 100, "link": "/system-status?check=storage"})
    @patch("assistant.monitoring._job_failures", return_value={"imports": {"recent_failed": 1, "stuck": 0, "link": "/imports?status=FAILED"}, "blast": {"recent_failed": 0, "stuck": 0, "link": "/blast?status=FAILED"}, "alignments": {"recent_failed": 0, "stuck": 0, "link": "/alignments?status=FAILED"}})
    @patch("assistant.monitoring._worker_status", return_value={"availability": "unavailable", "workers": 0, "queue_depth": 2, "active_tasks": 0})
    @patch("assistant.monitoring._check_redis", return_value="available")
    @patch("assistant.monitoring._check_database", return_value="available")
    def test_phase11_admin_monitoring_is_read_only_sanitized_and_links_warnings(self, *_mocks):
        self.client.force_authenticate(self.admin)
        before_events = Event.objects.count()
        response = self.chat("Show system status")

        self.assertEqual(response.status_code, 200)
        monitoring = response.data["monitoring"]
        self.assertTrue(monitoring["read_only"])
        self.assertEqual(monitoring["queue_depth"], 2)
        self.assertNotIn("SECRET_KEY", str(monitoring))
        self.assertNotIn("DATABASE_URL", str(monitoring))
        self.assertTrue(all(link["url"].startswith("/") for link in response.data["links"]))
        self.assertEqual(Event.objects.count(), before_events)

    def test_phase11_non_admin_cannot_view_monitoring_details(self):
        response = self.chat("Show system status")
        self.assertIn("only to authorized administrators", response.data["answer"])
        self.assertNotIn("monitoring", response.data)
        self.assertEqual(self.client.get("/api/assistant/system-monitoring/").status_code, 403)
