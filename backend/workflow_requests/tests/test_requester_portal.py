import re
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from events.models import Event
from pipelines.models import AnalysisDefinition, PipelineRun, PipelineTemplate, PipelineTemplateStep, ProcedureDefinition
from projects.models import Project
from samples.models import Sample, SampleAccession
from workflow_requests.models import AssayRequestType, WorkflowRequest, WorkflowRequestMessage, WorkflowRequestReport


PORTAL = "/api/v1/requester-requests/"
PASSWORD = "local-test-password"


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class RequesterPortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        def account(name, role):
            user = get_user_model().objects.create_user(username=name, password=PASSWORD)
            group, _ = Group.objects.get_or_create(name=role)
            user.groups.add(group)
            return user

        cls.requester = account("client-a", "requester")
        cls.neighbor = account("client-b", "requester")
        cls.director = account("director", "admin")
        cls.technician = account("receiver", "tech")
        cls.outsider = account("other-lab", "tech")
        cls.project = Project.objects.create(name="Client lab", code="CLIENT-LAB")
        cls.project.members.add(cls.requester, cls.neighbor, cls.technician)
        cls.other_project = Project.objects.create(name="Other lab", code="OTHER-LAB")
        cls.other_project.members.add(cls.technician, cls.outsider)
        pipeline = PipelineTemplate.objects.create(
            code="PORTAL-TEST", name="Portal test", created_by=cls.director,
            default_project=cls.project, is_default=True,
        )
        analysis = AnalysisDefinition.objects.create(code="PORTAL-CHECK", name="Portal check", created_by=cls.director)
        procedure = ProcedureDefinition.objects.create(
            code="PORTAL-CHECK-PROC", name="Portal check", version="1", analysis=analysis, created_by=cls.director,
        )
        PipelineTemplateStep.objects.create(template=pipeline, position=1, procedure=procedure, name="Check sample")
        schema = {
            "required": ["measurement_count", "include_summary"],
            "properties": {
                "measurement_count": {"type": "integer"},
                "include_summary": {"type": "boolean"},
            },
        }
        cls.test = AssayRequestType.objects.create(
            code="CLIENT-TEST", name="Test request", project=cls.project, portal_enabled=True,
            default_pipeline=pipeline, form_schema=schema,
        )
        cls.test_other_project = AssayRequestType.objects.create(
            code="OTHER-TEST", name="Other lab test", project=cls.other_project, portal_enabled=True,
            default_pipeline=pipeline,
        )
        AssayRequestType.objects.create(
            code="INTERNAL-TEST", name="Internal lab test", project=cls.project, default_pipeline=pipeline,
        )

    def setUp(self):
        self.owner = self.sign_in(self.requester)
        self.staff = self.sign_in(self.technician)
        self.admin = self.sign_in(self.director)

    def sign_in(self, user):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf/")
        response = client.post(
            "/api/v1/auth/login/", {"username": user.username, "password": PASSWORD},
            format="json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 200, response.data)
        client.credentials(HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        return client

    def payload(self, **overrides):
        return {
            "submission_id": str(uuid4()),
            "project": self.project.pk,
            "request_type": self.test.pk,
            "title": "Check incoming samples",
            "sample_references": ["Tube A", "Tube B"],
            "form_data": {"measurement_count": 0, "include_summary": False},
            **overrides,
        }

    def submit(self, **overrides):
        response = self.owner.post(PORTAL, self.payload(**overrides), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return WorkflowRequest.objects.get(public_id=response.data["public_id"])

    def test_requester_credentials_are_scoped_to_the_portal(self):
        self.assertEqual(APIClient().get(PORTAL).status_code, 401)
        access = self.owner.cookies["openlims_access"].value
        bearer = APIClient()
        bearer.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        for client in (self.owner, bearer):
            self.assertEqual(client.get(PORTAL).status_code, 200)
            for path in ("/api/v1/projects/", "/api/workflow-requests/", "/api/v1/inventory-items/", "/api/v1/my-work/"):
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 403)
        session = self.owner.get("/api/v1/session/").data
        self.assertEqual(session["user"]["roles"], ["requester"])
        self.assertEqual(session["feature_flags"], {})
        self.owner.credentials()
        self.assertEqual(self.owner.post(PORTAL, self.payload(), format="json").status_code, 403)

    def test_selects_only_published_tests_and_checks_input(self):
        catalog = self.owner.get(f"{PORTAL}catalog/").data
        self.assertEqual([project["id"] for project in catalog["projects"]], [self.project.pk])
        self.assertEqual([test["id"] for test in catalog["tests"]], [self.test.pk])
        for overrides in (
            {"project": self.other_project.pk, "request_type": self.test_other_project.pk},
            {"form_data": {"measurement_count": True, "include_summary": False}},
            {"form_data": {}},
            {"sample_references": ["Tube A", "tube a"]},
            {"sample_references": []},
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(self.owner.post(PORTAL, self.payload(**overrides), format="json").status_code, 400)
        workflow_request = self.submit(status="COMPLETED", priority="URGENT", requester=self.neighbor.pk)
        self.assertEqual(workflow_request.requester, self.requester)
        self.assertEqual(workflow_request.status, WorkflowRequest.STATUS_SUBMITTED)
        self.assertEqual(workflow_request.priority, self.test.default_priority)
        self.assertEqual(workflow_request.form_data, {"measurement_count": 0, "include_summary": False})
        self.assertFalse(Sample.objects.exists())

    def test_retries_are_idempotent_and_labels_require_the_owner(self):
        payload = self.payload()
        first = self.owner.post(PORTAL, payload, format="json")
        second = self.owner.post(PORTAL, payload, format="json")
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(first.data, second.data)
        self.assertEqual(WorkflowRequest.objects.count(), 1)
        self.assertEqual(Event.objects.filter(action="WORKFLOW_REQUEST_SUBMITTED").count(), 1)
        self.assertEqual(self.owner.post(PORTAL, {**payload, "title": "Changed"}, format="json").status_code, 409)
        path = f"{PORTAL}{first.data['public_id']}/"
        labels = self.owner.get(f"{path}labels/")
        self.assertEqual(labels.status_code, 200)
        self.assertTrue(labels.content.startswith(b"%PDF"))
        self.assertEqual(len(re.findall(rb"/Type /Page\b", labels.content)), 2)
        self.assertIn(f"{first.data['request_number']}-labels.pdf", labels["Content-Disposition"])

        neighbor = self.sign_in(self.neighbor)
        self.assertEqual(neighbor.get(PORTAL).data["count"], 0)
        self.assertEqual(neighbor.get(path).status_code, 404)
        self.assertEqual(neighbor.get(f"{path}labels/").status_code, 404)
        self.assertEqual(neighbor.post(PORTAL, payload, format="json").status_code, 409)
        self.project.members.remove(self.requester)
        self.assertEqual(self.owner.get(path).status_code, 404)
        self.assertEqual(self.owner.get(f"{path}labels/").status_code, 404)

    def test_submission_label_hands_off_to_staff_receipt_and_pipeline(self):
        workflow_request = self.submit(sample_references=["Tube A"])
        item = workflow_request.items.get()
        barcode = item.submission_barcode
        approve_url = f"/api/v1/workflow-requests/{workflow_request.pk}/approve/"
        detail_url = f"{PORTAL}{workflow_request.public_id}/"
        self.assertEqual(self.admin.post(approve_url, {}, format="json").status_code, 400)
        lookup_url = f"/api/v1/samples/accession-lookup/?barcode={barcode}"
        self.assertEqual(self.sign_in(self.outsider).get(lookup_url).status_code, 404)
        lookup = self.staff.get(lookup_url)
        self.assertEqual(lookup.status_code, 200)
        self.assertEqual(lookup.data["submission"]["project"], self.project.pk)
        self.assertEqual(lookup.data["submission"]["reference"], "Tube A")
        register_url = "/api/v1/samples/accession-register/"
        wrong = self.staff.post(
            register_url, {"barcode": barcode, "project": self.other_project.pk, "sample_type": "GENERAL"}, format="json",
        )
        self.assertEqual(wrong.status_code, 400, wrong.data)
        self.assertFalse(Sample.objects.exists())
        registered = self.staff.post(
            register_url, {"barcode": barcode, "project": self.project.pk, "sample_type": "GENERAL"}, format="json",
        )
        self.assertEqual(registered.status_code, 201, registered.data)
        item.refresh_from_db()
        self.assertEqual(item.sample_id, registered.data["sample"]["id"])
        self.assertFalse(PipelineRun.objects.exists())
        self.assertIsNone(self.owner.get(detail_url).data["samples"][0]["received_at"])
        self.assertEqual(self.admin.post(approve_url, {}, format="json").status_code, 400)
        receipt_url = f"/api/v1/samples/{item.sample_id}/receive/"
        receipt = {"barcode": barcode, "reason": "Tube received intact"}
        for _ in range(2):
            response = self.staff.post(receipt_url, receipt, format="json")
            self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(SampleAccession.objects.count(), 1)
        self.assertEqual(self.staff.get(lookup_url).data["kind"], "existing")
        self.assertIsNotNone(self.owner.get(detail_url).data["samples"][0]["received_at"])

        approved = self.admin.post(approve_url, {}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(PipelineRun.objects.count(), 1)
        self.assertEqual(self.owner.get(detail_url).data["status"], "IN_PROGRESS")
        PipelineRun.objects.update(status=PipelineRun.STATUS_COMPLETED)
        self.assertEqual(self.owner.get(detail_url).data["status"], "COMPLETED")

    def test_only_released_reports_can_be_downloaded_through_the_portal(self):
        workflow_request = self.submit()
        WorkflowRequestMessage.objects.create(
            request=workflow_request, author=self.technician, body="Private lab note", internal_only=True,
        )
        path = f"{PORTAL}{workflow_request.public_id}/"
        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            upload = self.staff.post(
                "/api/v1/workflow-request-reports/",
                {
                    "request": workflow_request.pk,
                    "title": "Lab report",
                    "file": SimpleUploadedFile("result.pdf", b"report content", content_type="application/pdf"),
                },
                format="multipart",
            )
            self.assertEqual(upload.status_code, 201, upload.data)
            report = WorkflowRequestReport.objects.get(pk=upload.data["id"])
            download_url = f"{path}reports/{report.public_id}/download/"
            private_path = report.file.url
            detail = self.owner.get(path)
            self.assertEqual(detail.data["reports"], [])
            self.assertNotIn("messages", detail.data)
            self.assertEqual(self.owner.get(download_url).status_code, 404)
            self.assertEqual(APIClient().get(private_path).status_code, 404)
            self.assertEqual(self.staff.get(upload.data["file"]).status_code, 200)
            release_url = f"/api/v1/workflow-request-reports/{report.pk}/approve/"
            for _ in range(2):
                self.assertEqual(self.admin.post(release_url, {}, format="json").status_code, 200)
            self.assertEqual(Event.objects.filter(action="WORKFLOW_REQUEST_REPORT_APPROVED").count(), 1)
            self.assertEqual(self.owner.get(path).data["reports"][0]["title"], "Lab report")
            downloaded = self.owner.get(download_url)
            self.assertEqual(downloaded.status_code, 200)
            self.assertEqual(b"".join(downloaded.streaming_content), b"report content")
            self.assertIn("attachment", downloaded["Content-Disposition"])
            self.assertEqual(APIClient().get(private_path).status_code, 404)
            self.assertEqual(self.sign_in(self.neighbor).get(download_url).status_code, 404)
