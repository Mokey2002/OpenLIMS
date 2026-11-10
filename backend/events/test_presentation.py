import csv
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from rest_framework.test import APITestCase

from events.models import Event
from events.serializers import EventSerializer
from notebook.models import Experiment, Notebook


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
class AuditPresentationTests(APITestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("readable-audit-owner", password=None)
        self.client.force_authenticate(self.admin)

    def event(self, **changes):
        return Event.objects.create(entity_type="Location", entity_id="18", action="LOCATION_CREATED",
            actor=self.admin, payload={"name": "Protein freezer", "code": "FZ-PROTEIN"}, **changes)

    def test_legacy_location_container_and_experiment_snapshots_are_readable(self):
        location = self.event()
        container = Event.objects.create(entity_type="Container", entity_id="13", action="CONTAINER_CREATED",
            payload={"container_id": "Protein box A"})
        experiment = Event.objects.create(entity_type="experiment", entity_id="83f882c1-1f5f-4d23-8a38-29461020d7f8",
            action="EXPERIMENT_REVISION_CREATED", payload={"entity": {"label": "Protein stability study"},
                "before": {"revision": 3}, "after": {"revision": 4}, "reason": "Notebook autosave"})
        rows = {row["id"]: row for row in self.client.get("/api/events/").data["results"]}
        self.assertEqual(rows[location.pk]["entity_label"], "Protein freezer")
        self.assertEqual(rows[container.pk]["entity_label"], "Protein box A")
        self.assertEqual(rows[experiment.pk]["entity_label"], "Protein stability study")
        self.assertEqual(rows[experiment.pk]["action_label"], "Experiment saved")
        self.assertEqual(rows[experiment.pk]["description"], "Revision 3 → 4")
        self.assertEqual(rows[experiment.pk]["source"], "Notebook autosave")
        self.assertEqual(rows[experiment.pk]["entity_id"], str(experiment.entity_id))

    def test_missing_names_and_malformed_historical_payloads_do_not_crash(self):
        for payload in [[], "legacy", {}, {"reason": []}, {"entity": [], "before": [], "after": {"revision": True}},
                        {"changed_fields": [None, {}, "status"], "before": {}, "after": {"status": "COMPLETE"}}]:
            event = Event.objects.create(entity_type="UnknownRecord", entity_id="unresolved-identifier", action="OLD_ACTION", payload=payload)
            response = self.client.get(f"/api/events/{event.pk}/")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertNotIn("unresolved-identifier", response.data["entity_label"])
            self.assertEqual(response.data["action_label"], "Old action")

    def test_labels_do_not_bypass_private_notebook_authorization(self):
        book = Notebook.objects.create(name="Private notebook", owner=self.admin)
        experiment = Experiment.objects.create(notebook=book, title="Private protein study", created_by=self.admin)
        event = Event.objects.create(entity_type="experiment", entity_id=str(experiment.public_id), action="EXPERIMENT_REVISION_CREATED",
            payload={"entity": {"type": "experiment", "public_id": str(experiment.public_id), "label": experiment.title}})
        outsider = get_user_model().objects.create_user("unrelated-reader")
        outsider.groups.add(Group.objects.get_or_create(name="viewer")[0])
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get("/api/events/").data["count"], 0)
        self.assertEqual(self.client.get(f"/api/events/{event.pk}/").status_code, 404)

    def test_csv_and_json_append_readable_fields_while_preserving_raw_records(self):
        event = self.event()
        csv_result = self.client.get("/api/events/export-csv/")
        row = next(csv.DictReader(StringIO(csv_result.content.decode())))
        self.assertEqual(row["entity_id"], "18")
        self.assertEqual(row["action"], "LOCATION_CREATED")
        self.assertEqual(row["entity_label"], "Protein freezer")
        exported = self.client.get("/api/events/export-json/").json()[0]
        self.assertEqual(exported["id"], event.pk)
        self.assertEqual(exported["payload"], event.payload)
        self.assertEqual(exported["action_label"], "Location created")

    def test_snapshot_names_are_escaped_as_text_in_spreadsheet_exports(self):
        Event.objects.create(entity_type="Location", entity_id="1", action="LOCATION_CREATED", payload={"name": "=1+1"})
        row = next(csv.DictReader(StringIO(self.client.get("/api/events/export-csv/").content.decode())))
        self.assertEqual(row["entity_label"], "'=1+1")
        self.assertEqual(self.client.get("/api/events/").data["results"][0]["entity_label"], "=1+1")

    def test_readable_fields_do_not_add_per_event_database_queries(self):
        for _ in range(5):
            self.event()
        with self.assertNumQueries(1):
            rows = EventSerializer(Event.objects.select_related("actor").all(), many=True).data
            self.assertEqual(len(rows), 5)
