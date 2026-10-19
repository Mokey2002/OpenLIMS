from unittest.mock import patch
from rest_framework.test import APITestCase
from assistant.models import AssistantAction
from assistant.natural_requests import normalize_request
from assistant.provider_tools import dispatch_tool
from . import test_comparisons
from .test_provider_tools import plan


class NaturalRequestTests(APITestCase):
    setUp = test_comparisons.AssistantComparisonTests.setUp
    chat = test_comparisons.AssistantComparisonTests.chat

    def test_project_wording_and_spanish_followup(self):
        for message in ['Could you please give me a quick overview of project ALPHA?',
                        'How is project ALPHA doing?', 'Dame un resumen del proyecto ALPHA',
                        'Por favor, resume el proyecto ALPHA']:
            with self.subTest(message=message), patch('assistant.views.classify_route_with_llm') as model:
                first = self.chat(message).data
                self.assertEqual(first['context']['project_id'], self.alpha.pk)
                second = self.chat('Muéstrame las muestras de ese proyecto', first['context']).data
                self.assertEqual({r['sample'] for r in second['comparison']['rows']}, {'S-100', 'S-101'})
                third = self.chat('same for BETA', second['context']).data
                self.assertEqual([r['sample'] for r in third['comparison']['rows']], ['S-102'])
                model.assert_not_called()

    def test_missing_project_then_identifier_then_same_task(self):
        first = self.chat('Could you summarize a project?').data
        self.assertTrue(first['clarification']['required'])
        first = self.chat('thanks', first['context']).data
        second = self.chat('ALPHA', first['context']).data
        self.assertEqual(second['context']['project_id'], self.alpha.pk)
        third = self.chat('same for BETA', second['context']).data
        self.assertEqual(third['context']['project_id'], self.beta.pk)
        self.assertIn('Work by assignee', third['comparison']['title'])

    def test_same_for_preserves_history_and_sample_list(self):
        first = self.chat('What happened to sample S-100?').data
        second = self.chat('What about sample S-102?', first['context']).data
        self.assertIn('history', second)
        self.assertIn('S-102', second['answer'])
        first = self.chat('Which samples are in project ALPHA?').data
        second = self.chat('And for BETA?', first['context']).data
        self.assertEqual([r['sample'] for r in second['comparison']['rows']], ['S-102'])
        first = self.chat('Summarize sample S-100').data
        second = self.chat('Show its history', first['context']).data
        third = self.chat('same for S-102', second['context']).data
        self.assertIn('history', third)
        self.assertIn('S-102', third['answer'])

    def test_provider_adapters_share_normalization_and_read_memory(self):
        for provider in ['openai', 'ollama']:
            first = dispatch_tool({**plan('record_search', command='Could you give me a rundown of project ALPHA?'), 'provider': provider}, self.tech)
            self.assertEqual(first['context']['project_id'], self.alpha.pk)
            second = self.chat('same for BETA', first['context']).data
            self.assertEqual(second['context']['project_id'], self.beta.pk)
        first = dispatch_tool(plan('sample_history', sample='S-100'), self.tech)
        self.assertIn('history', self.chat('same for S-102', first['context']).data)

    def test_personal_next_without_sample_and_sample_next_with_context(self):
        result = self.chat('What should I do next?').data
        self.assertIn('personal_work', result)
        self.assertIn('personal_work', self.chat('Could you show me my priorities?').data)
        first = self.chat('Summarize sample S-100').data
        result = self.chat('What should I do next?', first['context']).data
        self.assertIn('S-100', result['answer'])
        self.assertNotIn('personal_work', result)

    def test_inaccessible_ambiguous_invalid_state_and_cancellation(self):
        from projects.models import Project
        first = self.chat('Summarize a project').data
        for target in ['PRIVATE', 'MISSING', 'ALPHA and BETA']:
            result = self.chat(target, first['context']).data
            self.assertNotIn('comparison', result)
        duplicate = Project.objects.create(code='alpha', name='Duplicate')
        duplicate.members.add(self.tech)
        result = self.chat('ALPHA', first['context']).data
        self.assertTrue(result['clarification']['required'])
        self.assertEqual(self.chat('cancel', first['context']).data['context'], {})
        result = self.chat('S-100', {'awaiting_read': 'delete_sample'}).data
        self.assertNotIn('pending_action', result)
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_new_topic_and_filters_are_not_removed(self):
        first = self.chat('Summarize a project').data
        result = self.chat('Summarize sample S-100', first['context']).data
        self.assertNotIn('awaiting_read', result['context'])
        self.assertEqual(result['context']['read_intent'], 'sample_summary')
        text = normalize_request('Could you show samples in project ALPHA that failed yesterday?')
        self.assertIn('that failed yesterday', text)
        self.assertIn('do not', normalize_request('Could you please do not archive sample S-100?'))
