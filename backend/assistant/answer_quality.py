"""Repeatable fact/source checks for read-only answers, including live routing."""
import time
import math
import statistics

from .read_plans import handle_read_plan
from .sample_explanations import route_sample_explanations
from .sop_operations import route_sop_assistant

EXPECTED_KEYS = {"contains", "excludes", "citation_kinds", "citation_urls", "result_ids", "counts", "overview_contains", "operations", "clarification", "partial"}


def validate_cases(cases):
    if not isinstance(cases, list) or not 1 <= len(cases) <= 200:
        raise ValueError("Provide a JSON list of 1–200 answer-quality cases.")
    for case in cases:
        if (not isinstance(case, dict) or set(case) - {"name", "message", "turns", "expected"}
                or not {"name", "expected"} <= set(case) or ("message" in case) == ("turns" in case)):
            raise ValueError("Each case needs name, expected, and either message or turns.")
        turns = case.get("turns", [{"message": case.get("message")}])
        if (not isinstance(turns, list) or not 1 <= len(turns) <= 10
                or any(not isinstance(turn, dict) or set(turn) - {"message", "expected"} or "message" not in turn for turn in turns)):
            raise ValueError("Provide 1–10 turns with message and optional expected fields.")
        if (not isinstance(case["name"], str) or not 0 < len(case["name"]) <= 120 or any(
                not isinstance(turn["message"], str) or not turn["message"].strip() or len(turn["message"]) > 2000 for turn in turns)):
            raise ValueError("Case names/messages must be nonempty strings within 120/2000 characters.")
        for expected in [case["expected"]] + [turn["expected"] for turn in turns if "expected" in turn]:
            if not isinstance(expected, dict) or set(expected) - EXPECTED_KEYS or not expected:
                raise ValueError("Expected checks must use documented fact, source and operation fields.")
            for key, value in expected.items():
                if key in {"clarification", "partial"}:
                    valid = type(value) is bool
                elif key == "result_ids":
                    valid = isinstance(value, list) and len(value) <= 100 and all(type(pk) is int and pk > 0 for pk in value)
                elif key == "counts":
                    valid = isinstance(value, dict) and bool(value) and set(value) <= {"total", "shown", "failed", "rejected", "comparison_total"} and all(type(n) is int and n >= 0 for n in value.values())
                else:
                    valid = isinstance(value, list) and len(value) <= 100 and all(
                        isinstance(item, str) and 0 < len(item) <= 500 for item in value)
                if not valid:
                    raise ValueError(f"Invalid expected field: {key}.")
            if not any(value or key in {"clarification", "partial", "operations", "result_ids", "citation_urls"} for key, value in expected.items()):
                raise ValueError("Provide at least one observable expected fact, source, count, operation or clarification check.")
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
    if "citation_urls" in expected:
        checks["exact_sources"] = set(expected["citation_urls"]) == {c.get("url") for c in result.get("citations", [])}
    facts = [step["result_query"] for step in result.get("read_plan", {}).get("steps", []) if step.get("result_query")]
    if "result_ids" in expected:
        checks["exact_records"] = set(expected["result_ids"]) == {row["id"] for fact in facts for row in fact.get("rows", [])}
    if "counts" in expected:
        checks["exact_counts"] = bool(facts) and all(facts[0].get(key) == n for key, n in expected["counts"].items())
    if "overview_contains" in expected:
        overview = result.get("answer_overview", {}).get("text", "").casefold()
        checks["displayed_facts"] = all(text.casefold() in overview for text in expected["overview_contains"])
    return checks


def evaluate_cases(cases, user, *, live_provider=False):
    cases = validate_cases(cases)
    if live_provider:
        from .llm import assistant_llm_routing_enabled
        if not assistant_llm_routing_enabled():
            raise ValueError("Live evaluation requires an enabled, configured routing provider.")
    rows, provider_requests = [], 0
    for case in cases:
        started = time.monotonic()
        context, turn_checks = {}, []
        for turn in case.get("turns", [{"message": case.get("message")}]):
            message = turn["message"]
            result = handle_read_plan(message, user, context=context)
            if result and result.get("route_unmatched") and live_provider:
                from .llm import classify_route_with_llm
                provider_requests += 1
                plan = classify_route_with_llm(message)
                if plan and plan.get("route") == "read_plan":
                    result = handle_read_plan(message, user, plan, context=context)
            if result is None:
                result = route_sample_explanations(message, user, context) or route_sop_assistant(message, user)
            if result is None:
                raise ValueError(f"Unsupported read-only evaluation case: {case['name']}.")
            context = result.get("context", {})
            if "expected" in turn:
                turn_checks.append(check_answer(result, turn["expected"]))
        checks = check_answer(result, case["expected"])
        checks["turns"] = all(all(check.values()) for check in turn_checks)
        rows.append({"name": case["name"], "passed": all(checks.values()), "checks": checks,
                     "latency_ms": round((time.monotonic() - started) * 1000, 2)})
    latencies = sorted(row["latency_ms"] for row in rows)
    from .llm import configured_model_info
    return {"cases": len(rows), "passed": sum(row["passed"] for row in rows), "provider_requests": provider_requests,
            "configured_model": configured_model_info() if live_provider else None,
            "latency_p50_ms": statistics.median(latencies), "latency_p95_ms": latencies[math.ceil(len(latencies) * .95) - 1],
            "mode": "live_provider_routing" if live_provider else "rules",
            "limitations": "Expected-fact/source checks, not a scientific validation or general semantic accuracy score. SOP reads retain their normal audit events.",
            "results": rows}
