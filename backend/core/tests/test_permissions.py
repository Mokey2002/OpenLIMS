from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from alignments.models import AlignmentJob
from blast.models import BlastDatabase, BlastJob
from imports.models import InstrumentProfile
from inventory.models import Location, Container
from events.models import Event
from mass_spec.models import MassSpecRun
from projects.models import Project
from results.models import WorkItem
from samples.models import Sample
from sequences.models import Sequence


User = get_user_model()


def create_user(username, password, role=None, is_superuser=False):
    user = User.objects.create_user(
        username=username,
        password=password,
        email=f"{username}@example.com",
    )

    user.is_active = True
    user.is_staff = is_superuser
    user.is_superuser = is_superuser
    user.save()

    if role:
        group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(group)

    return user


class BackendPermissionTests(APITestCase):
    def setUp(self):
        self.admin = create_user(
            "admin",
            "Admin123456!",
            role="admin",
            is_superuser=True,
        )

        self.tech = create_user(
            "tech",
            "tech123",
            role="tech",
        )

        self.viewer = create_user(
            "viewer",
            "viewer123",
            role="viewer",
        )

        self.project = Project.objects.create(
            code="PRJ-TEST",
            name="Permission Test Project",
            description="Project used for backend permission tests.",
        )
        self.project.members.set([self.admin, self.tech, self.viewer])

        self.sample = Sample.objects.create(
            sample_id="S-TEST-001",
            status="RECEIVED",
            project=self.project,
        )

        self.instrument = InstrumentProfile.objects.create(
            name="Generic FASTA Sequencer",
            code="FASTA-TEST",
            delimiter=",",
            has_header=True,
            sample_id_column="sample_id",
        )

        self.sequence = Sequence.objects.create(
            name="Test Sequence",
            description="Permission test sequence.",
            sequence_type="DNA",
            sequence="ATGCGTACCGTAGGCTA",
            project=self.project,
            sample=self.sample,
            created_by=self.tech,
        )

        self.sequence_2 = Sequence.objects.create(
            name="Test Sequence 2",
            description="Second permission test sequence.",
            sequence_type="DNA",
            sequence="ATGCGTACCGTAGGCTT",
            project=self.project,
            sample=self.sample,
            created_by=self.tech,
        )

        self.blast_database = BlastDatabase.objects.create(
            name="Permission Test BLAST DB",
            description="BLAST database used for permission tests.",
            database_type=BlastDatabase.DATABASE_TYPE_DNA,
            status=BlastDatabase.STATUS_READY,
            db_path="/tmp/openlims-test-blast-db",
            created_by=self.tech,
        )

        self.work_item = WorkItem.objects.create(
            sample=self.sample,
            name="Permission QC Work Item",
            status="COMPLETED",
            qc_status=WorkItem.QC_PENDING_REVIEW,
        )

    def auth_as(self, user):
        self.client.force_authenticate(user=user)

    def test_admin_can_export_audit_events(self):
        self.auth_as(self.admin)

        response = self.client.get("/api/events/export-csv/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_tech_cannot_export_audit_events(self):
        self.auth_as(self.tech)

        response = self.client.get("/api/events/export-csv/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_export_audit_events(self):
        self.auth_as(self.viewer)

        response = self.client.get("/api/events/export-csv/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_can_read_audit_events(self):
        self.auth_as(self.viewer)

        response = self.client.get("/api/events/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_read_mass_spec_runs(self):
        self.auth_as(self.viewer)

        response = self.client.get("/api/mass-spec-runs/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_cannot_create_mass_spec_run(self):
        self.auth_as(self.viewer)

        upload = SimpleUploadedFile(
            "viewer-blocked.mzML",
            b"not a real mzML file",
            content_type="application/octet-stream",
        )

        response = self.client.post(
            "/api/mass-spec-runs/",
            {
                "name": "Viewer Blocked Mass Spec Run",
                "project": self.project.id,
                "sample": self.sample.id,
                "uploaded_file": upload,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("mass_spec.views.process_mass_spec_run_task.delay")
    def test_tech_can_create_mass_spec_run(self, mock_delay):
        self.auth_as(self.tech)

        upload = SimpleUploadedFile(
            "tech-upload.mzML",
            b"not a real mzML file",
            content_type="application/octet-stream",
        )

        response = self.client.post(
            "/api/mass-spec-runs/",
            {
                "name": "Tech Mass Spec Run",
                "project": self.project.id,
                "sample": self.sample.id,
                "uploaded_file": upload,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        run = MassSpecRun.objects.get(name="Tech Mass Spec Run")
        self.assertEqual(run.uploaded_by, self.tech)

        mock_delay.assert_called_once_with(run.id)

    @patch("mass_spec.views.process_mass_spec_run_task.delay")
    def test_admin_can_create_mass_spec_run(self, mock_delay):
        self.auth_as(self.admin)

        upload = SimpleUploadedFile(
            "admin-upload.mzML",
            b"not a real mzML file",
            content_type="application/octet-stream",
        )

        response = self.client.post(
            "/api/mass-spec-runs/",
            {
                "name": "Admin Mass Spec Run",
                "project": self.project.id,
                "sample": self.sample.id,
                "uploaded_file": upload,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        run = MassSpecRun.objects.get(name="Admin Mass Spec Run")
        self.assertEqual(run.uploaded_by, self.admin)

        mock_delay.assert_called_once_with(run.id)

    def test_viewer_cannot_reprocess_mass_spec_run(self):
        run = MassSpecRun.objects.create(
            name="Existing Mass Spec Run",
            project=self.project,
            sample=self.sample,
            uploaded_by=self.tech,
            uploaded_file="mass_spec/existing.mzML",
            original_filename="existing.mzML",
        )

        self.auth_as(self.viewer)

        response = self.client.post(f"/api/mass-spec-runs/{run.id}/reprocess/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("mass_spec.views.process_mass_spec_run_task.delay")
    def test_tech_can_reprocess_mass_spec_run(self, mock_delay):
        run = MassSpecRun.objects.create(
            name="Existing Mass Spec Run",
            project=self.project,
            sample=self.sample,
            uploaded_by=self.tech,
            uploaded_file="mass_spec/existing.mzML",
            original_filename="existing.mzML",
        )

        self.auth_as(self.tech)

        response = self.client.post(f"/api/mass-spec-runs/{run.id}/reprocess/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_delay.assert_called_once_with(run.id)

    @patch("mass_spec.views.process_mass_spec_run_task.delay")
    def test_admin_can_reprocess_mass_spec_run(self, mock_delay):
        run = MassSpecRun.objects.create(
            name="Existing Admin Mass Spec Run",
            project=self.project,
            sample=self.sample,
            uploaded_by=self.tech,
            uploaded_file="mass_spec/existing-admin.mzML",
            original_filename="existing-admin.mzML",
        )

        self.auth_as(self.admin)

        response = self.client.post(f"/api/mass-spec-runs/{run.id}/reprocess/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_delay.assert_called_once_with(run.id)

    def test_viewer_can_compare_mass_spec_runs_by_project(self):
        MassSpecRun.objects.create(
            name="Compare Run A",
            project=self.project,
            sample=self.sample,
            uploaded_by=self.tech,
            uploaded_file="mass_spec/compare-a.mzML",
            original_filename="compare-a.mzML",
            status=MassSpecRun.STATUS_COMPLETED,
            spectra_count=2,
            peak_count=6,
            feature_count=2,
            protein_count=1,
            peptide_count=3,
            base_peak_mz=150.0,
            base_peak_intensity=50.0,
            total_ion_current=80.0,
            detected_features=[
                {"mz": 100.01, "total_intensity": 30.0},
                {"mz": 150.02, "total_intensity": 50.0},
            ],
        )

        MassSpecRun.objects.create(
            name="Compare Run B",
            project=self.project,
            sample=self.sample,
            uploaded_by=self.tech,
            uploaded_file="mass_spec/compare-b.mzML",
            original_filename="compare-b.mzML",
            status=MassSpecRun.STATUS_COMPLETED,
            spectra_count=3,
            peak_count=8,
            feature_count=2,
            protein_count=2,
            peptide_count=4,
            base_peak_mz=150.1,
            base_peak_intensity=55.0,
            total_ion_current=95.0,
            detected_features=[
                {"mz": 100.04, "total_intensity": 33.0},
                {"mz": 200.01, "total_intensity": 62.0},
            ],
        )

        self.auth_as(self.viewer)

        response = self.client.get(
            f"/api/mass-spec-runs/compare/?project={self.project.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["summary"]["run_count"], 2)
        self.assertEqual(response.data["summary"]["feature_count_max"], 2)
        self.assertEqual(response.data["summary"]["protein_count_max"], 2)
        self.assertIn("feature_overlap", response.data)
        self.assertIn(100.0, response.data["feature_overlap"]["shared_feature_mz"])

    def test_viewer_can_compare_mass_spec_runs_by_sample(self):
        MassSpecRun.objects.create(
            name="Sample Compare Run A",
            project=self.project,
            sample=self.sample,
            uploaded_by=self.tech,
            uploaded_file="mass_spec/sample-compare-a.mzML",
            original_filename="sample-compare-a.mzML",
            status=MassSpecRun.STATUS_COMPLETED,
            spectra_count=1,
            peak_count=2,
            feature_count=1,
            detected_features=[{"mz": 300.0, "total_intensity": 10.0}],
        )

        MassSpecRun.objects.create(
            name="Sample Compare Run B",
            project=self.project,
            sample=self.sample,
            uploaded_by=self.tech,
            uploaded_file="mass_spec/sample-compare-b.mzML",
            original_filename="sample-compare-b.mzML",
            status=MassSpecRun.STATUS_COMPLETED,
            spectra_count=1,
            peak_count=2,
            feature_count=1,
            detected_features=[{"mz": 300.04, "total_intensity": 12.0}],
        )

        self.auth_as(self.viewer)

        response = self.client.get(
            f"/api/mass-spec-runs/compare/?sample={self.sample.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertIn(300.0, response.data["feature_overlap"]["shared_feature_mz"])

    def test_compare_mass_spec_runs_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(
            f"/api/mass-spec-runs/compare/?project={self.project.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_location_create_writes_audit_event(self):
        self.auth_as(self.admin)

        response = self.client.post(
            "/api/locations/",
            {
                "name": "Audit Freezer",
                "kind": "freezer",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        location = Location.objects.get(name="Audit Freezer")
        event = Event.objects.get(
            entity_type="Location",
            entity_id=str(location.id),
            action="LOCATION_CREATED",
        )

        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.payload["name"], "Audit Freezer")
        self.assertEqual(event.payload["kind"], "freezer")

    def test_admin_location_update_writes_audit_event(self):
        location = Location.objects.create(
            name="Old Audit Freezer",
            kind="freezer",
        )

        self.auth_as(self.admin)

        response = self.client.patch(
            f"/api/locations/{location.id}/",
            {
                "name": "Updated Audit Freezer",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event = Event.objects.get(
            entity_type="Location",
            entity_id=str(location.id),
            action="LOCATION_UPDATED",
        )

        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.payload["before"]["name"], "Old Audit Freezer")
        self.assertEqual(event.payload["after"]["name"], "Updated Audit Freezer")

    def test_admin_container_create_writes_audit_event(self):
        location = Location.objects.create(
            name="Container Audit Location",
            kind="freezer",
        )

        self.auth_as(self.admin)

        response = self.client.post(
            "/api/containers/",
            {
                "container_id": "AUDIT-BOX-001",
                "kind": "box",
                "location": location.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        container = Container.objects.get(container_id="AUDIT-BOX-001")
        event = Event.objects.get(
            entity_type="Container",
            entity_id=str(container.id),
            action="CONTAINER_CREATED",
        )

        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.payload["container_id"], "AUDIT-BOX-001")
        self.assertEqual(event.payload["location"], location.id)

    def test_sample_status_transition_requires_reason(self):
        self.auth_as(self.tech)

        response = self.client.post(
            f"/api/samples/{self.sample.id}/transition/",
            {
                "new_status": "IN_PROGRESS",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.sample.refresh_from_db()
        self.assertEqual(self.sample.status, "RECEIVED")

    def test_tech_can_change_sample_status_with_reason(self):
        self.auth_as(self.tech)

        response = self.client.post(
            f"/api/samples/{self.sample.id}/transition/",
            {
                "new_status": "IN_PROGRESS",
                "reason": "Initial processing started by lab tech.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.sample.refresh_from_db()
        self.assertEqual(self.sample.status, "IN_PROGRESS")

        event = Event.objects.get(
            entity_type="Sample",
            entity_id=str(self.sample.id),
            action="SAMPLE_STATUS_CHANGED",
        )

        self.assertEqual(event.actor, self.tech)
        self.assertEqual(event.payload["before"]["status"], "RECEIVED")
        self.assertEqual(event.payload["after"]["status"], "IN_PROGRESS")
        self.assertEqual(
            event.payload["reason"],
            "Initial processing started by lab tech.",
        )

    def test_sample_status_change_payload_includes_actor_and_reason(self):
        self.auth_as(self.tech)

        response = self.client.post(
            f"/api/samples/{self.sample.id}/transition/",
            {
                "new_status": "IN_PROGRESS",
                "reason": "Initial processing started after accessioning.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event = Event.objects.get(
            entity_type="Sample",
            entity_id=str(self.sample.id),
            action="SAMPLE_STATUS_CHANGED",
        )

        self.assertEqual(event.actor, self.tech)
        self.assertEqual(event.payload["actor_username"], "tech")
        self.assertEqual(event.payload["actor_id"], self.tech.id)
        self.assertEqual(
            event.payload["reason"],
            "Initial processing started after accessioning.",
        )
        self.assertEqual(event.payload["reason_type"], "sample_status_change")
        self.assertTrue(event.payload["reason_required"])

    def test_sample_status_change_does_not_create_generic_updated_event(self):
        self.auth_as(self.tech)

        response = self.client.post(
            f"/api/samples/{self.sample.id}/transition/",
            {
                "new_status": "IN_PROGRESS",
                "reason": "Initial processing started after accessioning.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertTrue(
            Event.objects.filter(
                entity_type="Sample",
                entity_id=str(self.sample.id),
                action="SAMPLE_STATUS_CHANGED",
            ).exists()
        )

        self.assertFalse(
            Event.objects.filter(
                entity_type="Sample",
                entity_id=str(self.sample.id),
                action="UPDATED",
            ).exists()
        )

    def test_direct_sample_status_patch_requires_reason(self):
        self.auth_as(self.tech)

        response = self.client.patch(
            f"/api/samples/{self.sample.id}/",
            {
                "status": "IN_PROGRESS",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.sample.refresh_from_db()
        self.assertEqual(self.sample.status, "RECEIVED")

    def test_bulk_sample_status_update_requires_reason(self):
        self.auth_as(self.tech)

        response = self.client.post(
            "/api/samples/bulk-update/",
            {
                "ids": [self.sample.id],
                "status": "IN_PROGRESS",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.sample.refresh_from_db()
        self.assertEqual(self.sample.status, "RECEIVED")

    def test_bulk_sample_status_update_accepts_reason(self):
        self.auth_as(self.tech)

        response = self.client.post(
            "/api/samples/bulk-update/",
            {
                "ids": [self.sample.id],
                "status": "IN_PROGRESS",
                "reason": "Bulk move into processing after sample intake.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.sample.refresh_from_db()
        self.assertEqual(self.sample.status, "IN_PROGRESS")

        event = Event.objects.get(
            entity_type="Sample",
            entity_id=str(self.sample.id),
            action="BULK_SAMPLE_STATUS_CHANGED",
        )

        self.assertEqual(event.actor, self.tech)
        self.assertTrue(event.payload["bulk"])
        self.assertEqual(
            event.payload["reason"],
            "Bulk move into processing after sample intake.",
        )

    def test_viewer_can_read_samples(self):
        self.auth_as(self.viewer)

        response = self.client.get("/api/samples/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_cannot_create_sample(self):
        self.auth_as(self.viewer)

        response = self.client.post(
            "/api/samples/",
            {
                "sample_id": "S-VIEWER-BLOCKED",
                "status": "RECEIVED",
                "project": self.project.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_update_sample(self):
        self.auth_as(self.viewer)

        response = self.client.patch(
            f"/api/samples/{self.sample.id}/",
            {
                "status": "IN_PROGRESS",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_bulk_update_samples(self):
        self.auth_as(self.viewer)

        response = self.client.post(
            "/api/samples/bulk-update/",
            {
                "ids": [self.sample.id],
                "status": "IN_PROGRESS",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_tech_can_create_sample(self):
        self.auth_as(self.tech)

        response = self.client.post(
            "/api/samples/",
            {
                "sample_id": "S-TECH-001",
                "status": "RECEIVED",
                "project": self.project.id,
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [status.HTTP_201_CREATED, status.HTTP_200_OK],
        )

    def test_tech_can_bulk_update_samples(self):
        self.auth_as(self.tech)

        response = self.client.post(
            "/api/samples/bulk-update/",
            {
                "ids": [self.sample.id],
                "status": "IN_PROGRESS",
                "reason": "Bulk status update allowed with audit reason.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.sample.refresh_from_db()
        self.assertEqual(self.sample.status, "IN_PROGRESS")

    def test_viewer_cannot_create_sequence(self):
        self.auth_as(self.viewer)

        response = self.client.post(
            "/api/sequences/",
            {
                "name": "Viewer Blocked Sequence",
                "description": "Viewer should not be able to create this.",
                "sequence_type": "DNA",
                "sequence": "ATGCGTACCGTAGGCTA",
                "project": self.project.id,
                "sample": self.sample.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_tech_can_create_sequence(self):
        self.auth_as(self.tech)

        response = self.client.post(
            "/api/sequences/",
            {
                "name": "Tech Sequence",
                "description": "Tech should be able to create this.",
                "sequence_type": "DNA",
                "sequence": "ATGCGTACCGTAGGCTA",
                "project": self.project.id,
                "sample": self.sample.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_viewer_cannot_update_sequence(self):
        self.auth_as(self.viewer)

        response = self.client.patch(
            f"/api/sequences/{self.sequence.id}/",
            {
                "name": "Viewer Updated This",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_qc_review_work_item(self):
        self.auth_as(self.viewer)

        response = self.client.post(
            f"/api/work-items/{self.work_item.id}/qc-review/",
            {
                "qc_status": "APPROVED",
                "review_note": "Viewer should not approve QC.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_tech_can_qc_review_work_item(self):
        self.auth_as(self.tech)

        response = self.client.post(
            f"/api/work-items/{self.work_item.id}/qc-review/",
            {
                "qc_status": "APPROVED",
                "review_note": "Tech approval is allowed.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.work_item.refresh_from_db()
        self.assertEqual(self.work_item.qc_status, WorkItem.QC_APPROVED)
        self.assertEqual(self.work_item.reviewed_by, self.tech)

    def test_viewer_cannot_run_fasta_preview(self):
        self.auth_as(self.viewer)

        fasta_file = SimpleUploadedFile(
            "demo.fasta",
            b">S-TEST-001 read\nATGCGTACCGTAGGCTA\n",
            content_type="text/plain",
        )

        response = self.client.post(
            "/api/import-jobs/sequence-fasta-preview/",
            {
                "instrument": self.instrument.id,
                "project": self.project.id,
                "uploaded_file": fasta_file,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_tech_can_run_fasta_preview(self):
        self.auth_as(self.tech)

        fasta_file = SimpleUploadedFile(
            "demo.fasta",
            b">S-TEST-001 read\nATGCGTACCGTAGGCTA\n",
            content_type="text/plain",
        )

        response = self.client.post(
            "/api/import-jobs/sequence-fasta-preview/",
            {
                "instrument": self.instrument.id,
                "project": self.project.id,
                "uploaded_file": fasta_file,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["matched_count"], 1)
        self.assertEqual(response.data["will_create_count"], 1)

    def test_viewer_cannot_run_fasta_import(self):
        self.auth_as(self.viewer)

        fasta_file = SimpleUploadedFile(
            "demo.fasta",
            b">S-TEST-001 read\nATGCGTACCGTAGGCTA\n",
            content_type="text/plain",
        )

        response = self.client.post(
            "/api/import-jobs/sequence-fasta-import/",
            {
                "instrument": self.instrument.id,
                "project": self.project.id,
                "uploaded_file": fasta_file,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_create_import_job(self):
        self.auth_as(self.viewer)

        upload = SimpleUploadedFile(
            "viewer-blocked.csv",
            b"sample_id,result\nS-TEST-001,pass\n",
            content_type="text/csv",
        )

        response = self.client.post(
            "/api/import-jobs/",
            {
                "instrument": self.instrument.id,
                "project": self.project.id,
                "source_type": "UPLOAD",
                "uploaded_file": upload,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_create_alignment_job(self):
        self.auth_as(self.viewer)

        response = self.client.post(
            "/api/alignment-jobs/",
            {
                "name": "Viewer Blocked Alignment",
                "project": self.project.id,
                "tool": "CLUSTAL_OMEGA",
                "sequence_ids": [self.sequence.id, self.sequence_2.id],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_tech_can_create_alignment_job(self):
        self.auth_as(self.tech)

        response = self.client.post(
            "/api/alignment-jobs/",
            {
                "name": "Tech Alignment",
                "project": self.project.id,
                "tool": "CLUSTAL_OMEGA",
                "sequence_ids": [self.sequence.id, self.sequence_2.id],
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [status.HTTP_201_CREATED, status.HTTP_202_ACCEPTED],
        )

    def test_viewer_can_read_blast_databases(self):
        self.auth_as(self.viewer)

        response = self.client.get("/api/blast-databases/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_read_blast_jobs(self):
        self.auth_as(self.viewer)

        response = self.client.get("/api/blast-jobs/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_cannot_create_blast_database(self):
        self.auth_as(self.viewer)

        fasta_file = SimpleUploadedFile(
            "viewer-blocked-blast-db.fasta",
            b">ref\nATGCGTACCGTAGGCTA\n",
            content_type="text/plain",
        )

        response = self.client.post(
            "/api/blast-databases/",
            {
                "name": "Viewer Blocked BLAST DB",
                "description": "Viewer should not create BLAST databases.",
                "database_type": BlastDatabase.DATABASE_TYPE_DNA,
                "source_fasta": fasta_file,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("blast.views.build_blast_database_task.delay")
    def test_viewer_cannot_build_blast_database(self, mock_delay):
        self.auth_as(self.viewer)

        response = self.client.post(
            f"/api/blast-databases/{self.blast_database.id}/build/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_delay.assert_not_called()

    def test_viewer_cannot_create_blast_job(self):
        self.auth_as(self.viewer)

        response = self.client.post(
            "/api/blast-jobs/",
            {
                "name": "Viewer Blocked BLAST Job",
                "project": self.project.id,
                "query_sequence": self.sequence.id,
                "database": self.blast_database.id,
                "program": BlastJob.PROGRAM_BLASTN,
                "evalue": "10",
                "max_target_seqs": 10,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_tech_can_create_blast_database(self):
        self.auth_as(self.tech)

        fasta_file = SimpleUploadedFile(
            "tech-blast-db.fasta",
            b">ref\nATGCGTACCGTAGGCTA\n",
            content_type="text/plain",
        )

        response = self.client.post(
            "/api/blast-databases/",
            {
                "name": "Tech BLAST DB",
                "description": "Tech should create BLAST databases.",
                "database_type": BlastDatabase.DATABASE_TYPE_DNA,
                "source_fasta": fasta_file,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch("blast.views.build_blast_database_task.delay")
    def test_tech_can_build_blast_database(self, mock_delay):
        self.auth_as(self.tech)

        response = self.client.post(
            f"/api/blast-databases/{self.blast_database.id}/build/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        self.blast_database.refresh_from_db()
        self.assertEqual(self.blast_database.status, BlastDatabase.STATUS_BUILDING)

        mock_delay.assert_called_once_with(self.blast_database.id)

    @patch("blast.views.run_blast_job_task.delay")
    def test_tech_can_create_blast_job(self, mock_delay):
        self.auth_as(self.tech)

        response = self.client.post(
            "/api/blast-jobs/",
            {
                "name": "Tech BLAST Job",
                "project": self.project.id,
                "query_sequence": self.sequence.id,
                "database": self.blast_database.id,
                "program": BlastJob.PROGRAM_BLASTN,
                "evalue": "10",
                "max_target_seqs": 10,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        job = BlastJob.objects.get(name="Tech BLAST Job")
        self.assertEqual(job.status, BlastJob.STATUS_PENDING)
        self.assertEqual(job.created_by, self.tech)

        mock_delay.assert_called_once_with(job.id)

    @patch("blast.views.run_blast_job_task.delay")
    def test_admin_can_create_blast_job(self, mock_delay):
        self.auth_as(self.admin)

        response = self.client.post(
            "/api/blast-jobs/",
            {
                "name": "Admin BLAST Job",
                "project": self.project.id,
                "query_sequence": self.sequence.id,
                "database": self.blast_database.id,
                "program": BlastJob.PROGRAM_BLASTN,
                "evalue": "10",
                "max_target_seqs": 10,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        job = BlastJob.objects.get(name="Admin BLAST Job")
        self.assertEqual(job.status, BlastJob.STATUS_PENDING)
        self.assertEqual(job.created_by, self.admin)

        mock_delay.assert_called_once_with(job.id)

    def test_admin_can_access_admin_users(self):
        self.auth_as(self.admin)

        response = self.client.get("/api/admin-users/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_tech_cannot_access_admin_users(self):
        self.auth_as(self.tech)

        response = self.client.get("/api/admin-users/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_access_admin_users(self):
        self.auth_as(self.viewer)

        response = self.client.get("/api/admin-users/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_create_user(self):
        self.auth_as(self.admin)

        response = self.client.post(
            "/api/admin-users/",
            {
                "username": "created_by_admin",
                "email": "created_by_admin@example.com",
                "password": "Password123!",
                "role": "viewer",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_tech_cannot_change_system_settings(self):
        self.auth_as(self.tech)

        response = self.client.patch(
            "/api/system-settings/1/",
            {
                "lab_name": "Tech Should Not Change This",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_change_system_settings(self):
        self.auth_as(self.viewer)

        response = self.client.patch(
            "/api/system-settings/1/",
            {
                "lab_name": "Viewer Should Not Change This",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
