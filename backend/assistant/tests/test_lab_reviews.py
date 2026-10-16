from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.models import AssistantAction
from custom_fields.models import FieldDefinition, FieldValue
from inventory.models import InventoryItem, InventoryLot, InventoryReservation, InventoryTransaction
from notebook.models import Notebook, Experiment, ExperimentRevision, ExperimentLink
from results.models import Result
from samples.models import Sample
from . import test_comparisons


class LabReviewTests(APITestCase):
    setUp = test_comparisons.AssistantComparisonTests.setUp
    chat = test_comparisons.AssistantComparisonTests.chat

    def lot(self):
        item = InventoryItem.objects.create(code="BUFFER", name="Buffer", default_unit="mL")
        return InventoryLot.objects.create(item=item, lot_code="LOT-12", quantity=100, unit="mL")

    def experiment(self, owner, title):
        notebook = Notebook.objects.create(owner=owner, name=title)
        experiment = Experiment.objects.create(notebook=notebook, created_by=owner, title=title)
        revision = ExperimentRevision.objects.create(experiment=experiment, number=1, checksum=title)
        experiment.current_revision = revision
        experiment.save()
        return experiment

    def consumption(self, lot, work=None, experiment=None):
        return InventoryTransaction.objects.create(lot=lot, operation="CONSUME", amount=2, unit="mL",
            before_quantity=100, after_quantity=98, before_status="ACTIVE", after_status="ACTIVE",
            actor=self.tech, reason="test", work_item=work, experiment=experiment)

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
    def test_impact_separates_active_reservations_past_use_and_notebook_links(self):
        lot = self.lot()
        work = self.samples[0].work_items.first()
        InventoryReservation.objects.create(lot=lot, project=self.alpha, work_item=work, quantity=5, unit="mL")
        self.consumption(lot, work=work)
        experiment = self.experiment(self.tech, "Accessible run")
        ExperimentLink.objects.create(revision=experiment.current_revision, entity_type="inventory_lot", entity_public_id=lot.public_id, label="Buffer")
        data = self.chat("What would be affected if we quarantine lot LOT-12?").data
        self.assertEqual({row["kind"] for row in data["comparison"]["rows"]}, {"Active reservation", "Recorded past use", "Current notebook link"})
        self.assertIn("S-100", str(data))
        self.assertIn("Accessible run", str(data))
        self.assertNotIn("pending_action", data)
        self.assertEqual(AssistantAction.objects.count(), 0)
        lot.refresh_from_db()
        self.assertEqual(lot.status, "ACTIVE")
        self.assertEqual(lot.quantity, 100)

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
    def test_impact_checks_every_linked_target_and_never_leaks_private_rows(self):
        lot = self.lot()
        private_work = self.private_sample.work_items.first()
        private_experiment = self.experiment(self.outsider, "Secret experiment")
        InventoryReservation.objects.create(lot=lot, project=self.private, quantity=50, unit="mL")
        InventoryReservation.objects.create(lot=lot, project=self.alpha, work_item=private_work, quantity=5, unit="mL")
        self.consumption(lot, work=private_work)
        self.consumption(lot, work=self.samples[0].work_items.first(), experiment=private_experiment)
        ExperimentLink.objects.create(revision=private_experiment.current_revision, entity_type="inventory_lot", entity_public_id=lot.public_id, label="Secret lot link")
        data = self.chat("Preview impact for lot LOT-12").data
        self.assertEqual(data["comparison"]["rows"], [])
        for hidden in ["Secret", "PRIVATE", "S-100", "50 mL"]:
            self.assertNotIn(hidden, str(data))
        self.assertIn("does not prove", data["answer"])

    def test_impact_ignores_released_reservations_and_discloses_limit(self):
        lot = self.lot()
        for status in ["ACTIVE", "ACTIVE", "RELEASED"]:
            InventoryReservation.objects.create(lot=lot, project=self.alpha, quantity=5, unit="mL", status=status)
        with patch("assistant.lab_reviews.IMPACT_LIMIT", 1):
            data = self.chat("Preview quarantine impact for lot LOT-12").data
        self.assertEqual(len(data["comparison"]["rows"]), 1)
        self.assertTrue(data["impact_preview"]["truncated"])
        self.assertIn("Partial preview", str(data))

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=True)
    def test_impact_respects_disabled_notebook_feature(self):
        from settings_app.models import SystemSettings
        settings = SystemSettings.load()
        settings.feature_flags["notebook"] = False
        settings.save()
        lot = self.lot()
        experiment = self.experiment(self.tech, "Hidden feature run")
        self.consumption(lot, experiment=experiment)
        data = self.chat("Preview impact for lot LOT-12").data
        self.assertNotIn("Hidden feature run", str(data))
        self.assertIn("disabled", str(data))

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
    def test_impact_only_reads_current_notebook_links_and_rechecks_access(self):
        lot = self.lot()
        experiment = self.experiment(self.tech, "Old linked run")
        ExperimentLink.objects.create(revision=experiment.current_revision, entity_type="inventory_lot", entity_public_id=lot.public_id, label="old")
        experiment.current_revision = ExperimentRevision.objects.create(experiment=experiment, number=2, checksum="new")
        experiment.save()
        InventoryReservation.objects.create(lot=lot, project=self.alpha, quantity=5, unit="mL")
        first = self.chat("Preview impact for lot LOT-12").data
        self.assertEqual(len(first["comparison"]["rows"]), 1)
        self.alpha.members.remove(self.tech)
        self.assertEqual(self.chat("Preview impact for lot LOT-12").data["comparison"]["rows"], [])

    def test_quality_detects_required_metadata_id_similarity_units_and_dates(self):
        Sample.objects.create(sample_id="S_100", project=self.alpha, created_by=self.tech)
        Result.objects.filter(work_item__sample=self.samples[1]).update(unit="mmol/L")
        Sample.objects.filter(pk=self.samples[0].pk).update(status_changed_at=timezone.now() + timedelta(days=1))
        data = self.chat("Check project ALPHA for suspicious records").data
        kinds = {row["kind"] for row in data["comparison"]["rows"]}
        self.assertTrue({"Missing required metadata", "Possible duplicate identifier", "Review result units", "Unusual date", "Unusual deadline"}.issubset(kinds))
        self.assertNotIn("PRIVATE", str(data))
        self.assertNotIn("S-102", str(data))
        self.assertTrue(data["links"])
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_quality_scopes_comparison_groups_and_rechecks_project_access(self):
        Result.objects.filter(work_item__sample=self.private_sample).update(unit="secretunit")
        Result.objects.filter(work_item__sample=self.samples[2]).update(unit="otherprojectunit")
        data = self.chat("Review data quality for project ALPHA").data
        self.assertNotIn("secretunit", str(data))
        self.assertNotIn("otherprojectunit", str(data))
        self.assertNotIn("Review result units", str(data))
        self.alpha.members.remove(self.tech)
        self.assertNotIn("quality_review", self.chat("Check project ALPHA for suspicious records").data)

    def test_quality_allows_false_zero_and_compatible_units(self):
        for name, value, kind in [("consent", False, "bool"), ("amount", 0, "int")]:
            definition = FieldDefinition.objects.create(entity_type="Sample", name=name, required=True, data_type=kind)
            for sample in self.samples[:2]:
                FieldValue.objects.create(field_definition=definition, entity_type="Sample", entity_id=str(sample.pk), value=value)
        Result.objects.filter(work_item__sample=self.samples[0]).update(unit="mL")
        Result.objects.filter(work_item__sample=self.samples[1]).update(unit="uL")
        data = self.chat("Check project ALPHA for data quality").data
        self.assertNotIn("Review result units", str(data))
        self.assertNotIn("field consent", str(data))
        self.assertNotIn("field amount", str(data))

    def test_quality_uses_conditional_intake_form_rules(self):
        schema = {"fields": [{"key": "needed", "type": "boolean"},
            {"key": "details", "type": "text", "required": True, "show_if": {"key": "needed", "equals": True}}]}
        Sample.objects.filter(pk=self.samples[0].pk).update(form_schema=schema, form_values={"needed": False})
        Sample.objects.filter(pk=self.samples[1].pk).update(form_schema=schema, form_values={"needed": True})
        rows = self.chat("Check project ALPHA for suspicious records").data["comparison"]["rows"]
        invalid = [row["sample"] for row in rows if row["kind"] == "Invalid intake form"]
        self.assertEqual(invalid, ["S-101"])

    def test_quality_discloses_sample_related_record_and_finding_limits(self):
        with patch("assistant.lab_reviews.SAMPLE_LIMIT", 1), patch("assistant.lab_reviews.RELATED_LIMIT", 1):
            data = self.chat("Check project ALPHA for suspicious records").data
        self.assertTrue(data["quality_review"]["partial_scan"])
        self.assertEqual(data["quality_review"]["scanned_samples"], 1)
        with patch("assistant.lab_reviews.FINDING_LIMIT", 1):
            data = self.chat("Check project ALPHA for suspicious records").data
        self.assertTrue(data["quality_review"]["truncated"])
        self.assertEqual(len(data["comparison"]["rows"]), 1)

    def test_ambiguous_or_private_project_never_produces_report(self):
        self.assertNotIn("quality_review", self.chat("Check project PRIVATE for suspicious records").data)
        other = type(self.alpha).objects.create(code="alpha", name="Other Alpha")
        other.members.add(self.tech)
        self.assertNotIn("quality_review", self.chat("Check project ALPHA for suspicious records").data)
