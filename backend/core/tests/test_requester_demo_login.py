from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.demo_requester_access import (
    DEMO_PROJECT_CODE, DEMO_PROJECT_DESCRIPTION, DEMO_REQUESTER_CLAIM,
    DEMO_REQUESTER_EMAIL, DEMO_REQUESTER_USERNAME,
)
from pipelines.models import PipelineTemplate
from projects.models import Project
from workflow_requests.models import AssayRequestType, ClientTeam, ClientTeamMembership, WorkflowRequest


DEMO_LOGIN = "/api/v1/auth/requester-demo/"
SESSION = "/api/v1/session/"
PORTAL = "/api/v1/requester-requests/"
REFRESH = "/api/v1/auth/refresh/"


@override_settings(OPENLIMS_REQUESTER_DEMO_ENABLED=True)
class RequesterDemoLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.requester = user_model.objects.create_user(username=DEMO_REQUESTER_USERNAME, email=DEMO_REQUESTER_EMAIL)
        cls.requester.groups.add(Group.objects.get_or_create(name="requester")[0])
        cls.director = user_model.objects.create_user(username="demo-director", is_superuser=True, is_staff=True)
        cls.project = Project.objects.create(
            name="Requester Portal Demo", code=DEMO_PROJECT_CODE, description=DEMO_PROJECT_DESCRIPTION,
        )
        cls.project.members.add(cls.requester)
        cls.private_project = Project.objects.create(name="Private project", code="PRIVATE")
        pipeline = PipelineTemplate.objects.create(
            code="DEMO-CHECK", name="Demo check", default_project=cls.project, created_by=cls.director,
        )
        cls.demo_test = AssayRequestType.objects.create(
            code="DEMO-CHECK", name="Demo check", project=cls.project, default_pipeline=pipeline, portal_enabled=True,
        )
        cls.global_test = AssayRequestType.objects.create(
            code="GLOBAL-CHECK", name="Global check", default_pipeline=pipeline, portal_enabled=True,
        )
        cls.other_request = WorkflowRequest.objects.create(
            request_number="OTHER-1", requester=cls.director, project=cls.project, request_type=cls.demo_test,
            title="Another account's request", status=WorkflowRequest.STATUS_SUBMITTED,
        )

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.get("/api/v1/auth/csrf/")
        self.client.credentials(HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value)

    def login(self):
        response = self.client.post(DEMO_LOGIN, {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def submission(self, request_type):
        return {
            "submission_id": str(uuid4()),
            "project": self.project.pk,
            "request_type": request_type.pk,
            "title": "Demo sample condition check",
            "sample_references": ["Example tube"],
        }

    def test_enabled_login_uses_http_only_cookies_and_limits_the_portal(self):
        self.assertTrue(self.client.get("/api/v1/ui-settings/").data["requester_demo_enabled"])
        response = self.login()
        self.assertEqual(response.data["user"]["username"], DEMO_REQUESTER_USERNAME)
        self.assertEqual(response.data["user"]["roles"], ["requester"])
        self.assertNotIn("refresh", response.data)
        self.assertTrue(response.cookies["openlims_access"]["httponly"])
        self.assertTrue(response.cookies["openlims_refresh"]["httponly"])
        self.requester.refresh_from_db()
        self.assertFalse(self.requester.has_usable_password())
        self.assertEqual(self.client.get(SESSION).data["user"]["username"], DEMO_REQUESTER_USERNAME)
        self.assertEqual(self.client.get("/api/v1/projects/").status_code, 403)
        self.assertEqual(self.client.get(f"{PORTAL}{self.other_request.public_id}/").status_code, 404)
        catalog = self.client.get(f"{PORTAL}catalog/").data
        self.assertEqual([project["id"] for project in catalog["projects"]], [self.project.pk])
        self.assertEqual([test["id"] for test in catalog["tests"]], [self.demo_test.pk])
        self.assertEqual(self.client.post(PORTAL, self.submission(self.global_test), format="json").status_code, 400)
        submitted = self.client.post(PORTAL, self.submission(self.demo_test), format="json")
        self.assertEqual(submitted.status_code, 201, submitted.data)
        self.assertEqual(self.client.get(f"{PORTAL}{submitted.data['public_id']}/").status_code, 200)

        refresh_before = self.client.cookies["openlims_refresh"].value
        self.assertEqual(self.client.post(REFRESH, {}, format="json").status_code, 200)
        refresh_after = self.client.cookies["openlims_refresh"].value
        self.assertNotEqual(refresh_before, refresh_after)
        self.assertTrue(RefreshToken(refresh_after)[DEMO_REQUESTER_CLAIM])
        self.assertEqual(self.client.get(SESSION).status_code, 200)

    @override_settings(OPENLIMS_REQUESTER_DEMO_ENABLED=False)
    def test_disabled_installation_never_issues_demo_cookies(self):
        self.assertFalse(self.client.get("/api/v1/ui-settings/").data["requester_demo_enabled"])
        response = self.client.post(DEMO_LOGIN, {}, format="json")
        self.assertEqual(response.status_code, 404, response.data)
        self.assertNotIn("openlims_access", response.cookies)

    def test_demo_login_requires_csrf(self):
        self.client.credentials()
        self.assertEqual(self.client.post(DEMO_LOGIN, {}, format="json").status_code, 403)

    def test_disabling_demo_revokes_existing_access_and_refresh(self):
        self.login()
        with self.settings(OPENLIMS_REQUESTER_DEMO_ENABLED=False):
            self.assertEqual(self.client.get(SESSION).status_code, 401)
            self.assertEqual(self.client.post(REFRESH, {}, format="json").status_code, 401)
            self.assertFalse(self.client.cookies["openlims_refresh"].value)

    def test_demo_session_cannot_gain_access_to_another_project(self):
        self.login()
        self.private_project.members.add(self.requester)
        self.assertEqual(self.client.get(f"{PORTAL}catalog/").status_code, 401)
        self.assertEqual(self.client.post(DEMO_LOGIN, {}, format="json").status_code, 404)

    def test_demo_login_requires_requester_only_access_and_no_team_enrollment(self):
        admin, _ = Group.objects.get_or_create(name="admin")
        self.requester.groups.add(admin)
        self.assertEqual(self.client.post(DEMO_LOGIN, {}, format="json").status_code, 404)
        self.requester.groups.remove(admin)
        team = ClientTeam.objects.create(project=self.project, name="Client team")
        ClientTeamMembership.objects.create(team=team, user=self.requester, can_view_results=True)
        self.assertEqual(self.client.post(DEMO_LOGIN, {}, format="json").status_code, 404)
