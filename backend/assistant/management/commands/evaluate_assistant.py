from django.core.management.base import BaseCommand, CommandError

from assistant.evaluation_cases import iter_routing_evaluation_cases
from assistant.routing import classify_route_with_rules


class Command(BaseCommand):
    help = "Run the deterministic OpenLIMS assistant routing evaluation corpus."

    def handle(self, *args, **options):
        failures = []
        cases = list(iter_routing_evaluation_cases())
        for case in cases:
            plan = classify_route_with_rules(case["message"])
            actual = plan.get("route") if plan else None
            if actual != case["expected_route"]:
                failures.append(
                    f"{case['message']!r}: expected {case['expected_route']}, got {actual}"
                )
        if failures:
            raise CommandError(
                f"{len(failures)} of {len(cases)} assistant evaluations failed:\n"
                + "\n".join(failures)
            )
        self.stdout.write(
            self.style.SUCCESS(f"Assistant routing evaluation passed: {len(cases)} cases.")
        )
