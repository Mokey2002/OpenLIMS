import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.models import GeneratedArtifact
from events.models import Event
from imports.models import ImportJob, InstrumentProfile
from inventory.models import InventoryItem, InventoryLot, InventoryReservation
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample, SampleBatch


class AssistantInvestigationTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_dir = tempfile.mkdtemp(prefix="openlims-investigation-test-")
        cls.settings_override = override_settings(MEDIA_ROOT=cls.media_dir)
        cls.settings_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.settings_override.disable()
        shutil.rmtree(cls.media_dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        user_model = get_user_model()
        tech_group, _ = Group.objects.get_or_create(name="tech")
        viewer_group, _ = Group.objects.get_or_create(name="viewer")
        self.tech = user_model.objects.create_user(username="investigator")
        self.outsider = user_model.objects.create_user(username="outsider")
        self.tech.groups.add(tech_group)
        self.outsider.groups.add(viewer_group)

        self.project = Project.objects.create(code="INV", name="Investigation Project")
        self.private_project = Project.objects.create(code="SECRET", name="Secret Project")
        self.project.members.add(self.tech)
        self.private_project.members.add(self.outsider)
        self.batch = SampleBatch.objects.create(code="B-INV", project=self.project, created_by=self.tech)

        self.subject = Sample.objects.create(
            sample_id="S-INV-001",
            project=self.project,
            batch=self.batch,
            created_by=self.tech,
        )
        self.peers = [
            Sample.objects.create(
                sample_id=f"S-INV-00{index}",
                project=self.project,
                batch=self.batch,
                created_by=self.tech,
            )
            for index in range(2, 6)
        ]
        self.private_sample = Sample.objects.create(
            sample_id="S-SECRET-001",
            project=self.private_project,
            created_by=self.outsider,
        )

        self.instrument = InstrumentProfile.objects.create(
            name="Analyzer One",
            code="AN-1",
            sample_id_column="sample_id",
        )
        self.import_job = ImportJob.objects.create(
            instrument=self.instrument,
            project=self.project,
            uploaded_by=self.tech,
            run_id="RUN-INV-1",
            status="COMPLETED",
        )
        subject_work = WorkItem.objects.create(
            sample=self.subject,
            source_import_job=self.import_job,
            name="Analyzer chemistry results",
            work_type="CHEMISTRY",
            status=WorkItem.STATUS_COMPLETED,
            notes="Imported through the instrument connector.",
            assigned_to=self.tech,
            created_by=self.tech,
        )
        self.subject_result = Result.objects.create(
            work_item=subject_work,
            key="glucose",
            value_type=Result.VALUE_TYPE_NUMBER,
            value_number=100.0,
            unit="mg/dL",
            reference_min=5.0,
            reference_max=20.0,
            qc_passed=False,
            qc_status=Result.QC_REJECTED,
            qc_failure_reason="Above configured range.",
            entered_by=self.tech,
        )
        for index, (sample, value) in enumerate(zip(self.peers, [10.0, 11.0, 12.0, 13.0])):
            work = WorkItem.objects.create(
                sample=sample,
                name="Chemistry",
                work_type="CHEMISTRY",
                status=WorkItem.STATUS_COMPLETED,
                created_by=self.tech,
            )
            Result.objects.create(
                work_item=work,
                key="glucose",
                value_type=Result.VALUE_TYPE_NUMBER,
                value_number=value,
                unit="mg/dL",
                reference_min=5.0,
                reference_max=20.0,
                qc_passed=index != 0,
                qc_status=Result.QC_REJECTED if index == 0 else Result.QC_APPROVED,
                qc_failure_reason="Peer failure" if index == 0 else "",
                entered_by=self.tech,
            )

        private_work = WorkItem.objects.create(
            sample=self.private_sample,
            name="Secret chemistry",
            work_type="CHEMISTRY",
            status=WorkItem.STATUS_COMPLETED,
            created_by=self.outsider,
        )
        Result.objects.create(
            work_item=private_work,
            key="glucose",
            value_type=Result.VALUE_TYPE_NUMBER,
            value_number=9999.0,
            qc_passed=False,
            qc_status=Result.QC_REJECTED,
            entered_by=self.outsider,
        )

        reagent = InventoryItem.objects.create(
            code="RG-1",
            name="Control reagent",
            category=InventoryItem.CATEGORY_REAGENT,
            default_unit="mL",
        )
        lot = InventoryLot.objects.create(
            item=reagent,
            lot_code="LOT-EXPIRED",
            quantity=Decimal("25"),
            unit="mL",
            expiration_date=timezone.localdate() - timedelta(days=1),
            status=InventoryLot.STATUS_EXPIRED,
        )
        InventoryReservation.objects.create(
            lot=lot,
            project=self.project,
            quantity=Decimal("2"),
            unit="mL",
            status=InventoryReservation.STATUS_CONSUMED,
            created_by=self.tech,
        )
        Event.objects.create(
            entity_type="Result",
            entity_id=str(self.subject_result.id),
            action="QC_REJECTED",
            actor=self.tech,
            payload={"reason": "Above configured range."},
        )
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

    def test_workbench_ranks_direct_comparative_and_contextual_evidence(self):
        response = self.client.post(
            "/api/assistant/investigations/",
            {
                "subject_type": "sample",
                "identifier": self.subject.sample_id,
                "days": 90,
                "group_by": "overview",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        investigation = response.data["investigation"]
        evidence_types = {row["evidence_type"] for row in investigation["findings"]}
        self.assertEqual(evidence_types, {"direct", "comparative", "contextual"})
        self.assertEqual(investigation["subject"]["sample_id"], "S-INV-001")
        self.assertEqual(investigation["scope"]["cohort"], "batch B-INV")
        self.assertTrue(investigation["instrument_context"][0]["direct_sample_link"])
        self.assertEqual(
            investigation["instrument_context"][0]["provenance_source"],
            "database_relation",
        )
        self.assertEqual(investigation["reagent_context"][0]["lot_code"], "LOT-EXPIRED")
        self.assertTrue(any(row["action"] == "QC_REJECTED" for row in investigation["timeline"]))
        self.assertNotIn("9999", str(response.data))

    def test_assistant_routes_investigation_and_reuses_context_for_graph(self):
        first = self.chat("Investigate why sample S-INV-001 failed QC")

        self.assertEqual(first.status_code, 200)
        self.assertIn("investigation", first.data)
        self.assertEqual(first.data["context"]["investigation"]["identifier"], "S-INV-001")

        follow_up = self.chat(
            "Graph failures by operator",
            context=first.data["context"],
        )
        self.assertEqual(follow_up.data["context"]["investigation"]["group_by"], "operator")
        self.assertEqual(follow_up.data["chart"]["meta"]["title"], "QC failure rate by result entrant")

        focused = self.chat(
            "Show instrument import context",
            context=first.data["context"],
        )
        self.assertIn("investigation", focused.data)
        self.assertNotIn("chart", focused.data)

    def test_investigation_context_does_not_capture_new_inventory_request(self):
        first = self.chat("Investigate why sample S-INV-001 failed QC")
        inventory = self.chat(
            "Show the inventory below its reorder level",
            context=first.data["context"],
        )

        self.assertNotIn("investigation", inventory.data)
        self.assertNotIn("chart", inventory.data)
        self.assertIn("reorder level", inventory.data["answer"])

    def test_non_qc_why_and_non_sample_investigation_do_not_start_workbench(self):
        workflow = self.chat("Why is sample S-INV-001 still processing?")
        import_job = self.chat("Investigate the root cause of the failed import job")

        for response in [workflow, import_job]:
            self.assertNotIn("investigation", response.data)
            self.assertNotIn("chart", response.data)

    def test_result_identifier_uses_same_permission_checked_investigation(self):
        response = self.client.post(
            "/api/assistant/investigations/",
            {
                "subject_type": "result",
                "identifier": f"R-{self.subject_result.id}",
                "group_by": "workflow",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["investigation"]["subject"]["result_id"], self.subject_result.id)
        self.assertTrue(response.data["investigation"]["results"][0]["is_subject_result"])

    def test_private_sample_is_not_disclosed(self):
        response = self.client.post(
            "/api/assistant/investigations/",
            {
                "subject_type": "sample",
                "identifier": self.private_sample.sample_id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("investigation", response.data)
        self.assertNotIn("9999", str(response.data))

    def test_confirmed_pdf_export_recalculates_and_creates_artifact(self):
        investigation = self.chat("Investigate why sample S-INV-001 failed QC")
        proposal = self.chat(
            "Export this investigation as PDF",
            context=investigation.data["context"],
        )

        self.assertEqual(proposal.data["pending_action"]["type"], "COMPLIANCE_REPORT")
        confirmed = self.confirm(proposal)
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.data["status"], "COMPLETED")
        artifact = GeneratedArtifact.objects.get(id=confirmed.data["result"]["artifact_id"])
        self.assertEqual(artifact.parameters["report_type"], "INVESTIGATION_REPORT")
        with artifact.file.open("rb") as stream:
            self.assertEqual(stream.read(4), b"%PDF")

    def test_endpoint_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            "/api/assistant/investigations/",
            {"subject_type": "sample", "identifier": self.subject.sample_id},
            format="json",
        )
        self.assertEqual(response.status_code, 401)
