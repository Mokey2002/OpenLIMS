from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.utils import timezone
from events.models import Event
from inventory.models import (
    Container,
    InventoryItem,
    InventoryLot,
    InventoryReservation,
    Location,
)
from projects.models import Project
from rest_framework.test import APITestCase
from samples.models import Sample


class AssistantInventoryOperationsTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.tech = user_model.objects.create_user(username="inventory-tech")
        tech_group, _ = Group.objects.get_or_create(name="tech")
        self.tech.groups.add(tech_group)

        self.project = Project.objects.create(code="ALPHA", name="Alpha")
        self.project.members.add(self.tech)

        self.freezer = Location.objects.create(name="F2", kind="FREEZER")
        self.rack = Container.objects.create(
            container_id="R4",
            kind="RACK",
            location=self.freezer,
        )
        self.box = Container.objects.create(
            container_id="B3",
            kind="BOX",
            location=self.freezer,
            parent=self.rack,
        )
        self.old_location = Location.objects.create(name="F1", kind="FREEZER")
        self.old_rack = Container.objects.create(
            container_id="R1",
            kind="RACK",
            location=self.old_location,
        )
        self.old_box = Container.objects.create(
            container_id="B1",
            kind="BOX",
            location=self.old_location,
            parent=self.old_rack,
        )
        self.sample = Sample.objects.create(
            sample_id="S-1042",
            project=self.project,
            container=self.old_box,
            created_by=self.tech,
        )

        self.item = InventoryItem.objects.create(
            code="R-100",
            name="Sequencing reagent",
            category=InventoryItem.CATEGORY_REAGENT,
            default_unit="mL",
            reorder_level=Decimal("150"),
        )
        self.lot = InventoryLot.objects.create(
            item=self.item,
            lot_code="L-204",
            quantity=Decimal("100"),
            unit="mL",
            expiration_date=timezone.localdate() + timedelta(days=20),
            location=self.freezer,
            container=self.box,
        )

    def chat(self, message, *, context=None):
        self.client.force_authenticate(self.tech)
        return self.client.post(
            "/api/assistant/chat/",
            {"message": message, "context": context or {}},
            format="json",
        )

    def confirm(self, proposal):
        token = proposal.data["pending_action"]["confirmation_token"]
        self.client.force_authenticate(self.tech)
        return self.client.post(
            f"/api/assistant/actions/{token}/confirm/",
            {"confirm": True},
            format="json",
        )

    def test_read_only_inventory_and_location_questions(self):
        expiring = self.chat("Which reagents expire in the next 30 days?")
        reorder = self.chat("Show inventory below its reorder level.")
        location = self.chat("Where is sample S-1042?")
        stored = self.chat("What is stored in freezer F2, rack R4?")

        self.assertIn("L-204", expiring.data["answer"])
        self.assertIn("R-100", reorder.data["answer"])
        self.assertIn("F1 / R1 / B1", location.data["answer"])
        self.assertIn("Lot L-204", stored.data["answer"])

    def test_sample_move_requires_confirmation_and_creates_chain_of_custody(self):
        proposal = self.chat("Move sample S-1042 to freezer F2, rack R4, box B3.")
        preview = proposal.data["pending_action"]["preview"]
        self.assertEqual(preview["records_affected"], 1)
        self.assertEqual(preview["records"][0]["current"]["location"], "F1 / R1 / B1")
        self.assertEqual(preview["records"][0]["proposed"]["location"], "F2 / R4 / B3")
        self.sample.refresh_from_db()
        self.assertEqual(self.sample.container, self.old_box)

        first = self.confirm(proposal)
        second = self.confirm(proposal)
        self.sample.refresh_from_db()

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(self.sample.container, self.box)
        event = Event.objects.get(
            entity_type="Sample",
            entity_id=str(self.sample.id),
            action="SAMPLE_MOVED",
        )
        self.assertEqual(event.payload["before"]["location"], "F1 / R1 / B1")
        self.assertEqual(event.payload["after"]["location"], "F2 / R4 / B3")
        self.assertEqual(
            Event.objects.filter(
                entity_type="Sample",
                entity_id=str(self.sample.id),
                action="SAMPLE_MOVED",
            ).count(),
            1,
        )

        last_move = self.chat("Who last moved sample S-1042?")
        self.assertIn(self.tech.username, last_move.data["answer"])
        self.assertIn("F1 / R1 / B1", last_move.data["answer"])
        self.assertIn("F2 / R4 / B3", last_move.data["answer"])
        follow_up = self.chat(
            "Who last moved it?",
            context={"sample_id": self.sample.id},
        )
        self.assertIn(self.tech.username, follow_up.data["answer"])

    def test_location_and_container_hierarchy_are_validated(self):
        wrong_box = Container.objects.create(
            container_id="B-WRONG",
            kind="BOX",
            location=self.freezer,
        )
        response = self.chat("Move sample S-1042 to freezer F2, rack R4, box B-WRONG.")
        self.assertNotIn("pending_action", response.data)
        self.assertIn("Container B-WRONG was not found", response.data["answer"])
        self.assertIsNone(wrong_box.parent)

    def test_reservation_uses_frozen_lot_and_audits_project(self):
        proposal = self.chat("Reserve two units of reagent R-100 for Project Alpha.")
        preview = proposal.data["pending_action"]["preview"]
        self.assertEqual(preview["project"]["code"], "ALPHA")
        self.assertIn("2 ml", preview["records"][0]["proposed"]["reserve"])

        response = self.confirm(proposal)
        reservation = InventoryReservation.objects.get(lot=self.lot)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(reservation.project, self.project)
        self.assertEqual(reservation.quantity, Decimal("2"))
        self.assertEqual(reservation.unit, "ml")
        event = Event.objects.get(
            entity_type="InventoryLot",
            entity_id=str(self.lot.id),
            action="INVENTORY_RESERVED",
        )
        self.assertEqual(event.payload["project_code"], "ALPHA")
        self.assertEqual(event.payload["before"]["available_quantity"], "100.0000")
        self.assertEqual(event.payload["after"]["available_quantity"], "98.0000")

    def test_consumption_converts_units_prevents_negative_and_is_audited(self):
        proposal = self.chat("Record consumption of 0.05 L from lot L-204.")
        response = self.confirm(proposal)
        self.lot.refresh_from_db()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.lot.quantity, Decimal("50"))
        self.assertTrue(
            Event.objects.filter(
                entity_id=str(self.lot.id),
                action="INVENTORY_CONSUMED",
            ).exists()
        )

        blocked = self.chat("Record consumption of 51 mL from lot L-204.")
        self.assertNotIn("pending_action", blocked.data)
        self.assertIn("cannot make quantity negative", blocked.data["answer"])
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.quantity, Decimal("50"))

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InventoryLot.objects.filter(id=self.lot.id).update(quantity=-1)

    def test_incompatible_units_are_rejected(self):
        response = self.chat("Record consumption of 50 g from lot L-204.")
        self.assertNotIn("pending_action", response.data)
        self.assertIn("not compatible", response.data["answer"])

    def test_lot_drift_after_preview_is_rejected(self):
        proposal = self.chat("Record consumption of 10 mL from lot L-204.")
        InventoryLot.objects.filter(id=self.lot.id).update(quantity=Decimal("90"))
        response = self.confirm(proposal)
        self.lot.refresh_from_db()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.lot.quantity, Decimal("90"))
        self.assertFalse(
            Event.objects.filter(
                entity_id=str(self.lot.id),
                action="INVENTORY_CONSUMED",
            ).exists()
        )

    def test_mark_expired_is_confirmed_and_audited(self):
        proposal = self.chat("Mark lot L-204 as expired.")
        response = self.confirm(proposal)
        self.lot.refresh_from_db()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.lot.status, InventoryLot.STATUS_EXPIRED)
        self.assertTrue(
            Event.objects.filter(
                entity_id=str(self.lot.id),
                action="INVENTORY_LOT_EXPIRED",
            ).exists()
        )
