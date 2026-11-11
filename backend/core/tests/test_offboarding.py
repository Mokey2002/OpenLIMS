from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.models import Session
from django.test import Client, TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from assistant.models import AssistantAction, NotificationSubscription
from core.models import AccessRequest, UserOffboarding, UserSessionState
from events.models import Event
from notebook.models import Notebook, Experiment, ExperimentComment, ExperimentWorkflowStep
from notifications.models import Notification
from projects.models import Project
from registry.models import RegistrySchema, RegistryRecord
from results.models import Result, WorkItem
from samples.models import Sample, SampleCustodyEvent

User = get_user_model()


class OffboardingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("offboard-director", password=None)
        cls.target = User.objects.create_user("departing-scientist", password=None, is_staff=True)
        cls.successor = User.objects.create_user("replacement-scientist", password=None)
        tech, _ = Group.objects.get_or_create(name="tech")
        qc, _ = Group.objects.get_or_create(name="qc_reviewer")
        cls.target.groups.add(tech, qc)
        cls.successor.groups.add(tech, qc)
        cls.target.user_permissions.add(Permission.objects.get(codename="change_user"))
        cls.project = Project.objects.create(code="HANDOVER", name="Handover study")
        cls.project.members.add(cls.target, cls.successor, cls.admin)
        cls.sample = Sample.objects.create(sample_id="PROTEIN-100", project=cls.project,
            created_by=cls.target, assigned_to=cls.target, custodian=cls.target)
        cls.work = WorkItem.objects.create(sample=cls.sample, name="Protein concentration", assigned_to=cls.target, created_by=cls.target)
        cls.result = Result.objects.create(work_item=cls.work, key="concentration", value_type="NUMBER", value_number=2.5,
            entered_by=cls.target, qc_assigned_to=cls.target)
        cls.notebook = Notebook.objects.create(name="Protein experiments", owner=cls.target, project=cls.project, scope="PROJECT")
        for field in ("team_members", "readers", "editors", "commenters", "reviewers", "lockers"):
            getattr(cls.notebook, field).add(cls.target)
        cls.experiment = Experiment.objects.create(notebook=cls.notebook, title="Protein stability", created_by=cls.target)
        cls.experiment.assignees.add(cls.target)
        cls.step = ExperimentWorkflowStep.objects.create(experiment=cls.experiment, position=1, assignee=cls.target, definition={"name": "Measure stability"})
        cls.comment = ExperimentComment.objects.create(experiment=cls.experiment, author=cls.target, assigned_to=cls.target, body="Check protein concentration")
        schema = RegistrySchema.objects.create(code="proteins", name="Proteins", entity_type="protein", schema={})
        cls.protein = RegistryRecord.objects.create(registry_id="PROTEIN-A", schema=schema, name="Protein A", owner=cls.target, project=cls.project)
        cls.access_request = AccessRequest.objects.create(requester=cls.target, requester_username=cls.target.username,
            kind="ROLE", role="viewer", target_key="ROLE:viewer", reason="Need read access for handover")
        cls.proposal = AssistantAction.objects.create(requested_by=cls.target, action_type="CREATE_SAMPLES", summary="Register follow-up samples",
            expires_at=timezone.now() + timedelta(hours=1))
        cls.subscription = NotificationSubscription.objects.create(recipient=cls.target, created_by=cls.target, trigger="SAMPLE_APPROVED",
            target_id=str(cls.sample.pk), project=cls.project, deduplication_key="offboarding-notification")
        Event.objects.all().delete()

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.base = f"/api/admin-users/{self.target.pk}/offboarding"

    def prepare(self, **overrides):
        body = {"successor_id": self.successor.pk, "reason": "Confirmed departure and laboratory handover", "custody_confirmed": True, **overrides}
        return self.client.post(self.base + "/preview/", body, format="json")

    def preview_id(self):
        response = self.prepare()
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["preview_id"]

    def confirm(self, preview_id, **overrides):
        return self.client.post(self.base + "/confirm/", {"preview_id": preview_id, "confirmed": True, **overrides}, format="json")

    def test_review_is_readable_admin_only_and_does_not_change_anything(self):
        response = self.client.get(self.base + "/")
        self.assertEqual(response.status_code, 200, response.data)
        snapshot = response.data["snapshot"]
        self.assertEqual(snapshot["total_responsibilities"], 9)
        self.assertEqual(snapshot["responsibilities"]["samples"][0]["label"], "PROTEIN-100")
        self.assertEqual(snapshot["projects"][0]["code"], "HANDOVER")
        self.assertEqual(snapshot["responsibilities"]["notebooks"][0]["label"], "Protein experiments")
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(UserOffboarding.objects.count(), 0)
        self.client.force_authenticate(self.successor)
        for suffix in ["/", "/preview/", "/confirm/"]:
            response = self.client.get(self.base + suffix) if suffix == "/" else self.client.post(self.base + suffix, {}, format="json")
            self.assertEqual(response.status_code, 403)

    def test_preview_has_no_business_changes_and_requires_explicit_confirmation(self):
        preview = self.preview_id()
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.assertEqual(self.sample.assigned_to_id, self.target.pk)
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(self.confirm(preview, confirmed=False).status_code, 400)
        self.assertEqual(self.client.post(self.base + "/confirm/", {"preview_id": preview}, format="json").status_code, 400)

    def test_completion_transfers_work_removes_access_preserves_authorship_and_is_repeat_safe(self):
        preview = self.preview_id()
        response = self.confirm(preview)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["total_transferred"], 9)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active or self.target.is_staff or self.target.is_superuser)
        self.assertFalse(self.target.groups.exists())
        self.assertFalse(self.target.user_permissions.exists())
        self.assertFalse(self.project.members.filter(pk=self.target.pk).exists())
        for field in ("team_members", "readers", "editors", "commenters", "reviewers", "lockers"):
            self.assertFalse(getattr(self.notebook, field).filter(pk=self.target.pk).exists())
        for row, field in [(self.sample, "assigned_to"), (self.sample, "custodian"), (self.work, "assigned_to"),
                           (self.result, "qc_assigned_to"), (self.notebook, "owner"), (self.step, "assignee"),
                           (self.comment, "assigned_to"), (self.protein, "owner")]:
            row.refresh_from_db()
            self.assertEqual(getattr(row, field + "_id"), self.successor.pk)
        self.assertEqual(self.step.version, 2)
        self.assertEqual(list(self.experiment.assignees.all()), [self.successor])
        self.assertEqual(self.sample.created_by_id, self.target.pk)
        self.assertEqual(self.work.created_by_id, self.target.pk)
        self.assertEqual(self.result.entered_by_id, self.target.pk)
        self.assertEqual(self.experiment.created_by_id, self.target.pk)
        self.assertEqual(self.comment.author_id, self.target.pk)
        custody = SampleCustodyEvent.objects.get(sample=self.sample)
        self.assertEqual(custody.from_custodian, self.target)
        self.assertEqual(custody.to_custodian, self.successor)
        self.assertEqual(custody.action, "TRANSFER")
        self.access_request.refresh_from_db()
        self.proposal.refresh_from_db()
        self.subscription.refresh_from_db()
        self.assertEqual(self.access_request.status, "CANCELLED")
        self.assertEqual(self.proposal.status, "CANCELLED")
        self.assertFalse(self.subscription.active)
        self.assertEqual(UserSessionState.objects.get(user=self.target).generation, 1)
        count = Event.objects.count()
        repeated = self.confirm(preview)
        self.assertEqual(repeated.data, response.data)
        self.assertEqual(Event.objects.count(), count)
        self.assertEqual(Event.objects.filter(action="USER_OFFBOARDED").count(), 1)
        self.assertEqual(SampleCustodyEvent.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.successor).count(), 1)
        displayed = self.client.get("/api/events/?action=RESPONSIBILITY_TRANSFERRED").data["results"]
        self.assertEqual(len(displayed), 9)
        self.assertTrue(any(row["entity_label"] == "Protein stability: step 1" for row in displayed))
        self.assertTrue(any(row["entity_label"] == "Protein stability: Check protein concentration" for row in displayed))
        self.assertTrue(all(self.target.username in row["description"] and self.successor.username in row["description"] for row in displayed))

    def test_completed_work_and_approved_results_keep_their_assignees(self):
        self.work.status = "COMPLETED"
        self.work.save()
        self.result.qc_status = "APPROVED"
        self.result.save()
        self.step.status = "COMPLETED"
        self.step.completed_by = self.target
        self.step.save()
        response = self.confirm(self.preview_id())
        self.assertEqual(response.status_code, 200, response.data)
        for row, field in [(self.work, "assigned_to_id"), (self.result, "qc_assigned_to_id"), (self.step, "assignee_id")]:
            row.refresh_from_db()
            self.assertEqual(getattr(row, field), self.target.pk)
        self.assertEqual(self.step.completed_by_id, self.target.pk)

    def test_replacement_is_required_and_physical_custody_must_be_confirmed(self):
        for body in [{"successor_id": None}, {"successor_id": self.target.pk}, {"custody_confirmed": False}, {"reason": "short"}]:
            with self.subTest(body=body):
                response = self.prepare(**body)
                self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(UserOffboarding.objects.count(), 0)

    def test_replacement_requires_project_access_qc_role_and_independence(self):
        self.project.members.remove(self.successor)
        self.assertIn("add the replacement to project", str(self.prepare().data))
        self.project.members.add(self.successor)
        self.successor.groups.remove(Group.objects.get(name="qc_reviewer"))
        self.assertIn("QC reviewer", str(self.prepare().data))
        self.successor.groups.add(Group.objects.get(name="qc_reviewer"))
        from settings_app.models import SystemSettings
        policy = SystemSettings.load()
        policy.qc_separation_of_duties = True
        policy.save()
        self.result.entered_by = self.successor
        self.result.save()
        self.assertIn("independent reviewer", str(self.prepare().data))

    def test_other_private_notebooks_require_existing_edit_access(self):
        private = Notebook.objects.create(name="Another private notebook", owner=self.admin, scope="USER")
        experiment = Experiment.objects.create(notebook=private, title="Private task", created_by=self.admin)
        experiment.assignees.add(self.target)
        response = self.prepare()
        self.assertEqual(response.status_code, 400)
        self.assertIn("edit access", str(response.data))
        private.editors.add(self.successor)
        self.assertEqual(self.prepare().status_code, 201)

    def test_changed_work_or_memberships_requires_new_preview_without_partial_changes(self):
        for change in [lambda: WorkItem.objects.create(sample=self.sample, name="New handover", work_type="EXTRA", assigned_to=self.target),
                       lambda: self.notebook.readers.remove(self.target)]:
            preview = self.preview_id()
            change()
            response = self.confirm(preview)
            self.assertEqual(response.status_code, 409, response.data)
            self.target.refresh_from_db()
            self.assertTrue(self.target.is_active)
            self.assertEqual(Event.objects.filter(action="USER_OFFBOARDED").count(), 0)

    def test_replacement_access_is_rechecked_at_confirmation(self):
        preview = self.preview_id()
        self.project.members.remove(self.successor)
        self.assertEqual(self.confirm(preview).status_code, 409)
        self.project.members.add(self.successor)
        self.successor.is_active = False
        self.successor.save()
        self.assertEqual(self.confirm(preview).status_code, 409)

    def test_preview_expires_and_is_bound_to_the_preparing_administrator(self):
        preview = self.preview_id()
        other = User.objects.create_superuser("another-director", password=None)
        self.client.force_authenticate(other)
        self.assertEqual(self.confirm(preview).status_code, 404)
        self.client.force_authenticate(self.admin)
        UserOffboarding.objects.filter(pk=preview).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.confirm(preview).status_code, 409)

    def test_self_offboarding_and_last_administrator_are_blocked(self):
        response = self.client.get(f"/api/admin-users/{self.admin.pk}/offboarding/")
        self.assertEqual(len(response.data["blockers"]), 2)
        response = self.client.post(f"/api/admin-users/{self.admin.pk}/offboarding/preview/", {
            "reason": "Cannot remove the only administrator", "successor_id": self.successor.pk}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(UserOffboarding.objects.count(), 0)

    def test_administrator_privileges_are_rechecked_after_preview(self):
        preview = self.preview_id()
        self.admin.is_superuser = self.admin.is_staff = False
        self.admin.save()
        self.assertEqual(self.confirm(preview).status_code, 403)

    def test_failure_rolls_back_transfers_access_sessions_and_receipt(self):
        preview = self.preview_id()
        token = RefreshToken.for_user(self.target)
        original = Event.objects.create

        def fail_master(**kwargs):
            if kwargs.get("action") == "USER_OFFBOARDED":
                raise RuntimeError("Simulated audit write failure")
            return original(**kwargs)

        with patch("events.models.Event.objects.create", side_effect=fail_master):
            with self.assertRaisesRegex(RuntimeError, "Simulated audit write failure"):
                self.confirm(preview)
        self.target.refresh_from_db()
        self.sample.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.assertEqual(self.sample.assigned_to_id, self.target.pk)
        self.assertTrue(self.project.members.filter(pk=self.target.pk).exists())
        self.assertFalse(UserSessionState.objects.filter(user=self.target).exists())
        self.assertFalse(UserOffboarding.objects.get(pk=preview).completed_at)
        self.assertEqual(SampleCustodyEvent.objects.count(), 0)
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(RefreshToken(str(token))["user_id"], str(self.target.pk))

    def test_old_bearer_cookie_refresh_and_native_sessions_stay_revoked_after_reactivation(self):
        self.target.set_password("Handover-Testing-123!")
        self.target.save()
        old_refresh = RefreshToken.for_user(self.target)
        old_access = str(old_refresh.access_token)
        native = Client()
        native.force_login(self.target)
        session_row = Session.objects.get(session_key=native.session.session_key)
        session_data = session_row.session_data
        other_token = str(RefreshToken.for_user(self.successor).access_token)
        self.assertEqual(self.confirm(self.preview_id()).status_code, 200)
        self.assertFalse(Session.objects.filter(pk=session_row.pk).exists())
        self.target.is_active = True
        self.target.save(update_fields=["is_active"])
        for prefix in ["/api", "/api/v1"]:
            bearer = APIClient()
            bearer.credentials(HTTP_AUTHORIZATION=f"Bearer {old_access}")
            self.assertEqual(bearer.get(prefix + "/me/").status_code, 401)
            refresh_response = APIClient().post(prefix + "/auth/token/refresh/", {"refresh": str(old_refresh)}, format="json")
            self.assertEqual(refresh_response.status_code, 401)
        browser = APIClient()
        browser.cookies["openlims_access"] = old_access
        self.assertEqual(browser.get("/api/v1/me/").status_code, 401)
        browser.cookies["openlims_refresh"] = str(old_refresh)
        browser.get("/api/v1/auth/csrf/")
        self.assertEqual(browser.post("/api/v1/auth/refresh/", {}, format="json", HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value).status_code, 401)
        Session.objects.create(session_key=session_row.pk, session_data=session_data, expire_date=session_row.expire_date)
        self.target.is_staff = self.target.is_superuser = True
        self.target.save()
        self.assertEqual(native.get("/admin/").status_code, 302)
        authenticated_other = APIClient()
        authenticated_other.credentials(HTTP_AUTHORIZATION=f"Bearer {other_token}")
        self.assertEqual(authenticated_other.get("/api/v1/me/").status_code, 200)
        fresh = APIClient().post("/api/v1/auth/token/", {"username": self.target.username, "password": "Handover-Testing-123!"}, format="json")
        self.assertEqual(fresh.status_code, 200, fresh.data)
        bearer = APIClient()
        bearer.credentials(HTTP_AUTHORIZATION=f"Bearer {fresh.data['access']}")
        self.assertEqual(bearer.get("/api/v1/me/").status_code, 200)

    def test_unknown_fields_cannot_bypass_the_preview(self):
        response = self.prepare(transfer_roles=True)
        self.assertEqual(response.status_code, 400)
        preview = self.preview_id()
        self.assertEqual(self.confirm(preview, successor_id=self.admin.pk).status_code, 400)

    def test_a_disabled_account_can_still_finish_its_handover(self):
        self.target.is_active = False
        self.target.save(update_fields=["is_active"])
        response = self.confirm(self.preview_id())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["total_transferred"], 9)
        self.target.refresh_from_db()
        self.assertFalse(self.target.groups.exists())

    def test_replaying_a_receipt_does_not_disable_a_later_reactivated_account(self):
        preview = self.preview_id()
        first = self.confirm(preview)
        self.target.is_active = True
        self.target.save(update_fields=["is_active"])
        self.target.groups.add(Group.objects.get(name="tech"))
        repeated = self.confirm(preview)
        self.assertEqual(repeated.data, first.data)
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.assertTrue(self.target.groups.filter(name="tech").exists())
        self.assertEqual(UserSessionState.objects.get(user=self.target).generation, 1)

    def test_unassigned_samples_require_an_accessible_replacement(self):
        Sample.objects.create(sample_id="PRIVATE-HANDOVER", created_by=self.target, assigned_to=self.target)
        response = self.prepare()
        self.assertEqual(response.status_code, 400)
        self.assertIn("unassigned sample", str(response.data))

    def test_policy_changes_invalidate_a_prepared_handover(self):
        preview = self.preview_id()
        from settings_app.models import SystemSettings
        policy = SystemSettings.load()
        policy.qc_separation_of_duties = not policy.qc_separation_of_duties
        policy.save()
        self.assertEqual(self.confirm(preview).status_code, 409)

    def test_offboarded_users_cannot_receive_new_work_or_notebook_assignments(self):
        self.assertEqual(self.confirm(self.preview_id()).status_code, 200)
        response = self.client.patch(f"/api/work-items/{self.work.pk}/", {"assigned_to": self.target.pk}, format="json")
        self.assertEqual(response.status_code, 400)
        response = self.client.patch(f"/api/experiments/{self.experiment.pk}/", {"assignees": [self.target.pk]}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_deleted_replacement_invalidates_even_a_preview_without_outstanding_work(self):
        empty = User.objects.create_user("empty-departing-account", password=None)
        base = f"/api/admin-users/{empty.pk}/offboarding"
        preview = self.client.post(base + "/preview/", {"successor_id": self.successor.pk, "reason": "A reviewed optional replacement selection"}, format="json")
        self.assertEqual(preview.status_code, 201, preview.data)
        self.successor.delete()
        response = self.client.post(base + "/confirm/", {"preview_id": preview.data["preview_id"], "confirmed": True}, format="json")
        self.assertEqual(response.status_code, 409, response.data)
        empty.refresh_from_db()
        self.assertTrue(empty.is_active)

    def test_administrative_reason_is_not_exposed_in_shared_record_history_or_recipient_notifications(self):
        import json
        private_reason = "Administrator-only departure details for this account"
        preview = self.prepare(reason=private_reason)
        self.assertEqual(preview.status_code, 201, preview.data)
        self.assertEqual(self.confirm(preview.data["preview_id"]).status_code, 200)
        master = Event.objects.get(action="USER_OFFBOARDED")
        self.assertEqual(master.payload["reason"], private_reason)
        self.client.force_authenticate(self.successor)
        shared = self.client.get("/api/events/").data
        self.assertNotIn(private_reason, json.dumps(shared))
        self.assertEqual(self.client.get(f"/api/events/{master.pk}/").status_code, 404)
        self.assertNotIn(private_reason, Notification.objects.get(user=self.successor).message)
        self.assertNotIn(private_reason, SampleCustodyEvent.objects.get(sample=self.sample).reason)
