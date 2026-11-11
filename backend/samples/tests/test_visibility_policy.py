from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from unittest.mock import patch
from reportlab.platypus import Table

from core.entities import get_accessible_entity_queryset, user_can_access_entity
from events.models import Event
from projects.models import Project
from results.models import Result, WorkItem
from samples.access import get_sample_access_queryset, user_can_access_sample, user_can_modify_sample
from samples.models import Sample


class SampleVisibilityPolicyTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = []
        for role in ("admin", "tech", "viewer", "qc_reviewer"):
            user = get_user_model().objects.create_user(f"visibility-{role}", is_superuser=role == "admin")
            user.groups.add(Group.objects.get_or_create(name=role)[0])
            cls.users.append(user)
        cls.primary = Project.objects.create(code="VISIBLE", name="Member project")
        cls.private = Project.objects.create(code="PRIVATE", name="Other project")
        cls.primary.members.add(*cls.users)
        cls.direct = Sample.objects.create(sample_id="VIS-DIRECT", project=cls.primary)
        cls.linked = Sample.objects.create(sample_id="VIS-LINKED", project=cls.private)
        cls.linked.linked_projects.add(cls.primary)
        cls.duplicate = Sample.objects.create(sample_id="VIS-DUPLICATE", project=cls.primary)
        cls.duplicate.linked_projects.add(cls.primary, cls.private)
        cls.unassigned = Sample.objects.create(sample_id="VIS-UNASSIGNED", created_by=cls.users[0])
        cls.hidden = Sample.objects.create(sample_id="VIS-HIDDEN", project=cls.private, created_by=cls.users[1], assigned_to=cls.users[1])
        cls.link_only_hidden = Sample.objects.create(sample_id="VIS-LINK-ONLY-PRIVATE", created_by=cls.users[1])
        cls.link_only_hidden.linked_projects.add(cls.private)

    def allowed(self):
        return {self.direct.pk, self.linked.pk, self.duplicate.pk, self.unassigned.pk}

    def test_list_detail_helpers_and_shared_entities_use_the_same_policy_for_all_roles(self):
        for user in self.users:
            with self.subTest(role=user.username):
                self.client.force_authenticate(user)
                response = self.client.get("/api/v1/samples/?page_size=200")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["count"], 4)
                self.assertEqual({row["id"] for row in response.data["results"]}, self.allowed())
                self.assertEqual(set(get_accessible_entity_queryset("sample", user).values_list("pk", flat=True)), self.allowed())
                for sample in Sample.objects.all():
                    expected = sample.pk in self.allowed()
                    self.assertEqual(user_can_access_sample(user, sample), expected)
                    self.assertEqual(user_can_access_entity(user, sample), expected)
                    self.assertEqual(self.client.get(f"/api/v1/samples/{sample.pk}/").status_code, 200 if expected else 404)

    def test_no_memberships_means_only_completely_unassigned_samples_even_for_admin(self):
        for user in self.users:
            with self.subTest(role=user.username):
                self.primary.members.remove(user)
                self.assertEqual(list(get_sample_access_queryset(Sample.objects.all(), user).values_list("pk", flat=True)), [self.unassigned.pk])

    def test_revoked_membership_and_creator_or_assignee_do_not_bypass_project_restrictions(self):
        tech = self.users[1]
        self.primary.members.remove(tech)
        self.assertFalse(user_can_access_sample(tech, self.hidden))
        self.assertFalse(user_can_modify_sample(tech, self.hidden))
        self.assertFalse(user_can_access_sample(tech, self.link_only_hidden))
        self.assertFalse(user_can_modify_sample(tech, self.link_only_hidden))
        self.assertTrue(user_can_access_sample(tech, self.unassigned))
        self.assertFalse(user_can_modify_sample(tech, self.unassigned))

    def test_anonymous_and_disabled_accounts_have_no_sample_access(self):
        self.assertFalse(get_sample_access_queryset(Sample.objects.all(), AnonymousUser()).exists())
        self.users[0].is_active = False
        self.users[0].save(update_fields=["is_active"])
        self.assertFalse(user_can_access_sample(self.users[0], self.unassigned))
        self.assertFalse(user_can_modify_sample(self.users[0], self.unassigned))

    def test_search_export_and_work_items_cannot_expose_private_samples(self):
        for sample in (self.direct, self.linked, self.unassigned, self.hidden, self.link_only_hidden):
            WorkItem.objects.create(sample=sample, work_type="GENERAL", name=sample.sample_id)
        for user in (self.users[0], self.users[1]):
            with self.subTest(role=user.username):
                self.client.force_authenticate(user)
                response = self.client.get("/api/v1/search/?q=VIS-")
                self.assertEqual(response.status_code, 200)
                self.assertEqual({row["id"] for row in response.data["results"]["samples"]}, self.allowed())
                work = self.client.get("/api/v1/work-items/?page_size=200")
                self.assertEqual(work.status_code, 200)
                self.assertNotIn(self.hidden.sample_id, str(work.data))
                self.assertNotIn(self.link_only_hidden.sample_id, str(work.data))
                export = self.client.post("/api/v1/samples/export-selected/", {"ids": list(Sample.objects.values_list("id", flat=True))}, format="json")
                self.assertEqual(export.status_code, 200)
                self.assertIn(self.unassigned.sample_id, export.content.decode())
                self.assertNotIn(self.hidden.sample_id, export.content.decode())
                self.assertNotIn(self.link_only_hidden.sample_id, export.content.decode())

    def test_private_sample_history_and_mutation_are_unavailable(self):
        hidden_event = Event.objects.create(entity_type="Sample", entity_id=str(self.hidden.pk), action="PRIVATE_CHANGE")
        visible_event = Event.objects.create(entity_type="Sample", entity_id=str(self.direct.public_id), action="PUBLIC_CHANGE")
        for user in self.users:
            self.client.force_authenticate(user)
            for section in ("history", "experiments"):
                self.assertEqual(self.client.get(f"/api/v1/samples/{self.hidden.pk}/{section}/").status_code, 404)
            # The standalone audit page retains its existing role gate; QC-only
            # accounts still use authorized sample-scoped history.
            audit_allowed = user != self.users[3]
            self.assertEqual(self.client.get(f"/api/v1/events/{hidden_event.pk}/").status_code, 404 if audit_allowed else 403)
            self.assertEqual(self.client.get(f"/api/v1/events/{visible_event.pk}/").status_code, 200 if audit_allowed else 403)
            if user in self.users[:2]:
                self.assertEqual(self.client.patch(f"/api/v1/samples/{self.hidden.pk}/", {"sample_type": "DNA"}, format="json").status_code, 404)

    def test_admin_audit_reference_checks_private_samples_without_hiding_unrelated_records(self):
        private = Event.objects.create(entity_type="Project", entity_id=str(self.primary.pk), action="REFERENCE",
            payload={"entity": {"type": "sample", "public_id": str(self.hidden.public_id)}})
        public = Event.objects.create(entity_type="Project", entity_id=str(self.primary.pk), action="REFERENCE",
            payload={"entity": {"type": "sample", "public_id": str(self.unassigned.public_id)}})
        unrelated = Event.objects.create(entity_type="Project", entity_id=str(self.primary.pk), action="PROJECT_UPDATED")
        self.client.force_authenticate(self.users[0])
        self.assertEqual(self.client.get(f"/api/v1/events/{private.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/events/{public.pk}/").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/events/{unrelated.pk}/").status_code, 200)

    def test_safe_sorting_pagination_and_no_duplicate_rows(self):
        self.client.force_authenticate(self.users[1])
        expected = sorted(self.allowed(), key=lambda pk: Sample.objects.get(pk=pk).sample_id)
        first = self.client.get("/api/v1/samples/?ordering=sample_id&page_size=2")
        second = self.client.get(first.data["next"])
        self.assertEqual([row["id"] for row in first.data["results"] + second.data["results"]], expected)
        invalid = self.client.get("/api/v1/samples/?ordering=created_by__password")
        self.assertEqual(invalid.status_code, 400)

    def test_project_pdf_metrics_include_only_accessible_sample_work_and_qc_results(self):
        from assistant.reporting_operations import _pdf_bytes
        for sample in (self.linked, self.hidden):
            work = WorkItem.objects.create(sample=sample, name="Protein work", work_type="GENERAL")
            Result.objects.create(work_item=work, key="protein", value_type="NUMBER", value_number=1,
                entered_by=self.users[0], qc_status=Result.QC_PENDING_REVIEW)
        for expected in (1, 0):
            with patch("assistant.reporting_operations.Table", wraps=Table) as table:
                output = _pdf_bytes([], {"report_type": "PROJECT_REPORT", "project_label": "Private project"}, self.private, user=self.users[0])
            self.assertTrue(output.startswith(b"%PDF"))
            metrics = dict(table.call_args_list[0].args[0][1:])
            self.assertEqual(metrics["Samples"], expected)
            self.assertEqual(metrics["Open work items"], expected)
            self.assertEqual(metrics["QC pending results"], expected)
            self.primary.members.remove(self.users[0])

    def test_public_read_access_does_not_grant_work_result_or_attachment_mutations(self):
        from assistant.workitem_operations import _accessible_work
        tech = self.users[1]
        work = WorkItem.objects.create(sample=self.unassigned, name="Other person's work", work_type="GENERAL")
        result = Result.objects.create(work_item=work, key="protein", value_type="NUMBER", value_number=1, entered_by=self.users[0])
        self.client.force_authenticate(tech)
        self.assertTrue(_accessible_work(tech).filter(pk=work.pk).exists())
        self.assertFalse(_accessible_work(tech, for_write=True).filter(pk=work.pk).exists())
        response = self.client.get(f"/api/v1/work-items/{work.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["can_update"])
        self.assertEqual(self.client.get(f"/api/v1/results/{result.pk}/").status_code, 200)
        self.assertEqual(self.client.patch(f"/api/v1/work-items/{work.pk}/", {"status": "IN_PROGRESS"}, format="json").status_code, 404)
        self.assertEqual(self.client.patch(f"/api/v1/results/{result.pk}/", {"value_number": 2}, format="json").status_code, 404)
        self.assertEqual(self.client.post("/api/v1/work-items/", {"sample": self.unassigned.pk, "name": "Unauthorized work", "work_type": "GENERAL"}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/v1/results/", {"work_item": work.pk, "key": "extra", "value_type": "NUMBER", "value_number": 2}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/v1/sample-attachments/", {"sample": self.unassigned.pk, "file": SimpleUploadedFile("protein.txt", b"observation", content_type="text/plain")}, format="multipart").status_code, 400)
        work.refresh_from_db(); result.refresh_from_db()
        self.assertEqual(work.status, "PENDING")
        self.assertEqual(result.value_number, 1)

    def test_writable_parent_validation_blocks_fk_reassignment_without_blocking_owned_work(self):
        tech = self.users[1]
        owned = Sample.objects.create(sample_id="VIS-OWNED-PUBLIC", created_by=tech)
        other_work = WorkItem.objects.create(sample=self.unassigned, name="Other person's work", work_type="GENERAL")
        self.client.force_authenticate(tech)
        response = self.client.post("/api/v1/work-items/", {"sample": owned.pk, "name": "Owned work", "work_type": "GENERAL"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["can_update"])
        own_work = WorkItem.objects.get(pk=response.data["id"])
        for target in (self.unassigned, self.hidden):
            response = self.client.patch(f"/api/v1/work-items/{own_work.pk}/", {"sample": target.pk}, format="json")
            self.assertEqual(response.status_code, 400, response.data)
        response = self.client.post("/api/v1/results/", {"work_item": own_work.pk, "key": "protein", "value_type": "NUMBER", "value_number": 2}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        response = self.client.patch(f"/api/v1/results/{response.data['id']}/", {"work_item": other_work.pk}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        own_work.refresh_from_db(); self.assertEqual(own_work.sample_id, owned.pk)

    def test_qc_read_visibility_does_not_expand_native_or_assistant_review_permissions(self):
        from assistant.qc_operations import _propose_review_decision, _result_queryset
        work = WorkItem.objects.create(sample=self.unassigned, name="Public QC work", work_type="GENERAL")
        result = Result.objects.create(work_item=work, key="protein", value_type="NUMBER", value_number=1,
            entered_by=self.users[0], qc_status=Result.QC_PENDING_REVIEW)
        reviewer = self.users[3]
        self.assertTrue(_result_queryset(reviewer).filter(pk=result.pk).exists())
        self.assertFalse(_result_queryset(reviewer, for_write=True).filter(pk=result.pk).exists())
        proposal = _propose_review_decision(f"Approve result R-{result.pk} because the controls passed.", reviewer)
        self.assertNotIn("pending_action", proposal)
        self.client.force_authenticate(reviewer)
        self.assertEqual(self.client.post(f"/api/v1/work-items/{work.pk}/qc-review/", {"qc_status": "APPROVED", "review_note": "Controls passed"}, format="json").status_code, 404)
