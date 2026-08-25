from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from assistant.models import BarcodeLabel
from inventory.models import Container, Location
from projects.models import Project
from samples.models import Sample, SampleCustodyEvent, SampleRelationship


User = get_user_model()


class SampleTraceabilityTests(APITestCase):
    def setUp(self):
        tech_group, _ = Group.objects.get_or_create(name="tech")
        viewer_group, _ = Group.objects.get_or_create(name="viewer")
        self.tech = User.objects.create_user("trace-tech", password="pass")
        self.tech.groups.add(tech_group)
        self.other_tech = User.objects.create_user("receiver", password="pass")
        self.other_tech.groups.add(tech_group)
        self.viewer = User.objects.create_user("trace-viewer", password="pass")
        self.viewer.groups.add(viewer_group)
        self.project = Project.objects.create(code="TRACE", name="Traceability")
        self.project.members.add(self.tech, self.other_tech, self.viewer)
        self.source = Sample.objects.create(
            sample_id="TRACE-001", sample_type="DNA", project=self.project, created_by=self.tech
        )
        self.location = Location.objects.create(name="Freezer A", kind="freezer")
        self.container = Container.objects.create(
            container_id="BOX-A1", kind="box", location=self.location
        )
        self.label = BarcodeLabel.objects.create(
            sample=self.source, barcode="OL-S-TRACE-001"
        )

    def test_create_aliquot_records_lineage(self):
        self.client.force_authenticate(self.tech)
        response = self.client.post(
            f"/api/samples/{self.source.id}/derive/",
            {
                "sample_id": "TRACE-001-A1",
                "relationship_type": "ALIQUOT",
                "quantity": "0.5000",
                "unit": "mL",
                "reason": "Created aliquot for sequencing analysis.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        child = Sample.objects.get(sample_id="TRACE-001-A1")
        relationship = SampleRelationship.objects.get(
            source_sample=self.source, derived_sample=child
        )
        self.assertEqual(relationship.relationship_type, SampleRelationship.TYPE_ALIQUOT)
        self.assertEqual(child.project, self.project)

    def test_lineage_cycle_is_rejected(self):
        child = Sample.objects.create(sample_id="TRACE-002", project=self.project)
        SampleRelationship.objects.create(
            source_sample=self.source,
            derived_sample=child,
            relationship_type=SampleRelationship.TYPE_DERIVED,
            reason="Created from original source material.",
            created_by=self.tech,
        )
        self.client.force_authenticate(self.tech)
        response = self.client.post(
            "/api/sample-relationships/",
            {
                "source_sample": child.id,
                "derived_sample": self.source.id,
                "relationship_type": "DERIVED",
                "reason": "Invalid reverse lineage relationship.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_barcode_scan_updates_storage_and_custody(self):
        self.client.force_authenticate(self.tech)
        moved = self.client.post(
            "/api/sample-custody-events/scan/",
            {
                "barcode": self.label.barcode,
                "action": "MOVE",
                "container": self.container.id,
                "reason": "Moved into validated freezer storage.",
            },
            format="json",
        )
        self.assertEqual(moved.status_code, 201, moved.data)
        checked_out = self.client.post(
            "/api/sample-custody-events/scan/",
            {
                "barcode": self.source.sample_id,
                "action": "CHECK_OUT",
                "reason": "Checked out for extraction procedure.",
            },
            format="json",
        )
        self.assertEqual(checked_out.status_code, 201, checked_out.data)
        self.source.refresh_from_db()
        self.assertEqual(self.source.container, self.container)
        self.assertEqual(self.source.custodian, self.tech)
        self.assertEqual(SampleCustodyEvent.objects.filter(sample=self.source).count(), 2)

    def test_transfer_and_disposal_are_audited(self):
        self.source.container = self.container
        self.source.custodian = self.tech
        self.source.save(update_fields=["container", "custodian"])
        self.client.force_authenticate(self.tech)
        transferred = self.client.post(
            "/api/sample-custody-events/scan/",
            {
                "barcode": self.label.barcode,
                "action": "TRANSFER",
                "custodian": self.other_tech.id,
                "reason": "Transferred to the sequencing operator.",
            },
            format="json",
        )
        self.assertEqual(transferred.status_code, 201, transferred.data)
        disposed = self.client.post(
            "/api/sample-custody-events/scan/",
            {
                "barcode": self.label.barcode,
                "action": "DISPOSE",
                "reason": "Material consumed and disposal documented.",
            },
            format="json",
        )
        self.assertEqual(disposed.status_code, 201, disposed.data)
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, Sample.STATUS_ARCHIVED)
        self.assertIsNone(self.source.container)
        self.assertIsNone(self.source.custodian)

    def test_viewer_cannot_scan_or_create_lineage(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.post(
            "/api/sample-custody-events/scan/",
            {
                "barcode": self.label.barcode,
                "action": "PROCESS",
                "reason": "Attempted read-only processing event.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
