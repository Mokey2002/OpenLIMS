from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIClient

from assistant.models import SOPDocument
from inventory.models import InventoryItem, InventoryLot
from notebook.models import Experiment, ExperimentBlock, ExperimentComment, ExperimentRevision
from projects.models import Project
from registry.models import RegistryRecord, RegistryRecordVersion, RegistrySchema
from samples.models import Sample


User = get_user_model()


def user_with_role(username, role):
    user = User.objects.create_user(username=username, password="test-pass")
    group, _ = Group.objects.get_or_create(name=role)
    user.groups.add(group)
    return user


class NotebookV1Tests(TestCase):
    def setUp(self):
        self.director = user_with_role("director-notebook", "admin")
        self.scientist = user_with_role("scientist-notebook", "tech")
        self.reviewer = user_with_role("reviewer-notebook", "qc_reviewer")
        self.collaborator = user_with_role("collaborator-notebook", "viewer")
        self.outsider = user_with_role("outsider-notebook", "viewer")
        self.project = Project.objects.create(name="Notebook Project", code="NB-PROJ")
        self.project.members.add(self.scientist, self.reviewer, self.collaborator)
        self.sample = Sample.objects.create(sample_id="NB-SAMPLE-001", project=self.project, created_by=self.scientist)
        item = InventoryItem.objects.create(code="NB-REAGENT", name="Notebook reagent", default_unit="uL")
        self.lot = InventoryLot.objects.create(item=item, lot_code="NB-LOT-001", quantity="100", unit="uL")
        schema = RegistrySchema.objects.create(code="nb-plasmid", name="Notebook plasmid", entity_type="plasmid", id_prefix="NBP", created_by=self.director)
        self.plasmid = RegistryRecord.objects.create(registry_id="NBP-0001", schema=schema, name="pNotebook", project=self.project, owner=self.scientist)
        version = RegistryRecordVersion.objects.create(record=self.plasmid, schema=schema, version=1, data={"backbone": "pUC"}, created_by=self.scientist)
        self.plasmid.current_version = version
        self.plasmid.save(update_fields=["current_version"])
        self.sop = SOPDocument.objects.create(document_code="SOP-NB", title="Notebook SOP", version="2.1", section="Main", content="Protocol", project=self.project, uploaded_by=self.director, approved=True)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_template_revision_restore_review_lock_comment_and_pdf(self):
        scientist = self.client_for(self.scientist)
        notebook_response = scientist.post(
            "/api/notebooks/",
            {"name": "Plasmid experiments", "scope": "PROJECT", "project": self.project.pk},
            format="json",
        )
        self.assertEqual(notebook_response.status_code, 201, notebook_response.data)
        notebook_id = notebook_response.data["id"]
        versioned_notebooks = scientist.get("/api/v1/notebooks/")
        self.assertEqual(versioned_notebooks.status_code, 200, versioned_notebooks.data)
        self.assertEqual(versioned_notebooks.data["results"][0]["public_id"], notebook_response.data["public_id"])
        template_response = scientist.post(
            "/api/experiment-templates/",
            {
                "notebook": notebook_id,
                "name": "Plasmid validation",
                "blocks": [
                    {"block_type": "HEADING", "data": {"text": "Plasmid validation"}},
                    {"block_type": "CHECKLIST", "data": {"items": [{"text": "Digest", "checked": False}]}},
                ],
            },
            format="json",
        )
        self.assertEqual(template_response.status_code, 201, template_response.data)
        experiment_response = scientist.post(
            f"/api/experiment-templates/{template_response.data['id']}/instantiate/",
            {"title": "pNotebook validation"},
            format="json",
        )
        self.assertEqual(experiment_response.status_code, 201, experiment_response.data)
        experiment_id = experiment_response.data["id"]

        autosave = scientist.post(
            f"/api/experiments/{experiment_id}/autosave/",
            {
                "reason": "Recorded exact materials",
                "blocks": [
                    {"block_type": "HEADING", "data": {"text": "pNotebook validation"}},
                    {"block_type": "PROTOCOL_STEP", "data": {"text": "Digest 1 ug DNA", "completed": True}},
                    {"block_type": "STRUCTURED_RESULT", "data": {"name": "Digest", "value": "Pass"}},
                ],
                "links": [
                    {"entity_type": "registry_record", "public_id": str(self.plasmid.public_id), "relation_type": "plasmid"},
                    {"entity_type": "sop_document", "public_id": str(self.sop.public_id), "relation_type": "protocol"},
                    {"entity_type": "sample", "public_id": str(self.sample.public_id), "relation_type": "physical_sample"},
                    {"entity_type": "inventory_lot", "public_id": str(self.lot.public_id), "relation_type": "reagent_lot"},
                ],
            },
            format="json",
        )
        self.assertEqual(autosave.status_code, 200, autosave.data)
        self.assertTrue(autosave.data["created"])
        self.assertEqual(ExperimentRevision.objects.filter(experiment_id=experiment_id).count(), 2)
        link_versions = {link.entity_type: link.version for link in ExperimentRevision.objects.get(experiment_id=experiment_id, number=2).links.all()}
        self.assertEqual(link_versions["registry_record"]["record_version"], 1)
        self.assertEqual(link_versions["sop_document"]["version"], "2.1")
        self.assertEqual(link_versions["inventory_lot"]["lot_code"], "NB-LOT-001")

        unchanged = scientist.post(
            f"/api/experiments/{experiment_id}/autosave/",
            {
                "reason": "Repeated autosave",
                "blocks": [
                    {"block_type": "HEADING", "data": {"text": "pNotebook validation"}},
                    {"block_type": "PROTOCOL_STEP", "data": {"text": "Digest 1 ug DNA", "completed": True}},
                    {"block_type": "STRUCTURED_RESULT", "data": {"name": "Digest", "value": "Pass"}},
                ],
                "links": [
                    {"entity_type": "registry_record", "public_id": str(self.plasmid.public_id), "relation_type": "plasmid"},
                    {"entity_type": "sop_document", "public_id": str(self.sop.public_id), "relation_type": "protocol"},
                    {"entity_type": "sample", "public_id": str(self.sample.public_id), "relation_type": "physical_sample"},
                    {"entity_type": "inventory_lot", "public_id": str(self.lot.public_id), "relation_type": "reagent_lot"},
                ],
            },
            format="json",
        )
        self.assertEqual(unchanged.status_code, 200, unchanged.data)
        self.assertFalse(unchanged.data["created"])
        self.assertEqual(ExperimentRevision.objects.filter(experiment_id=experiment_id).count(), 2)

        first_revision = ExperimentRevision.objects.get(experiment_id=experiment_id, number=1)
        restore = scientist.post(
            f"/api/experiments/{experiment_id}/restore/",
            {"revision_public_id": str(first_revision.public_id), "reason": "Restore template state"},
            format="json",
        )
        self.assertEqual(restore.status_code, 201, restore.data)
        self.assertEqual(ExperimentRevision.objects.filter(experiment_id=experiment_id).count(), 3)
        self.assertEqual(ExperimentBlock.objects.filter(revision=first_revision).count(), 2)

        newer_plasmid_version = RegistryRecordVersion.objects.create(
            record=self.plasmid,
            schema=self.plasmid.schema,
            version=2,
            data={"backbone": "pUC", "marker": "ampicillin"},
            created_by=self.scientist,
        )
        self.plasmid.current_version = newer_plasmid_version
        self.plasmid.save(update_fields=["current_version"])
        linked_revision = ExperimentRevision.objects.get(experiment_id=experiment_id, number=2)
        restored_linked = scientist.post(
            f"/api/experiments/{experiment_id}/restore/",
            {"revision_public_id": str(linked_revision.public_id), "reason": "Restore exact material snapshot"},
            format="json",
        )
        self.assertEqual(restored_linked.status_code, 201, restored_linked.data)
        restored_versions = {
            link["entity_type"]: link["version"] for link in restored_linked.data["links"]
        }
        self.assertEqual(restored_versions["registry_record"]["record_version"], 1)
        self.assertEqual(ExperimentRevision.objects.filter(experiment_id=experiment_id).count(), 4)

        complete = scientist.post(f"/api/experiments/{experiment_id}/transition/", {"status": "COMPLETED", "reason": "Execution complete"}, format="json")
        self.assertEqual(complete.status_code, 200, complete.data)
        reviewer = self.client_for(self.reviewer)
        review = reviewer.post(
            f"/api/experiments/{experiment_id}/review/",
            {"decision": "APPROVED", "comment": "Reviewed against SOP", "signed_name": "Notebook Reviewer"},
            format="json",
        )
        self.assertEqual(review.status_code, 201, review.data)
        locked = reviewer.post(f"/api/experiments/{experiment_id}/lock/", {"reason": "Final project record"}, format="json")
        self.assertEqual(locked.status_code, 200, locked.data)
        self.assertEqual(locked.data["status"], "LOCKED")

        collaborator = self.client_for(self.collaborator)
        comment = collaborator.post(
            "/api/experiment-comments/",
            {"experiment": experiment_id, "revision": locked.data["current_revision"], "body": "Checked the signed-off result.", "mentions": [self.scientist.pk]},
            format="json",
        )
        self.assertEqual(comment.status_code, 201, comment.data)
        self.assertEqual(ExperimentComment.objects.filter(experiment_id=experiment_id).count(), 1)
        blocked_edit = scientist.post(f"/api/experiments/{experiment_id}/autosave/", {"blocks": [], "links": []}, format="json")
        self.assertEqual(blocked_edit.status_code, 400)
        pdf = collaborator.get(f"/api/experiments/{experiment_id}/export-pdf/")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertGreater(len(pdf.content), 2000)

        outsider = self.client_for(self.outsider)
        self.assertEqual(outsider.get(f"/api/experiments/{experiment_id}/").status_code, 404)

    def test_clone_preserves_signed_content_without_modifying_source(self):
        notebook = self.client_for(self.scientist).post(
            "/api/notebooks/", {"name": "Clone notebook", "scope": "PROJECT", "project": self.project.pk}, format="json"
        ).data
        experiment = self.client_for(self.scientist).post(
            "/api/experiments/",
            {"notebook": notebook["id"], "title": "Source experiment", "initial_blocks": [{"block_type": "RICH_TEXT", "data": {"text": "Original"}}]},
            format="json",
        )
        clone = self.client_for(self.scientist).post(
            f"/api/experiments/{experiment.data['id']}/clone/", {"title": "Cloned experiment"}, format="json"
        )
        self.assertEqual(clone.status_code, 201, clone.data)
        self.assertNotEqual(clone.data["public_id"], experiment.data["public_id"])
        self.assertEqual(clone.data["current_revision_detail"]["blocks"][0]["data"]["text"], "Original")
