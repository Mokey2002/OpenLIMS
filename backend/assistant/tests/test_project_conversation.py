from unittest.mock import patch
from rest_framework.test import APITestCase
from assistant.project_conversation import project_request
from assistant.provider_tools import dispatch_tool
from . import test_comparisons
from .test_provider_tools import plan


class ProjectConversationTests(APITestCase):
    setUp = test_comparisons.AssistantComparisonTests.setUp
    chat = test_comparisons.AssistantComparisonTests.chat

    def test_summary_then_samples_and_assignments_without_provider(self):
        with patch('assistant.views.classify_route_with_llm') as model:
            first = self.chat('Summarize project ALPHA').data
            self.assertEqual(first['context']['project_id'], self.alpha.pk)
            self.assertIn('eduardo', first['answer'])
            rows = first['comparison']['rows']
            self.assertEqual(sum(r['total'] for r in rows), 2)
            self.assertEqual(sum(r['overdue'] for r in rows), 1)
            second = self.chat('show me samples in that project', first['context']).data
            self.assertEqual({r['sample'] for r in second['comparison']['rows']}, {'S-100', 'S-101'})
            third = self.chat("who's assigned work in that project?", second['context']).data
            self.assertEqual(third['comparison']['rows'], rows)
            self.assertNotIn('S-PRIVATE', str(second))
            model.assert_not_called()

    def test_missing_invalid_and_revoked_project_context(self):
        for context in [{}, {'project_id': 'bad'}, {'project_id': 10**100}, {'project_id': self.private.pk}]:
            result = self.chat('show me samples in that project', context).data
            self.assertNotIn('comparison', result)
            self.assertEqual(result['context'], {})
        first = self.chat('Summarize project ALPHA').data
        self.alpha.members.remove(self.tech)
        result = self.chat('show me samples in that project', first['context']).data
        self.assertNotIn('S-100', str(result))
        self.assertEqual(result['context'], {})

    def test_stable_identity_explicit_switch_and_linked_samples(self):
        first = self.chat('Summarize project ALPHA').data
        self.alpha.code = 'RENAMED'
        self.alpha.save()
        self.samples[2].linked_projects.add(self.alpha)
        second = self.chat('show me samples in that project', first['context']).data
        self.assertIn('RENAMED', second['answer'])
        self.assertEqual(len(second['comparison']['rows']), 3)
        beta = self.chat('show me samples in project BETA', second['context']).data
        self.assertEqual([r['sample'] for r in beta['comparison']['rows']], ['S-102'])
        self.assertEqual(beta['context']['project_id'], self.beta.pk)

    def test_provider_adapter_uses_same_project_resolution(self):
        for command in ['Summarize project ALPHA', 'Show me samples in project ALPHA']:
            result = dispatch_tool(plan('record_search', command=command), self.tech)
            self.assertEqual(result['context']['project_id'], self.alpha.pk)
            self.assertIn('comparison', result)

    def test_terminal_work_excluded_from_attention_counts(self):
        item = self.samples[1].work_items.first()
        item.status = 'COMPLETED'
        item.qc_status = 'REJECTED'
        item.save()
        result = project_request('Summarize project ALPHA', self.tech)
        self.assertEqual(sum(r['overdue'] for r in result['comparison']['rows']), 0)
        self.assertEqual(sum(r['qc'] for r in result['comparison']['rows']), 0)
        self.assertEqual(sum(r['unfinished'] for r in result['comparison']['rows']), 1)

    def test_project_update_draft_keeps_project_for_followup(self):
        first = dispatch_tool(plan('project_update', project='ALPHA'), self.tech)
        second = self.chat('show me samples in that project', first['context']).data
        self.assertEqual({r['sample'] for r in second['comparison']['rows']}, {'S-100', 'S-101'})

    def test_empty_and_ambiguous_projects_and_unsupported_filters(self):
        from projects.models import Project
        empty = Project.objects.create(code='EMPTY', name='Empty')
        empty.members.add(self.tech)
        result = self.chat('Summarize project EMPTY').data
        self.assertIn('0 accessible samples', result['answer'])
        self.assertEqual(result['comparison']['rows'], [])
        duplicate = Project.objects.create(code='alpha', name='Another Alpha')
        duplicate.members.add(self.tech)
        result = self.chat('Summarize project ALPHA').data
        self.assertNotIn('comparison', result)
        self.assertEqual(result['context'], {})
        result = project_request('show me samples in project BETA that failed yesterday', self.tech)
        self.assertNotIn('comparison', result)
