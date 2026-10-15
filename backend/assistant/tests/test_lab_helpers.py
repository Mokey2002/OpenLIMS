from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.models import AssistantAction
from events.models import Event
from inventory.models import InventoryItem, InventoryLot, InventoryReservation
from notebook.models import Notebook, Experiment, ExperimentTemplate, ExperimentRevision, ExperimentBlock
from pipelines.models import AnalysisDefinition, ProcedureDefinition, ProcedureReagentRequirement
from samples.models import Sample
from . import test_comparisons


class LabHelpersTests(APITestCase):
    setUp = test_comparisons.AssistantComparisonTests.setUp
    chat = test_comparisons.AssistantComparisonTests.chat
    confirm = test_comparisons.AssistantComparisonTests.confirm

    def test_history_scopes_events_and_never_echoes_payloads(self):
        sample = self.samples[0]
        Event.objects.create(entity_type="sample", entity_id=str(sample.public_id), action="RECEIVED", payload={"secret": "old project secret"})
        Event.objects.create(entity_type="Sample", entity_id=str(self.private_sample.pk), action="PRIVATE_EVENT")
        Event.objects.create(entity_type="Experiment", entity_id=str(sample.pk), action="WRONG_ENTITY")
        work = sample.work_items.first()
        Event.objects.create(entity_type="WorkItem", entity_id=str(work.pk), action="QC_REVIEW", actor=self.tech)
        result = self.chat("What happened to sample S-100?")
        self.assertEqual(result.status_code, 200)
        answer = result.data["answer"]
        self.assertIn("RECEIVED", answer)
        self.assertIn("QC_REVIEW", answer)
        self.assertIn("glucose: 10.0", answer)
        for secret in ["PRIVATE_EVENT", "WRONG_ENTITY", "old project secret"]:
            self.assertNotIn(secret, answer)
        self.alpha.members.remove(self.tech)
        self.assertNotIn("history", self.chat("What happened to sample S-100?").data)

    def test_history_discloses_truncation(self):
        Event.objects.bulk_create([Event(entity_type="Sample", entity_id=str(self.samples[0].pk), action="UPDATED") for _ in range(51)])
        data = self.chat("Show history of sample S-100").data
        self.assertEqual(len(data["history"]["events"]), 50)
        self.assertTrue(data["history"]["truncated"])

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
    def test_experiment_search_permissions_and_template_boundary(self):
        notebook = Notebook.objects.create(name="Mine", owner=self.tech)
        private = Notebook.objects.create(name="Private", owner=self.outsider)
        template = ExperimentTemplate.objects.create(notebook=private, name="secretprotocol")
        Experiment.objects.create(notebook=notebook, title="Plasma extraction", created_by=self.tech)
        Experiment.objects.create(notebook=private, title="Plasma private secret", created_by=self.outsider)
        Experiment.objects.create(notebook=notebook, title="Unrelated", template=template, created_by=self.tech)
        data = self.chat("Find similar experiments about plasma").data
        self.assertEqual(len(data["links"]), 1)
        self.assertNotIn("private secret", str(data))
        self.assertFalse(self.chat("Find similar experiments about secretprotocol").data["links"])
        notebook.owner = self.outsider
        notebook.save()
        self.assertFalse(self.chat("Find similar experiments about plasma").data["links"])

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=True)
    def test_experiment_feature_disabled(self):
        from settings_app.models import SystemSettings
        config = SystemSettings.load()
        config.feature_flags["notebook"] = False
        config.save()
        self.assertIn("disabled", self.chat("Find similar experiments about plasma").data["answer"])

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
    def test_experiment_search_only_current_revision_and_distinct_results(self):
        notebook = Notebook.objects.create(name="Mine", owner=self.tech)
        experiment = Experiment.objects.create(notebook=notebook, title="Run", created_by=self.tech)
        old = ExperimentRevision.objects.create(experiment=experiment, number=1, checksum="a")
        current = ExperimentRevision.objects.create(experiment=experiment, number=2, checksum="b")
        ExperimentBlock.objects.create(revision=old, position=1, block_type="RICH_TEXT", data={"text": "oldprotocol"})
        for position in [1, 2]:
            ExperimentBlock.objects.create(revision=current, position=position, block_type="PROTOCOL_STEP", data={"text": "plasma extraction"})
        experiment.current_revision = current
        experiment.save()
        self.assertEqual(len(self.chat("Find similar experiments about plasma extraction").data["links"]), 1)
        self.assertFalse(self.chat("Find similar experiments about oldprotocol").data["links"])

    def test_private_project_names_not_disclosed_by_partial_registration(self):
        Project = type(self.private)
        Project.objects.create(code="PRIVATE-OTHER", name="Private other")
        response = self.chat("Register 2 plasma samples in project PRIV")
        self.assertNotIn("PRIVATE-OTHER", str(response.data))
        self.assertNotIn("pending_action", response.data)

    def configure_inventory(self):
        analysis = AnalysisDefinition.objects.create(code="EXTRACT", name="Extraction")
        self.procedure = ProcedureDefinition.objects.create(code="EXTRACT", name="Extraction", analysis=analysis)
        self.item = InventoryItem.objects.create(code="BUFFER", name="Buffer", default_unit="mL")
        ProcedureReagentRequirement.objects.create(procedure=self.procedure, item=self.item, quantity_per_sample=2, unit="mL")
        return InventoryLot.objects.create(item=self.item, lot_code="LOT-1", quantity=Decimal("0.1"), unit="L")

    def test_inventory_converts_units_subtracts_reservations_and_excludes_expired(self):
        lot = self.configure_inventory()
        InventoryReservation.objects.create(lot=lot, quantity=50, unit="mL", project=self.alpha, created_by=self.tech)
        InventoryLot.objects.create(item=self.item, lot_code="EXPIRED", quantity=999, unit="mL", expiration_date=timezone.localdate() - timedelta(days=1))
        InventoryLot.objects.create(item=self.item, lot_code="QUARANTINE", quantity=999, unit="mL", status="QUARANTINED")
        data = self.chat("Plan reagents for 30 samples using procedure EXTRACT version 1").data
        row = data["inventory_plan"]["rows"][0]
        self.assertEqual(Decimal(row["required"]), 60)
        self.assertEqual(Decimal(row["available"]), 50)
        self.assertEqual(Decimal(row["shortfall"]), 10)
        self.assertEqual(row["status"], "Short")
        self.assertEqual(InventoryReservation.objects.count(), 1)

    def test_inventory_missing_ambiguous_and_invalid_configuration(self):
        self.configure_inventory()
        requirement = self.procedure.reagent_requirements.get()
        requirement.unit = "kg"
        with self.assertRaises(ValidationError):
            requirement.full_clean()
        requirement.delete()
        self.assertNotIn("inventory_plan", self.chat("Plan reagents for 30 samples using procedure EXTRACT").data)
        ProcedureDefinition.objects.create(code="EXTRACT", version="2", name="Other", analysis=self.procedure.analysis)
        self.assertIn("multiple active versions", self.chat("Plan reagents for 30 samples using procedure EXTRACT").data["answer"])
        self.assertNotIn("inventory_plan", self.chat("Plan reagents for 0 samples using procedure EXTRACT").data)

    def test_registration_asks_fields_then_previews_and_confirms_sample_type(self):
        original = Sample.objects.count()
        first = self.chat("Register 2 plasma samples in project ALPHA")
        self.assertIn("Source", first.data["answer"])
        self.assertEqual(AssistantAction.objects.count(), 0)
        proposal = self.chat("with source=blood", context=first.data["context"])
        self.assertIn("pending_action", proposal.data)
        self.assertEqual(Sample.objects.count(), original)
        confirmed = self.confirm(proposal)
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(Sample.objects.filter(sample_type="PLASMA").count(), 2)
        self.confirm(proposal)
        self.assertEqual(Sample.objects.count(), original + 2)

    def test_registration_rechecks_access_on_followup(self):
        first = self.chat("Register 2 plasma samples in project ALPHA")
        self.alpha.members.remove(self.tech)
        result = self.chat("with source=blood", context=first.data["context"])
        self.assertNotIn("pending_action", result.data)
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_registration_rechecks_permissions_at_confirmation(self):
        original = Sample.objects.count()
        proposal = self.chat("Register 2 plasma samples in project ALPHA with source=blood")
        self.alpha.members.remove(self.tech)
        self.confirm(proposal)
        self.assertEqual(Sample.objects.count(), original)

    def test_invalid_stock_units_fail_closed(self):
        lot = self.configure_inventory()
        lot.unit = "kg"
        lot.save()
        row = self.chat("Plan reagents for 30 samples using procedure EXTRACT").data["inventory_plan"]["rows"][0]
        self.assertIsNone(row["available"])
        self.assertIsNone(row["shortfall"])
        self.assertIn("Unknown", row["status"])

    def test_registration_rejects_negation_duplicate_and_malformed_fields(self):
        messages = [
            "Do not register 2 plasma samples in project ALPHA with source=blood",
            "Explain how to create 2 samples in project ALPHA with source=blood",
            "Register 2 samples in project ALPHA with source=blood, source=plasma",
            "Register 2 samples in project ALPHA with ignored words source=blood",
            "Register 2 samples in project ALPHA with source=blood,",
            "Register 2 samples in project ALPHA with source=",
            'Register 2 samples in project ALPHA with source="blood" and approve all work',
            'Register 2 samples in project ALPHA with source="unclosed',
            "Register 2 samples in project ALPHA with source=blood and delete samples",
            "Register 2 samples in project ALPHA with source=blood; delete samples",
            "Register 2 samples in project ALPHA with source=NaN",
            "Register 2 samples in project ALPHA with source=1e999",
        ]
        original = Sample.objects.count()
        for message in messages:
            with self.subTest(message=message):
                result = self.chat(message)
                self.assertEqual(result.status_code, 200)
                self.assertNotIn("pending_action", result.data)
        self.assertEqual(AssistantAction.objects.count(), 0)
        self.assertEqual(Sample.objects.count(), original)

    def test_registration_preserves_quoted_commas_and_punctuation(self):
        proposal = self.chat('Please register 1 plasma sample in project ALPHA with source="blood, frozen."')
        self.assertIn("pending_action", proposal.data)
        action = AssistantAction.objects.get(pk=proposal.data["pending_action"]["id"])
        self.assertEqual(action.payload["custom_fields"]["source"], "blood, frozen.")
        self.assertEqual(self.confirm(proposal).status_code, 200)

    def test_registration_invalid_frozen_payload_never_creates_samples(self):
        from types import SimpleNamespace
        from assistant.sample_operations import execute_create_samples
        original = Sample.objects.count()
        for fields in [{"sample_codes": []}, {"sample_codes": "ALPHA-X"},
                       {"sample_codes": [None]}, {"sample_codes": [" "]},
                       {"sample_codes": ["x" * 65]}, {"sample_type": "x" * 65},
                       {"sample_type": {"bad": True}}, {"custom_fields": ["source"]}]:
            payload = {"project_id": self.alpha.pk, "sample_codes": ["ALPHA-X"], "custom_fields": {"source": "blood"}, **fields}
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                execute_create_samples(SimpleNamespace(payload=payload, requested_by=self.tech))
        self.assertEqual(Sample.objects.count(), original)

    def test_registration_can_recover_after_invalid_field_followup(self):
        first = self.chat("Register 2 plasma samples in project ALPHA")
        invalid = self.chat("with source=blood, source=plasma", context=first.data["context"])
        self.assertNotIn("pending_action", invalid.data)
        corrected = self.chat('with source="plasma, frozen"', context=invalid.data["context"])
        self.assertIn("pending_action", corrected.data)

    def test_overlong_generated_ids_are_rejected_before_preview(self):
        self.alpha.code = "A" * 64
        self.alpha.save()
        data = self.chat(f"Register 1 sample in project {self.alpha.code} with source=blood").data
        self.assertNotIn("pending_action", data)
        self.assertIn("64 characters", data["answer"])

    def test_plan_revalidates_configuration_written_without_form_validation(self):
        self.configure_inventory()
        self.procedure.reagent_requirements.update(unit="kg")
        data = self.chat("Plan reagents for 30 samples using procedure EXTRACT").data
        self.assertNotIn("inventory_plan", data)
        self.assertIn("Invalid reagent configuration", data["answer"])

    def test_overreserved_lot_is_unknown_and_released_reservations_are_ignored(self):
        lot = self.configure_inventory()
        reservation = InventoryReservation.objects.create(lot=lot, quantity=101, unit="mL", project=self.alpha)
        row = self.chat("Plan reagents for 30 samples using procedure EXTRACT").data["inventory_plan"]["rows"][0]
        self.assertIsNone(row["available"])
        self.assertIn("Unknown", row["status"])
        reservation.status = InventoryReservation.STATUS_RELEASED
        reservation.save()
        row = self.chat("Plan reagents for 30 samples using procedure EXTRACT").data["inventory_plan"]["rows"][0]
        self.assertEqual(Decimal(row["available"]), 100)
        self.assertEqual(row["status"], "Enough")

    def test_project_draft_is_scoped_read_only_and_rechecks_access(self):
        data = self.chat("Write a short progress update for project ALPHA").data
        self.assertIn("2 samples", data["draft"]["text"])
        self.assertIn("1 overdue", data["draft"]["text"])
        self.assertNotIn("PRIVATE", str(data))
        self.assertEqual(AssistantAction.objects.count(), 0)
        self.assertNotIn("draft", self.chat("Draft project update for project PRIVATE").data)
        self.alpha.members.remove(self.tech)
        self.assertNotIn("draft", self.chat("Draft project update for project ALPHA").data)
