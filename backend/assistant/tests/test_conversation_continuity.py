from unittest.mock import patch
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from assistant.clarifications import CHOICE_REQUESTS, resume_clarification, route_assistant_clarification
from assistant.models import AssistantAction
from assistant.qc_operations import _read_reference_comparison
from assistant.provider_tools import dispatch_tool
from . import test_comparisons, test_lab_reviews
from .test_provider_tools import plan


class ConversationContinuityTests(APITestCase):
    setUp = test_comparisons.AssistantComparisonTests.setUp
    chat = test_comparisons.AssistantComparisonTests.chat
    lot = test_lab_reviews.LabReviewTests.lot

    def expiring_lot(self):
        lot = self.lot()
        lot.item.category = 'REAGENT'
        lot.item.save()
        lot.expiration_date = timezone.localdate() + timedelta(days=5)
        lot.save()
        return lot

    def test_every_offered_choice_accepts_name_id_and_number(self):
        for topic, request in CHOICE_REQUESTS.items():
            question = route_assistant_clarification(request)
            self.assertEqual(question['context']['clarification_topic'], topic)
            for i, option in enumerate(question['clarification']['options']):
                for reply in [option['label'], option['id'], str(i + 1), f'option {i + 1}']:
                    with self.subTest(topic=topic, reply=reply):
                        command, error = resume_clarification(reply, question['context'])
                        self.assertIsNone(error)
                        self.assertEqual(command, option['message'])

    def test_inventory_and_qc_choices_execute_without_model(self):
        self.expiring_lot()
        for request, reply, expected in [('Show inventory', 'expiring soon', 'inventory_lot_ids'),
                                         ('Show QC results', 'the second one', 'result_ids')]:
            with self.subTest(request=request), patch('assistant.views.classify_route_with_llm') as model:
                first = self.chat(request).data
                second = self.chat(reply, first['context'])
                self.assertEqual(second.status_code, 200)
                self.assertIn(expected, second.data['context'])
                self.assertNotIn('clarification_topic', second.data['context'])
                model.assert_not_called()

    def test_courtesy_preserves_project_and_pending_choice(self):
        self.expiring_lot()
        first = self.chat('Summarize project ALPHA').data
        for reply in ['thanks', 'okay', 'got it']:
            first = self.chat(reply, first['context']).data
            self.assertEqual(first['context']['project_id'], self.alpha.pk)
        result = self.chat('Summarize it', first['context']).data
        self.assertIn('ALPHA', result['answer'])
        first = self.chat('Show inventory').data
        second = self.chat('thanks', first['context']).data
        third = self.chat('2', second['context']).data
        self.assertIn('inventory_lot_ids', third['context'])

    def test_thanks_keeps_comparison_for_chart_and_export(self):
        first = self.chat('Where are samples getting stuck in project ALPHA?').data
        second = self.chat('thanks', first['context']).data
        chart = self.chat('Graph overdue and unassigned work', second['context']).data
        self.assertIn('chart', chart)
        exported = self.chat('Export this comparison as CSV', chart['context']).data
        self.assertNotIn('clarification', exported)
        self.assertIn('confirmation_token', exported['pending_action'])
        self.assertEqual(exported['pending_action']['preview']['proposed_values']['format'], 'CSV')

    def test_invalid_choices_new_topics_and_cancel(self):
        first = self.chat('Show inventory').data
        for answer in ['99', 'that one', 'yes']:
            result = self.chat(answer, first['context']).data
            self.assertIn('clarification', result)
            self.assertEqual(result['context']['clarification_topic'], 'inventory_scope')
        result = self.chat('start over', first['context']).data
        self.assertEqual(result['context'], {})
        result = self.chat('Summarize project BETA', first['context']).data
        self.assertNotIn('clarification_topic', result['context'])
        self.assertEqual(result['context']['project_id'], self.beta.pk)
        command, question = resume_clarification('1', {'clarification_topic': ['bad']})
        self.assertEqual((command, question), (None, None))
        command, _ = resume_clarification('2', {'clarification_topic': 'inventory_scope', 'options': [{'message': 'Delete samples'}]})
        self.assertEqual(command, 'Which reagents expire in the next 30 days?')
        self.assertEqual(AssistantAction.objects.count(), 0)

    def test_qc_single_plural_context_and_invalid_ids(self):
        result = self.samples[0].work_items.first().results.first()
        for context in [{'result_ids': [result.pk]}, {'result_id': result.pk}]:
            answer = _read_reference_comparison('Compare it with its reference range', self.tech, context)
            self.assertEqual(answer['context']['result_id'], result.pk)
        for context in [{'result_id': 'bad'}, {'result_id': 10**100}, {'result_ids': [result.pk, 999]},
                        {'result_ids': 'invalid'}, {'result_id': result.pk, 'result_ids': [999]}]:
            answer = _read_reference_comparison('Compare it with its reference range', self.tech, context)
            self.assertIn('Tell me which result', answer['answer'])
        self.alpha.members.remove(self.tech)
        answer = _read_reference_comparison('Compare it with its reference range', self.tech, {'result_id': result.pk})
        self.assertIn('not accessible', answer['answer'])

    def test_acknowledgment_does_not_fill_missing_provider_argument(self):
        first = dispatch_tool(plan('handover'), self.tech)
        for reply in ['okay', 'understood', 'thanks']:
            first = self.chat(reply, first['context']).data
            self.assertIn('provider_conversation', first['context'])
        second = self.chat('me', first['context']).data
        self.assertIn('Who is taking over', second['answer'])

    def test_unresolved_followup_offers_contextual_next_steps(self):
        first = self.chat('Summarize project ALPHA').data
        second = self.chat('Do something useful with that', first['context']).data
        self.assertEqual(second['context']['project_id'], self.alpha.pk)
        self.assertIn('Show samples in that project', second['suggestions'])

    @override_settings(OPENLIMS_ENFORCE_FEATURE_FLAGS=False)
    def test_lot_followup_preserves_scope_without_mutation(self):
        lot = self.lot()
        first = dispatch_tool(plan('quarantine_impact', lot=lot.lot_code), self.tech)
        result = self.chat('Preview quarantine impact for that lot', first['context']).data
        self.assertEqual(result['impact_preview']['lot_id'], lot.pk)
        self.assertEqual(result['context']['inventory_lot_id'], lot.pk)
        ambiguous = self.chat('Preview quarantine impact for that lot', {'inventory_lot_ids': [lot.pk, lot.pk + 1]}).data
        self.assertTrue(ambiguous['clarification']['required'])
        self.assertEqual(AssistantAction.objects.count(), 0)
