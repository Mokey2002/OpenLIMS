from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from custom_fields.models import SampleForm
from custom_fields.forms import validate_fields, validate_values
from samples.models import Sample
from samples.serializers import SampleSerializer

FIELD = {"key": "concentration", "en": "Concentration", "es": "Concentración", "type": "number", "required": True, "unit": "ng/µL"}


class SampleFormTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(username="admin", is_superuser=True)
        self.tech = get_user_model().objects.create_user(username="tech")
        self.tech.groups.add(Group.objects.get_or_create(name="tech")[0])
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.form = SampleForm.objects.create(code="DNA", name_en="DNA", name_es="ADN", fields=[FIELD])

    def publish(self):
        return self.client.post(f"/api/sample-forms/{self.form.pk}/publish/")

    def test_permission_boundary(self):
        self.client.force_authenticate(self.tech)
        self.assertEqual(self.client.get("/api/sample-forms/").data, [])
        self.assertEqual(self.publish().status_code, 403)
        self.assertEqual(self.client.post("/api/sample-forms/", {}, format="json").status_code, 403)

    def test_published_version_immutable_and_no_delete(self):
        self.assertEqual(self.publish().status_code, 200)
        response = self.client.patch(f"/api/sample-forms/{self.form.pk}/", {"fields": []}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.delete(f"/api/sample-forms/{self.form.pk}/").status_code, 405)

    def test_required_and_wrong_types_rejected(self):
        self.publish()
        for values in ({}, {"concentration": True}, {"concentration": "10"}, {"unexpected": 4}):
            serializer = SampleSerializer(data={"sample_id": "S1", "sample_type": "DNA", "form_values": values})
            self.assertFalse(serializer.is_valid(), values)

    def test_existing_sample_keeps_schema_after_new_version(self):
        self.publish()
        sample = Sample.objects.create(sample_id="S1", sample_type="DNA", form_values={"concentration": 0})
        SampleForm.objects.create(code="DNA", name_en="DNA", name_es="ADN", fields=[], published=True)
        serializer = SampleSerializer(sample, data={"form_values": {"concentration": 5}}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        sample.refresh_from_db()
        self.assertEqual(sample.form_schema["version"], self.form.pk)
        self.assertEqual(sample.form_values["concentration"], 5)

    def test_archive_blocks_new_samples_without_erasing_history(self):
        self.publish()
        sample = Sample.objects.create(sample_id="S1", sample_type="DNA", form_values={"concentration": 2})
        self.client.post(f"/api/sample-forms/{self.form.pk}/archive/")
        with self.assertRaises(ValidationError):
            Sample.objects.create(sample_id="S2", sample_type="DNA", form_values={"concentration": 2})
        sample.save()
        self.assertEqual(sample.form_values["concentration"], 2)

    def test_archiving_latest_does_not_revive_older(self):
        self.publish()
        SampleForm.objects.create(code="DNA", name_en="DNA", name_es="ADN", fields=[], published=True, archived=True)
        self.assertEqual(self.client.get("/api/sample-forms/?active=1").data, [])

    def test_direct_orm_cannot_bypass_required_fields(self):
        self.publish()
        with self.assertRaises(ValidationError):
            Sample.objects.create(sample_id="S1", sample_type="DNA")

    def test_legacy_samples_remain_editable(self):
        sample = Sample.objects.create(sample_id="S1", sample_type="DNA")
        self.publish()
        serializer = SampleSerializer(sample, data={"status": "IN_PROGRESS"}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        self.assertEqual(sample.form_schema, {})

    def test_duplicate_keys_and_missing_translations_rejected(self):
        for fields in ([FIELD, FIELD], [{**FIELD, "es": ""}], [{**FIELD, "required": "yes"}], "invalid"):
            with self.assertRaises(ValidationError):
                validate_fields(fields)

    def test_false_boolean_is_valid_required_value(self):
        validate_values({"fields": [{**FIELD, "type": "boolean"}]}, {"concentration": False})

    def test_invalid_dates_and_nonfinite_numbers(self):
        for kind, value in [("date", "2026-02-30"), ("number", float("inf")), ("number", float("nan"))]:
            with self.assertRaises(ValidationError):
                validate_values({"fields": [{**FIELD, "type": kind}]}, {"concentration": value})

    def test_publish_audited(self):
        from events.models import Event
        self.publish()
        self.assertTrue(Event.objects.filter(entity_type="SampleForm", entity_id=str(self.form.pk), action="FORM_PUBLISHED", actor=self.admin).exists())

    def test_intake_api_ignores_forged_schema_and_checks_required(self):
        self.publish()
        self.client.force_authenticate(self.tech)
        payload = {"sample_id": "S1", "sample_type": "DNA", "form_schema": {}, "form_values": {}}
        self.assertEqual(self.client.post("/api/samples/", payload, format="json").status_code, 400)
        payload["form_values"] = {"concentration": 15}
        response = self.client.post("/api/samples/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["form_schema"]["version"], self.form.pk)

    def test_change_legacy_type_to_configured_type_validates(self):
        sample = Sample.objects.create(sample_id="S1")
        self.publish()
        serializer = SampleSerializer(sample, data={"sample_type": "DNA"}, partial=True)
        self.assertFalse(serializer.is_valid())
