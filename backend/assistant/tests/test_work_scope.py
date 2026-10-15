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

    def test_rescheduled_overdue_work_requires_a_new_preview(self):
        item = WorkItem.objects.get(sample=self.samples[1])
        item.work_type = 'GENERAL'
        item.save(update_fields=['work_type'])
        proposal = self.chat('Assign overdue work to eduardo')
        item.due_at = timezone.now() + timedelta(days=7)
        item.save(update_fields=['due_at'])
        self.confirm(proposal)
        item.refresh_from_db()
        self.assertIsNone(item.assigned_to_id)

    def test_changed_work_type_requires_a_new_preview(self):
        item = WorkItem.objects.get(sample=self.samples[1])
        item.work_type = 'PCR'
        item.save(update_fields=['work_type'])
        proposal = self.chat('Assign PCR work to eduardo')
        item.work_type = 'EXTRACTION'
        item.save(update_fields=['work_type'])
        self.confirm(proposal)
        item.refresh_from_db()
        self.assertIsNone(item.assigned_to_id)

    def test_relinked_sample_requires_a_new_preview(self):
        item = WorkItem.objects.get(sample=self.samples[1])
        item.work_type = 'GENERAL'
        item.save(update_fields=['work_type'])
        proposal = self.chat('Assign work to eduardo')
        item.sample = self.samples[0]
        item.save(update_fields=['sample'])
        self.confirm(proposal)
        item.refresh_from_db()
        self.assertIsNone(item.assigned_to_id)

    def test_assignment_limit_does_not_silently_select_first_100(self):
        from samples.models import Sample
        from assistant.models import AssistantAction
        for index in range(101):
            sample = Sample.objects.create(sample_id=f'LIMIT-{index}', project=self.alpha, created_by=self.tech)
            WorkItem.objects.create(sample=sample, name='General', created_by=self.tech)
        response = self.chat('Assign work in project ALPHA to eduardo')
        self.assertIn('100-item', response.data['answer'])
        self.assertNotIn('pending_action', response.data)
        self.assertFalse(AssistantAction.objects.exists())

    def test_multiple_assignees_require_clarification(self):
        from assistant.models import AssistantAction
        for message in ['Assign work to eduardo and outsider', 'Assign work to eduardo, outsider']:
            with self.subTest(message=message):
                response = self.chat(message)
                self.assertIn('one assignee', response.data['answer'])
                self.assertNotIn('pending_action', response.data)
        self.assertFalse(AssistantAction.objects.exists())

    def test_multi_project_assignment_keeps_unscoped_preview_and_confirmation(self):
        from assistant.models import AssistantAction
        WorkItem.objects.filter(sample__in=self.samples).update(work_type='GENERAL')
        proposal = self.chat('Assign unassigned work to eduardo')
        action = AssistantAction.objects.latest('created_at')
        self.assertIsNone(action.payload['project_id'])
        self.assertEqual(action.payload['preview']['project'], 'Multiple accessible projects')
        response = self.confirm(proposal)
        self.assertEqual(response.status_code, 200, response.data)
        for sample in self.samples[1:]:
            self.assertEqual(WorkItem.objects.get(sample=sample).assigned_to_id, self.tech.id)

    def test_unsupported_modifiers_do_not_return_records_or_propose_actions(self):
        from assistant.models import AssistantAction
        for message in [
            'Show work that is not overdue',
            'Show overdue work except unassigned work',
            'Do not assign work to eduardo',
            "Don't reassign work from eduardo to eduardo",
            'Show unassigned work tomorrow',
            'Show overdue work before 2026-10-14',
            'Assign overdue or unassigned work to eduardo',
            'Assign work to eduardo and delete work',
        ]:
            with self.subTest(message=message):
                response = self.chat(message)
                self.assertIn('Please rephrase', response.data['answer'])
                self.assertNotIn('pending_action', response.data)
                self.assertFalse(response.data.get('links'))
        self.assertFalse(AssistantAction.objects.exists())

    def test_repeated_project_scopes_are_not_silently_discarded(self):
        response = self.chat('Assign work in project ALPHA to eduardo in project BETA')
        self.assertIn('exact code or name', response.data['answer'])
        self.assertNotIn('pending_action', response.data)

    def test_inactive_assignee_has_no_preview(self):
        self.tech.is_active = False
        self.tech.save(update_fields=['is_active'])
        result = _propose_assignment('Assign work to eduardo', self.tech)
        self.assertIn('inactive', result['answer'])
        self.assertNotIn('pending_action', result)

    def test_large_work_lists_disclose_total_and_display_limit(self):
        WorkItem.objects.bulk_create([
            WorkItem(sample=self.samples[1], name=f'Extra {i}', work_type=f'TEST_{i}', created_by=self.tech)
            for i in range(101)
        ])
        response = self.chat('Show unassigned work in project ALPHA')
        self.assertIn('102 item(s)', response.data['answer'])
        self.assertIn('Showing the first 100', response.data['answer'])
        self.assertEqual(len(response.data['links']), 100)

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
