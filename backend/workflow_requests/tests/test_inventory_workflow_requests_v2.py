from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import (
    BarcodeIdentity,
    Container,
    InventoryItem,
    InventoryLot,
    InventoryReservation,
    InventoryTransaction,
    Location,
)
from pipelines.models import AnalysisDefinition, PipelineTemplate, PipelineTemplateStep, ProcedureDefinition
from projects.models import Project
from samples.models import Sample
from workflow_requests.models import AssayRequestType, RequestResourceRequirement, WorkflowRequest


User = get_user_model()


def user_with_role(username, role):
    user = User.objects.create_user(username=username, password="test-pass")
    group, _ = Group.objects.get_or_create(name=role)
    user.groups.add(group)
    return user


class InventoryWorkflowRequestV2Tests(TestCase):
    def setUp(self):
        self.director = user_with_role("request-director", "admin")
        self.requester = user_with_role("requester", "viewer")
        self.technician = user_with_role("request-tech", "tech")
        self.project = Project.objects.create(name="Sequencing Requests", code="SEQ-REQ")
        self.project.members.add(self.requester, self.technician)
        self.sample = Sample.objects.create(sample_id="SEQ-REQ-001", sample_type="DNA", project=self.project, created_by=self.requester)
        analysis = AnalysisDefinition.objects.create(code="SEQUENCE_QC", name="Sequence QC", required_fields=[{"key": "read_count", "type": "NUMBER"}], created_by=self.director)
        procedure = ProcedureDefinition.objects.create(code="SEQ-QC-PROC", name="Sequencing QC", version="1", analysis=analysis, created_by=self.director)
        self.pipeline = PipelineTemplate.objects.create(code="SEQUENCING-REQUEST", name="Sequencing request pipeline", default_project=self.project, created_by=self.director)
        PipelineTemplateStep.objects.create(template=self.pipeline, position=1, procedure=procedure, name="Sequence and QC", requires_qc=True)
        self.site = Location.objects.create(code="SITE-DEMO", name="Demo site", kind="SITE")
        self.building = Location.objects.create(code="BLDG-DEMO", name="Biology building", kind="BUILDING", parent=self.site)
        self.lab = Location.objects.create(code="LAB-DEMO", name="Sequencing lab", kind="LABORATORY", parent=self.building, project=self.project)
        self.freezer = Location.objects.create(code="FREEZER-DEMO", name="Freezer 1", kind="FREEZER", parent=self.lab, project=self.project)
        self.plate = Container.objects.create(container_id="PLATE-REQ-001", kind="plate", location=self.freezer, rows=8, columns=12)
        self.item = InventoryItem.objects.create(
            code="SEQ-KIT", name="Sequencing reagent kit", default_unit="reaction", reorder_level="2",
            vendor="Demo Vendor", manufacturer="Demo Manufacturer", catalog_number="DV-SEQ-01",
            storage_conditions="-20 C", hazard_statements=["H315"], ghs_classifications=["Irritant"],
        )
        self.lot = InventoryLot.objects.create(
            item=self.item, lot_code="SEQ-KIT-LOT-01", quantity="10", unit="reaction",
            location=self.freezer, container=self.plate, received_date="2026-08-01", storage_conditions="-20 C",
        )
        self.request_type = AssayRequestType.objects.create(
            code="SEQ", name="Sequencing", description="Internal sequencing request",
            form_schema={"type": "object", "required": ["read_length"], "properties": {"read_length": {"type": "integer"}}},
            default_pipeline=self.pipeline, project=self.project, sla_hours=48, created_by=self.director,
        )
        RequestResourceRequirement.objects.create(
            request_type=self.request_type, kind="MATERIAL", inventory_item=self.item,
            quantity="1", unit="reaction", required=True,
        )

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_request_approval_reserves_material_executes_and_reports_status(self):
        requester = self.client_for(self.requester)
        submitted = requester.post(
            "/api/workflow-requests/",
            {
                "request_type": self.request_type.pk,
                "project": self.project.pk,
                "title": "Sequence selected plasmid samples",
                "form_data": {"read_length": 250},
                "sample_ids": [self.sample.pk],
                "priority": "HIGH",
            },
            format="json",
        )
        self.assertEqual(submitted.status_code, 201, submitted.data)
        self.assertEqual(submitted.data["status"], "SUBMITTED")
        versioned_requests = requester.get("/api/v1/workflow-requests/")
        self.assertEqual(versioned_requests.status_code, 200, versioned_requests.data)
        self.assertEqual(versioned_requests.data["results"][0]["public_id"], submitted.data["public_id"])
        request_id = submitted.data["id"]
        item_public_id = submitted.data["items"][0]["public_id"]

        technician = self.client_for(self.technician)
        triage = technician.post(f"/api/workflow-requests/{request_id}/triage/", {"priority": "URGENT"}, format="json")
        self.assertEqual(triage.status_code, 200, triage.data)
        director = self.client_for(self.director)
        approval = director.post(
            f"/api/workflow-requests/{request_id}/approve/",
            {"pipeline": self.pipeline.pk, "reason": "Capacity and materials confirmed", "group_name": "Plate 1"},
            format="json",
        )
        self.assertEqual(approval.status_code, 200, approval.data)
        self.assertEqual(approval.data["request"]["status"], "APPROVED")
        self.assertEqual(approval.data["reservation_count"], 1)
        reservation = InventoryReservation.objects.get(request_item_public_id=item_public_id)
        self.assertEqual(str(reservation.quantity), "1.0000")
        self.assertIsNotNone(reservation.work_item)

        refreshed_alerts = technician.post("/api/inventory-alerts/refresh/", {}, format="json")
        self.assertEqual(refreshed_alerts.status_code, 200, refreshed_alerts.data)
        reservation_alerts = technician.get("/api/inventory-alerts/?alert_type=RESERVATION")
        self.assertEqual(reservation_alerts.status_code, 200, reservation_alerts.data)
        self.assertTrue(any(row["alert_type"] == "RESERVATION" for row in reservation_alerts.data["results"]))

        barcode = director.post(
            "/api/inventory-barcodes/",
            {"barcode": "LOT:SEQ-KIT-LOT-01", "entity_type": "inventory_lot", "target_public_id": str(self.lot.public_id)},
            format="json",
        )
        self.assertEqual(barcode.status_code, 201, barcode.data)
        consume = technician.post(
            "/api/inventory-transactions/",
            {
                "barcode": "LOT:SEQ-KIT-LOT-01", "operation": "CONSUME", "amount": "1",
                "unit": "reaction", "reason": "Consumed during sequencing execution",
                "work_item_public_id": str(reservation.work_item.public_id),
                "request_item_public_id": item_public_id,
            },
            format="json",
        )
        self.assertEqual(consume.status_code, 201, consume.data)
        self.assertEqual(consume.data["before_quantity"], "10.0000")
        self.assertEqual(consume.data["after_quantity"], "9.0000")
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, InventoryReservation.STATUS_CONSUMED)
        technician.post("/api/inventory-alerts/refresh/", {}, format="json")

        visible = requester.get(f"/api/workflow-requests/{request_id}/")
        self.assertEqual(visible.status_code, 200, visible.data)
        self.assertEqual(visible.data["items"][0]["execution"]["template"], self.pipeline.code)
        self.assertEqual(visible.data["items"][0]["reservations"][0]["status"], "CONSUMED")

        attachment = requester.post(
            "/api/shared-attachments/",
            {
                "target_type": "workflow_request",
                "target_public_id": submitted.data["public_id"],
                "file": SimpleUploadedFile("sample-manifest.txt", b"SEQ-REQ-001\n", content_type="text/plain"),
                "description": "Requester sample manifest",
            },
            format="multipart",
        )
        self.assertEqual(attachment.status_code, 201, attachment.data)
        self.assertEqual(attachment.data["target"]["public_id"], submitted.data["public_id"])

    def test_hierarchy_scan_ledger_plate_and_cycle_count(self):
        director = self.client_for(self.director)
        barcode = director.post(
            "/api/inventory-barcodes/",
            {"barcode": "LOC:FREEZER-DEMO", "entity_type": "location", "target_public_id": str(self.freezer.public_id)},
            format="json",
        )
        self.assertEqual(barcode.status_code, 201, barcode.data)
        resolved = self.client_for(self.technician).get("/api/inventory-barcodes/resolve/?barcode=LOC:FREEZER-DEMO")
        self.assertEqual(resolved.status_code, 200, resolved.data)
        self.assertEqual(resolved.data["target"]["public_id"], str(self.freezer.public_id))
        self.assertEqual(self.freezer.path_label, "Demo site / Biology building / Sequencing lab / Freezer 1")

        placement = self.client_for(self.technician).post(
            "/api/inventory-placements/",
            {"container": self.plate.pk, "position": "A1", "sample": self.sample.pk},
            format="json",
        )
        self.assertEqual(placement.status_code, 201, placement.data)
        invalid_placement = self.client_for(self.technician).post(
            "/api/inventory-placements/",
            {"container": self.plate.pk, "position": "Z99", "lot": self.lot.pk},
            format="json",
        )
        self.assertEqual(invalid_placement.status_code, 400, invalid_placement.data)
        receive = self.client_for(self.technician).post(
            "/api/inventory-transactions/",
            {"lot": self.lot.pk, "operation": "RECEIVE", "amount": "2", "unit": "reaction", "reason": "Received replacement reactions"},
            format="json",
        )
        self.assertEqual(receive.status_code, 201, receive.data)
        self.assertEqual(InventoryTransaction.objects.count(), 1)
        entry = InventoryTransaction.objects.get()
        with self.assertRaises(Exception):
            entry.delete()

        count = director.post(
            "/api/inventory-cycle-counts/",
            {"name": "August freezer count", "location": self.freezer.pk},
            format="json",
        )
        self.assertEqual(count.status_code, 201, count.data)
        detail = director.get(f"/api/inventory-cycle-counts/{count.data['id']}/")
        self.assertEqual(len(detail.data["lines"]), 1)
        line = detail.data["lines"][0]
        observed = self.client_for(self.technician).patch(
            f"/api/inventory-cycle-count-lines/{line['id']}/",
            {"observed_quantity": "11", "note": "One reaction used outside system"},
            format="json",
        )
        self.assertEqual(observed.status_code, 200, observed.data)
        reconciled = director.post(
            f"/api/inventory-cycle-counts/{count.data['id']}/reconcile/",
            {"reason": "Monthly cycle count variance"},
            format="json",
        )
        self.assertEqual(reconciled.status_code, 200, reconciled.data)
        self.lot.refresh_from_db()
        self.assertEqual(str(self.lot.quantity), "11.0000")
        self.assertEqual(InventoryTransaction.objects.count(), 2)
        report = director.get(f"/api/inventory-cycle-counts/{count.data['id']}/export/")
        self.assertEqual(report.status_code, 200)
        self.assertIn("SEQ-KIT-LOT-01", report.content.decode("utf-8"))
