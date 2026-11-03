"""User-bound read plans and bounded investigation history, without record values."""
import copy
import re

from django.core import signing

KEY = "read_plan_memory"
SALT = "assistant.read-plan-memory.v1"
MAX_TOKEN = 24000


def recall(context, user):
    token = (context or {}).get(KEY)
    if not isinstance(token, str) or len(token) > MAX_TOKEN:
        return None
    try:
        state = signing.loads(token, salt=SALT, max_age=3600)
    except (signing.BadSignature, ValueError, TypeError):
        return None
    if not isinstance(state, dict) or state.get("user") != user.pk:
        return None
    from .read_plans import validate_read_plan
    if validate_read_plan(state.get("plan")) is None:
        return None
    trail = state.get("trail", [])
    if not isinstance(trail, list) or len(trail) > 4 or any(validate_read_plan(plan) is None for plan in trail):
        return None
    ids = state.get("result_ids", [])
    if not isinstance(ids, list) or len(ids) > 80 or any(type(pk) is not int or not 0 < pk < 2**63 for pk in ids):
        return None
    return state


def remember(plan, result_ids, user, previous=None):
    trail = list((previous or {}).get("trail", []))
    old = (previous or {}).get("plan")
    if old and plan != old:
        # A return consumes its earlier breadcrumb; ordinary drill-downs retain it.
        if plan in trail:
            trail = trail[:trail.index(plan)]
        elif any(step["operation"] in {"project_results", "sample_results", "project_results_compare", "sample_results_compare"} for step in old["steps"]):
            trail = (trail + [old])[-4:]
    token = signing.dumps({"user": user.pk, "plan": plan, "trail": trail, "result_ids": list(dict.fromkeys(result_ids))[:80]}, salt=SALT, compress=True)
    return token if len(token) <= MAX_TOKEN else None


def resume(message, context, user):
    """Return a server-resolved plan, or an explicit ambiguity question."""
    original = message.strip().rstrip(".!?")
    text = original.lower()
    state = recall(context, user)
    if not state:
        return None, None
    plan = copy.deepcopy(state["plan"])
    back = re.fullmatch(r"(?:go )?back(?: to (?:the )?(comparison|results|result list))?", text)
    if back:
        for candidate in reversed(state.get("trail", [])):
            if not back[1] or any(step["operation"].endswith("_compare") if back[1] == "comparison" else step["operation"] in {
                    "project_results", "sample_results", "project_results_compare", "sample_results_compare"} for step in candidate["steps"]):
                return copy.deepcopy(candidate), None
        return None, "There is no earlier matching result query in this investigation. Ask for a sample or project result list first."
    # Filtering or changing targets after a drill-down applies to the parent query.
    if all(step["operation"] == "result_detail" for step in plan["steps"]) and state.get("trail"):
        plan = copy.deepcopy(state["trail"][-1])
    result_steps = [step for step in plan["steps"] if step["operation"] in {
        "project_results", "sample_results", "project_results_compare", "sample_results_compare", "sample_failures"}]
    from .result_corrections import parse_correction
    correction, question = parse_correction(original) if result_steps else (None, None)
    if question:
        return None, question
    if correction:
        if len(result_steps) != 1:
            return None, "Which result query should I correct? Start with one sample or project result list."
        step = result_steps[0]
        if step["operation"] == "sample_failures":
            step.update(operation="sample_results", filters={"qc": "failed"})
        filters = step.setdefault("filters", {})
        changes = correction["filters"]
        if "period" in changes or "created_from" in changes:
            for key in ["period", "created_from", "created_before"]:
                filters.pop(key, None)
        if "exclude_keys" in changes:
            changes["exclude_keys"] = list(dict.fromkeys(filters.get("exclude_keys", []) + changes["exclude_keys"]))
        filters.update(changes)
        if correction["target"]:
            target = correction["target"]
            step["arguments"] = {target["kind"]: target["identifier"]}
            step["operation"] = target["kind"] + "_results" + ("_compare" if step["operation"].endswith("_compare") else "")
        plan["steps"] = [step]
        return plan, None
    focus_match = re.fullmatch(r"(?:explain|show|compare) (?:the )?(?:(?:qc )?failure[- ]rates?(?: differences?)?|(numeric|measurement|count) differences?)(?: and link (?:the )?(?:supporting )?results)?", text)
    overview = text in {"show comparison overview", "explain comparison overview"}
    largest = re.fullmatch(r"explain (?:the )?(?:largest|biggest) (?:difference|change)(?: and link (?:the )?(?:supporting )?results)?", text)
    if focus_match or overview or largest:
        comparisons = [step for step in plan["steps"] if step["operation"].endswith("_compare")]
        if len(comparisons) != 1:
            return None, "Choose one sample or project result comparison first. Start with a result list, then ask to compare it with last week."
        focus = "overview" if overview else "counts" if largest else {"numeric": "numeric", "measurement": "numeric", "count": "counts"}.get(focus_match[1], "qc_rates")
        comparisons[0]["focus"] = focus
        plan["steps"] = comparisons
        return plan, None
    if re.match(r"(?:explain|show|compare) (?:the )?(?:qc )?(?:failure[- ]rates?|numeric|measurements?|counts?|comparison overview)\b", text):
        return None, "Choose count differences, failure-rate differences, or numeric differences for the current comparison. Change a filter in a separate request; no result query was run."
    detail = re.fullmatch(r"(?:explain|show|open) (?:the )?(first|second|third|fourth|\d+)(?:st|nd|rd|th)? result", text)
    if detail:
        index = {"first": 1, "second": 2, "third": 3, "fourth": 4}.get(detail[1])
        index = int(detail[1]) if index is None else index
        ids = state["result_ids"]
        if not 1 <= index <= len(ids):
            return None, "Choose a result number from the displayed results."
        return {"route": "read_plan", "confidence": 1.0, "steps": [
            {"operation": "result_detail", "arguments": {"result_id": str(ids[index - 1])}}]}, None
    from .result_filter_language import PERIOD
    compare = re.fullmatch(r"compare (?:those |these |them |those results |these results )?with (" + PERIOD + r")", text)
    switch = re.fullmatch(r'(?:apply (?:the )?same filters to|same filters for|same for|what about) (sample|project) ("[^"\n]{1,128}"|[\w.:/-]{1,128})', original, re.I)
    clear = re.fullmatch(r"clear (date|qc|keys|excluded keys|instrument|operator|comparison) filter", text)
    from .result_filter_language import parse_filters
    try:
        changes = parse_filters(original)
    except ValueError:
        changes = None
    if not any([changes, compare, switch, clear]):
        if re.match(r"(?:only|since|from|excluding|exclude|without|clear .* filter|apply .*filters)\b", text):
            return None, "I could not preserve every requested filter. No result query was run. Use an exact date range, weekday, QC status, result key, instrument code or operator username."
        return None, None
    if len(result_steps) != 1:
        return None, "Which result query should I change? Ask for one sample or project result list first."
    step = result_steps[0]
    if step["operation"] == "sample_failures":
        step["operation"] = "sample_results"
        step["filters"] = {"qc": "failed"}
    filters = step.setdefault("filters", {})
    if changes and ("period" in changes or "created_from" in changes):
        filters.pop("period", None)
        filters.pop("created_from", None)
        filters.pop("created_before", None)
    if changes:
        filters.update(changes)
    if compare:
        step["operation"] = step["operation"].removesuffix("_compare") + "_compare"
        filters["compare_period"] = compare[1].replace("previous month", "last month").replace(" ", "_")
    if switch:
        kind, target = switch.groups()
        kind = kind.lower()
        step["arguments"] = {kind: target.strip('"')}
        step["operation"] = kind + "_results" + ("_compare" if step["operation"].endswith("_compare") else "")
    if clear:
        for key in {"date": ["period", "created_from", "created_before"], "qc": ["qc"], "keys": ["keys"],
                    "excluded keys": ["exclude_keys"], "comparison": ["compare_period"]}.get(clear[1], [clear[1]]):
            filters.pop(key, None)
        if clear[1] == "comparison":
            step["operation"] = step["operation"].removesuffix("_compare")
            step.pop("focus", None)
    # A follow-up changes the selected query, not unrelated reads in the earlier plan.
    plan["steps"] = [step]
    return plan, None


def explicit_result_plan(message):
    text = message.strip().rstrip(".!?")
    text = re.sub(r"^(show|list|find)\s+(?:the\s+)?QC\s+failures\s+", r"\1 failed QC results ", text, flags=re.I)
    match = re.fullmatch(r'(?:show|list|find)\s+(?:(failed|passed|pending|rejected|approved)\s+)?(?:QC\s+)?results?\s+(?:for|in)\s+(sample|project)\s+("[^"\n]{1,128}"|[\w.:/-]{1,128})(.*)', text, re.I)
    if not match:
        return None
    qc, kind, identifier, suffix = match.groups()
    filters = {"qc": qc.lower()} if qc else {}
    from .result_filter_language import parse_filters
    try:
        parsed = parse_filters(suffix)
    except ValueError:
        return None
    if parsed is None or parsed.keys() & filters.keys():
        return None
    filters.update(parsed)
    return {"route": "read_plan", "confidence": 1.0, "steps": [
        {"operation": f"{kind.lower()}_results", "arguments": {kind.lower(): identifier.strip('"')}, "filters": filters}]}
