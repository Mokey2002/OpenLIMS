from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from projects.models import Project
from samples.models import Sample


class SampleListPerformanceTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tech = get_user_model().objects.create_user(username="list-tech")
        cls.tech.groups.add(Group.objects.get_or_create(name="tech")[0])
        cls.viewer = get_user_model().objects.create_user(username="list-viewer")
        cls.viewer.groups.add(Group.objects.get_or_create(name="viewer")[0])
        cls.admin = get_user_model().objects.create_user(username="list-admin", is_superuser=True)
        cls.primary = Project.objects.create(code="PRIMARY", name="Primary")
        cls.primary.members.add(cls.tech, cls.viewer)
        cls.other = Project.objects.create(code="OTHER", name="Other")
        Sample.objects.bulk_create([Sample(sample_id=f"LIST-{i:03}", project=cls.primary) for i in range(60)])
        cls.linked = Sample.objects.create(sample_id="LINKED", project=cls.other)
        cls.linked.linked_projects.add(cls.primary)
        cls.owned = Sample.objects.create(sample_id="OWNED", created_by=cls.tech)
        cls.private = Sample.objects.create(sample_id="PRIVATE", project=cls.other)

    def test_query_count_is_bounded_as_page_grows(self):
        self.client.force_authenticate(self.tech)
        self.client.get("/api/v1/samples/?page_size=1")
        counts = []
        for size in [1, 50]:
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(f"/api/v1/samples/?page_size={size}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data["results"]), size)
            counts.append(len(queries))
        self.assertLessEqual(counts[1], counts[0] + 2, counts)
        self.assertLessEqual(counts[1], 15, counts)

    def test_display_permission_matches_ownership_and_rechecks_membership(self):
        self.client.force_authenticate(self.tech)
        rows = self.client.get("/api/v1/samples/?page_size=200").data["results"]
        permissions = {r["sample_id"]: r["can_modify"] for r in rows}
        self.assertTrue(permissions["LIST-000"])
        self.assertTrue(permissions["OWNED"])
        self.assertFalse(permissions["LINKED"])
        self.assertNotIn("PRIVATE", permissions)
        self.assertEqual(self.client.patch(f"/api/v1/samples/{self.linked.pk}/", {"sample_type": "DNA"}, format="json").status_code, 403)
        self.primary.members.remove(self.tech)
        response = self.client.get("/api/v1/samples/?page_size=200")
        self.assertEqual([r["sample_id"] for r in response.data["results"]], ["OWNED"])

    def test_viewer_and_admin_permissions_and_link_order(self):
        self.linked.linked_projects.add(self.other)
        self.client.force_authenticate(self.viewer)
        rows = self.client.get("/api/v1/samples/?page_size=200").data["results"]
        self.assertTrue(rows)
        self.assertTrue(all(not r["can_modify"] for r in rows))
        self.client.force_authenticate(self.admin)
        rows = self.client.get("/api/v1/samples/?page_size=200").data["results"]
        self.assertTrue(all(r["can_modify"] for r in rows))
        linked = next(r for r in rows if r["sample_id"] == "LINKED")
        self.assertEqual([p["code"] for p in linked["linked_project_summaries"]], ["OTHER", "PRIMARY"])
