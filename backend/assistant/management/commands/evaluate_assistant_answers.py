import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from assistant.answer_quality import evaluate_cases, validate_cases


class Command(BaseCommand):
    help = "Check expected facts, sources and operations against current accessible read-only answers."

    def add_arguments(self, parser):
        parser.add_argument("--cases", required=True, help="JSON cases with expectations for this database.")
        parser.add_argument("--user", required=True, help="Active username whose record permissions apply.")
        parser.add_argument("--live-provider", action="store_true", help="Allow the configured provider to interpret unsupported compound wording; may incur provider charges.")

    def handle(self, *args, **options):
        try:
            cases = validate_cases(json.loads(Path(options["cases"]).read_text()))
            user = get_user_model().objects.get(username=options["user"], is_active=True)
            if options["live_provider"]:
                from assistant.llm import assistant_llm_routing_enabled
                if not assistant_llm_routing_enabled():
                    raise ValueError("Live evaluation requires an enabled, configured routing provider.")
            report = evaluate_cases(cases, user, live_provider=options["live_provider"])
        except (OSError, ValueError, get_user_model().DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, indent=2))
        if report["passed"] != report["cases"]:
            raise CommandError(f"Answer-quality checks failed: {report['passed']}/{report['cases']} passed.")
