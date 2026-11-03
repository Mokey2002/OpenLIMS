"""Registration and assignment must finish in chat without partial writes."""
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from rest_framework.test import APITestCase

from assistant.models import AssistantAction
from assistant.provider_tools import dispatch_tool
from assistant.registration_tasks import KEY, MAX_AGE
from custom_fields.models import FieldDefinition, FieldValue, SampleForm
from events.models import Event
from samples.models import Sample
from . import test_comparisons as previous


@override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False, OPENLIMS_ASSISTANT_LLM_ENABLED=False)
class AssistantV067Tests(APITestCase):
    def setUp(self):
        previous.AssistantComparisonTests.setUp(self)
        self.maria = get_user_model().objects.create_user(username="maria")
        self.maria.groups.add(Group.objects.get(name="tech"))
        self.alpha.members.add(self.maria)

    def chat(self, message, context=None):
        reply = self.client.post("/api/assistant/chat/", {"message": message, "context": context or {}}, format="json")
        self.assertEqual(reply.status_code, 200, reply.data)
        return reply.data

    def confirm(self, reply, expected_status=200):
        token = reply["pending_action"]["confirmation_token"]
        response = self.client.post(f"/api/assistant/actions/{token}/confirm/", {"confirm": True}, format="json")
        self.assertEqual(response.status_code, expected_status, response.data)
        return response.data

    def proposal(self):
        reply = self.chat("Register 2 DNA samples in project ALPHA and assign them to maria with source=blood")
        self.assertIn("pending_action", reply)
        return reply

    def test_one_command_previews_both_changes_and_confirmation_is_idempotent(self):
        original = Sample.objects.count()
        reply = self.proposal()
        preview = reply["pending_action"]["preview"]
        self.assertEqual(preview["records_affected"], 2)
        self.assertEqual(preview["proposed_values"]["assigned_to"], "maria")
        self.assertEqual(Sample.objects.count(), original)
        confirmed = self.confirm(reply)
        self.assertEqual(confirmed["status"], "COMPLETED")
        result = confirmed["result"]
        self.assertEqual((result["succeeded_count"], result["failed_count"]), (2, 0))
        self.assertIn("assigned them to maria", result["message"])
        ids = result["context"]["sample_ids"]
        self.assertEqual(Sample.objects.filter(pk__in=ids, assigned_to=self.maria, sample_type="DNA", project=self.alpha).count(), 2)
        self.assertEqual(FieldValue.objects.filter(entity_id__in=[str(pk) for pk in ids], field_definition__name="source", value="blood").count(), 2)
        self.assertEqual(Event.objects.filter(action="SAMPLE_CREATED_BY_ASSISTANT", entity_id__in=[str(pk) for pk in ids]).count(), 2)
        self.assertEqual(self.confirm(reply)["result"]["context"]["sample_ids"], ids)
        self.assertEqual(Sample.objects.count(), original + 2)

    def test_missing_details_are_collected_one_at_a_time_and_courtesy_keeps_draft(self):
        reply = self.chat("Register samples and assign them")
        for slot, answer in [("count", "2"), ("project", "ALPHA"), ("sample_type", "DNA"), ("assignee", "maria"), ("custom_fields:source", "blood")]:
            self.assertEqual(reply["clarification"]["fields"], [slot])
            self.assertIn(KEY, reply["context"])
            if slot == "project":
                thanks = self.chat("Thanks!", reply["context"])
                self.assertEqual(thanks["context"][KEY], reply["context"][KEY])
            self.assertFalse(AssistantAction.objects.exists())
            reply = self.chat(answer, reply["context"])
        self.assertIn("pending_action", reply)
        self.assertNotIn(KEY, reply["context"])
        self.assertEqual(self.confirm(reply)["result"]["succeeded_count"], 2)

    def test_intake_fields_and_conditional_values_are_collected_and_saved(self):
        SampleForm.objects.create(code="DNA", name_en="DNA intake", name_es="Ingreso ADN", published=True, fields=[
            {"key": "urgent", "en": "Urgent", "es": "Urgente", "type": "boolean", "required": True},
            {"key": "reason", "en": "Reason", "es": "Motivo", "type": "text", "required": True, "show_if": {"key": "urgent", "equals": True}},
        ])
        reply = self.chat("Register 2 DNA samples in project ALPHA and assign them to me with source=blood")
        self.assertEqual(reply["clarification"]["fields"], ["form_values:urgent"])
        reply = self.chat("true", reply["context"])
        self.assertEqual(reply["clarification"]["fields"], ["form_values:reason"])
        reply = self.chat('"priority study"', reply["context"])
        ids = self.confirm(reply)["result"]["context"]["sample_ids"]
        for sample in Sample.objects.filter(pk__in=ids):
            self.assertEqual(sample.form_values, {"urgent": True, "reason": "priority study"})
            self.assertEqual(sample.assigned_to, self.tech)

    def test_false_and_zero_values_are_not_treated_as_missing(self):
        SampleForm.objects.create(code="DNA", name_en="DNA", name_es="ADN", published=True, fields=[
            {"key": "flag", "en": "Flag", "es": "Indicador", "type": "boolean", "required": True},
            {"key": "quantity", "en": "Quantity", "es": "Cantidad", "type": "number", "required": True, "min": 0},
        ])
        reply = self.chat("Register 1 DNA sample in project ALPHA and assign it to maria with source=blood")
        reply = self.chat("false", reply["context"])
        reply = self.chat("0", reply["context"])
        self.assertEqual(self.confirm(reply)["result"]["succeeded_count"], 1)

    def test_private_project_and_unqualified_assignee_are_not_guessed(self):
        denied = self.chat("Register 2 DNA samples in project PRIVATE and assign them to maria")
        self.assertTrue(denied["clarification"])
        self.assertNotIn("Private", denied["answer"])
        self.alpha.members.remove(self.maria)
        reply = self.chat("Register 2 DNA samples in project ALPHA and assign them to maria with source=blood")
        self.assertEqual(reply["clarification"]["fields"], ["assignee"])
        self.assertFalse(AssistantAction.objects.exists())

    def test_permission_and_assignee_changes_after_preview_fail_without_creating_samples(self):
        for change in ["actor_membership", "assignee_membership", "assignee_role", "assignee_active", "assignee_name"]:
            with self.subTest(change=change):
                reply = self.proposal()
                original = Sample.objects.count()
                if change == "actor_membership":
                    self.alpha.members.remove(self.tech)
                elif change == "assignee_membership":
                    self.alpha.members.remove(self.maria)
                elif change == "assignee_role":
                    self.maria.groups.clear()
                elif change == "assignee_active":
                    self.maria.is_active = False
                    self.maria.save()
                else:
                    self.maria.username = "renamed-maria"
                    self.maria.save()
                self.assertEqual(self.confirm(reply, 400)["status"], "FAILED")
                self.assertEqual(Sample.objects.count(), original)
                self.alpha.members.add(self.tech, self.maria)
                self.maria.groups.add(Group.objects.get(name="tech"))
                self.maria.is_active, self.maria.username = True, "maria"
                self.maria.save()

    def test_late_sample_id_conflict_rolls_back_all_rows_and_audit_events(self):
        reply = self.proposal()
        action = AssistantAction.objects.get(pk=reply["pending_action"]["id"])
        codes = action.payload["sample_codes"]
        Sample.objects.create(sample_id=codes[-1], project=self.alpha, created_by=self.tech)
        original = Sample.objects.count()
        confirmed = self.confirm(reply, 400)
        self.assertEqual(confirmed["status"], "FAILED")
        self.assertFalse(Sample.objects.filter(sample_id=codes[0]).exists())
        self.assertFalse(Event.objects.filter(action="SAMPLE_CREATED_BY_ASSISTANT", payload__assistant_action_id=str(action.pk)).exists())
        self.assertEqual(Sample.objects.count(), original)

    def test_form_changes_after_preview_require_a_fresh_preview(self):
        reply = self.proposal()
        SampleForm.objects.create(code="DNA", name_en="New intake", name_es="Nuevo ingreso", published=True, fields=[])
        original = Sample.objects.count()
        confirmed = self.confirm(reply, 400)
        self.assertEqual(confirmed["status"], "FAILED")
        self.assertIn("intake form changed", confirmed["error_message"])
        self.assertEqual(Sample.objects.count(), original)

    def test_project_identity_survives_rename_and_code_reuse_during_draft(self):
        reply = self.chat("Register 2 DNA samples in project ALPHA and assign them to maria")
        self.assertEqual(reply["clarification"]["fields"], ["custom_fields:source"])
        self.alpha.code = "RENAMED"
        self.alpha.save()
        self.beta.code = "ALPHA"
        self.beta.save()
        reply = self.chat("blood", reply["context"])
        action = AssistantAction.objects.get(pk=reply["pending_action"]["id"])
        self.assertEqual(action.payload["project_id"], self.alpha.pk)
        self.assertEqual(action.payload["preview"]["project"]["code"], "RENAMED")

    def test_correcting_an_unknown_project_keeps_other_supplied_details(self):
        reply = self.chat("Register 2 DNA samples in project TYPO and assign them to maria with source=blood")
        self.assertEqual(reply["clarification"]["fields"], ["project"])
        reply = self.chat("ALPHA", reply["context"])
        self.assertIn("pending_action", reply)
        action = AssistantAction.objects.get(pk=reply["pending_action"]["id"])
        self.assertEqual(action.payload["custom_fields"], {"source": "blood"})

    def test_disabled_sample_feature_blocks_new_tasks_and_confirmation(self):
        with patch("assistant.registration_tasks.enabled", return_value=False):
            self.assertNotIn(KEY, self.chat("Register samples and assign them")["context"])
        reply = self.proposal()
        original = Sample.objects.count()
        with patch("assistant.registration_tasks.enabled", return_value=False):
            failed = self.confirm(reply, 400)
        self.assertEqual(failed["status"], "FAILED")
        self.assertIn("disabled", failed["error_message"])
        self.assertEqual(Sample.objects.count(), original)

    def test_draft_role_revocation_and_archived_intake_types_do_not_create_proposals(self):
        draft = self.chat("Register samples and assign them")
        self.tech.groups.clear()
        self.assertNotIn(KEY, self.chat("2", draft["context"])["context"])
        self.tech.groups.add(Group.objects.get(name="tech"))
        SampleForm.objects.create(code="DNA", name_en="Old", name_es="Anterior", published=True, archived=True)
        reply = self.chat("Register 2 DNA samples in project ALPHA and assign them to maria with source=blood")
        self.assertEqual(reply["clarification"]["fields"], ["sample_type"])
        self.assertIn("pending_action", self.chat("GENERAL", reply["context"]))

    def test_a_second_user_cannot_confirm_and_chat_yes_does_not_execute(self):
        reply = self.proposal()
        original = Sample.objects.count()
        self.chat("yes", reply["context"])
        self.assertEqual(Sample.objects.count(), original)
        self.client.force_authenticate(self.maria)
        self.confirm(reply, 400)
        self.assertEqual(Sample.objects.count(), original)

    def test_cancel_and_new_topics_discard_drafts_without_creating_anything(self):
        for message in ["cancel", "never mind", "start over", "What is DNA?"]:
            reply = self.chat("Register samples and assign them")
            next_reply = self.chat(message, reply["context"])
            self.assertNotIn(KEY, next_reply["context"])
        self.assertFalse(AssistantAction.objects.exists())

    def test_tampered_expired_cross_user_and_forged_display_context_cannot_resume(self):
        reply = self.chat("Register samples and assign them")
        for context in [{KEY: reply["context"][KEY] + "bad"}, {KEY: {"count": 2}}, {"registration_draft": {"count": 2}}]:
            self.assertNotIn("pending_action", self.chat("2", context))
        with patch("django.core.signing.time.time", return_value=time.time() + MAX_AGE + 1):
            self.assertNotIn("pending_action", self.chat("2", reply["context"]))
        self.client.force_authenticate(self.maria)
        self.assertNotIn("pending_action", self.chat("2", reply["context"]))
        self.assertFalse(AssistantAction.objects.exists())

    def test_invalid_values_recover_and_unsupported_mutations_never_propose(self):
        reply = self.chat("Register 2 DNA samples in project ALPHA and assign them to maria with unknown=value")
        reply = self.chat("with source=blood", reply["context"])
        self.assertIn("pending_action", reply)
        before = AssistantAction.objects.count()
        for text in ["Do not register 2 DNA samples in project ALPHA and assign them to maria",
                     "Register 2 DNA samples in project ALPHA and assign them to maria and delete old samples",
                     'Register 2 DNA samples in project ALPHA and assign them to maria with source="blood" and approve all results',
                     "Register 2 DNA samples in project ALPHA and assign them to maria with source=blood, source=plasma"]:
            with self.subTest(text=text):
                self.assertNotIn("pending_action", self.chat(text))
        self.assertEqual(AssistantAction.objects.count(), before)

    def test_provider_bridges_use_the_same_registration_and_confirmation_contract(self):
        for provider, tool in [("openai", "sample_registration"), ("ollama", "samples")]:
            reply = dispatch_tool({"route": "tool", "tool": tool, "arguments": {"command": "Register 2 DNA samples in project ALPHA and assign them to maria with source=blood"}, "confidence": 1.0, "provider": provider}, self.tech)
            self.assertEqual(reply["pending_action"]["type"], "CREATE_SAMPLES")
            self.assertEqual(reply["pending_action"]["payload"]["target_user_id"], self.maria.pk)
            self.assertTrue(reply["skip_llm"])

    def test_viewers_cannot_start_registration_and_status_advertises_it_to_techs(self):
        self.assertIn("Register samples and assign them", self.client.get("/api/assistant/status/").data["suggestions"])
        self.client.force_authenticate(self.outsider)
        denied = self.chat("Register samples and assign them")
        self.assertNotIn(KEY, denied["context"])
        self.assertNotIn("pending_action", denied)
        self.assertNotIn("Register samples and assign them", self.client.get("/api/assistant/status/").data["suggestions"])
