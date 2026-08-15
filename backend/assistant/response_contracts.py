import re


VISUAL_REQUEST_PATTERN = re.compile(
    r"\b(?:chart|graph|plot|scatter|bars?|dots?|points?|visuali[sz]e)\b",
    re.IGNORECASE,
)


def visual_requested(message):
    return bool(VISUAL_REQUEST_PATTERN.search(str(message or "")))


def _record_count(result):
    comparison = result.get("comparison") or {}
    if isinstance(comparison.get("rows"), list):
        return len(comparison["rows"])
    investigation = result.get("investigation") or {}
    if isinstance(investigation.get("findings"), list):
        return len(investigation["findings"])
    links = result.get("links") or []
    return len(links) if isinstance(links, list) else 0


def normalize_assistant_response(message, result):
    normalized = dict(result or {})
    normalized["answer"] = str(normalized.get("answer") or "No answer returned.")
    normalized["links"] = list(normalized.get("links") or [])[:100]
    normalized["suggestions"] = [
        str(value).strip()
        for value in (normalized.get("suggestions") or [])
        if str(value).strip()
    ][:8]

    requested_visual = visual_requested(message)
    chart = normalized.get("chart")
    if chart and not requested_visual and not normalized.pop("chart_required", False):
        normalized["chart_available"] = {
            "chartType": chart.get("chartType", "auto") if isinstance(chart, dict) else "auto",
            "message": "A chart is available if you ask to graph or plot this result.",
        }
        normalized["chart"] = None
        normalized["answer"] = re.sub(
            r"\bGraphed\b",
            "Summarized",
            normalized["answer"],
            count=1,
        )

    if normalized.get("chart"):
        display_mode = "chart"
    elif normalized.get("comparison"):
        display_mode = "table"
    elif normalized.get("clarification"):
        display_mode = "clarification"
    elif normalized.get("pending_action"):
        display_mode = "action_preview"
    else:
        display_mode = "text"

    normalized["presentation"] = {
        "mode": display_mode,
        "chart_requested": requested_visual,
        "record_count": _record_count(normalized),
        "has_evidence": bool(
            normalized.get("investigation")
            or normalized.get("comparison")
            or normalized.get("links")
        ),
    }
    normalized["response_contract"] = {
        "version": "1.0",
        "summary": normalized["answer"],
        "display_mode": display_mode,
        "record_count": normalized["presentation"]["record_count"],
        "has_evidence": normalized["presentation"]["has_evidence"],
        "next_actions": normalized["suggestions"],
    }
    normalized.setdefault("response_type", display_mode)
    return normalized
