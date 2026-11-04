"""Natural multi-turn regressions found in the v0.70 conversation review."""
import json
from unittest.mock import patch

from django.test import override_settings
from rest_framework.test import APITestCase

from assistant.context_state import sanitize_context
from assistant.models import AssistantAction, GeneratedArtifact
from assistant.tests import test_comparisons


@override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=False, OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
class ConversationFluencyTests(APITestCase):
    setUp = test_comparisons.AssistantComparisonTests.setUp

    def chat(self, message, context=None):
        reply = self.client.post('/api/assistant/chat/', {'message': message, 'context': context or {}}, format='json')
        self.assertEqual(reply.status_code, 200, reply.data)
        self.assertNotIn('9999.0', json.dumps(reply.data, default=str))
        return reply.data

    def test_small_talk_help_and_conceptual_explanations(self):
        first = self.chat('hey')
        self.assertIn('Hello', first['answer'])
        self.assertIn('ready to help', self.chat('how are you?', first['context'])['answer'])
        self.assertIn('permission-filtered', self.chat('what can you help me with?')['answer'])
        first = self.chat('Explain the difference between a sample and a work item')
        self.assertEqual(first['context']['lab_concept'], ['sample', 'work_item'])
        self.assertNotIn('comparison', first)
        second = self.chat('Can you give me a simple example?', first['context'])
        self.assertIn('Illustrative example', second['answer'])
        self.assertEqual(second['context'], first['context'])
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_concepts_are_narrow_and_do_not_capture_record_commands(self):
        first = self.chat('What is a work item?')
        second = self.chat('Show me sample S-100', first['context'])
        self.assertNotIn('lab_concept', second['context'])
        self.assertEqual(second['context']['sample_ids'], [self.samples[0].pk])
        for context in [{'lab_concept': {}}, {'lab_concept': [{}]}, {'lab_concept': ['unknown']}, {'lab_concept': ['sample'] * 3}]:
            with self.subTest(context=context):
                reply = self.chat('Give me a simple example', context)
                self.assertNotIn('lab_concept', reply['context'])

    def test_concept_routes_bypass_both_model_providers(self):
        for provider in ['openai', 'ollama']:
            with self.subTest(provider=provider), override_settings(OPENLIMS_ASSISTANT_LLM_ENABLED=True,
                    OPENLIMS_ASSISTANT_LLM_PROVIDER=provider, OPENAI_API_KEY='test-key'), \
                    patch('assistant.views.classify_route_with_llm') as classify, \
                    patch(f'assistant.llm.call_{provider}') as model:
                reply = self.chat('What is the difference between a sample and a result?')
                self.assertIn('lab_concept', reply)
                classify.assert_not_called()
                model.assert_not_called()

    def test_provider_tool_dispatch_supports_concepts_but_not_record_commands(self):
        from assistant.provider_tools import dispatch_tool
        first = self.chat('What is a sample?')
        for provider in ['openai', 'ollama']:
            with self.subTest(provider=provider):
                plan = {'route': 'tool', 'tool': 'lab_concepts', 'confidence': .99, 'provider': provider,
                        'arguments': {'command': 'Give me a simple example'}}
                reply = dispatch_tool(plan, self.tech, first['context'])
                self.assertIn('Illustrative example', reply['answer'])
                self.assertEqual(reply['context']['lab_concept'], ['sample'])
                denied = dispatch_tool({**plan, 'arguments': {'command': 'Delete sample S-100'}}, self.tech)
                self.assertNotIn('pending_action', denied)
                self.assertNotIn('sample_ids', denied['context'])
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_daily_explanation_uses_current_reasons(self):
        first = self.chat('What should I work on today?')
        for text in ['why that one?', 'Why these priorities?', 'explain that more simply']:
            with self.subTest(text=text):
                reply = self.chat(text, first['context'])
                self.assertEqual(reply['context']['daily_work'], first['context']['daily_work'])
                self.assertIn('No deadline', reply['daily_work']['rows'][0]['review'])
                self.assertIn(reply['daily_work']['rows'][0]['reason'], reply['answer'])
                self.assertNotIn('pending_action', reply)

    def test_daily_scope_and_project_filters_survive_natural_wording(self):
        first = self.chat('What should I work on today?')
        second = self.chat('show me the unassigned work instead', first['context'])
        self.assertEqual(second['context']['daily_work']['scope'], 'unassigned')
        third = self.chat('only project ALPHA', second['context'])
        self.assertEqual(third['context']['daily_work']['project'], 'ALPHA')
        self.assertEqual([row['sample'] for row in third['daily_work']['rows']], ['S-101'])
        fourth = self.chat('only the overdue ones', third['context'])
        self.assertEqual(fourth['context']['daily_work']['focus'], 'overdue')
        fifth = self.chat('show me my tasks again', fourth['context'])
        self.assertEqual(fifth['context']['daily_work']['scope'], 'mine')
        self.assertEqual(fifth['context']['daily_work']['project'], 'ALPHA')
        self.assertEqual(fifth['context']['daily_work']['focus'], 'overdue')

    def test_project_overview_to_overdue_work_and_back(self):
        first = self.chat('Hi, could you please give me a quick overview of project ALPHA?')
        second = self.chat('thanks', first['context'])
        third = self.chat('which samples are overdue?', second['context'])
        self.assertEqual(third['context']['project_id'], self.alpha.pk)
        self.assertEqual([row['sample'] for row in third['daily_work']['rows']], ['S-101'])
        fourth = self.chat('only the unassigned ones', third['context'])
        self.assertEqual(fourth['context']['daily_work']['focus'], 'overdue')
        self.assertEqual(fourth['context']['daily_work']['scope'], 'unassigned')
        fifth = self.chat('why are they blocked?', fourth['context'])
        self.assertIn('recorded deadline', fifth['answer'])
        sixth = self.chat('same for BETA', fifth['context'])
        self.assertEqual(sixth['context']['daily_work']['project'], 'BETA')
        seventh = self.chat('go back to ALPHA', sixth['context'])
        self.assertEqual(seventh['context']['project_id'], self.alpha.pk)

    def test_sample_next_step_wording_and_qc_followups(self):
        first = self.chat('show me sample S-100')
        for text in ['what should I do next?', 'what do I need to do next?', "what's blocking it?"]:
            with self.subTest(text=text):
                reply = self.chat(text, first['context'])
                self.assertEqual(reply['context']['sample_id'], self.samples[0].pk)
                self.assertIn('No pipeline', reply['answer'])
        second = self.chat('what do I need to do next?', first['context'])
        third = self.chat('explain that more simply', second['context'])
        fourth = self.chat('no, I meant S-101', third['context'])
        fifth = self.chat('what about its QC?', fourth['context'])
        self.assertEqual(fifth['context']['sample_id'], self.samples[1].pk)
        self.assertIn('sample_explanation', fifth)

    def test_multiple_samples_still_require_disambiguation(self):
        reply = self.chat('what do I need to do next?', {'sample_ids': [s.pk for s in self.samples[:2]]})
        self.assertTrue(reply['clarification']['required'])
        self.assertNotIn('sample_guidance', reply)
        self.assertNotIn('pending_action', reply)

    def test_investigation_failure_evidence_and_followup_chain(self):
        first = self.chat("Investigate BETA's QC failures")
        second = self.chat('which ones failed?', first['context'])
        self.assertEqual(second['context']['project_investigation']['project_id'], self.beta.pk)
        self.assertIn('S-102', second['answer'])
        self.assertIn('No failure/rejection reason is recorded', second['answer'])
        third = self.chat('why?', second['context'])
        self.assertIn('do not establish the scientific root cause', third['answer'])
        fourth = self.chat('group by instrument', third['context'])
        self.assertEqual(fourth['project_investigation']['group_by'], 'instrument')
        fifth = self.chat('export as csv', fourth['context'])
        self.assertEqual(fifth['pending_action']['type'], 'COMPLIANCE_REPORT')
        self.assertEqual(fifth['pending_action']['preview']['proposed_values']['format'], 'CSV')
        self.assertEqual(GeneratedArtifact.objects.count(), 0)
        action = AssistantAction.objects.get()
        before = action.status
        sixth = self.chat('cancel', fifth['context'])
        self.assertEqual(sixth['context'], {})
        self.assertIn('Cancel button', sixth['answer'])
        action.refresh_from_db()
        self.assertEqual(action.status, before)

    def test_investigation_project_correction_preserves_filters_and_never_replays_export(self):
        first = self.chat("Investigate BETA's QC failures for last 7 days and export a report as CSV")
        second = self.chat('actually use ALPHA', first['context'])
        spec = second['context']['project_investigation']
        self.assertEqual(spec['project_id'], self.alpha.pk)
        self.assertEqual(spec['days'], 7)
        self.assertNotIn('pending_action', second)
        self.assertEqual(AssistantAction.objects.count(), 1)
        self.assertIn('No failed/rejected results', self.chat('which ones failed?', second['context'])['answer'])

    def test_informal_project_and_help_wording(self):
        first = self.chat('whats going on with project ALPHA')
        self.assertEqual(first['context']['project_id'], self.alpha.pk)
        second = self.chat('thanks, can you show me its samples?', first['context'])
        self.assertIn('S-100', json.dumps(second))
        self.assertEqual(second['context']['project_id'], self.alpha.pk)
        third = self.chat('can u show me overdue samples in ALPHA')
        self.assertEqual(third['daily_work']['scope']['project'], 'ALPHA')
        self.assertEqual([row['sample'] for row in third['daily_work']['rows']], ['S-101'])

    def test_unknown_followup_retains_live_read_scope(self):
        starters = ['What should I work on today?', "Investigate BETA's QC failures", 'Summarize project ALPHA', 'Show me sample S-100']
        keys = ['daily_work', 'project_investigation', 'project_id', 'sample_ids']
        for starter, key in zip(starters, keys):
            with self.subTest(starter=starter):
                first = self.chat(starter)
                second = self.chat('can you unpack that bit for me?', first['context'])
                self.assertIn(key, second['context'])
                self.assertTrue(second['clarification']['required'])
                self.assertNotIn('pending_action', second)
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_unknown_recovery_rereads_data_and_redacts_revoked_access(self):
        first = self.chat("Investigate BETA's QC failures")
        result = self.samples[2].work_items.first().results.first()
        result.qc_passed = True
        result.save()
        second = self.chat('please unpack that bit', first['context'])
        self.assertEqual(second['project_investigation']['summary']['failed_checks'], 0)
        self.beta.members.remove(self.tech)
        third = self.chat('please unpack that bit', second['context'])
        self.assertNotIn('project_investigation', third)
        self.assertEqual(third['context'], {})
        self.assertNotIn('S-102', str(third))

    def test_invalid_or_revoked_scopes_are_cleared(self):
        for context in [{'daily_work': {'project': 'PRIVATE'}}, {'project_investigation': {'project_id': self.private.pk}},
                        {'daily_work': []}, {'project_investigation': {'project_id': 'bad'}},
                        {'sample_ids': [self.private_sample.pk]}, {'project_id': 10 ** 100}]:
            with self.subTest(context=context):
                reply = self.chat('please unpack that bit', context)
                self.assertEqual(reply['context'], {})
                self.assertNotIn('daily_work', reply)
                self.assertNotIn('project_investigation', reply)

    def test_explicit_topic_change_and_reset_clear_previous_scope(self):
        first = self.chat('What should I work on today?')
        second = self.chat('Summarize project BETA', first['context'])
        self.assertNotIn('daily_work', second['context'])
        self.assertEqual(second['context']['project_id'], self.beta.pk)
        for text in ['start over', 'never mind', 'cancel']:
            with self.subTest(text=text):
                self.assertEqual(self.chat(text, first['context'])['context'], {})

    def test_malformed_investigation_ids_never_become_database_lookups(self):
        for value in [[], {}, None, True, 1.2, '1', -1, 10 ** 100]:
            for message in ['which ones failed?', 'please unpack that bit']:
                with self.subTest(value=value, message=message):
                    reply = self.chat(message, {'project_investigation': {'project_id': value}})
                    self.assertEqual(reply['context'], {})
                    self.assertNotIn('project_investigation', reply)
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_concept_saved_conversation_restores_followup(self):
        first = self.chat('What is a sample?')
        saved = self.client.post('/api/assistant/conversations/', {'name': 'Concept help', 'turn_tokens': [first['save_turn_token']]}, format='json')
        self.assertEqual(saved.status_code, 201, saved.data)
        restored = self.client.get(f"/api/assistant/conversations/{saved.data['id']}/")
        self.assertEqual(restored.status_code, 200, restored.data)
        self.assertEqual(restored.data['context']['lab_concept'], ['sample'])
        reply = self.chat('Give me a simple example', restored.data['context'])
        self.assertIn('Illustrative example', reply['answer'])
        self.assertEqual(sanitize_context(reply['context'])['lab_concept'], ['sample'])
