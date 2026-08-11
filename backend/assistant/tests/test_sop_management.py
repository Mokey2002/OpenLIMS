import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from events.models import Event
from projects.models import Project

from assistant.models import SOPDocument


User = get_user_model()


def create_user(username, role):
    user = User.objects.create_user(username=username, password="test-password")
    group, _ = Group.objects.get_or_create(name=role)
    user.groups.add(group)
    return user


class SOPDocumentManagementTests(APITestCase):
    def setUp(self):
        self.media_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)

        self.admin = create_user("director", "admin")
        self.tech = create_user("peter", "tech")
        self.viewer = create_user("michael", "viewer")
        self.qc_group = Group.objects.create(name="qc_reviewer")
        self.project = Project.objects.create(name="Project Alpha", code="ALPHA")
        self.project.members.add(self.tech)

    def payload(self, **overrides):
        payload = {
            "document_code": "SOP-SAMPLE-001",
            "title": "Sample receipt",
            "version": "3",
            "section": "4.2 Receive a sample",
            "content": "Verify the identifier and record the received time.",
            "status": SOPDocument.STATUS_CURRENT,
            "approved": True,
            "project": self.project.id,
            "allowed_group_names": ["tech", "qc_reviewer"],
            "effective_at": timezone.now().isoformat(),
        }
        payload.update(overrides)
        return payload

    def test_director_can_create_sop_with_access_scope_and_audit_event(self):
        self.client.force_authenticate(self.admin)

        response = self.client.post("/api/sop-documents/", self.payload(), format="json")

        self.assertEqual(response.status_code, 201)
        document = SOPDocument.objects.get(id=response.data["id"])
        self.assertEqual(document.uploaded_by, self.admin)
        self.assertEqual(document.project, self.project)
        self.assertSetEqual(
            set(document.allowed_groups.values_list("name", flat=True)),
            {"tech", "qc_reviewer"},
        )
        self.assertEqual(response.data["project_code"], "ALPHA")
        self.assertEqual(
            set(response.data["allowed_group_names"]),
            {"tech", "qc_reviewer"},
        )
        event = Event.objects.get(
            entity_type="SOPDocument",
            entity_id=str(document.id),
            action="SOP_DOCUMENT_CREATED",
        )
        self.assertEqual(event.actor, self.admin)

    def test_tech_and_viewer_cannot_create_or_modify_sops(self):
        document = SOPDocument.objects.create(
            document_code="SOP-EXISTING-001",
            title="Existing SOP",
            version="1",
            section="1",
            content="Existing content",
            approved=True,
            uploaded_by=self.admin,
        )

        for user in [self.tech, self.viewer]:
            with self.subTest(user=user.username):
                self.client.force_authenticate(user)
                create_response = self.client.post(
                    "/api/sop-documents/",
                    self.payload(document_code=f"SOP-{user.username.upper()}-001"),
                    format="json",
                )
                update_response = self.client.patch(
                    f"/api/sop-documents/{document.id}/",
                    {"title": "Unauthorized change"},
                    format="json",
                )
                self.assertEqual(create_response.status_code, 403)
                self.assertEqual(update_response.status_code, 403)

        document.refresh_from_db()
        self.assertEqual(document.title, "Existing SOP")

    def test_role_initializer_reserves_sop_writes_for_directors(self):
        call_command("init_roles", verbosity=0)
        write_permissions = [
            "add_sopdocument",
            "change_sopdocument",
            "delete_sopdocument",
        ]

        admin_group = Group.objects.get(name="admin")
        for codename in write_permissions:
            self.assertTrue(
                admin_group.permissions.filter(codename=codename).exists(),
                codename,
            )

        for role in ["tech", "viewer", "qc_reviewer"]:
            group = Group.objects.get(name=role)
            with self.subTest(role=role):
                self.assertFalse(
                    group.permissions.filter(codename__in=write_permissions).exists()
                )

    def test_director_can_upload_source_file(self):
        self.client.force_authenticate(self.admin)
        payload = self.payload(allowed_group_names=["tech"])
        payload["source_file"] = SimpleUploadedFile(
            "sample-receipt.txt",
            b"Approved sample receipt procedure",
            content_type="text/plain",
        )

        response = self.client.post(
            "/api/sop-documents/",
            payload,
            format="multipart",
        )

        self.assertEqual(response.status_code, 201, response.data)
        document = SOPDocument.objects.get(id=response.data["id"])
        self.assertTrue(document.source_file.name.startswith("sops/sample-receipt"))
        with document.source_file.open("rb") as source:
            self.assertEqual(source.read(), b"Approved sample receipt procedure")
        self.assertSetEqual(
            set(document.allowed_groups.values_list("name", flat=True)),
            {"tech"},
        )

    def test_archiving_sets_timestamp_and_creates_audit_event(self):
        document = SOPDocument.objects.create(
            document_code="SOP-ARCHIVE-001",
            title="Archive me",
            version="1",
            section="1",
            content="Archive content",
            approved=True,
            uploaded_by=self.admin,
        )
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            f"/api/sop-documents/{document.id}/",
            {"status": SOPDocument.STATUS_ARCHIVED},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        document.refresh_from_db()
        self.assertEqual(document.status, SOPDocument.STATUS_ARCHIVED)
        self.assertIsNotNone(document.archived_at)
        self.assertTrue(
            Event.objects.filter(
                entity_type="SOPDocument",
                entity_id=str(document.id),
                action="SOP_DOCUMENT_ARCHIVED",
                actor=self.admin,
            ).exists()
        )

    def test_non_admin_only_lists_current_approved_effective_accessible_sops(self):
        visible = SOPDocument.objects.create(
            document_code="SOP-VISIBLE-001",
            title="Visible SOP",
            version="1",
            section="1",
            content="Visible content",
            approved=True,
            project=self.project,
            uploaded_by=self.admin,
        )
        visible.allowed_groups.add(Group.objects.get(name="tech"))
        SOPDocument.objects.create(
            document_code="SOP-DRAFT-001",
            title="Draft SOP",
            version="1",
            section="1",
            content="Draft content",
            approved=False,
            uploaded_by=self.admin,
        )
        restricted = SOPDocument.objects.create(
            document_code="SOP-QC-001",
            title="QC SOP",
            version="1",
            section="1",
            content="QC content",
            approved=True,
            uploaded_by=self.admin,
        )
        restricted.allowed_groups.add(self.qc_group)

        self.client.force_authenticate(self.tech)
        response = self.client.get("/api/sop-documents/")

        self.assertEqual(response.status_code, 200)
        codes = {
            item["document_code"]
            for item in (response.data.get("results") or response.data)
        }
        self.assertSetEqual(codes, {visible.document_code})
