from unittest.mock import patch
from django.utils import timezone
from rest_framework.test import APITestCase

from assistant.dialogue_memory import load_topics, LIMIT
from assistant.models import AssistantAction
from assistant.provider_conversation import classifier_context
from . import test_comparisons


class DialogueMemoryTests(APITestCase):
    setUp = test_comparisons.AssistantComparisonTests.setUp
    chat = test_comparisons.AssistantComparisonTests.chat

    def test_corrections_repeat_current_read_task(self):
        for correction in ['No, I meant BETA', 'Actually BETA', 'Sorry, I meant project BETA']:
            with self.subTest(correction=correction):
                first = self.chat('Show samples in project ALPHA').data
                second = self.chat(correction, first['context']).data
                self.assertEqual([row['sample'] for row in second['comparison']['rows']], ['S-102'])

    def test_switch_topics_then_return_to_previous_project(self):
        first = self.chat('Show samples in project ALPHA').data
        second = self.chat('What happened to sample S-102?', first['context']).data
        third = self.chat('Also show system status', second['context']).data
        self.assertNotIn('read_intent', third['context'])
        with patch('assistant.views.classify_route_with_llm') as model:
            back = self.chat('Go back to the previous project', third['context']).data
            self.assertEqual(back['context']['project_id'], self.alpha.pk)
            self.assertEqual({row['sample'] for row in back['comparison']['rows']}, {'S-100', 'S-101'})
            model.assert_not_called()
        recap = self.chat('What were we talking about?', back['context']).data
        self.assertIn('ALPHA', recap['answer'])
        self.assertIn('S-102', recap['answer'])

    def test_previous_topic_uses_live_identity_and_records(self):
        first = self.chat('Summarize project ALPHA').data
        second = self.chat('Summarize project BETA', first['context']).data
        self.alpha.code = 'RENAMED'
        self.alpha.save()
        self.samples[0].status = 'QC'
        self.samples[0].save()
        back = self.chat('Back to the previous topic', second['context']).data
        self.assertIn('RENAMED', back['answer'])
        self.assertIn('QC: 1', back['answer'])

    def test_revocation_tampering_cross_user_and_expiry(self):
        first = self.chat('Summarize project ALPHA').data
        token = first['context']['dialogue_memory']
        self.assertEqual(load_topics({'dialogue_memory': token + 'x'}, self.tech), [])
        self.assertEqual(load_topics(first['context'], self.outsider), [])
        self.assertNotIn('dialogue_memory', classifier_context(first['context'], self.tech, 'more details'))
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp() + 3601):
            self.assertEqual(load_topics(first['context'], self.tech), [])
        self.alpha.members.remove(self.tech)
        result = self.chat('What were we discussing?', first['context']).data
        self.assertNotIn('ALPHA', result['answer'])
        self.assertNotIn('dialogue_memory', result['context'])

    def test_reset_clears_history_and_no_write_replay(self):
        first = self.chat('Summarize project ALPHA').data
        cleared = self.chat('Forget this conversation', first['context']).data
        self.assertEqual(cleared['context'], {})
        recap = self.chat('Where were we?', cleared['context']).data
        self.assertNotIn('ALPHA', recap['answer'])
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_memory_is_bounded_and_contains_only_references(self):
        from projects.models import Project
        context = {}
        for i in range(LIMIT + 2):
            project = Project.objects.create(code=f'MEM-{i}', name=f'Memory {i}')
            project.members.add(self.tech)
            context = self.chat(f'Summarize project {project.code}', context).data['context']
        topics = load_topics(context, self.tech)
        self.assertEqual(len(topics), LIMIT)
        self.assertTrue(all(set(topic) == {'intent', 'id'} for topic in topics))
