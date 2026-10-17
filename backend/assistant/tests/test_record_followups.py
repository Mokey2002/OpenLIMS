from unittest.mock import patch
from rest_framework.test import APITestCase
from assistant.provider_tools import dispatch_tool
from assistant.models import AssistantAction
from assistant.sequences import find_sample_sequences, summarize_sequence_records
from sequences.models import Sequence
from . import test_comparisons
from .test_provider_tools import plan


class RecordFollowupTests(APITestCase):
    setUp = test_comparisons.AssistantComparisonTests.setUp
    chat = test_comparisons.AssistantComparisonTests.chat

    def test_summary_history_location_and_last_move_chain(self):
        with patch('assistant.views.classify_route_with_llm') as model:
            result = self.chat('Summarize sample S-100').data
            for question in ['Show its history', 'Where is it stored?', 'Who last moved it?', 'Summarize that sample']:
                result = self.chat(question, result['context']).data
                self.assertIn('S-100', result['answer'])
                self.assertNotIn('S-101', result['answer'])
            model.assert_not_called()

    def test_history_to_guidance(self):
        first = self.chat('What happened to sample S-100?').data
        result = self.chat("What's next?", first['context']).data
        self.assertIn('S-100', result['answer'])
        self.assertFalse(result.get('clarification', {}).get('required'))

    def test_quality_review_to_project_samples(self):
        first = self.chat('Review data quality for project ALPHA').data
        result = self.chat('Show samples in that project', first['context']).data
        self.assertEqual({r['sample'] for r in result['comparison']['rows']}, {'S-100', 'S-101'})

    def test_provider_history_to_read_followup(self):
        first = dispatch_tool(plan('sample_history', sample='S-100'), self.tech)
        result = self.chat('Where is it?', first['context']).data
        self.assertIn('S-100', result['answer'])
        self.assertIn('stored', result['answer'])

    def test_provider_memory_does_not_preempt_existing_commands(self):
        first = dispatch_tool(plan('project_update', project='ALPHA'), self.tech)
        with patch('assistant.views.classify_route_with_llm') as model:
            result = self.chat('Also show system status', first['context']).data
            self.assertNotIn('follow-up', result['answer'])
            model.assert_not_called()

    def test_ambiguous_invalid_and_revoked_sample_context(self):
        contexts = [{}, {'sample_ids': [s.pk for s in self.samples]}, {'sample_id': 'bad'},
                    {'sample_id': 10**100}, {'sample_id': self.samples[0].pk, 'sample_ids': [self.samples[1].pk]}]
        for context in contexts:
            result = self.chat('Show its history', context).data
            self.assertTrue(result['clarification']['required'])
            self.assertNotIn('history', result)
        first = self.chat('Summarize sample S-100').data
        self.alpha.members.remove(self.tech)
        result = self.chat('Show its history', first['context']).data
        self.assertEqual(result['context'], {})
        self.assertNotIn('S-100', result['answer'])

    def test_rename_follows_stable_sample_id(self):
        first = self.chat('Summarize sample S-100').data
        sample = self.samples[0]
        sample.sample_id = 'RENAMED-100'
        sample.save()
        result = self.chat('Show its history', first['context']).data
        self.assertIn('RENAMED-100', result['answer'])

    def test_sequence_scope_and_followup(self):
        Sequence.objects.create(name='Visible sequence', sequence='ATGC', sample=self.samples[0], project=self.alpha, created_by=self.tech)
        first = self.chat('Summarize sample S-100').data
        result = self.chat('Show its sequences', first['context']).data
        self.assertIn('S-100', result['answer'])
        self.assertEqual(result['context']['sample_id'], self.samples[0].pk)
        result = self.chat('Show its history', result['context']).data
        self.assertIn('S-100', result['answer'])
        for fn in [find_sample_sequences, summarize_sequence_records]:
            for code in ['MISSING-999', 'S-PRIVATE', 'S-10', 'S-100 and sample S-101']:
                result = fn(f'Find sequences for sample {code}', self.tech)
                self.assertTrue(result['clarification']['required'])
                self.assertNotIn('Visible sequence', str(result))

    def test_read_followups_do_not_create_actions(self):
        first = self.chat('Summarize sample S-100').data
        self.chat('Show its history', first['context'])
        self.assertEqual(AssistantAction.objects.count(), 0)
