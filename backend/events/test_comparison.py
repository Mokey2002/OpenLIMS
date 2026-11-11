from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIClient

from events.comparison import field_changes
from events.models import Event
from events.serializers import EventSerializer
from inventory.models import Container, Location
from notebook.models import Notebook, Experiment
from notebook.services import create_revision
from projects.models import Project
from results.models import WorkItem
from samples.models import Sample

User = get_user_model()


class AuditComparisonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("comparison-director", password=None)
        cls.reader = User.objects.create_user("comparison-reader", password=None)
        cls.reader.groups.add(Group.objects.get_or_create(name="tech")[0])
        cls.project = Project.objects.create(code="DIFF", name="Protein comparisons")
        cls.project.members.add(cls.reader, cls.admin)
        cls.first = Location.objects.create(name="Freezer A", kind="FREEZER")
        cls.second = Location.objects.create(name="Freezer B", kind="FREEZER")
        cls.box_a = Container.objects.create(container_id="BOX-A", kind="BOX", location=cls.first)
        cls.box_b = Container.objects.create(container_id="BOX-B", kind="BOX", location=cls.second)
        cls.sample = Sample.objects.create(sample_id="PROTEIN-DIFF", project=cls.project, container=cls.box_a, created_by=cls.admin)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_reference_names_come_from_snapshots_without_database_lookups(self):
        event = Event(entity_type="Container", entity_id="1", action="CONTAINER_UPDATED", payload={
            "before": {"location": 1, "location_name": "Freezer A"},
            "after": {"location": 2, "location_name": "Freezer B"}})
        with self.assertNumQueries(0):
            data = EventSerializer(event).data
        self.assertEqual(len(data["field_changes"]), 1)
        change = data["field_changes"][0]
        self.assertEqual((change["label"], change["before"], change["after"]), ("Location", "Freezer A", "Freezer B"))
        self.assertEqual(event.payload["before"]["location"], 1)

    def test_missing_historical_names_are_explicit_and_raw_identifiers_remain(self):
        event = Event(entity_type="Sample", action="UPDATED", payload={"before": {"container_id": 13}, "after": {"container_id": 14}})
        changes = field_changes(event)
        self.assertTrue(changes[0]["historical_name_missing"])
        self.assertEqual(changes[0]["before"], "Historical name not recorded")
        self.assertEqual(EventSerializer(event).data["payload"]["before"]["container_id"], 13)

    def test_missing_null_false_and_real_numeric_values_are_distinct(self):
        event = Event(payload={"before": {"value": None, "approved": False, "quantity": 0},
                               "after": {"approved": True, "quantity": 2, "note": ""}})
        changes = {row["field"]: row for row in field_changes(event)}
        self.assertTrue(changes["value"]["before_present"])
        self.assertFalse(changes["value"]["after_present"])
        self.assertFalse(changes["approved"]["before"])
        self.assertEqual(changes["quantity"]["after"], 2)
        self.assertFalse(changes["note"]["before_present"])

    def test_malformed_legacy_snapshots_and_unknown_field_names_are_safe(self):
        for payload in [[], "old", {"before": [], "after": 5}, {"changed_fields": [None, {}, "status"], "before": {}, "after": {"status": "READY"}}]:
            self.assertIsInstance(field_changes(Event(payload=payload)), list)

    def test_sample_storage_patch_preserves_one_action_and_historical_location_names(self):
        last = Event.objects.latest("pk").pk
        response = self.client.patch(f"/api/samples/{self.sample.pk}/", {"container": self.box_b.pk}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        event = Event.objects.filter(pk__gt=last).get()
        self.assertEqual(event.action, "CONTAINER_ASSIGNED")
        self.assertEqual(event.payload["changed_fields"], ["container_id"])
        self.first.name = "Renamed after transfer"
        self.first.save()
        changes = {row["field"]: row for row in self.client.get(f"/api/events/{event.pk}/").data["field_changes"]}
        self.assertEqual((changes["container_id"]["before"], changes["container_id"]["after"]), ("BOX-A", "BOX-B"))
        self.assertEqual((changes["location"]["before"], changes["location"]["after"]), ("Freezer A", "Freezer B"))

    def test_assignment_records_capture_both_usernames(self):
        work = WorkItem.objects.create(sample=self.sample, name="Protein QC", assigned_to=self.admin)
        response = self.client.patch(f"/api/work-items/{work.pk}/", {"assigned_to": self.reader.pk}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        event = Event.objects.get(action="WORK_ITEM_REASSIGNED")
        change = field_changes(event)[0]
        self.assertEqual((change["before"], change["after"]), (self.admin.username, self.reader.username))

    def revisions(self):
        notebook = Notebook.objects.create(name="Private protein notebook", owner=self.admin)
        experiment = Experiment.objects.create(notebook=notebook, title="Protein storage protocol", created_by=self.admin)
        first, _ = create_revision(experiment=experiment, actor=self.admin, blocks=[{"block_type": "RICH_TEXT", "data": {"text": "Store protein at 4 C."}}], links=[])
        second, _ = create_revision(experiment=experiment, actor=self.admin, blocks=[{"block_type": "RICH_TEXT", "data": {"text": "Store protein at -20 C."}}], links=[])
        return experiment, first, second

    def test_revision_comparison_returns_exact_immutable_text_without_writing_history(self):
        experiment, first, second = self.revisions()
        event = Event.objects.get(entity_id=str(experiment.public_id), action="EXPERIMENT_REVISION_CREATED", payload__after__revision=2)
        count = Event.objects.count()
        response = self.client.get(f"/api/events/{event.pk}/comparison/")
        self.assertEqual(response.status_code, 200, response.data)
        comparison = response.data["revision_comparison"]
        self.assertEqual(comparison["before"]["public_id"], str(first.public_id))
        self.assertEqual(comparison["after"]["public_id"], str(second.public_id))
        self.assertEqual(comparison["block_changes"][0]["before"]["data"]["text"], "Store protein at 4 C.")
        self.assertEqual(Event.objects.count(), count)
        self.assertEqual(experiment.revisions.count(), 2)

    def test_initial_revision_compares_to_empty_content(self):
        experiment, _, _ = self.revisions()
        event = Event.objects.get(entity_id=str(experiment.public_id), payload__after__revision=1)
        response = self.client.get(f"/api/events/{event.pk}/comparison/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["revision_comparison"]["before"]["number"], 0)
        self.assertEqual(response.data["revision_comparison"]["block_changes"][0]["change"], "added")

    def test_private_revision_comparisons_and_revoked_memberships_are_not_exposed(self):
        experiment, _, _ = self.revisions()
        event = Event.objects.filter(entity_id=str(experiment.public_id)).first()
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get(f"/api/events/{event.pk}/comparison/").status_code, 404)
        sample_event = Event.objects.get(action="CREATED", entity_id=str(self.sample.pk))
        self.assertEqual(self.client.get(f"/api/events/{sample_event.pk}/comparison/").status_code, 200)
        self.project.members.remove(self.reader)
        self.assertEqual(self.client.get(f"/api/events/{sample_event.pk}/comparison/").status_code, 404)
