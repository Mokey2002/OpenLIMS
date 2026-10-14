from datetime import timedelta
from django.utils import timezone
from assistant.tests import test_comparisons as fixtures
from assistant.workitem_operations import _propose_assignment
from results.models import WorkItem

from rest_framework.test import APITestCase

class WorkScopeTests(APITestCase):
    setUp = fixtures.AssistantComparisonTests.setUp
    chat = fixtures.AssistantComparisonTests.chat
    confirm = fixtures.AssistantComparisonTests.confirm

    def test_combined_filters(self):
        WorkItem.objects.filter(sample=self.samples[0]).update(due_at=timezone.now()-timedelta(days=1))
        response = self.chat('Show overdue and unassigned work')
        self.assertNotIn('S-100', response.data['answer'])
        self.assertIn('S-101', response.data['answer'])
        either = self.chat('Show overdue or unassigned work')
        for code in ['S-100', 'S-101', 'S-102']:
            self.assertIn(code, either.data['answer'])

    def test_project_read_scope(self):
        response = self.chat('Show unassigned work for project ALPHA')
        self.assertNotIn('S-102', response.data['answer'])
        self.assertIn('S-101', response.data['answer'])

    def test_graph_switches_back_to_status(self):
        first = self.chat('Where are samples getting stuck in project ALPHA')
        work = self.chat('Graph overdue and unassigned work', context=first.data['context'])
        status = self.chat('Graph sample status', context=work.data['context'])
        self.assertTrue(all(s['dataKey'].startswith('status_') for s in status.data['chart']['series']), status.data['chart']['series'])

    def test_private_workload_count(self):
        before = _propose_assignment('Assign work to eduardo', self.tech)['pending_action']['payload']['preview']['current_values']['target_workload']
        WorkItem.objects.filter(sample=self.private_sample).update(assigned_to=self.tech)
        after = _propose_assignment('Assign work to eduardo', self.tech)['pending_action']['payload']['preview']['current_values']['target_workload']
        self.assertEqual(before, after)

    def test_assignment_project_scope(self):
        WorkItem.objects.filter(sample__in=self.samples).update(work_type='GENERAL')
        response = self.chat('Assign unassigned work in project ALPHA to eduardo')
        from assistant.models import AssistantAction
        action = AssistantAction.objects.latest('created_at')
        beta = WorkItem.objects.get(sample=self.samples[2])
        self.assertNotIn(beta.id, action.payload['work_item_ids'])
        self.assertEqual(action.payload['project_id'], self.alpha.id)
        confirmed = self.confirm(response)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        beta.refresh_from_db()
        self.assertIsNone(beta.assigned_to_id)
        self.assertEqual(WorkItem.objects.get(sample=self.samples[1]).assigned_to_id, self.tech.id)

    def test_unresolved_project_does_not_fall_back_to_all_work(self):
        from assistant.models import AssistantAction
        for scope in ['PRIVATE', 'UNKNOWN', 'ALPH', 'ALPHA and BETA', '']:
            for command in ['Show unassigned work in project ', 'Assign work to eduardo in project ']:
                with self.subTest(scope=scope, command=command):
                    response = self.chat(command + scope)
                    self.assertIn('exact code or name', response.data['answer'])
                    self.assertNotIn('pending_action', response.data)
                    self.assertFalse(response.data.get('links'))
        self.assertFalse(AssistantAction.objects.exists())

    def test_confirmation_rejects_work_moved_to_another_accessible_project(self):
        WorkItem.objects.filter(sample__in=self.samples).update(work_type='GENERAL')
        proposal = self.chat('Assign unassigned work in project ALPHA to eduardo')
        self.samples[1].project = self.beta
        self.samples[1].save(update_fields=['project'])
        response = self.confirm(proposal)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(WorkItem.objects.get(sample=self.samples[1]).assigned_to_id)
