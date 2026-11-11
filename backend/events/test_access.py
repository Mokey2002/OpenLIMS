from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from alignments.models import AlignmentJob
from assistant.models import AssistantAction, SOPDocument
from blast.models import BlastDatabase, BlastJob
from core.audit import record_audit_event
from core.entities import entity_reference
from events.models import Event
from imports.models import ImportJob, InstrumentProfile
from inventory.models import Location
from mass_spec.models import MassSpecRun
from notebook.models import Experiment, Notebook
from pipelines.models import PipelineRun, PipelineTemplate
from projects.models import Project
from registry.models import RegistryRecord, RegistrySchema
from results.models import Result, WorkItem
from samples.models import Sample
from sequences.models import Sequence
from settings_app.models import SystemSettings


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
class AuditAccessTests(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("audit-director", password=None)
        self.tech = self.user("audit-tech", "tech")
        self.viewer = self.user("audit-viewer", "viewer")
        self.other = self.user("audit-other", "tech")
        self.project = Project.objects.create(code="VISIBLE", name="Visible project")
        self.private = Project.objects.create(code="PRIVATE", name="Private project")
        self.project.members.add(self.tech, self.viewer)
        self.private.members.add(self.other)
        template = PipelineTemplate.objects.create(code="AUDIT", name="Audit workflow")
        instrument = InstrumentProfile.objects.create(code="AUDIT", name="Audit sequencer")
        database = BlastDatabase.objects.create(name="Audit database")
        self.entities = {}
        for scope, project in [("allowed", self.project), ("denied", self.private)]:
            sample = Sample.objects.create(sample_id=f"AUDIT-{scope}", project=project, created_by=self.tech)
            work = WorkItem.objects.create(sample=sample, name=f"Work {scope}", created_by=self.other)
            sequence = Sequence.objects.create(name=f"Sequence {scope}", sequence="ATGC", project=project)
            self.entities[scope] = {
                "Project": project,
                "Sample": sample,
                "WorkItem": work,
                "Result": Result.objects.create(work_item=work, key="concentration", value_type="NUMBER", value_number=10),
                "PipelineRun": PipelineRun.objects.create(sample=sample, template=template),
                "Sequence": sequence,
                "ImportJob": ImportJob.objects.create(instrument=instrument, project=project, uploaded_by=self.other),
                "AlignmentJob": AlignmentJob.objects.create(name=f"Alignment {scope}", project=project, created_by=self.other),
                "BlastJob": BlastJob.objects.create(name=f"BLAST {scope}", query_sequence=sequence, database=database, project=project, created_by=self.other),
                "mass_spec_run": MassSpecRun.objects.create(name=f"Mass spec {scope}", project=project, uploaded_by=self.other),
            }
        Event.objects.all().delete()
        self.allowed = {}
        self.denied = {}
        for kind, target in self.entities["allowed"].items():
            self.allowed[kind] = self.event(kind, target, f"VISIBLE_{kind}")
        for kind, target in self.entities["denied"].items():
            self.denied[kind] = self.event(kind, target, f"SECRET_{kind}", actor=self.tech)
        self.client.force_authenticate(self.tech)

    def user(self, username, role):
        user = get_user_model().objects.create_user(username)
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        return user

    def event(self, kind, target, action, *, actor=None, payload=None, public=False):
        return Event.objects.create(
            entity_type=kind, entity_id=str(target.public_id if public else target.pk),
            action=action, actor=actor or self.other, payload={} if payload is None else payload,
        )

    def ids(self, **params):
        response = self.client.get("/api/v1/events/", {"page_size": 200, **params})
        self.assertEqual(response.status_code, 200, response.data)
        return {row["id"] for row in response.data["results"]}

    def test_technicians_and_viewers_only_see_current_accessible_entities(self):
        for user in [self.tech, self.viewer]:
            with self.subTest(user=user.username):
                self.client.force_authenticate(user)
                self.assertEqual(self.ids(), {row.pk for row in self.allowed.values()})

    def test_private_detail_is_404_even_when_the_requester_wrote_the_event(self):
        for row in self.denied.values():
            with self.subTest(kind=row.entity_type):
                response = self.client.get(f"/api/events/{row.pk}/")
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(row.action, str(response.data))

    def test_summary_and_search_filters_cannot_reveal_private_events(self):
        response = self.client.get("/api/events/summary/")
        self.assertEqual(response.data["total_events"], len(self.allowed))
        self.assertEqual(set(response.data["actions"]), {row.action for row in self.allowed.values()})
        for query in [{"search": "SECRET"}, {"action": "SECRET_Sample"}, {"actor": self.tech.username, "entity_type": "Sample"}]:
            with self.subTest(query=query):
                self.assertEqual(self.ids(**query), set())
                self.assertEqual(self.client.get("/api/events/summary/", query).data["total_events"], 0)

    def test_pagination_counts_and_pages_are_scoped_before_slicing(self):
        response = self.client.get("/api/events/?page_size=2")
        self.assertEqual(response.data["count"], len(self.allowed))
        seen = []
        while True:
            seen.extend(row["id"] for row in response.data["results"])
            if not response.data["next"]:
                break
            response = self.client.get(response.data["next"])
        self.assertCountEqual(seen, [row.pk for row in self.allowed.values()])

    def test_membership_revocation_hides_existing_records_immediately(self):
        self.project.members.remove(self.tech)
        self.assertEqual(self.ids(), set())
        self.assertEqual(self.client.get("/api/events/summary/").data["total_events"], 0)
        self.assertEqual(self.client.get(f"/api/events/{self.allowed['Sample'].pk}/").status_code, 404)

    def test_actual_ownership_wins_over_a_forged_project_claim(self):
        row = self.event("Sample", self.entities["denied"]["Sample"], "FORGED_PROJECT", payload={"project_id": self.project.pk})
        self.assertNotIn(row.pk, self.ids())

    def test_old_project_snapshots_do_not_leak_after_an_entity_moves(self):
        sample = self.entities["allowed"]["Sample"]
        for payload in [
            {"project_id": self.private.pk}, {"project_id": str(self.private.pk)},
            {"project": self.private.pk}, {"project": {"public_id": str(self.private.public_id), "code": "PRIVATE"}},
            {"before": {"project_id": self.private.pk}, "after": {"project_id": self.project.pk}},
        ]:
            with self.subTest(payload=payload):
                row = self.event("Sample", sample, "FORMER_PRIVATE_PROJECT", payload=payload)
                self.assertNotIn(row.pk, self.ids())

    def test_numeric_and_public_ids_and_entity_aliases_follow_the_same_policy(self):
        for kind, canonical in [("sample", "Sample"), ("work_item", "WorkItem"), ("PIPELINE_RUN", "PipelineRun")]:
            with self.subTest(kind=kind):
                allowed = self.event(kind, self.entities["allowed"][canonical], "VISIBLE_ALIAS", public=True)
                denied = self.event(kind, self.entities["denied"][canonical], "SECRET_ALIAS", public=True)
                ids = self.ids()
                self.assertIn(allowed.pk, ids)
                self.assertNotIn(denied.pk, ids)

    def test_invalid_and_overflowing_identifiers_are_hidden_without_cast_errors(self):
        for identifier in ["not-a-uuid", "9" * 64, "9223372036854775808", "' OR 1=1 --"]:
            with self.subTest(identifier=identifier):
                row = Event.objects.create(entity_type="Sample", entity_id=identifier, action="INVALID_IDENTIFIER")
                self.assertNotIn(row.pk, self.ids())
                self.assertEqual(self.client.get(f"/api/events/{row.pk}/").status_code, 404)

    def test_linked_project_and_completely_unassigned_samples_are_visible(self):
        sample = self.entities["denied"]["Sample"]
        sample.linked_projects.add(self.project)
        self.assertIn(self.denied["Sample"].pk, self.ids())
        self.assertIn(self.denied["WorkItem"].pk, self.ids())
        own = Sample.objects.create(sample_id="UNASSIGNED-OWN", created_by=self.tech)
        other = Sample.objects.create(sample_id="UNASSIGNED-OTHER", created_by=self.other)
        own_event = self.event("Sample", own, "UNASSIGNED_OWN")
        other_event = self.event("Sample", other, "UNASSIGNED_OTHER")
        self.assertIn(own_event.pk, self.ids())
        self.assertIn(other_event.pk, self.ids())
        self.client.force_authenticate(self.viewer)
        self.assertIn(own_event.pk, self.ids())
        self.assertIn(other_event.pk, self.ids())

    def test_private_notebooks_require_notebook_access_not_just_project_membership(self):
        notebook = Notebook.objects.create(name="Private scientific notes", owner=self.other)
        experiment = Experiment.objects.create(notebook=notebook, title="Private experiment", created_by=self.other)
        row = self.event("experiment", experiment, "PRIVATE_EXPERIMENT", payload={"project_id": self.project.pk})
        self.assertNotIn(row.pk, self.ids())
        notebook.readers.add(self.tech)
        self.assertIn(row.pk, self.ids())
        notebook.readers.remove(self.tech)
        self.assertNotIn(row.pk, self.ids())

    def test_link_audits_require_access_to_both_the_source_and_target(self):
        notebook = Notebook.objects.create(name="Private linked notebook", owner=self.other)
        experiment = Experiment.objects.create(notebook=notebook, title="Private linked experiment", created_by=self.other)
        row = record_audit_event(
            entity=self.entities["allowed"]["Sample"], action="ENTITY_LINK_CREATED", actor=self.other,
            details={"target": entity_reference(experiment)},
        )
        self.assertNotIn(row.pk, self.ids())
        notebook.readers.add(self.tech)
        self.assertIn(row.pk, self.ids())
        notebook.readers.remove(self.tech)
        self.assertNotIn(row.pk, self.ids())

    def test_visible_project_snapshots_and_null_context_are_retained(self):
        sample = self.entities["allowed"]["Sample"]
        for payload in [
            {"project_id": None}, {"project": None}, {"project_id": self.project.pk},
            {"project_id": str(self.project.pk)}, {"project": {"public_id": str(self.project.public_id), "code": self.project.code}},
        ]:
            with self.subTest(payload=payload):
                row = self.event("Sample", sample, "VISIBLE_PROJECT_CONTEXT", payload=payload)
                self.assertIn(row.pk, self.ids())

    def test_registry_private_visibility_overrides_its_public_project(self):
        schema = RegistrySchema.objects.create(code="PROTEIN", name="Protein", entity_type="protein")
        record = RegistryRecord.objects.create(
            registry_id="AUDIT-PROTEIN", name="Private protein", schema=schema,
            project=self.project, owner=self.other, visibility="PRIVATE",
        )
        row = self.event("registry_record", record, "PRIVATE_REGISTRY")
        self.assertNotIn(row.pk, self.ids())
        record.visibility = "INSTITUTION"
        record.save()
        self.assertIn(row.pk, self.ids())

    def test_unknown_deleted_and_administrative_events_are_admin_only(self):
        rows = [Event.objects.create(entity_type=kind, entity_id="999999999", action="UNRESOLVED_PRIVATE", actor=self.tech, payload={"project_id": self.project.pk})
                for kind in ["UnknownModule", "Sample", "User", "SystemSettings"]]
        self.assertFalse({row.pk for row in rows} & self.ids())
        self.client.force_authenticate(self.admin)
        visible = self.ids()
        self.assertTrue({row.pk for row in rows if row.entity_type != "Sample"} <= visible)
        self.assertNotIn(next(row.pk for row in rows if row.entity_type == "Sample"), visible)

    def test_assistant_privacy_remains_an_additional_boundary(self):
        action = AssistantAction.objects.create(
            requested_by=self.tech, action_type="CREATE_SAMPLES", summary="Own action",
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        own = self.event("AssistantAction", action, "OWN_ASSISTANT", actor=self.tech)
        other = self.event("Sample", self.entities["allowed"]["Sample"], "PRIVATE_OTHER_ASSISTANT", payload={"assistant_action_id": "other-action"})
        self.assertIn(own.pk, self.ids())
        self.assertNotIn(other.pk, self.ids())

    def test_shared_location_metadata_remains_visible_without_private_project_payloads(self):
        location = Location.objects.create(name="Shared freezer", kind="freezer")
        shared = self.event("Location", location, "VISIBLE_LOCATION")
        private = self.event("Location", location, "PRIVATE_LOCATION_CONTEXT", payload={"project_id": self.private.pk})
        self.assertIn(shared.pk, self.ids())
        self.assertNotIn(private.pk, self.ids())

    def test_sop_drafts_are_not_exposed_as_audit_payloads(self):
        document = SOPDocument.objects.create(document_code="AUDIT-SOP", title="Private draft", project=self.project, uploaded_by=self.other, approved=False)
        row = self.event("SOPDocument", document, "PRIVATE_SOP_DRAFT")
        self.assertNotIn(row.pk, self.ids())
        document.approved = True
        document.save()
        self.assertIn(row.pk, self.ids())

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=True)
    def test_disabled_optional_modules_do_not_leak_through_audit(self):
        notebook = Notebook.objects.create(name="Disabled notes", owner=self.tech)
        row = self.event("notebook", notebook, "DISABLED_NOTEBOOK")
        settings = SystemSettings.load()
        settings.notebook_enabled = False
        settings.save()
        self.assertNotIn(row.pk, self.ids())
        settings.notebook_enabled = True
        settings.save()
        self.assertIn(row.pk, self.ids())

    def test_admin_project_members_see_the_full_project_log_and_exports_remain_admin_only(self):
        self.project.members.add(self.admin)
        self.private.members.add(self.admin)
        self.client.force_authenticate(self.admin)
        self.assertEqual(len(self.ids()), len(self.allowed) + len(self.denied))
        exported = self.client.get("/api/events/export-json/")
        self.assertEqual(len(exported.json()), len(self.allowed) + len(self.denied))
        self.assertEqual(self.client.get("/api/events/export-csv/").status_code, 200)
        for user in [self.tech, self.viewer]:
            self.client.force_authenticate(user)
            for output in ["csv", "json"]:
                self.assertEqual(self.client.get(f"/api/events/export-{output}/").status_code, 403)

    def test_unauthenticated_clients_cannot_read_any_audit_surface(self):
        self.client.force_authenticate(None)
        for url in ["/api/events/", "/api/events/summary/", f"/api/events/{self.allowed['Sample'].pk}/", "/api/events/export-json/"]:
            self.assertIn(self.client.get(url).status_code, [401, 403])

    def test_access_checks_do_not_add_a_query_per_event(self):
        with CaptureQueriesContext(connection) as small:
            self.ids()
        sample = self.entities["allowed"]["Sample"]
        Event.objects.bulk_create([Event(entity_type="Sample", entity_id=str(sample.pk), action="VISIBLE_MORE") for _ in range(70)])
        with CaptureQueriesContext(connection) as large:
            self.ids()
        self.assertLessEqual(len(large), len(small) + 2)
        summary = self.client.get("/api/events/summary/").data
        self.assertEqual(len(summary["actions"]), len(set(summary["actions"])))
        self.assertEqual(len(summary["entity_types"]), len(set(summary["entity_types"])))
