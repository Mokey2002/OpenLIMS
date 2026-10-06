"""Cross-module journeys through real API views and the test database (no API mocks)."""
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from events.models import Event
from inventory.models import Container, Location
from pipelines.models import PipelineRun
from projects.models import Project
from results.models import Result, WorkItem
from samples.models import Sample, SampleCustodyEvent
from settings_app.models import SystemSettings


class CompleteLabWorkflowTests(APITestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings_override = override_settings(MEDIA_ROOT=media.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        settings = SystemSettings.load()
        settings.notebook_enabled = True
        settings.save()
        self.users = {}
        for role in ("admin", "tech", "qc_reviewer", "viewer", "outsider"):
            user = get_user_model().objects.create_user(username=f"journey-{role}")
            user.groups.add(Group.objects.get_or_create(name="tech" if role == "outsider" else role)[0])
            self.users[role] = user
        self.project = Project.objects.create(code="JOURNEY", name="Sequencing pilot")
        self.project.members.add(*(self.users[r] for r in ("tech", "qc_reviewer", "viewer")))
        self.as_role("admin")
        procedures = []
        for code, key in (("EXTRACT", "concentration"), ("SEQUENCE", "quality_score")):
            analysis = self.send("post", "/api/analysis-definitions/", {
                "code": code, "name": code, "required_fields": [
                    {"key": key, "label": key, "value_type": "NUMBER", "required": True}],
            }, 201)
            procedures.append(self.send("post", "/api/procedure-definitions/", {
                "code": code, "name": code, "version": "1", "analysis": analysis["id"],
            }, 201)["id"])
        self.template = self.send("post", "/api/pipeline-templates/", {
            "code": "JOURNEY", "name": "Extraction to sequencing", "active": True,
            "steps": [{"position": i + 1, "procedure": p, "requires_qc": True}
                      for i, p in enumerate(procedures)],
        }, 201)
        self.as_role("tech")
        self.sample = self.send("post", "/api/samples/", {
            "sample_id": "JOURNEY-001", "sample_type": "DNA", "project": self.project.pk,
        }, 201)
        self.run = self.send("post", "/api/pipeline-runs/", {
            "sample": self.sample["id"], "template": self.template["id"],
        }, 201)
        self.run_model = PipelineRun.objects.get(pk=self.run["id"])

    def as_role(self, role):
        self.client.force_authenticate(self.users[role])

    def send(self, method, url, data, expected=200):
        response = getattr(self.client, method)(url, data, format="json")
        self.assertEqual(response.status_code, expected, getattr(response, "data", None))
        return response.data

    def result(self, work_id, key, value):
        return self.send("post", "/api/results/", {
            "work_item": work_id, "key": key, "value_type": "NUMBER", "value_number": value,
        }, 201)

    def approve(self, work_id):
        self.as_role("qc_reviewer")
        self.send("post", f"/api/work-items/{work_id}/qc-review/", {
            "qc_status": "APPROVED", "review_note": "Measurements independently verified.",
        })

    def test_registered_sample_through_qc_sequence_storage_and_experiment_export(self):
        first = self.run_model.steps.get(position=1)
        second = self.run_model.steps.get(position=2)
        self.assertIsNone(second.work_item_id)
        work_url = f"/api/work-items/{first.work_item_id}/"
        missing = self.send("patch", work_url, {"status": "COMPLETED"}, 400)
        self.assertEqual(missing["missing_required_fields"], ["concentration"])
        concentration = self.result(first.work_item_id, "concentration", 43)
        self.send("patch", work_url, {"status": "COMPLETED"})
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, "AWAITING_QC")
        self.assertIsNone(second.work_item_id)
        self.send("post", work_url + "qc-review/", {
            "qc_status": "APPROVED", "review_note": "Operator cannot approve own work.",
        }, 403)
        self.approve(first.work_item_id)
        second.refresh_from_db()
        self.assertEqual(second.status, "READY")
        self.as_role("tech")
        quality = self.result(second.work_item_id, "quality_score", 98)
        sequence = self.send("post", "/api/sequences/", {
            "name": "JOURNEY consensus", "sequence_type": "DNA", "sequence": "ACGTACGT",
            "project": self.project.pk, "sample": self.sample["id"],
        }, 201)
        upload = self.client.post("/api/sample-attachments/", {
            "sample": self.sample["id"],
            "file": SimpleUploadedFile("reads.csv", b"sample,quality\nJOURNEY-001,98\n", "text/csv"),
        }, format="multipart")
        self.assertEqual(upload.status_code, 201, upload.data)
        self.send("patch", f"/api/work-items/{second.work_item_id}/", {"status": "COMPLETED"})
        self.approve(second.work_item_id)
        self.run_model.refresh_from_db()
        self.assertEqual(self.run_model.status, "COMPLETED")
        self.as_role("tech")
        location = Location.objects.create(name="Journey freezer", kind="freezer")
        container = Container.objects.create(container_id="JOURNEY-BOX", kind="box", location=location)
        self.send("post", "/api/sample-custody-events/scan/", {
            "barcode": self.sample["sample_id"], "action": "MOVE", "container": container.pk,
            "reason": "Stored after sequencing and independent QC review.",
        }, 201)
        notebook = self.send("post", "/api/notebooks/", {
            "name": "Sequencing record", "scope": "PROJECT", "project": self.project.pk,
        }, 201)
        experiment = self.send("post", "/api/experiments/", {
            "notebook": notebook["id"], "title": "JOURNEY sequencing report",
            "initial_blocks": [{"block_type": "RICH_TEXT", "data": {"text": "Concentration 43; sequence quality 98; independently approved."}}],
            "initial_links": [{"entity_type": "sample", "public_id": self.sample["public_id"], "relation_type": "physical_sample"}],
        }, 201)
        exp_url = f"/api/experiments/{experiment['id']}/"
        self.send("post", exp_url + "autosave/", {
            "reason": "Record final storage after QC",
            "blocks": [{"block_type": "RICH_TEXT", "data": {"text": "Approved sequence stored in JOURNEY-BOX."}}],
            "links": [{"entity_type": "sample", "public_id": self.sample["public_id"], "relation_type": "physical_sample"}],
        })
        self.send("post", exp_url + "transition/", {"status": "COMPLETED"})
        # Independent, newly authenticated reader retrieves the persisted chain.
        self.as_role("viewer")
        detail = self.send("get", f"/api/samples/{self.sample['id']}/", {})
        self.assertEqual(detail["container_id"], container.pk)
        self.assertEqual(detail["location_name"], location.name)
        for recorded in (concentration, quality):
            result = self.send("get", f"/api/results/{recorded['id']}/", {})
            self.assertEqual(result["sample_id"], self.sample["id"])
        self.assertEqual(self.send("get", f"/api/sequences/{sequence['id']}/", {})["sample"], self.sample["id"])
        self.assertEqual(self.send("get", f"/api/sample-attachments/{upload.data['id']}/", {})["sample"], self.sample["id"])
        exported = self.client.get(exp_url + "export-pdf/")
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported["Content-Type"], "application/pdf")
        self.assertTrue(exported.content.startswith(b"%PDF"))
        record = self.send("get", exp_url, {})
        self.assertEqual(str(record["current_revision_detail"]["links"][0]["entity_public_id"]), str(self.sample["public_id"]))
        self.send("post", exp_url + "autosave/", {"blocks": [], "links": []}, 403)
        self.assertEqual(SampleCustodyEvent.objects.get(sample_id=self.sample["id"]).performed_by, self.users["tech"])
        self.assertTrue(Event.objects.filter(action="PIPELINE_RUN_COMPLETED", entity_id=str(self.sample["id"])).exists())
        self.assertEqual(WorkItem.objects.get(pk=second.work_item_id).reviewed_by, self.users["qc_reviewer"])
        self.as_role("outsider")
        for url in (exp_url, exp_url + "export-pdf/", f"/api/sequences/{sequence['id']}/",
                    f"/api/sample-attachments/{upload.data['id']}/"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404, url)

    def test_rejected_qc_blocks_downstream_work_and_preserves_measurements(self):
        first = self.run_model.steps.get(position=1)
        recorded = self.result(first.work_item_id, "concentration", 2)
        self.send("patch", f"/api/work-items/{first.work_item_id}/", {"status": "COMPLETED"})
        self.as_role("qc_reviewer")
        self.send("post", f"/api/work-items/{first.work_item_id}/qc-review/", {
            "qc_status": "REJECTED", "review_note": "Concentration insufficient for sequencing.",
        })
        self.run_model.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(self.run_model.status, "BLOCKED")
        self.assertEqual(first.status, "FAILED")
        self.assertIsNone(self.run_model.steps.get(position=2).work_item_id)
        self.assertEqual(Result.objects.get(pk=recorded["id"]).value_number, 2)
        self.assertFalse(Event.objects.filter(action="PIPELINE_RUN_COMPLETED").exists())
        review = Event.objects.get(entity_type="WorkItem", entity_id=str(first.work_item_id), action="QC_REJECTED")
        self.assertEqual(review.actor, self.users["qc_reviewer"])
        self.assertIn("insufficient", review.payload["after"]["review_note"])

    def test_readonly_outsider_and_revoked_member_cannot_change_or_retrieve_work(self):
        work = self.run_model.steps.get(position=1).work_item
        result = self.result(work.pk, "concentration", 43)
        urls = [f"/api/samples/{self.sample['id']}/", f"/api/pipeline-runs/{self.run['id']}/",
                f"/api/work-items/{work.pk}/", f"/api/results/{result['id']}/"]
        self.as_role("viewer")
        for url in urls:
            self.send("get", url, {})
        self.send("patch", urls[0], {"sample_type": "CHANGED"}, 403)
        self.send("patch", urls[2], {"status": "COMPLETED"}, 403)
        self.send("patch", urls[3], {"value_number": 999}, 403)
        for role in ("outsider", "tech"):
            if role == "tech":
                self.project.members.remove(self.users["tech"])
            self.as_role(role)
            for url in urls:
                self.send("get", url, {}, 404)
            self.send("patch", urls[3], {"value_number": 999}, 404)
        self.assertEqual(Result.objects.get(pk=result["id"]).value_number, 43)
        self.assertEqual(Sample.objects.get(pk=self.sample["id"]).sample_type, "DNA")
        work.refresh_from_db()
        self.assertEqual(work.status, "PENDING")
