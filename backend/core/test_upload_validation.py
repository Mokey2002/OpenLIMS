from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework import status

from projects.models import Project
from samples.models import Sample
from imports.models import InstrumentProfile


User = get_user_model()


def create_user(username, password, role=None):
    user = User.objects.create_user(
        username=username,
        password=password,
        email=f"{username}@example.com",
    )
    user.is_active = True
    user.save()

    if role:
        group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(group)

    return user


class UploadValidationTests(APITestCase):
    def setUp(self):
        self.tech = create_user("tech", "tech123", role="tech")

        self.project = Project.objects.create(
            code="PRJ-UPLOAD",
            name="Upload Validation Project",
        )

        self.sample = Sample.objects.create(
            sample_id="S-UPLOAD-001",
            status="RECEIVED",
            project=self.project,
        )

        self.instrument = InstrumentProfile.objects.create(
            name="Generic FASTA Sequencer",
            code="FASTA-UPLOAD",
            delimiter=",",
            has_header=True,
            sample_id_column="sample_id",
        )

        self.client.force_authenticate(user=self.tech)

    def test_rejects_wrong_fasta_extension(self):
        bad_file = SimpleUploadedFile(
            "bad.exe",
            b">S-UPLOAD-001 read\nATGCGT\n",
            content_type="application/octet-stream",
        )

        response = self.client.post(
            "/api/import-jobs/sequence-fasta-preview/",
            {
                "instrument": self.instrument.id,
                "project": self.project.id,
                "uploaded_file": bad_file,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_empty_fasta_file(self):
        empty_file = SimpleUploadedFile(
            "empty.fasta",
            b"",
            content_type="text/plain",
        )

        response = self.client.post(
            "/api/import-jobs/sequence-fasta-preview/",
            {
                "instrument": self.instrument.id,
                "project": self.project.id,
                "uploaded_file": empty_file,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_invalid_fasta_characters(self):
        invalid_file = SimpleUploadedFile(
            "invalid.fasta",
            b">S-UPLOAD-001 read\nATGCGT123\n",
            content_type="text/plain",
        )

        response = self.client.post(
            "/api/import-jobs/sequence-fasta-preview/",
            {
                "instrument": self.instrument.id,
                "project": self.project.id,
                "uploaded_file": invalid_file,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_accepts_valid_fasta_file(self):
        valid_file = SimpleUploadedFile(
            "valid.fasta",
            b">S-UPLOAD-001 read\nATGCGTACCGTAGGCTA\n",
            content_type="text/plain",
        )

        response = self.client.post(
            "/api/import-jobs/sequence-fasta-preview/",
            {
                "instrument": self.instrument.id,
                "project": self.project.id,
                "uploaded_file": valid_file,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["matched_count"], 1)