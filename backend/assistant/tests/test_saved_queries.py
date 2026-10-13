from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from rest_framework.test import APITestCase

from assistant.models import AssistantAction, SavedWorkflowQuery
from events.models import Event
from projects.models import Project


@override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=False)
class SavedWorkflowQueryTests(APITestCase):
    url = "/api/assistant/saved-queries/"

    def setUp(self):
        self.user = get_user_model().objects.create_user("owner")
        self.other = get_user_model().objects.create_user("other")
        self.user.groups.add(Group.objects.get_or_create(name="tech")[0])
        self.other.groups.add(Group.objects.get_or_create(name="admin")[0])
        self.project = Project.objects.create(code="SAVE", name="Saved project")
        self.project.members.add(self.user)
        self.client.force_authenticate(self.user)
        self.query = {"project_code": "SAVE", "filters": ["assigned", "due_today"], "match": "all", "scope": "step", "assignee": "me", "language": "en"}

    def save(self, name="Daily work", query=None, **extra):
        return self.client.post(self.url, {"name": name, "query": self.query if query is None else query, **extra}, format="json")

    def test_save_canonical_settings_without_execution_or_sensitive_context(self):
        before = Event.objects.count()
        query = {**self.query, "after": 99, "has_more": True, "rows": [{"secret": "result"}], "confirmation_token": "token", "deadline_windows": [{"start": "stale"}]}
        with patch("assistant.project_workflows.get_sample_access_queryset", side_effect=AssertionError("scan")), patch("assistant.llm.OpenAI", side_effect=AssertionError("provider")):
            response = self.save(query=query, owner=self.other.pk)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["query"], {**self.query, "assignee": "owner"})
        item = SavedWorkflowQuery.objects.get()
        self.assertEqual(item.owner, self.user)
        self.assertEqual(Event.objects.count(), before)
        self.assertFalse(AssistantAction.objects.exists())

    def test_users_cannot_list_or_delete_another_accounts_questions_even_as_admin(self):
        saved = self.save().data
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(self.url).data, [])
        self.assertEqual(self.client.delete(f"{self.url}{saved['id']}/").status_code, 404)
        self.assertTrue(SavedWorkflowQuery.objects.filter(pk=saved["id"]).exists())
        self.client.force_authenticate(self.user)
        self.assertEqual(len(self.client.get(self.url).data), 1)
        self.assertEqual(self.client.delete(f"{self.url}{saved['id']}/").status_code, 204)
        self.assertFalse(SavedWorkflowQuery.objects.exists())

    def test_login_required_and_saved_records_follow_account_lifetime(self):
        self.save()
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(self.url).status_code, (401, 403))
        self.assertIn(self.save().status_code, (401, 403))
        self.user.delete()
        self.assertFalse(SavedWorkflowQuery.objects.exists())

    def test_invalid_queries_and_unavailable_projects_or_owners_are_rejected(self):
        for change in ({"filters": []}, {"filters": ["invalid"]}, {"filters": ["all", "blocked"]}, {"filters": ["all"], "scope": "step"}, {"project_code": "SECRET"}, {"assignee": "other"}, {"scope": "invalid"}, {"match": "invalid"}):
            with self.subTest(change=change):
                self.assertEqual(self.save(query={**self.query, **change}).status_code, 400)
        self.assertFalse(SavedWorkflowQuery.objects.exists())

    def test_names_and_limit_are_enforced_and_deletion_frees_a_slot(self):
        first = self.save().data
        self.assertEqual(self.save().status_code, 400)
        self.assertEqual(self.save(name=" ").status_code, 400)
        self.assertEqual(self.save(name="X" * 81).status_code, 400)
        SavedWorkflowQuery.objects.bulk_create([SavedWorkflowQuery(owner=self.user, name=f"Saved {i}", query=self.query) for i in range(19)])
        self.assertEqual(self.save(name="Twenty one").status_code, 400)
        self.client.delete(f"{self.url}{first['id']}/")
        self.assertEqual(self.save(name="Replacement").status_code, 201)

    def test_loading_a_saved_query_does_not_grant_revoked_access(self):
        saved = self.save().data
        self.project.members.remove(self.user)
        self.assertEqual(self.save(name="Again").status_code, 400)
        # A bookmark remains editable, but cannot authorize a fresh query.
        self.assertEqual(self.client.get(self.url).data[0]["id"], saved["id"])
        with patch("assistant.project_workflows.get_sample_access_queryset", side_effect=AssertionError("scan")):
            response = self.client.post("/api/assistant/chat/", {"message": "Refresh results", "context": {"project_workflows": saved["query"]}}, format="json")
        self.assertNotIn("project_workflows", response.data)
        self.assertEqual(response.data["context"], {})

    def test_spanish_and_unused_owner_fields_are_canonicalized(self):
        response = self.save(query={**self.query, "language": "es", "assignee": "mí"})
        self.assertEqual(response.data["query"]["assignee"], "owner")
        response = self.save(name="No owner", query={**self.query, "filters": ["blocked"], "assignee": "other"})
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("assignee", response.data["query"])
