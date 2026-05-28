from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework import status

from projects.models import Project
from samples.models import Sample
from imports.models import InstrumentProfile
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

    def auth_as(self, user):
        self.client.force_authenticate(user=user)

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
