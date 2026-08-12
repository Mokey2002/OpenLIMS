from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from inventory.models import InventoryItem, InventoryLot, InventoryReservation
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample, SampleBatch


class ManualOperationsUISupportTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        tech_group, _ = Group.objects.get_or_create(name="tech")
        viewer_group, _ = Group.objects.get_or_create(name="viewer")
        qc_group, _ = Group.objects.get_or_create(name="qc_reviewer")

        self.tech = user_model.objects.create_user(username="tech-user")
        self.viewer = user_model.objects.create_user(username="viewer-user")
        self.reviewer = user_model.objects.create_user(username="qc-user")
        self.tech.groups.add(tech_group)
        self.viewer.groups.add(viewer_group)
        self.reviewer.groups.add(qc_group)

        self.project = Project.objects.create(code="ALPHA", name="Alpha")
        self.project.members.add(self.tech, self.viewer, self.reviewer)
        self.batch = SampleBatch.objects.create(
            code="B-100",
            project=self.project,
            created_by=self.tech,
        )
        self.sample = Sample.objects.create(
            sample_id="S-100",
            project=self.project,
            batch=self.batch,
            created_by=self.tech,
        )
        self.work_item = WorkItem.objects.create(
            sample=self.sample,
            name="Sequencing work",
            work_type="SEQUENCING",
            created_by=self.tech,
        )
        self.result = Result.objects.create(
            work_item=self.work_item,
            key="concentration",
            value_type=Result.VALUE_TYPE_NUMBER,
            value_number=5.0,
            unit="ng/uL",
            reference_min=10.0,
            qc_passed=False,
        )

        item = InventoryItem.objects.create(
            code="R-100",
            name="Reagent",
            default_unit="mL",
        )
        lot = InventoryLot.objects.create(
            item=item,
            lot_code="L-100",
            quantity=Decimal("10"),
            unit="mL",
        )
        self.reservation = InventoryReservation.objects.create(
            lot=lot,
            project=self.project,
            quantity=Decimal("2"),
            unit="mL",
            created_by=self.tech,
        )

        private_project = Project.objects.create(code="PRIVATE", name="Private")
        private_lot = InventoryLot.objects.create(
            item=item,
            lot_code="L-PRIVATE",
            quantity=Decimal("5"),
            unit="mL",
        )
        self.private_reservation = InventoryReservation.objects.create(
            lot=private_lot,
            project=private_project,
            quantity=Decimal("1"),
            unit="mL",
            created_by=self.tech,
        )

    def test_result_list_exposes_manual_qc_context_and_filters(self):
        self.client.force_authenticate(self.reviewer)

        response = self.client.get("/api/results/?qc_status=PENDING_REVIEW&qc_passed=false")

        self.assertEqual(response.status_code, 200)
        rows = response.data["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], self.result.id)
        self.assertEqual(rows[0]["sample_code"], "S-100")
        self.assertEqual(rows[0]["project_code"], "ALPHA")
        self.assertEqual(rows[0]["work_item_name"], "Sequencing work")

    def test_batch_and_work_lists_expose_manual_ui_context(self):
        self.client.force_authenticate(self.tech)

        samples = self.client.get(f"/api/samples/?batch={self.batch.id}")
        work = self.client.get(f"/api/work-items/?batch={self.batch.id}&work_type=SEQUENCING")

        self.assertEqual(samples.status_code, 200)
        self.assertEqual(samples.data["results"][0]["batch_code"], "B-100")
        self.assertEqual(work.status_code, 200)
        self.assertEqual(work.data["results"][0]["sample_code"], "S-100")
        self.assertEqual(work.data["results"][0]["batch_code"], "B-100")
        self.assertEqual(work.data["results"][0]["project_code"], "ALPHA")

    def test_viewer_cannot_propose_work_creation_or_label_generation(self):
        self.client.force_authenticate(self.viewer)

        work = self.client.post(
            "/api/assistant/chat/",
            {"message": "Create extraction work for samples in batch B-100"},
            format="json",
        )
        labels = self.client.post(
            "/api/assistant/chat/",
            {"message": "Create barcode labels for batch B-100"},
            format="json",
        )

        self.assertEqual(work.status_code, 200)
        self.assertNotIn("pending_action", work.data)
        self.assertIn("Tech or Director", work.data["answer"])
        self.assertEqual(labels.status_code, 200)
        self.assertNotIn("pending_action", labels.data)
        self.assertIn("Tech or Director", labels.data["answer"])

    def test_viewer_can_still_read_unassigned_work(self):
        self.client.force_authenticate(self.viewer)

        response = self.client.post(
            "/api/assistant/chat/",
            {"message": "Show unassigned sequencing work today"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Tech or Director", response.data["answer"])
        self.assertNotIn("pending_action", response.data)

    def test_tech_can_still_propose_work_and_labels(self):
        self.client.force_authenticate(self.tech)

        work = self.client.post(
            "/api/assistant/chat/",
            {"message": "Create extraction work for samples in batch B-100"},
            format="json",
        )
        labels = self.client.post(
            "/api/assistant/chat/",
            {"message": "Create barcode labels for batch B-100"},
            format="json",
        )

        self.assertEqual(work.data["pending_action"]["status"], "PROPOSED")
        self.assertEqual(labels.data["pending_action"]["status"], "PROPOSED")

    def test_reservations_are_limited_to_accessible_projects(self):
        self.client.force_authenticate(self.viewer)

        response = self.client.get("/api/inventory-reservations/")

        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data["results"]}
        self.assertIn(self.reservation.id, ids)
        self.assertNotIn(self.private_reservation.id, ids)

    def test_viewer_can_create_own_notification_subscription(self):
        self.client.force_authenticate(self.viewer)
        proposal = self.client.post(
            "/api/assistant/chat/",
            {"message": "Alert me when reagent R-100 falls below 10 units"},
            format="json",
        )
        token = proposal.data["pending_action"]["confirmation_token"]

        confirmed = self.client.post(
            f"/api/assistant/actions/{token}/confirm/",
            {"confirm": True},
            format="json",
        )

        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.data["status"], "COMPLETED")
        self.assertEqual(
            confirmed.data["result"]["operation"],
            "CREATE_SUBSCRIPTION",
        )

    def test_manual_ui_command_templates_create_expected_confirmed_previews(self):
        self.client.force_authenticate(self.tech)
        commands = [
            (
                "Add samples S-100 to batch B-200",
                "BULK_SAMPLE_UPDATE",
            ),
            (
                "Reserve 1 mL of reagent R-100 for ALPHA",
                "INVENTORY_OPERATION",
            ),
            (
                "Create extraction work for samples in batch B-100",
                "WORK_ITEM_OPERATION",
            ),
            (
                "Create barcode labels for batch B-100",
                "LABEL_GENERATION",
            ),
            (
                "Generate sample status changes report for Project ALPHA from August as PDF",
                "COMPLIANCE_REPORT",
            ),
            (
                "Alert me by email daily when reagent R-100 falls below 10 units",
                "NOTIFICATION_MANAGEMENT",
            ),
        ]

        for command, action_type in commands:
            with self.subTest(command=command):
                response = self.client.post(
                    "/api/assistant/chat/",
                    {"message": command},
                    format="json",
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.data["pending_action"]["type"],
                    action_type,
                )

        self.client.force_authenticate(self.reviewer)
        qc = self.client.post(
            "/api/assistant/chat/",
            {
                "message": (
                    f"approve result R-{self.result.id} because controls passed"
                )
            },
            format="json",
        )
        self.assertEqual(qc.status_code, 200)
        self.assertEqual(qc.data["pending_action"]["type"], "QC_REVIEW")
