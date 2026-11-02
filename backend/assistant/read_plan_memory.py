"""User-bound references to the last read plan. Never retain record values."""
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
    ids = state.get("result_ids", [])
    if not isinstance(ids, list) or len(ids) > 80 or any(type(pk) is not int or not 0 < pk < 2**63 for pk in ids):
        return None
    return state


def remember(plan, result_ids, user):
    token = signing.dumps({"user": user.pk, "plan": plan, "result_ids": list(dict.fromkeys(result_ids))[:80]}, salt=SALT, compress=True)
    return token if len(token) <= MAX_TOKEN else None


def resume(message, context, user):
    """Return a server-resolved plan, or an explicit ambiguity question."""
    original = message.strip().rstrip(".!?")
    text = original.lower()
    state = recall(context, user)
    if not state:
        return None, None
    import copy
    plan = copy.deepcopy(state["plan"])
    if re.fullmatch(r"explain (?:the )?(?:largest|biggest) (?:difference|change)(?: and link (?:the )?(?:supporting )?results)?", text):
        if any(step["operation"].endswith("_compare") for step in plan["steps"]):
            return plan, None
        return None, "Which two periods should I compare? Start with a result list, then ask to compare it with last week."
    result_steps = [step for step in plan["steps"] if step["operation"] in {
        "project_results", "sample_results", "project_results_compare", "sample_results_compare", "sample_failures"}]
    detail = re.fullmatch(r"(?:explain|show|open) (?:the )?(first|second|third|fourth|\d+)(?:st|nd|rd|th)? result", text)
    if detail:
        index = {"first": 1, "second": 2, "third": 3, "fourth": 4}.get(detail[1])
        index = int(detail[1]) if index is None else index
        ids = state["result_ids"]
        if not 1 <= index <= len(ids):
            return None, "Choose a result number from the displayed results."
        return {"route": "read_plan", "confidence": 1.0, "steps": [
            {"operation": "result_detail", "arguments": {"result_id": str(ids[index - 1])}}]}, None
    period = re.fullmatch(r"(?:only |from |only from )?(today|yesterday|last week|this week|last 7 days)", text)
    compare = re.fullmatch(r"compare (?:those |these |them |those results |these results )?with (today|yesterday|last week|this week|last 7 days)", text)
    qc = re.fullmatch(r"only (failed|passed|pending|rejected|approved)(?: (?:ones|results|checks))?", text)
    exclude = re.fullmatch(r"(?:exclude|excluding|without) (?:the )?(?:result )?keys? ([\w.:/-]+(?:\s*,\s*[\w.:/-]+)*)", original, re.I)
    keys = re.fullmatch(r"only (?:the )?(?:result )?key ([\w.:/-]+)", original, re.I)
    if not any([period, compare, qc, exclude, keys]):
        return None, None
    if len(result_steps) != 1:
        return None, "Which result query should I change? Ask for one sample or project result list first."
    step = result_steps[0]
    if step["operation"] == "sample_failures":
        step["operation"] = "sample_results"
        step["filters"] = {"qc": "failed"}
    filters = step.setdefault("filters", {})
    if period:
        filters.pop("created_from", None)
        filters.pop("created_before", None)
        filters["period"] = period[1].replace(" ", "_")
    if compare:
        step["operation"] = step["operation"].removesuffix("_compare") + "_compare"
        filters["compare_period"] = compare[1].replace(" ", "_")
    if qc:
        filters["qc"] = qc[1]
    if exclude:
        filters["exclude_keys"] = [item.strip() for item in exclude[1].split(",")]
    if keys:
        filters["keys"] = [keys[1]]
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
    suffix = suffix.strip()
    exclusion = re.search(r"\s*(?:excluding|except|without) (?:the )?(?:result )?keys? ([\w.:/-]+(?:\s*,\s*[\w.:/-]+)*)$", suffix, re.I)
    if exclusion:
        filters["exclude_keys"] = [item.strip() for item in exclusion[1].split(",")]
        suffix = suffix[:exclusion.start()].strip()
    if suffix:
        period = re.fullmatch(r"(?:from |for )?(today|yesterday|last week|this week|last 7 days)", suffix, re.I)
        dates = re.fullmatch(r"from (\d{4}-\d{2}-\d{2}) (?:until|before) (\d{4}-\d{2}-\d{2})", suffix, re.I)
        if period:
            filters["period"] = period[1].lower().replace(" ", "_")
        elif dates:
            filters.update(created_from=dates[1], created_before=dates[2])
        else:
            return None
    return {"route": "read_plan", "confidence": 1.0, "steps": [
        {"operation": f"{kind.lower()}_results", "arguments": {kind.lower(): identifier.strip('"')}, "filters": filters}]}
