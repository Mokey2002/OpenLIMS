from django.test import SimpleTestCase

from assistant.intent_matching import (
    compact_command_text,
    contains_intent_phrase,
    normalize_intent_text,
    work_graph_metrics,
)


class AssistantIntentMatchingTests(SimpleTestCase):
    def test_work_graph_variations_preserve_requested_metrics(self):
        for message, expected in [
            ("Could you please graph the overdue and unassigned work?", ["overdue_work", "unassigned_work"]),
            ("Show unassigned work as a bar chart", ["unassigned_work"]),
            ("Plot overdue work items, please", ["overdue_work"]),
            ("Chart unassigned and overdue work", ["overdue_work", "unassigned_work"]),
        ]:
            with self.subTest(message=message):
                self.assertEqual(work_graph_metrics(message), expected)

    def test_work_graph_does_not_discard_meaningful_modifiers(self):
        for message in [
            "Graph overdue work and assign it to peter",
            "Do not graph overdue work",
            "Graph overdue work in project PRIVATE",
            "Graph overdue work tomorrow",
            "Show unassigned work",
            "Graph not overdue work",
        ]:
            with self.subTest(message=message):
                self.assertEqual(work_graph_metrics(message), [])

    def test_harmless_filler_words_can_appear_inside_known_phrases(self):
        self.assertTrue(
            contains_intent_phrase(
                "Could you show me the failed jobs, please?",
                "show failed jobs",
            )
        )
        self.assertTrue(
            contains_intent_phrase(
                "What needs my attention right now?",
                "what needs attention",
            )
        )

    def test_need_and_require_variants_are_equivalent_for_intent_matching(self):
        self.assertEqual(
            normalize_intent_text("What requires my attention?"),
            "what need my attention",
        )
        self.assertTrue(
            contains_intent_phrase(
                "What requires my attention?",
                "what needs attention",
            )
        )

    def test_meaningful_words_cannot_be_skipped(self):
        self.assertFalse(
            contains_intent_phrase(
                "What needs migration attention?",
                "what needs attention",
            )
        )

    def test_command_compaction_removes_politeness_without_changing_subject(self):
        self.assertEqual(
            compact_command_text("Could you please show me all the samples?"),
            "show samples",
        )
