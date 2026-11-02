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
        parser.add_argument("--provider", choices=["openai", "ollama"], help="Provider to benchmark with --live-provider.")
        parser.add_argument("--model", help="Model to benchmark with --live-provider.")

    def handle(self, *args, **options):
        try:
            cases = validate_cases(json.loads(Path(options["cases"]).read_text()))
            user = get_user_model().objects.get(username=options["user"], is_active=True)
            if (options.get("provider") or options.get("model")) and not options["live_provider"]:
                raise ValueError("Provider/model overrides require --live-provider.")
            from django.test import override_settings
            overrides = {}
            if options.get("provider"):
                overrides["OPENLIMS_ASSISTANT_LLM_PROVIDER"] = options["provider"]
            if options.get("model"):
                from assistant.llm import llm_provider
                provider = options.get("provider") or llm_provider()
                overrides["OPENAI_MODEL" if provider == "openai" else "OLLAMA_MODEL"] = options["model"]
            with override_settings(**overrides):
                report = self._evaluate(cases, user, options)
        except (OSError, ValueError, get_user_model().DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, indent=2))
        if report["passed"] != report["cases"]:
            raise CommandError(f"Answer-quality checks failed: {report['passed']}/{report['cases']} passed.")

    def _evaluate(self, cases, user, options):
        if options["live_provider"]:
            from assistant.llm import assistant_llm_routing_enabled
            if not assistant_llm_routing_enabled():
                raise ValueError("Live evaluation requires an enabled, configured routing provider.")
        return evaluate_cases(cases, user, live_provider=options["live_provider"])
