from django.test import SimpleTestCase

from assistant.intent_matching import (
    compact_command_text,
    contains_intent_phrase,
    normalize_intent_text,
)


class AssistantIntentMatchingTests(SimpleTestCase):
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
