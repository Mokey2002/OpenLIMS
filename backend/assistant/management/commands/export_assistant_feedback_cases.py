import json
import os
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from assistant.models import AssistantConversation, AssistantFeedback


class Command(BaseCommand):
    help = "Export personal negative feedback linked to opted-in saved chats for manual benchmark review."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True)
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        try:
            user = get_user_model().objects.get(username=options["user"], is_active=True)
            questions = {turn["interaction_id"]: turn["question"] for conversation in AssistantConversation.objects.filter(owner=user)
                         for turn in conversation.turns if turn.get("interaction_id")}
            rows, skipped = [], 0
            for feedback in AssistantFeedback.objects.filter(user=user, rating=AssistantFeedback.RATING_DOWN).order_by("pk")[:200]:
                message = questions.get(str(feedback.interaction_id))
                if message is None:
                    skipped += 1
                    continue
                rows.append({"name": f"feedback-{feedback.pk}", "message": message, "category": feedback.category,
                             "review_note": feedback.note, "expected": None})
            report = {"needs_review": True, "instructions": "Verify record access and facts, write nonempty expectations, then copy cases into an evaluation JSON list. This export cannot be evaluated as a passing benchmark.",
                      "cases": rows, "skipped_without_saved_question": skipped}
            path = Path(options["output"])
            with path.open("x", encoding="utf-8") as output:
                os.chmod(path, 0o600)
                json.dump(report, output, indent=2)
        except (OSError, get_user_model().DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Exported {len(rows)} cases for review; skipped {skipped} without saved questions.")
