from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings

from core.models import AccessRequest
from events.models import Event
from notifications.models import Notification
from projects.models import Project


class AccessRequestTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser("access-admin", password=None)
        self.other_admin = get_user_model().objects.create_user("group-admin")
        self.other_admin.groups.add(Group.objects.get_or_create(name="admin")[0])
        self.user = get_user_model().objects.create_user("requester")
        self.other = get_user_model().objects.create_user("other-requester")
        viewer = Group.objects.get_or_create(name="viewer")[0]
        self.user.groups.add(viewer)
        self.other.groups.add(viewer)
        self.project = Project.objects.create(code="ALPHA", name="Private scientific project")
        self.client.force_authenticate(self.user)

    def submit(self, **changes):
        return self.client.post("/api/v1/access-requests/", {
            "kind": "PROJECT", "project_code": "ALPHA", "reason": "Please add me to the sequencing project", **changes,
        }, format="json")

    def pending(self, **changes):
        response = self.submit(**changes)
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def decide(self, request_id, decision="APPROVED", **changes):
        return self.client.post(f"/api/v1/access-requests/{request_id}/review/", {
            "decision": decision, "decision_reason": "Reviewed access requirements with the laboratory manager",
            "project_public_id": str(self.project.public_id), **changes,
        }, format="json")

    def test_project_requests_grant_nothing_until_admin_review(self):
        request_id = self.pending()
        self.assertEqual(self.client.get(f"/api/projects/{self.project.pk}/").status_code, 404)
        self.assertFalse(self.project.members.filter(pk=self.user.pk).exists())
        self.client.force_authenticate(self.admin)
        preview = self.client.get(f"/api/access-requests/{request_id}/preview/")
        self.assertTrue(preview.data["can_approve"])
        self.assertTrue(preview.data["request"]["can_review"])
        self.assertEqual(preview.data["project"]["name"], self.project.name)
        self.assertEqual(preview.data["current_roles"], ["viewer"])
        result = self.decide(request_id)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["status"], "APPROVED")
        self.assertTrue(result.data["access_changed"])
        self.assertEqual(Notification.objects.get(user=self.user).link, "/access-requests?status=ALL")
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(f"/api/projects/{self.project.pk}/").status_code, 200)
        self.assertEqual(self.client.post("/api/samples/", {"sample_id": "NOT-A-TECH", "project": self.project.pk}).status_code, 403)

    def test_unknown_and_private_codes_have_the_same_submission_contract(self):
        for code in ["ALPHA", "DOES-NOT-EXIST"]:
            response = self.submit(project_code=code)
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data["status"], "PENDING")
            self.assertEqual(response.data["project_code"], code)
            self.assertNotIn(self.project.name, str(response.data))
            self.assertNotIn("project", response.data)
            self.assertNotIn("requester", response.data)
        self.assertFalse(AccessRequest.objects.exclude(project__isnull=True).exists())

    def test_duplicates_reuse_pending_request_without_repeated_notifications_or_audit(self):
        original = self.pending()
        events = Event.objects.count()
        notices = Notification.objects.count()
        repeated = self.submit(project_code="alpha", reason="A different reason must not overwrite the original request")
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data["id"], original)
        self.assertEqual(repeated.data["reason"], "Please add me to the sequencing project")
        self.assertEqual(Event.objects.count(), events)
        self.assertEqual(Notification.objects.count(), notices)
        self.assertEqual(AccessRequest.objects.count(), 1)

    def test_requesters_cannot_review_see_other_requests_or_change_targets(self):
        request_id = self.pending()
        self.assertEqual(self.decide(request_id).status_code, 403)
        self.assertEqual(self.client.get(f"/api/access-requests/{request_id}/preview/").status_code, 403)
        for method in [self.client.patch, self.client.put, self.client.delete]:
            self.assertEqual(method(f"/api/access-requests/{request_id}/", {"status": "APPROVED"}, format="json").status_code, 405)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get("/api/access-requests/").data["count"], 0)
        self.assertEqual(self.client.get(f"/api/access-requests/{request_id}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/access-requests/{request_id}/withdraw/", {}).status_code, 404)

    def test_admin_queue_paginates_and_filters_pending_and_decided_requests(self):
        first = self.pending()
        second = self.pending(project_code="BETA")
        self.client.force_authenticate(self.admin)
        result = self.client.get("/api/access-requests/?status=PENDING&page_size=1")
        self.assertEqual(result.data["count"], 2)
        self.assertIsNotNone(result.data["next"])
        self.assertTrue(result.data["results"][0]["can_review"])
        self.assertEqual(self.decide(first, "REJECTED").status_code, 200)
        self.assertEqual(self.client.get("/api/access-requests/?status=PENDING").data["results"][0]["id"], second)
        self.assertEqual(self.client.get("/api/access-requests/?mine=1").data["count"], 0)
        self.assertEqual(self.client.get("/api/access-requests/?status=made-up").status_code, 400)

    def test_rejection_and_withdrawal_preserve_history_without_granting_access(self):
        first = self.pending()
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.decide(first, "REJECTED").data["status"], "REJECTED")
        self.assertEqual(self.decide(first).status_code, 409)
        self.client.force_authenticate(self.user)
        second = self.pending()
        self.assertNotEqual(first, second)
        result = self.client.post(f"/api/access-requests/{second}/withdraw/", {})
        self.assertEqual(result.data["status"], "CANCELLED")
        self.assertEqual(self.client.post(f"/api/access-requests/{second}/withdraw/", {}).status_code, 200)
        self.assertEqual(Event.objects.filter(action="ACCESS_REQUEST_CANCELLED").count(), 1)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.decide(second).status_code, 409)
        self.assertFalse(self.project.members.filter(pk=self.user.pk).exists())

    def test_replayed_approval_never_restores_access_removed_later(self):
        request_id = self.pending()
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.decide(request_id).status_code, 200)
        self.project.members.remove(self.user)
        notices = Notification.objects.count()
        self.assertEqual(self.decide(request_id).status_code, 200)
        self.assertFalse(self.project.members.filter(pk=self.user.pk).exists())
        self.assertEqual(Event.objects.filter(action="ACCESS_REQUEST_APPROVED").count(), 1)
        self.assertEqual(Notification.objects.count(), notices)

    def test_role_grants_are_additive_and_do_not_set_administrator_flags(self):
        for role in ["tech", "qc_reviewer"]:
            request_id = self.pending(kind="ROLE", project_code="", role=role)
            self.client.force_authenticate(self.admin)
            result = self.decide(request_id)
            self.assertEqual(result.status_code, 200, result.data)
            self.client.force_authenticate(self.user)
        self.user.refresh_from_db()
        self.assertEqual(set(self.user.groups.values_list("name", flat=True)), {"viewer", "tech", "qc_reviewer"})
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertEqual(set(self.client.get("/api/me/").data["roles"]), {"viewer", "tech", "qc_reviewer"})
        self.project.members.add(self.user)
        created = self.client.post("/api/samples/", {"sample_id": "NEW-TECH-SAMPLE", "project": self.project.pk}, format="json")
        self.assertEqual(created.status_code, 201, created.data)

    def test_no_role_account_can_request_a_baseline_role(self):
        self.user.groups.clear()
        request_id = self.pending(kind="ROLE", project_code="", role="viewer")
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.decide(request_id).status_code, 200)
        self.assertTrue(self.user.groups.filter(name="viewer").exists())

    def test_submission_cannot_supply_requester_status_or_privileged_roles(self):
        for changes in [
            {"requester": self.admin.pk}, {"status": "APPROVED"}, {"is_superuser": True},
            {"project": self.project.pk}, {"kind": "ROLE", "project_code": "", "role": "admin"},
            {"kind": "ROLE", "project_code": "", "role": "superuser"},
            {"reason": "short"}, {"reason": " " * 20}, {"project_code": ""},
            {"kind": "ROLE", "role": "tech"},
        ]:
            self.assertEqual(self.submit(**changes).status_code, 400, changes)
        for data in [[], ["bad"], 123]:
            self.assertEqual(self.client.post("/api/access-requests/", data, format="json").status_code, 400)
        self.assertEqual(AccessRequest.objects.count(), 0)

    def test_review_requires_a_reason_and_current_project_preview(self):
        request_id = self.pending()
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.decide(request_id, decision_reason="").status_code, 400)
        self.assertEqual(self.decide(request_id, role="admin").status_code, 400)
        missing = self.client.post(f"/api/access-requests/{request_id}/review/", {"decision": "APPROVED", "decision_reason": "Reviewed requested project access"})
        self.assertEqual(missing.status_code, 409)
        self.assertEqual(AccessRequest.objects.get(pk=request_id).status, "PENDING")

    def test_deleted_and_recreated_project_cannot_use_a_stale_preview(self):
        request_id = self.pending()
        expected = str(self.project.public_id)
        self.project.delete()
        self.project = Project.objects.create(code="ALPHA", name="A different project")
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.decide(request_id, project_public_id=expected).status_code, 409)
        self.assertFalse(self.project.members.filter(pk=self.user.pk).exists())
        self.assertEqual(self.decide(request_id).status_code, 200)

    def test_unknown_or_ambiguous_project_blocks_approval_but_can_be_rejected(self):
        request_id = self.pending(project_code="MISSING")
        self.client.force_authenticate(self.admin)
        self.assertFalse(self.client.get(f"/api/access-requests/{request_id}/preview/").data["can_approve"])
        self.assertEqual(self.decide(request_id).status_code, 409)
        self.assertEqual(self.decide(request_id, "REJECTED").status_code, 200)
        self.client.force_authenticate(self.user)
        request_id = self.pending()
        Project.objects.create(code="alpha", name="Ambiguous code")
        self.client.force_authenticate(self.admin)
        self.assertFalse(self.client.get(f"/api/access-requests/{request_id}/preview/").data["can_approve"])
        self.assertEqual(self.decide(request_id).status_code, 409)

    def test_disabled_requester_cannot_receive_access(self):
        request_id = self.pending()
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.client.force_authenticate(self.admin)
        self.assertFalse(self.client.get(f"/api/access-requests/{request_id}/preview/").data["can_approve"])
        self.assertEqual(self.decide(request_id).status_code, 400)
        self.assertFalse(self.project.members.filter(pk=self.user.pk).exists())

    def test_deleted_requester_history_remains_reviewable_without_granting_access(self):
        request_id = self.pending()
        self.user.delete()
        self.client.force_authenticate(self.admin)
        preview = self.client.get(f"/api/access-requests/{request_id}/preview/")
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data["requester_active"])
        self.assertEqual(preview.data["current_roles"], [])
        self.assertEqual(self.decide(request_id).status_code, 400)
        self.assertEqual(self.decide(request_id, "REJECTED").status_code, 200)
        self.assertEqual(AccessRequest.objects.get(pk=request_id).requester_username, "requester")
        self.assertFalse(self.project.members.exists())

    def test_admin_can_manage_qc_role_and_profile_edits_preserve_additional_roles(self):
        self.user.groups.add(Group.objects.get_or_create(name="tech")[0])
        self.client.force_authenticate(self.admin)
        path = f"/api/admin-users/{self.user.pk}/"
        changed = self.client.patch(path, {"email": "scientist@example.org"}, format="json")
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(set(changed.data["roles"]), {"viewer", "tech"})
        changed = self.client.patch(path, {"role": "qc_reviewer"}, format="json")
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(changed.data["roles"], ["qc_reviewer"])
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)
        self.assertFalse(self.user.is_staff)

    def test_submission_rate_limit_does_not_create_duplicate_requests(self):
        for _ in range(20):
            self.assertIn(self.submit().status_code, [200, 201])
        self.assertEqual(self.submit().status_code, 429)
        self.assertEqual(AccessRequest.objects.count(), 1)
        self.assertEqual(Event.objects.filter(action="ACCESS_REQUEST_SUBMITTED").count(), 1)

    def test_reviewer_privileges_are_rechecked_on_fresh_locked_records(self):
        request_id = self.pending()
        self.client.force_authenticate(self.admin)
        get_user_model().objects.filter(pk=self.admin.pk).update(is_superuser=False)
        self.assertEqual(self.decide(request_id).status_code, 403)
        self.assertEqual(AccessRequest.objects.get(pk=request_id).status, "PENDING")
        self.assertFalse(self.project.members.filter(pk=self.user.pk).exists())

    def test_group_based_administrators_can_review_but_no_self_review(self):
        request_id = self.pending()
        self.client.force_authenticate(self.other_admin)
        self.assertEqual(self.decide(request_id).status_code, 200)
        self.client.force_authenticate(self.user)
        second = self.pending(project_code="BETA")
        self.user.groups.add(Group.objects.get(name="admin"))
        self.assertEqual(self.decide(second).status_code, 403)

    def test_already_assigned_access_does_not_create_duplicate_membership(self):
        request_id = self.pending()
        self.project.members.add(self.user)
        self.client.force_authenticate(self.admin)
        self.assertTrue(self.client.get(f"/api/access-requests/{request_id}/preview/").data["already_granted"])
        self.assertFalse(self.decide(request_id).data["access_changed"])

    def test_audit_failure_rolls_back_grant_status_and_notification(self):
        request_id = self.pending()
        self.client.force_authenticate(self.admin)
        before = Notification.objects.count()
        with patch("core.access_requests._audit", side_effect=RuntimeError("Audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.decide(request_id)
        self.assertFalse(self.project.members.filter(pk=self.user.pk).exists())
        self.assertEqual(AccessRequest.objects.get(pk=request_id).status, "PENDING")
        self.assertEqual(Notification.objects.count(), before)

    def test_own_request_audit_is_not_visible_to_other_users(self):
        self.pending()
        own = self.client.get("/api/events/?entity_type=AccessRequest")
        self.assertEqual(own.data["count"], 1)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get("/api/events/?entity_type=AccessRequest").data["count"], 0)

    def test_cookie_requests_require_csrf_and_anonymous_requests_are_denied(self):
        client = APIClient(enforce_csrf_checks=True)
        self.assertIn(client.get("/api/access-requests/").status_code, [401, 403])
        client.cookies[settings.JWT_ACCESS_COOKIE_NAME] = str(RefreshToken.for_user(self.user).access_token)
        payload = {"kind": "PROJECT", "project_code": "ALPHA", "reason": "Please add me to this laboratory project"}
        self.assertEqual(client.post("/api/v1/access-requests/", payload).status_code, 403)
        client.get("/api/v1/auth/csrf/")
        response = client.post("/api/v1/access-requests/", payload, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 201, response.data)

    def test_database_rejects_duplicate_pending_or_invalid_target_requests(self):
        request_id = self.pending()
        row = AccessRequest.objects.get(pk=request_id)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccessRequest.objects.create(requester=self.user, requester_username=self.user.username, kind="PROJECT", project_code="ALPHA", target_key=row.target_key, reason="Duplicate pending request")
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccessRequest.objects.create(requester=self.user, requester_username=self.user.username, kind="ROLE", role="admin", target_key="ROLE:admin", reason="Invalid administrator request")
