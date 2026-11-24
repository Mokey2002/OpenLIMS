import re
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from events.models import Event, KafkaOutboxEvent
from notifications.models import Notification
from pipelines.models import AnalysisDefinition, PipelineRun, PipelineTemplate, PipelineTemplateStep, ProcedureDefinition
from projects.models import Project
from samples.models import Sample, SampleAccession
from workflow_requests.models import AssayRequestType, ClientTeam, WorkflowRequest, WorkflowRequestMessage, WorkflowRequestReport


PORTAL = "/api/v1/requester-requests/"
TEAMS = "/api/v1/client-teams/"
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

    def grant_team_access(self, team, user, *, submit=False, results=False):
        response = self.admin.post(
            f"{TEAMS}{team.pk}/member-access/",
            {"user": user.pk, "can_submit": submit, "can_view_results": results},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_team_submission_and_results_are_independent_and_scoped(self):
        created = self.admin.post(TEAMS, {"name": "Client A", "project": self.project.pk}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        team = ClientTeam.objects.get(pk=created.data["id"])
        other_team = ClientTeam.objects.create(name="Client B", project=self.project)
        other_client = get_user_model().objects.create_user(username="other-client", password=PASSWORD)
        other_client.groups.add(Group.objects.get(name="requester"))
        self.project.members.add(other_client)
        self.grant_team_access(team, self.requester, submit=True)
        self.grant_team_access(team, self.neighbor, results=True)
        self.grant_team_access(other_team, other_client, results=True)
        results_viewer = self.sign_in(self.neighbor)
        unrelated = self.sign_in(other_client)

        self.assertEqual(self.owner.get(f"{PORTAL}catalog/").data["client_teams"], [
            {"id": team.pk, "name": "Client A", "project_id": self.project.pk},
        ])
        self.assertEqual(results_viewer.get(f"{PORTAL}catalog/").data["projects"], [])
        self.assertEqual(results_viewer.post(PORTAL, self.payload(), format="json").status_code, 403)
        self.assertEqual(self.owner.post(PORTAL, self.payload(), format="json").status_code, 400)
        self.assertEqual(
            self.owner.post(PORTAL, self.payload(client_team=other_team.pk), format="json").status_code, 400,
        )
        payload = self.payload(client_team=team.pk)
        first = self.owner.post(PORTAL, payload, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(self.owner.post(PORTAL, payload, format="json").status_code, 200)
        workflow_request = WorkflowRequest.objects.get(public_id=first.data["public_id"])
        self.assertEqual(workflow_request.client_team, team)
        path = f"{PORTAL}{workflow_request.public_id}/"
        self.assertEqual(results_viewer.get(PORTAL).data["count"], 1)
        self.assertEqual(unrelated.get(PORTAL).data["count"], 0)
        self.assertEqual(unrelated.get(path).status_code, 404)
        self.assertEqual(results_viewer.get(path).data["client_team_name"], "Client A")
        self.assertIsNone(results_viewer.get(path).data["samples"][0]["barcode"])
        self.assertEqual(results_viewer.get(f"{path}labels/").status_code, 404)
        self.assertEqual(self.owner.get(f"{path}labels/").status_code, 200)
        self.assertFalse(self.owner.get(path).data["can_view_reports"])

        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            report = WorkflowRequestReport.objects.create(
                request=workflow_request, title="Client A report", uploaded_by=self.technician,
                file=SimpleUploadedFile("released.pdf", b"team report", content_type="application/pdf"),
            )
            download = f"{path}reports/{report.public_id}/download/"
            self.assertEqual(results_viewer.get(download).status_code, 404)
            release = self.admin.post(f"/api/v1/workflow-request-reports/{report.pk}/approve/", {}, format="json")
            self.assertEqual(release.status_code, 200, release.data)

            self.assertEqual(results_viewer.get(path).data["reports"][0]["title"], report.title)
            response = results_viewer.get(download)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), b"team report")
            self.assertEqual(self.owner.get(path).data["reports"], [])
            self.assertEqual(self.owner.get(download).status_code, 404)
            self.assertEqual(unrelated.get(download).status_code, 404)
            self.assertEqual(
                list(Notification.objects.filter(message=report.title).values_list("user_id", flat=True)), [self.neighbor.pk],
            )
            self.grant_team_access(team, self.requester, submit=True, results=True)
            self.assertEqual(self.owner.get(download).status_code, 200)

            self.project.members.remove(self.neighbor)
            self.assertEqual(results_viewer.get(download).status_code, 404)
            self.project.members.add(self.neighbor)
            self.grant_team_access(team, self.neighbor)
            self.assertEqual(results_viewer.get(path).status_code, 404)
            self.assertEqual(results_viewer.post(PORTAL, self.payload(), format="json").status_code, 403)

    def test_directors_can_share_and_revoke_existing_request_visibility(self):
        workflow_request = self.submit()
        team = ClientTeam.objects.create(name="Client A", project=self.project)
        wrong_team = ClientTeam.objects.create(name="Other project", project=self.other_project)
        self.grant_team_access(team, self.requester, submit=True, results=True)
        self.grant_team_access(team, self.neighbor, results=True)
        viewer = self.sign_in(self.neighbor)
        path = f"{PORTAL}{workflow_request.public_id}/"
        share = f"/api/v1/workflow-requests/{workflow_request.pk}/client-team/"
        self.assertEqual(viewer.get(path).status_code, 404)
        self.assertEqual(self.owner.get(path).status_code, 200)
        self.assertEqual(self.staff.post(share, {"client_team": team.pk}, format="json").status_code, 403)
        self.assertEqual(self.admin.post(share, {"client_team": wrong_team.pk}, format="json").status_code, 400)
        self.assertEqual(self.admin.get(share).data["teams"], [{"id": team.pk, "name": team.name}])
        response = self.admin.post(share, {"client_team": team.pk}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(viewer.get(path).status_code, 200)
        self.assertEqual(self.admin.post(share, {"client_team": None}, format="json").status_code, 200)
        self.assertEqual(viewer.get(path).status_code, 404)
        self.assertEqual(Event.objects.filter(action="WORKFLOW_REQUEST_TEAM_UPDATED").count(), 2)

    def test_team_configuration_requires_director_and_project_requesters(self):
        team = ClientTeam.objects.create(name="Client A", project=self.project)
        self.assertEqual(self.staff.get(f"{TEAMS}?project={self.project.pk}").status_code, 403)
        self.assertEqual(self.owner.get(f"{TEAMS}?project={self.project.pk}").status_code, 403)
        roster = self.admin.get(f"{TEAMS}?project={self.project.pk}")
        self.assertEqual(roster.status_code, 200, roster.data)
        self.assertCountEqual([row["id"] for row in roster.data["requesters"]], [self.requester.pk, self.neighbor.pk])
        for user in (self.technician, self.outsider):
            response = self.admin.post(f"{TEAMS}{team.pk}/member-access/", {
                "user": user.pk, "can_submit": True, "can_view_results": True,
            }, format="json")
            self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(team.memberships.exists())

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

    @override_settings(KAFKA_BOOTSTRAP_SERVERS="kafka:9092")
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
        event = KafkaOutboxEvent.objects.get()
        workflow_request = WorkflowRequest.objects.get()
        self.assertEqual(event.request_id, workflow_request.public_id)
        self.assertEqual(event.payload, {
            "schema_version": 1,
            "event_id": str(event.event_id),
            "event_type": "request.submitted",
            "request_id": str(workflow_request.public_id),
            "project_id": str(self.project.public_id),
            "occurred_at": workflow_request.submitted_at.isoformat(),
            "data": {},
        })
        self.project.members.remove(self.requester)
        self.assertEqual(self.owner.get(path).status_code, 404)
        self.assertEqual(self.owner.get(f"{path}labels/").status_code, 404)

    @override_settings(KAFKA_BOOTSTRAP_SERVERS="")
    def test_kafka_is_optional(self):
        self.submit()
        self.assertFalse(KafkaOutboxEvent.objects.exists())

    @override_settings(KAFKA_BOOTSTRAP_SERVERS="kafka:9092")
    def test_outbox_write_failure_rolls_back_submission(self):
        with patch.object(KafkaOutboxEvent, "save", side_effect=IntegrityError("Outbox write failed")):
            with self.assertRaisesMessage(IntegrityError, "Outbox write failed"):
                self.owner.post(PORTAL, self.payload(), format="json")
        self.assertFalse(WorkflowRequest.objects.exists())
        self.assertFalse(Event.objects.filter(action="WORKFLOW_REQUEST_SUBMITTED").exists())

    @override_settings(KAFKA_BOOTSTRAP_SERVERS="kafka:9092")
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
        self.assertEqual(KafkaOutboxEvent.objects.count(), 2)
        event = KafkaOutboxEvent.objects.filter(payload__event_type="sample.received").get()
        self.assertEqual(event.request_id, workflow_request.public_id)
        self.assertEqual(event.payload["data"], {"sample_id": str(item.sample.public_id)})
        self.assertEqual(event.payload["occurred_at"], item.sample.accession.receipt.occurred_at.isoformat())
        self.assertEqual(self.staff.get(lookup_url).data["kind"], "existing")
        self.assertIsNotNone(self.owner.get(detail_url).data["samples"][0]["received_at"])

        approved = self.admin.post(approve_url, {}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(PipelineRun.objects.count(), 1)
        self.assertEqual(self.owner.get(detail_url).data["status"], "IN_PROGRESS")
        PipelineRun.objects.update(status=PipelineRun.STATUS_COMPLETED)
        self.assertEqual(self.owner.get(detail_url).data["status"], "COMPLETED")

    @override_settings(KAFKA_BOOTSTRAP_SERVERS="kafka:9092")
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
            self.assertEqual(KafkaOutboxEvent.objects.count(), 1)
            release_url = f"/api/v1/workflow-request-reports/{report.pk}/approve/"
            for _ in range(2):
                self.assertEqual(self.admin.post(release_url, {}, format="json").status_code, 200)
            self.assertEqual(Event.objects.filter(action="WORKFLOW_REQUEST_REPORT_APPROVED").count(), 1)
            self.assertEqual(KafkaOutboxEvent.objects.count(), 2)
            event = KafkaOutboxEvent.objects.get(payload__event_type="report.released")
            report.refresh_from_db()
            self.assertEqual(event.request_id, workflow_request.public_id)
            self.assertEqual(event.payload["data"], {"report_id": str(report.public_id)})
            self.assertEqual(event.payload["occurred_at"], report.approved_at.isoformat())
            self.assertEqual(self.owner.get(path).data["reports"][0]["title"], "Lab report")
            downloaded = self.owner.get(download_url)
            self.assertEqual(downloaded.status_code, 200)
            self.assertEqual(b"".join(downloaded.streaming_content), b"report content")
            self.assertIn("attachment", downloaded["Content-Disposition"])
            self.assertEqual(APIClient().get(private_path).status_code, 404)
            self.assertEqual(self.sign_in(self.neighbor).get(download_url).status_code, 404)
