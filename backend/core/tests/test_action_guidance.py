from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from events.models import Event
from projects.models import Project
from results.models import WorkItem
from samples.models import Sample


class ActionGuidanceTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tech = get_user_model().objects.create_user("guidance-tech")
        cls.other = get_user_model().objects.create_user("guidance-other")
        cls.viewer = get_user_model().objects.create_user("guidance-viewer")
        cls.admin = get_user_model().objects.create_superuser("guidance-admin", password=None)
        for user, role in [(cls.tech, "tech"), (cls.other, "tech"), (cls.viewer, "viewer")]:
            user.groups.add(Group.objects.get_or_create(name=role)[0])
        cls.project = Project.objects.create(code="GUIDE", name="Guidance project")
        cls.project.members.add(cls.tech, cls.other, cls.viewer, cls.admin)
        cls.private = Project.objects.create(code="HIDDEN-GUIDANCE", name="Private project")
        cls.primary = Sample.objects.create(sample_id="GUIDE-PRIMARY", project=cls.project, created_by=cls.tech)
        cls.linked = Sample.objects.create(sample_id="GUIDE-LINKED", project=cls.private, created_by=cls.other)
        cls.linked.linked_projects.add(cls.project)
        cls.public = Sample.objects.create(sample_id="GUIDE-PUBLIC", created_by=cls.other)
        cls.hidden = Sample.objects.create(sample_id="GUIDE-HIDDEN", project=cls.private)

    def sample(self, user, sample):
        self.client.force_authenticate(user)
        response = self.client.get(f"/api/v1/samples/{sample.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["can_modify"], response.data["modification_access"]["allowed"])
        return response.data["modification_access"]

    def test_role_project_and_owner_reasons_match_actual_permissions(self):
        self.assertTrue(self.sample(self.tech, self.primary)["allowed"])
        role = self.sample(self.viewer, self.primary)
        self.assertEqual(role["reason_code"], "EDIT_ROLE_REQUIRED")
        self.assertEqual(role["href"], "/access-requests")
        linked = self.sample(self.tech, self.linked)
        self.assertEqual(linked["reason_code"], "PRIMARY_PROJECT_REQUIRED")
        self.assertNotIn(self.private.code, str(linked))
        public = self.sample(self.tech, self.public)
        self.assertEqual(public["reason_code"], "SAMPLE_OWNER_REQUIRED")
        self.assertIsNone(public["href"])
        self.assertTrue(self.sample(self.other, self.public)["allowed"])
        self.assertTrue(self.sample(self.admin, self.public)["allowed"])

    def test_role_and_membership_changes_are_rechecked_on_the_next_request(self):
        self.assertFalse(self.sample(self.viewer, self.primary)["allowed"])
        self.viewer.groups.add(Group.objects.get(name="tech"))
        self.assertTrue(self.sample(self.viewer, self.primary)["allowed"])
        self.project.members.remove(self.viewer)
        response = self.client.get(f"/api/v1/samples/{self.primary.pk}/")
        self.assertEqual(response.status_code, 404)

    def test_guidance_does_not_expose_inaccessible_records(self):
        self.client.force_authenticate(self.tech)
        response = self.client.get(f"/api/v1/samples/{self.hidden.pk}/")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(self.private.code, str(response.data))
        self.assertNotIn("modification_access", response.data)

    def test_permission_metadata_cannot_be_used_to_grant_edit_access(self):
        self.client.force_authenticate(self.tech)
        response = self.client.patch(f"/api/v1/samples/{self.linked.pk}/", {
            "sample_type": "DNA", "can_modify": True, "modification_access": {"allowed": True},
        }, format="json")
        self.assertEqual(response.status_code, 403)
        self.linked.refresh_from_db()
        self.assertEqual(self.linked.sample_type, "GENERAL")

    def test_work_explanations_distinguish_public_read_access_from_update_access(self):
        work = WorkItem.objects.create(sample=self.public, work_type="GENERAL", name="Public work")
        for user, code in [(self.tech, "WORK_OWNER_REQUIRED"), (self.viewer, "WORK_ROLE_REQUIRED")]:
            self.client.force_authenticate(user)
            response = self.client.get(f"/api/v1/work-items/{work.pk}/")
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.data["can_update"])
            self.assertEqual(response.data["update_access"]["reason_code"], code)
        self.client.force_authenticate(self.other)
        response = self.client.get(f"/api/v1/work-items/{work.pk}/")
        self.assertTrue(response.data["can_update"])
        self.assertTrue(response.data["update_access"]["allowed"])

    def test_list_explanations_do_not_add_queries_per_record_or_write_audit_entries(self):
        Sample.objects.bulk_create([Sample(sample_id=f"GUIDE-{index:03}", project=self.project) for index in range(50)])
        self.client.force_authenticate(self.viewer)
        before = Event.objects.count()
        counts = []
        for size in (1, 40):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(f"/api/v1/samples/?page_size={size}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data["results"]), size)
            self.assertTrue(all(not row["modification_access"]["allowed"] for row in response.data["results"]))
            counts.append(len(queries))
        self.assertLessEqual(counts[1], counts[0] + 2, counts)
        self.assertEqual(Event.objects.count(), before)
