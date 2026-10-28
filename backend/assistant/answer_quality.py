"""Repeatable fact/source checks for read-only answers, including live routing."""
import time

from .read_plans import handle_read_plan
from .sample_explanations import route_sample_explanations
from .sop_operations import route_sop_assistant

EXPECTED_KEYS = {"contains", "excludes", "citation_kinds", "operations", "clarification", "partial"}


def validate_cases(cases):
    if not isinstance(cases, list) or not 1 <= len(cases) <= 200:
        raise ValueError("Provide a JSON list of 1–200 answer-quality cases.")
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"name", "message", "expected"}:
            raise ValueError("Each case needs exactly name, message and expected.")
        if any(not isinstance(case[key], str) or not case[key].strip() or len(case[key]) > limit
               for key, limit in [("name", 120), ("message", 2000)]):
            raise ValueError("Case names/messages must be nonempty strings within 120/2000 characters.")
        expected = case["expected"]
        if not isinstance(expected, dict) or set(expected) - EXPECTED_KEYS or not expected:
            raise ValueError("Expected checks must use documented fact, source and operation fields.")
        for key, value in expected.items():
            if key in {"clarification", "partial"}:
                valid = type(value) is bool
            else:
                valid = isinstance(value, list) and len(value) <= 50 and all(
                    isinstance(item, str) and 0 < len(item) <= 500 for item in value)
            if not valid:
                raise ValueError(f"Invalid expected field: {key}.")
    return cases


def check_answer(result, expected):
    answer = result.get("answer", "").casefold()
    checks = {"read_only": not bool(result.get("pending_action") or result.get("action_error"))}
    if "contains" in expected:
        checks["required_facts"] = all(text.casefold() in answer for text in expected["contains"])
    if "excludes" in expected:
        checks["forbidden_claims"] = all(text.casefold() not in answer for text in expected["excludes"])
    if "citation_kinds" in expected:
        checks["sources"] = set(expected["citation_kinds"]) <= {c.get("kind") for c in result.get("citations", [])}
    if "operations" in expected:
        checks["operations"] = expected["operations"] == [s["operation"] for s in result.get("read_plan", {}).get("steps", [])]
    if "clarification" in expected:
        checks["clarification"] = bool(result.get("clarification")) == expected["clarification"]
    if "partial" in expected:
        checks["partial"] = bool(result.get("read_plan", {}).get("partial")) == expected["partial"]
    return checks


def evaluate_cases(cases, user, *, live_provider=False):
    cases = validate_cases(cases)
    rows = []
    for case in cases:
        started = time.monotonic()
        message = case["message"]
        result = handle_read_plan(message, user)
        if result and result.get("route_unmatched") and live_provider:
            from .llm import classify_route_with_llm
            plan = classify_route_with_llm(message)
            if plan and plan.get("route") == "read_plan":
                result = handle_read_plan(message, user, plan)
        if result is None:
            result = route_sample_explanations(message, user) or route_sop_assistant(message, user)
        if result is None:
            raise ValueError(f"Unsupported read-only evaluation case: {case['name']}.")
        checks = check_answer(result, case["expected"])
        rows.append({"name": case["name"], "passed": all(checks.values()), "checks": checks,
                     "latency_ms": round((time.monotonic() - started) * 1000, 2)})
    return {"cases": len(rows), "passed": sum(row["passed"] for row in rows),
            "mode": "live_provider_routing" if live_provider else "rules",
            "limitations": "Expected-fact/source checks, not a scientific validation or general semantic accuracy score. SOP reads retain their normal audit events.",
            "results": rows}
