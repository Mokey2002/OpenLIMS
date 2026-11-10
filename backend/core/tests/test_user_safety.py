from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from core.user_safety import LAST_ADMIN_MESSAGE
from events.models import Event
from migration_toolkit.models import MigrationJob, MigrationObjectChange, MigrationProfile

User = get_user_model()


class AdministratorSafetyAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("only-administrator", password=None)
        self.client.force_authenticate(self.admin)
        self.path = f"/api/v1/admin-users/{self.admin.pk}/"

    def assertProtected(self, response):
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "last_active_administrator")
        self.assertEqual(response.data["detail"], LAST_ADMIN_MESSAGE)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertTrue(self.admin.is_superuser)
        self.assertFalse(Event.objects.filter(entity_type="User").exists())

    def test_last_superuser_without_groups_cannot_be_disabled_deleted_or_demoted(self):
        self.assertProtected(self.client.patch(self.path, {"is_active": False}, format="json"))
        self.assertProtected(self.client.delete(self.path))
        for role in ["viewer", "tech", "qc_reviewer"]:
            self.assertProtected(self.client.patch(self.path, {"role": role}, format="json"))
        self.assertFalse(self.admin.groups.exists())

    def test_full_put_and_compatibility_route_cannot_bypass_protection(self):
        self.assertProtected(self.client.put(self.path, {"role": "tech", "email": "changed@example.org"}, format="json"))
        self.assertProtected(self.client.patch(self.path.replace("/api/v1/", "/api/"), {"is_active": False}, format="json"))
        self.assertEqual(User.objects.get(pk=self.admin.pk).email, "")

    def test_sole_group_based_administrator_is_protected(self):
        self.admin.is_superuser = self.admin.is_staff = False
        self.admin.save()
        self.admin.groups.add(Group.objects.get_or_create(name="admin")[0])
        for payload in [{"role": "viewer"}, {"is_active": False}]:
            response = self.client.patch(self.path, payload, format="json")
            self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(self.client.delete(self.path).status_code, 409)
        self.assertTrue(self.admin.groups.filter(name="admin").exists())

    def test_inactive_administrators_and_staff_only_accounts_are_not_backups(self):
        User.objects.create_superuser("inactive-owner", password=None, is_active=False)
        inactive = User.objects.create_user("inactive-group-owner", is_active=False)
        inactive.groups.add(Group.objects.get_or_create(name="admin")[0])
        User.objects.create_user("staff-only", is_staff=True)
        self.assertProtected(self.client.patch(self.path, {"is_active": False}, format="json"))

    def test_duplicate_admin_grants_do_not_count_one_account_twice(self):
        self.admin.groups.add(Group.objects.get_or_create(name="admin")[0])
        self.assertProtected(self.client.delete(self.path))

    def test_profile_edits_and_preserving_admin_role_remain_allowed(self):
        self.admin.groups.add(Group.objects.get_or_create(name="viewer")[0])
        changed = self.client.patch(self.path, {"email": "owner@example.org", "first_name": "Lab"}, format="json")
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(set(changed.data["roles"]), {"viewer", "admin"})
        changed = self.client.patch(self.path, {"role": "admin", "is_active": True}, format="json")
        self.assertEqual(changed.status_code, 200, changed.data)

    def test_active_group_administrator_allows_a_superuser_handover(self):
        backup = User.objects.create_user("backup")
        backup.groups.add(Group.objects.get_or_create(name="admin")[0])
        response = self.client.patch(self.path, {"role": "viewer"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["roles"], ["viewer"])
        self.client.force_authenticate(backup)
        self.assertEqual(self.client.get("/api/admin-users/").status_code, 200)

    def test_removing_an_administrator_with_a_backup_is_allowed_and_audited_once(self):
        other = User.objects.create_superuser("backup", password=None)
        response = self.client.delete(f"/api/admin-users/{other.pk}/")
        self.assertEqual(response.status_code, 204, response.data)
        self.assertFalse(User.objects.filter(pk=other.pk).exists())
        self.assertEqual(Event.objects.filter(action="USER_DELETED").count(), 1)

    def test_disabling_an_administrator_with_a_backup_is_allowed(self):
        User.objects.create_superuser("backup", password=None)
        response = self.client.patch(self.path, {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(User.objects.get(pk=self.admin.pk).is_active)
        self.assertEqual(Event.objects.filter(action="USER_STATUS_UPDATED").count(), 1)

    def test_ordinary_user_edits_and_deletion_remain_available(self):
        other = User.objects.create_user("scientist")
        path = f"/api/admin-users/{other.pk}/"
        self.assertEqual(self.client.patch(path, {"role": "viewer", "is_active": False}, format="json").status_code, 200)
        self.assertEqual(self.client.delete(path).status_code, 204)

    def test_list_and_detail_mark_only_the_last_active_administrator(self):
        User.objects.create_user("scientist")
        rows = self.client.get("/api/admin-users/").data["results"]
        self.assertEqual([row["id"] for row in rows if row["is_last_active_admin"]], [self.admin.pk])
        self.assertTrue(self.client.get(self.path).data["is_last_active_admin"])
        User.objects.create_superuser("backup", password=None)
        self.assertFalse(any(row["is_last_active_admin"] for row in self.client.get("/api/admin-users/").data["results"]))

    def test_stale_authenticated_admin_is_rechecked_before_a_write(self):
        backup = User.objects.create_superuser("backup", password=None)
        User.objects.filter(pk=self.admin.pk).update(is_superuser=False)
        response = self.client.patch(f"/api/admin-users/{backup.pk}/", {"email": "unauthorized@example.org"}, format="json")
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(User.objects.get(pk=backup.pk).email, "")

    def test_user_update_and_role_change_roll_back_if_audit_fails(self):
        other = User.objects.create_user("scientist")
        with patch("core.views.Event.objects.create", side_effect=RuntimeError("Audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.client.patch(f"/api/admin-users/{other.pk}/", {"role": "tech", "email": "changed@example.org"}, format="json")
        other.refresh_from_db()
        self.assertEqual(other.email, "")
        self.assertFalse(other.groups.exists())

    def migration_job(self, action, **changes):
        profile = MigrationProfile.objects.create(name="Administrator rollback safety")
        job = MigrationJob.objects.create(profile=profile, status=MigrationJob.STATUS_COMPLETED, uploaded_by=self.admin)
        MigrationObjectChange.objects.create(
            migration_job=job, object_type="USER", object_id=str(self.admin.pk), action=action, **changes,
        )
        return job

    def test_migration_rollback_cannot_delete_the_last_administrator(self):
        job = self.migration_job("CREATED")
        response = self.client.post(f"/api/migration-jobs/{job.pk}/rollback/", {}, format="json")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn(LAST_ADMIN_MESSAGE, response.data["detail"])
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
        self.assertEqual(MigrationJob.objects.get(pk=job.pk).status, MigrationJob.STATUS_COMPLETED)

    def test_migration_rollback_cannot_restore_inactive_state_or_remove_sole_admin_group(self):
        self.admin.is_superuser = False
        self.admin.save()
        self.admin.groups.add(Group.objects.get_or_create(name="admin")[0])
        job = self.migration_job("UPDATED", previous_values={"email": "old@example.org"}, metadata={"groups": ["viewer"]})
        response = self.client.post(f"/api/migration-jobs/{job.pk}/rollback/", {}, format="json")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn(LAST_ADMIN_MESSAGE, response.data["detail"])
        self.assertEqual(User.objects.get(pk=self.admin.pk).email, "")
        self.assertTrue(self.admin.groups.filter(name="admin").exists())
        job.object_changes.update(previous_values={"is_active": False}, metadata={"groups": ["admin"]})
        self.assertEqual(self.client.post(f"/api/migration-jobs/{job.pk}/rollback/", {}, format="json").status_code, 409)
        self.assertTrue(User.objects.get(pk=self.admin.pk).is_active)

    def test_migration_role_restore_is_allowed_when_another_active_admin_remains(self):
        self.admin.is_superuser = False
        self.admin.save()
        self.admin.groups.add(Group.objects.get_or_create(name="admin")[0])
        Group.objects.get_or_create(name="viewer")
        User.objects.create_superuser("backup", password=None)
        job = self.migration_job("UPDATED", metadata={"groups": ["viewer"]})
        response = self.client.post(f"/api/migration-jobs/{job.pk}/rollback/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(list(self.admin.groups.values_list("name", flat=True)), ["viewer"])


class AdministratorSafetyDjangoAdminTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("staff-operator", is_staff=True)
        self.staff.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="auth", codename__in=[
                "view_user", "change_user", "delete_user", "view_group", "change_group", "delete_group",
            ],
        ))
        self.admin = User.objects.create_superuser("only-owner", password=None)
        self.client.force_login(self.staff)

    def user_form(self, **changes):
        values = {
            "username": self.admin.username, "email": "", "first_name": "", "last_name": "",
            "is_active": "on", "is_staff": "on", "is_superuser": "on", "groups": [], "user_permissions": [],
            "date_joined_0": self.admin.date_joined.strftime("%Y-%m-%d"),
            "date_joined_1": self.admin.date_joined.strftime("%H:%M:%S"), "_save": "Save",
        }
        values.update(changes)
        return values

    def test_user_change_form_blocks_disabling_and_demotion(self):
        path = reverse("admin:auth_user_change", args=[self.admin.pk])
        for changes in [{"is_active": ""}, {"is_superuser": ""}]:
            response = self.client.post(path, self.user_form(**changes))
            self.assertContains(response, LAST_ADMIN_MESSAGE)
            self.admin.refresh_from_db()
            self.assertTrue(self.admin.is_active)
            self.assertTrue(self.admin.is_superuser)

    def test_user_change_form_allows_profile_edits(self):
        response = self.client.post(reverse("admin:auth_user_change", args=[self.admin.pk]), self.user_form(email="owner@example.org"))
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.email, "owner@example.org")

    def test_password_change_keeps_the_administrator_active(self):
        response = self.client.post(reverse("admin:auth_user_password_change", args=[self.admin.pk]), {
            "password1": "Safe-handover-password-8492!", "password2": "Safe-handover-password-8492!",
            "usable_password": "true",
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertTrue(self.admin.is_superuser)
        self.assertTrue(self.admin.check_password("Safe-handover-password-8492!"))

    def group_only_admin(self):
        group = Group.objects.get_or_create(name="admin")[0]
        self.admin.groups.add(group)
        self.admin.is_superuser = False
        self.admin.save()
        return group

    def test_user_change_form_blocks_removing_the_only_admin_group_membership(self):
        self.group_only_admin()
        response = self.client.post(reverse("admin:auth_user_change", args=[self.admin.pk]), self.user_form(is_superuser="", groups=[]))
        self.assertContains(response, LAST_ADMIN_MESSAGE)
        self.assertTrue(self.admin.groups.filter(name="admin").exists())

    def test_single_user_delete_is_blocked(self):
        response = self.client.post(reverse("admin:auth_user_delete", args=[self.admin.pk]), {"post": "yes"})
        self.assertContains(response, LAST_ADMIN_MESSAGE)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_bulk_user_delete_is_all_or_nothing(self):
        scientist = User.objects.create_user("scientist")
        response = self.client.post(reverse("admin:auth_user_changelist"), {
            "action": "delete_selected", "_selected_action": [self.admin.pk, scientist.pk], "post": "yes",
        })
        self.assertContains(response, LAST_ADMIN_MESSAGE)
        self.assertTrue(User.objects.filter(pk=scientist.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_admin_group_cannot_be_renamed_or_deleted_when_it_is_the_only_access(self):
        group = self.group_only_admin()
        response = self.client.post(reverse("admin:auth_group_change", args=[group.pk]), {"name": "former-admin", "permissions": [], "_save": "Save"})
        self.assertContains(response, LAST_ADMIN_MESSAGE)
        group.refresh_from_db()
        self.assertEqual(group.name, "admin")
        response = self.client.post(reverse("admin:auth_group_delete", args=[group.pk]), {"post": "yes"})
        self.assertContains(response, LAST_ADMIN_MESSAGE)
        self.assertTrue(Group.objects.filter(pk=group.pk).exists())

    def test_bulk_group_delete_preserves_all_selected_groups_if_protected(self):
        group = self.group_only_admin()
        other = Group.objects.create(name="scientists")
        response = self.client.post(reverse("admin:auth_group_changelist"), {
            "action": "delete_selected", "_selected_action": [group.pk, other.pk], "post": "yes",
        })
        self.assertContains(response, LAST_ADMIN_MESSAGE)
        self.assertEqual(Group.objects.filter(pk__in=[group.pk, other.pk]).count(), 2)

    def test_admin_group_removal_is_allowed_when_an_active_superuser_remains(self):
        group = Group.objects.create(name="admin")
        self.admin.groups.add(group)
        response = self.client.post(reverse("admin:auth_group_delete", args=[group.pk]), {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Group.objects.filter(pk=group.pk).exists())
        self.assertTrue(User.objects.get(pk=self.admin.pk).is_superuser)
