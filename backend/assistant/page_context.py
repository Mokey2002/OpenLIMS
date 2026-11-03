"""Explicit page-relative reads. A client page reference never grants access."""
import re
import uuid

from rest_framework import serializers

from .lab_helpers import response


class AssistantPageContextSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["sample", "project"])
    record_id = serializers.CharField(max_length=64)

    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - {"kind", "record_id"}:
            raise serializers.ValidationError("Only kind and record_id are supported.")
        return super().to_internal_value(data)

    def validate(self, attrs):
        value = attrs["record_id"]
        if re.fullmatch(r"[1-9]\d{0,17}", value):
            return attrs
        try:
            attrs["record_id"] = str(uuid.UUID(value))
        except ValueError:
            raise serializers.ValidationError("Use a positive record ID or public UUID.")
        return attrs


# Complete, read-only phrases; never strip extra conditions or mutation clauses.
TASKS = {
    "summary": r"(?:summarize|explain|give me (?:a |the )?summary of) (?:this|the current|the open)(?: (?:sample|project|record))?",
    "evidence": r"(?:show (?:the )?evidence for|why does) (?:this|this sample)(?: need attention)?",
    "guidance": r"why is (?:this|this sample) blocked|what(?:'s| is) (?:holding (?:this|this sample) up|next for (?:this|this sample))|what should I check first for (?:this|this sample)",
    "results": r"(?:show|list|find)(?: me)? (?:the )?results (?:for|of|in) (?:this|this sample|this project)|show (?:this sample|this project)'s results",
    "history": r"(?:show (?:the )?history (?:for|of)|what happened to) (?:this|this sample)",
    "samples": r"(?:show|list) (?:the )?samples in (?:this|this project)",
}
PAGE_RESULTS = re.compile(
    r"(?:show|list|find)(?: me)? (?:the )?(?:(failed|passed|pending|rejected|approved) )?(?:QC )?results? "
    r"(?:for|of|in) (?:this|the current|the open)(?: (?:sample|project|record))?(?=\s|$)(.*)", re.I,
)


def _resolve(page, user):
    from .sample_operations import _sample_queryset
    from .lab_reviews import _projects
    records = _sample_queryset(user) if page["kind"] == "sample" else _projects(user)
    value = page["record_id"]
    return records.filter(**({"pk": int(value)} if value.isdecimal() else {"public_id": value})).first()


def _unavailable():
    return response("The page record was not found or is no longer accessible. Reopen an accessible sample or project and ask again.",
                    context={}, replace_context=True, clarification={"required": True})


def _read(task, page, user, filters=None):
    record = _resolve(page, user)
    if record is None:
        return _unavailable()
    kind = page["kind"]
    label = record.sample_id if kind == "sample" else record.code
    if task == "results":
        from .read_plans import handle_read_plan
        from .read_plan_memory import KEY, remember
        plan = {"route": "read_plan", "confidence": 1.0, "steps": [
            {"operation": f"{kind}_results", "arguments": {kind: label}, "filters": filters or {}}]}
        result = handle_read_plan("read current page results", user, context={KEY: remember(plan, [], user)}, restored_plan=True)
    elif kind == "project":
        from .project_conversation import project_briefing, project_sample_list
        result = (project_sample_list if task == "samples" else project_briefing)(record, user)
        result["context"]["read_intent"] = "project_samples" if task == "samples" else "project_summary"
    elif task == "guidance":
        from .sample_guidance import route_sample_guidance
        result = route_sample_guidance("What's holding this up?", user, {"sample_code": label, "sample_id": record.pk})
    elif task == "history":
        from .lab_helpers import sample_history
        result = sample_history(label, user)
        result["context"] = {"sample_id": record.pk, "sample_code": label, "read_intent": "sample_history"}
    else:
        from .sample_explanations import route_sample_explanations
        result = route_sample_explanations("Show supporting evidence" if task == "evidence" else "Explain this more simply",
                                           user, {"sample_id": record.pk, "sample_code": label})
    if not result:
        return _unavailable()
    result["replace_context"] = True
    result["page_read_reference"] = {"kind": kind, "record_id": str(record.public_id), "task": task}
    if filters:
        result["page_read_reference"]["filters"] = filters
    result["page_context_used"] = {"kind": kind, "record_id": str(record.public_id), "label": label}
    if task != "results":
        result.setdefault("citations", []).append({"kind": kind, "id": record.pk, "label": label,
            "url": f"/{'samples' if kind == 'sample' else 'projects'}/{record.pk}",
            "scope": "Current accessible page record; see the answer for bounded history/workflow/result limits."})
    return result


def route_page_read(message, user, page, context=None):
    if not page:
        return None
    from .natural_requests import normalize_request
    text = normalize_request(message)
    deictic = (re.search(r"\b(?:this|current|open) (?:sample|project|record|results?)\b", text, re.I)
               or re.search(r"\bthis\b(?=\s*(?:$|[?.!;,]|and\b|because\b))", text, re.I))
    if deictic and re.search(r"(?:^|;\s*|\band\s+)(?:please\s+)?(?:approve|reject|assign|delete|archive|create|run|import|update|move|complete)\b", text, re.I):
        return response("For a change, name the exact record and request the action explicitly. Page context is only used for supported reads; no action preview was created.",
                        context=context or {}, clarification={"required": True})
    task = next((task for task, pattern in TASKS.items() if re.fullmatch(pattern, text, re.I)), None)
    filters = {}
    result_request = PAGE_RESULTS.fullmatch(text)
    if result_request:
        from .result_filter_language import parse_filters
        from .result_queries import validate_filters
        qc, suffix = result_request.groups()
        try:
            filters = parse_filters(suffix)
        except ValueError:
            filters = None
        if filters is not None and qc:
            filters = None if "qc" in filters else {"qc": qc.lower(), **filters}
        if filters is not None:
            filters = validate_filters(filters, f"{page['kind']}_results")
        if filters is None:
            return response("I could not preserve every requested page filter. Use a supported date window, QC status, exact result key, instrument code or operator username. "
                            "No query was run; the previous conversation is retained.", context=context or {}, clarification={"required": True})
        task = "results"
    if task is None:
        if re.search(r"\b(?:this|the current|the open) (?:sample|project|record)\b", text, re.I):
            kind = page["kind"]
            return response(f"Try 'Summarize this {kind}' or 'Show results for this {kind} yesterday'. "
                            "I could not interpret the complete request, so no page query was run.",
                            context=context or {}, clarification={"required": True})
        return None
    kind = page["kind"]
    explicit_kind = re.search(r"\b(?:this|the current|the open) (sample|project)\b", text, re.I)
    if (explicit_kind and explicit_kind[1].lower() != kind
            or kind == "project" and task in {"evidence", "guidance", "history"}
            or kind == "sample" and task == "samples"):
        return response("The requested read does not match the open page. Open the relevant sample/project or give its exact identifier.",
                        context=context or {}, clarification={"required": True})
    return _read(task, page, user, filters)


def restore_page_read(reference, user):
    kind, task = reference.get("kind"), reference.get("task")
    if (kind not in {"sample", "project"} or task not in TASKS
            or kind == "project" and task not in {"summary", "samples", "results"}
            or kind == "sample" and task == "samples"):
        return _unavailable()
    serializer = AssistantPageContextSerializer(data={key: reference.get(key) for key in ["kind", "record_id"]})
    if not serializer.is_valid():
        return _unavailable()
    from .result_queries import validate_filters
    filters = validate_filters(reference.get("filters", {}), f"{kind}_results")
    if filters is None or filters and task != "results":
        return _unavailable()
    return _read(task, serializer.validated_data, user, filters)
