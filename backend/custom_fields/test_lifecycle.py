import csv
import io
import json
from django.test import TestCase
from rest_framework.exceptions import ValidationError
from .test_forms import SampleFormTests, FIELD
from .forms import validate_fields, validate_values
from .models import SampleForm
from samples.models import Sample
from events.models import Event


class SampleLifecycleTests(TestCase):
    setUp = SampleFormTests.setUp
    publish = SampleFormTests.publish

    def csv(self, rows):
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["sample_id", "sample_type", "form_values"])
        for code, values in rows:
            writer.writerow([code, "DNA", json.dumps(values)])
        return stream.getvalue()

    def test_preview_then_atomic_confirm(self):
        self.publish()
        payload = {"csv": self.csv([("S1", {"concentration": 5}), ("S2", {"concentration": 6})])}
        preview = self.client.post("/api/samples/import-configured/", payload, format="json")
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(Sample.objects.count(), 0)
        payload.update(confirm=True, preview_token=preview.data["preview_token"])
        response = self.client.post("/api/samples/import-configured/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Sample.objects.count(), 2)
        self.assertEqual(self.client.post("/api/samples/import-configured/", payload, format="json").status_code, 400)
        self.assertEqual(Sample.objects.count(), 2)

    def test_invalid_batch_creates_nothing(self):
        self.publish()
        response = self.client.post("/api/samples/import-configured/", {"csv": self.csv([("S1", {"concentration": 5}), ("S2", {})]), "confirm": True}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Sample.objects.count(), 0)

    def test_changed_configuration_requires_new_preview(self):
        self.publish()
        payload = {"csv": self.csv([("S1", {"concentration": 5})])}
        preview = self.client.post("/api/samples/import-configured/", payload, format="json")
        SampleForm.objects.create(code="DNA", name_en="DNA", name_es="ADN", fields=[FIELD], published=True)
        payload.update(confirm=True, preview_token=preview.data["preview_token"])
        self.assertEqual(self.client.post("/api/samples/import-configured/", payload, format="json").status_code, 400)
        self.assertFalse(Sample.objects.exists())

    def test_export_preserves_values_and_schema(self):
        self.publish()
        sample = Sample.objects.create(sample_id="S1", sample_type="DNA", form_values={"concentration": 1.5})
        response = self.client.post("/api/samples/export-selected/", {"ids": [sample.id]}, format="json")
        row = next(csv.DictReader(io.StringIO(response.content.decode())))
        self.assertEqual(json.loads(row["form_values"]), sample.form_values)
        self.assertEqual(json.loads(row["form_schema"]), sample.form_schema)

    def test_edit_requires_reason_and_original_values(self):
        self.publish()
        sample = Sample.objects.create(sample_id="S1", sample_type="DNA", form_values={"concentration": 1})
        url = f"/api/samples/{sample.pk}/"
        payload = {"form_values": {"concentration": 2}}
        self.assertEqual(self.client.patch(url, payload, format="json").status_code, 400)
        payload["form_values_before"] = {"concentration": 1}
        self.assertEqual(self.client.patch(url, payload, format="json").status_code, 400)
        payload["reason"] = "Corrected instrument reading"
        response = self.client.patch(url, payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        event = Event.objects.filter(entity_type="Sample", entity_id=str(sample.pk), action="UPDATED").latest("id")
        self.assertEqual(event.payload["reason"], payload["reason"])
        payload["form_values"] = {"concentration": 3}
        self.assertEqual(self.client.patch(url, payload, format="json").status_code, 400)

    def test_dropdown_and_bounds(self):
        choice = {**FIELD, "type": "select", "choices": ["A", "B"]}
        validate_fields([choice])
        validate_values({"fields": [choice]}, {"concentration": "A"})
        with self.assertRaises(ValidationError):
            validate_values({"fields": [choice]}, {"concentration": "C"})
        numeric = {**FIELD, "min": 0, "max": 10}
        validate_fields([numeric])
        for value in (-1, 11):
            with self.assertRaises(ValidationError):
                validate_values({"fields": [numeric]}, {"concentration": value})

    def test_conditions_enforce_visibility_and_required(self):
        parent = {**FIELD, "key": "extracted", "type": "boolean"}
        child = {**FIELD, "show_if": {"key": "extracted", "equals": True}}
        schema = {"fields": [parent, child]}
        validate_fields(schema["fields"])
        validate_values(schema, {"extracted": False})
        with self.assertRaises(ValidationError):
            validate_values(schema, {"extracted": True})
        with self.assertRaises(ValidationError):
            validate_values(schema, {"extracted": False, "concentration": 10})
        with self.assertRaises(ValidationError):
            validate_fields([child, parent])

    def test_publication_comparison(self):
        self.publish()
        draft = SampleForm.objects.create(code="DNA", name_en="DNA", name_es="ADN", fields=[{**FIELD, "min": 0}])
        response = self.client.get(f"/api/sample-forms/{draft.pk}/publish-preview/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["changed"], ["concentration"])

    def test_publication_rejects_stale_review(self):
        response = self.client.get(f"/api/sample-forms/{self.form.pk}/publish-preview/")
        self.form.fields = [{**FIELD, "min": 0}]
        self.form.save()
        result = self.client.post(f"/api/sample-forms/{self.form.pk}/publish/", {"review_token": response.data["review_token"]}, format="json")
        self.assertEqual(result.status_code, 400)

    def test_viewer_cannot_import_or_edit(self):
        from django.contrib.auth.models import Group
        self.tech.groups.clear()
        self.tech.groups.add(Group.objects.get_or_create(name="viewer")[0])
        self.client.force_authenticate(self.tech)
        self.assertEqual(self.client.post("/api/samples/import-configured/", {"csv": self.csv([])}, format="json").status_code, 403)

    def test_no_commit_without_preview_token(self):
        self.publish()
        response = self.client.post("/api/samples/import-configured/", {"csv": self.csv([("S1", {"concentration": 1})]), "confirm": True}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Sample.objects.exists())
