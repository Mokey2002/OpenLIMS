"""Bounded, typed read plans. No command router or action executor is reachable."""
import math
import re

from django.db.models import Q
from django.utils import timezone

from .lab_helpers import response
from .result_queries import QUERY_OPERATIONS, validate_filters

MAX_STEPS = 4
OPERATIONS = {
    "sample_summary": ("sample",),
    "sample_evidence": ("sample",),
    "sample_failures": ("sample",),
    "sample_history": ("sample",),
    "project_summary": ("project",),
    "project_samples": ("project",),
    "compare_runs": ("left", "right"),
    "sop_search": ("question",),
}
OPERATIONS.update(QUERY_OPERATIONS)
IDENTIFIER = r'(?:"[^"\n]{1,128}"|[\w][\w.:/-]{0,127})'
SEPARATOR = re.compile(
    r'\s*;\s*|\s*,?\s+(?:and\s+(?:then\s+)?|then\s+)'
    r'(?=(?:show|explain|summarize|compare|find|list|what|which|how|'
    r'approve|reject|assign|delete|archive|create|run|import|update|move)\b)', re.I,
)


def catalog_prompt():
    return "\n".join(f"- {name}: {', '.join(fields)}" for name, fields in OPERATIONS.items())


def validate_read_plan(data, threshold=0.65):
    if not isinstance(data, dict) or data.get("route") != "read_plan":
        return None
    if set(data) - {"route", "steps", "confidence", "provider", "accepted"}:
        return None
    confidence = data.get("confidence")
    if type(confidence) not in (int, float) or not math.isfinite(confidence) or not threshold <= confidence <= 1:
        return None
    steps = data.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        return None
    if len(steps) == 1 and (not isinstance(steps[0], dict) or steps[0].get("operation") not in QUERY_OPERATIONS):
        return None
    clean = []
    for step in steps:
        if not isinstance(step, dict) or not {"operation", "arguments"} <= set(step) or set(step) - {"operation", "arguments", "filters"}:
            return None
        operation, args = step["operation"], step["arguments"]
        if not isinstance(operation, str) or operation not in OPERATIONS:
            return None
        if not isinstance(args, dict) or set(args) != set(OPERATIONS[operation]):
            return None
        for key, value in args.items():
            if (not isinstance(value, str) or not value.strip()
                    or len(value) > (500 if key == "question" else 128)
                    or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
                return None
        if operation == "result_detail" and not re.fullmatch(r"[1-9]\d{0,17}", args["result_id"]):
            return None
        filters = validate_filters(step.get("filters", {}), operation)
        if filters is None:
            return None
        entry = {"operation": operation, "arguments": {k: v.strip() for k, v in args.items()}}
        if filters:
            entry["filters"] = filters
        clean.append(entry)
    return {"route": "read_plan", "steps": clean, "confidence": confidence, "accepted": True}


def _clauses(message):
    # A quoted run title may itself contain "and show" or a semicolon.
    cuts = [match for match in SEPARATOR.finditer(message)
            if message[:match.start()].count('"') % 2 == 0]
    starts = [0] + [match.end() for match in cuts]
    ends = [match.start() for match in cuts] + [len(message)]
    return [message[start:end].strip().rstrip(".!?") for start, end in zip(starts, ends)
            if message[start:end].strip()]


def is_compound_read(message):
    return len(_clauses(message)) > 1 and bool(re.search(
        r"\b(?:samples?|projects?|runs?|experiments?|sops?|qc|history|evidence)\b", message, re.I))


def parse_read_plan(message):
    """Recognize complete clauses; an unknown clause invalidates the whole plan."""
    parts = _clauses(message)
    if not 2 <= len(parts) <= MAX_STEPS:
        return None
    steps, samples = [], set()
    for part in parts:
        step = None
        patterns = [
            ("sample_summary", rf"(?:summarize|explain) sample ({IDENTIFIER})"),
            ("sample_evidence", rf"show (?:me )?(?:the )?evidence for sample ({IDENTIFIER})"),
            ("sample_failures", rf"(?:show|list) (?:the )?failed QC results for sample ({IDENTIFIER})"),
            ("sample_history", rf"show (?:the )?history (?:for|of) sample ({IDENTIFIER})"),
            ("project_summary", rf"summarize project ({IDENTIFIER})"),
            ("project_samples", rf"(?:show|list) samples in project ({IDENTIFIER})"),
        ]
        for operation, pattern in patterns:
            match = re.fullmatch(pattern, part, re.I)
            if match:
                key = OPERATIONS[operation][0]
                value = match[1].strip('"')
                step = {"operation": operation, "arguments": {key: value}}
                if key == "sample":
                    samples.add(value)
                break
        if step is None and len(samples) == 1:
            operation = {"show its history": "sample_history", "show the evidence": "sample_evidence",
                         "show its failed qc results": "sample_failures"}.get(part.lower())
            if operation:
                step = {"operation": operation, "arguments": {"sample": next(iter(samples))}}
        if step is None:
            match = re.fullmatch(rf"compare (?:runs|experiments) ({IDENTIFIER}) (?:and|with|versus|vs\.?) ({IDENTIFIER})", part, re.I)
            if match:
                step = {"operation": "compare_runs", "arguments": {"left": match[1].strip('"'), "right": match[2].strip('"')}}
        if step is None and re.fullmatch(r"(?:what does the SOP say about|(?:show|find) (?:the )?(?:relevant )?SOP (?:for|about)) .+", part, re.I):
            step = {"operation": "sop_search", "arguments": {"question": part}}
        if step is None:
            from .read_plan_memory import explicit_result_plan
            parsed = explicit_result_plan(part)
            if parsed:
                step = parsed["steps"][0]
        if step is None:
            return None
        steps.append(step)
    return validate_read_plan({"route": "read_plan", "steps": steps, "confidence": 1.0})


def _grounded(plan, message):
    # Models may rearrange reads, but cannot invent record identities or silently
    # add hidden targets. This first version requires identifiers in this turn.
    tokens = {match.group(1).casefold() if match.group(1) is not None else match.group(2).rstrip('.!?').casefold()
              for match in re.finditer(r'"([^"\n]+)"|([\w][\w.:/-]*)', message)}
    for step in plan["steps"]:
        for key, value in step["arguments"].items():
            if key == "question":
                if value.rstrip('.!?').casefold() not in message.casefold():
                    return False
            elif value.casefold() not in tokens and not (key == "result_id" and f"r-{value}" in tokens):
                return False
    return True


def _read(step, user):
    operation, args = step["operation"], step["arguments"]
    if operation in QUERY_OPERATIONS:
        from .result_queries import read_results
        return read_results(step, user)
    if operation.startswith("sample_"):
        from .sample_operations import _sample_queryset
        matches = list(_sample_queryset(user).filter(sample_id__iexact=args["sample"])[:2])
        if len(matches) != 1:
            return response("Sample not found, not accessible, or ambiguous. Use one exact accessible sample ID.", unavailable=True)
        sample = matches[0]
        if operation == "sample_history":
            from .lab_helpers import sample_history
            result = sample_history(sample.sample_id, user)
            result["citations"] = [{"kind": "sample", "label": sample.sample_id, "url": f"/samples/{sample.pk}",
                                    "scope": "Latest 50 audit/custody events and 10 current results; see history limits."}]
            return result
        if operation == "sample_failures":
            from results.models import Result
            from .sample_briefing import _result_evidence, _result_line
            from .evidence import sample_citations
            results = Result.objects.filter(work_item__sample=sample).filter(Q(qc_passed=False) | Q(qc_status=Result.QC_REJECTED))
            total = results.count()
            rows = [_result_evidence(row) for row in results.select_related("work_item__source_import_job__instrument").order_by("-created_at", "-pk")[:20]]
            briefing = {"recent_results": rows, "attention": {"results": [], "work_items": []}}
            return response(f"{sample.sample_id}: showing {len(rows)} of {total} results with a failed QC check or rejected review.\n"
                            + "\n".join(_result_line(row) for row in rows)
                            + "\nQC checks and review decisions are separate; results may be historical. This does not establish a scientific cause.",
                            citations=sample_citations(sample, briefing),
                            context={"sample_id": sample.pk}, failure_results=rows,
                            selected_result_ids=[row["id"] for row in rows])
        from .sample_explanations import route_sample_explanations
        command = "Show evidence for sample" if operation == "sample_evidence" else "Explain sample"
        return route_sample_explanations(f'{command} "{sample.sample_id}"', user)
    if operation.startswith("project_"):
        from .lab_reviews import _projects
        from .project_conversation import project_briefing, project_sample_list
        matches = list(_projects(user).filter(code__iexact=args["project"])[:2])
        if len(matches) != 1:
            return response("Project not found, not accessible, or ambiguous. Use one exact accessible project code.", unavailable=True)
        project = matches[0]
        result = (project_briefing if operation == "project_summary" else project_sample_list)(project, user)
        result["citations"] = [{"kind": "project", "label": project.code, "url": f"/projects/{project.pk}",
                                "scope": "Current accessible primary and linked samples; see table limits."}]
        return result
    if operation == "compare_runs":
        from .lab_collaboration import compare_runs
        result = compare_runs(args["left"], args["right"], user)
        if not result.get("comparison"):
            result["unavailable"] = True
        result["citations"] = [{"kind": "experiment", **link, "scope": "Current recorded run comparison; differences do not establish causes."}
                               for link in result.get("links", [])]
        if result.get("comparison") and len(result.get("links", [])) == 2:
            result["reference"] = {"kind": "experiments", "left": result["links"][0]["url"].split("experiment=", 1)[1],
                                   "right": result["links"][1]["url"].split("experiment=", 1)[1]}
        return result
    from .sop_operations import search_sops
    return search_sops(args["question"], user)


def handle_read_plan(message, user, plan=None, context=None, *, restored_plan=False):
    from .read_plan_memory import KEY, explicit_result_plan, recall, remember, resume
    from .chat_progress import emit
    resumed = False
    if plan is None:
        if restored_plan:
            from .read_plan_memory import recall
            state = recall(context, user)
            plan, question = (state["plan"] if state else None), None
        else:
            plan, question = resume(message, context, user)
        if question:
            return response(question, clarification={"required": True}, context=context or {})
        resumed = plan is not None
        plan = plan or explicit_result_plan(message)
        if plan is None and not is_compound_read(message) and re.match(r"(?:show|list|find)\s+(?:(?:failed|passed|pending|rejected|approved)\s+)?(?:QC\s+)?(?:results?|failures)\s+(?:for|in)\s+(?:sample|project)\b", message, re.I):
            return response("I could not preserve every requested filter. Use a QC status, a supported date window, an exact result key, instrument code or entered-by username. "
                            "No result query was run.", clarification={"required": True}, requires_read_plan=True)
    if plan is None and not is_compound_read(message):
        return None
    validated = validate_read_plan(plan) if plan is not None else parse_read_plan(message)
    # Never let a classifier drop a requested mutation/negation and execute a
    # convenient read-only subset. Single-action flows remain in their own path.
    unquoted = re.sub(r'"[^"\n]*"', '', message)
    mutation = any(re.match(r"(?:please\s+)?(?:approve|reject|assign|delete|archive|create|run|import|update|move)\b", clause, re.I)
                   for clause in _clauses(unquoted))
    exclusion = re.search(r"\b(?:except|excluding|without)\b", unquoted, re.I)
    typed_exclusion = validated and all(step["operation"] in QUERY_OPERATIONS and step.get("filters", {}).get("exclude_keys") for step in validated["steps"])
    prohibited = mutation or re.search(r"\b(?:do not|don't)\b", unquoted, re.I) or (exclusion and not typed_exclusion)
    if prohibited:
        return response("Please separate changes or exclusions from this combined read request. "
                        "I have not run any part of it.", clarification={"required": True}, requires_read_plan=True)
    if (not validated and isinstance(plan, dict) and isinstance(plan.get("steps"), list)
            and any(isinstance(step.get("operation"), str) and step["operation"] in QUERY_OPERATIONS
                    for step in plan["steps"] if isinstance(step, dict))):
        return response("The result filters are invalid or conflicting. Check the date range (start inclusive, end exclusive), QC status, keys, instrument code and entered-by username. No result query was run.",
                        clarification={"required": True}, context=(context or {}) if resumed else {}, requires_read_plan=True)
    if not validated or (not resumed and not _grounded(validated, message)):
        return response("I need two to four complete supported read requests with exact sample IDs, project codes, or run IDs/titles. "
                        "Include the SOP topic explicitly. I have not run any part of this request. Changes must be requested separately.",
                        clarification={"required": True}, route_unmatched=plan is None,
                        requires_read_plan=True)
    steps, citations, links, result_ids = [], [], [], []
    next_context = {}
    for step in validated["steps"]:
        emit("progress", message=f"Reading {step['operation'].replace('_', ' ')}", step=len(steps) + 1, total=len(validated["steps"]))
        result = _read(step, user)
        emit("checkpoint")
        unavailable = result.get("unavailable", False)
        entry = {**step, "status": "unavailable" if unavailable else "completed", "answer": result["answer"],
                 "citations": result.get("citations", []), "comparison": result.get("comparison"),
                 "result_query": result.get("result_query"), "sample_briefing": result.get("sample_briefing")}
        entry["statistics_tables"] = result.get("statistics_tables", [])
        target_context = result.get("context", {})
        entry["reference"] = result.get("reference") or next(({"kind": kind, "id": target_context[kind + "_id"]}
                                   for kind in ["sample", "project"] if target_context.get(kind + "_id")), None)
        steps.append(entry)
        citations.extend(entry["citations"])
        links.extend(result.get("links", []))
        result_ids.extend(result.get("selected_result_ids", []))
        if not unavailable:
            next_context = result.get("context") or next_context
    # Ambiguous multi-record follow-ups must ask again instead of picking the last record.
    sample_ids = {entry["arguments"]["sample"].casefold() for entry in steps if "sample" in entry["arguments"]}
    project_ids = {entry["arguments"]["project"].casefold() for entry in steps if "project" in entry["arguments"]}
    if len(sample_ids) > 1 or len(project_ids) > 1 or (sample_ids and project_ids):
        next_context = {}
    unique_citations = list({(c.get("kind"), c.get("url"), c.get("label")): c for c in citations}.values())
    token = remember(validated, result_ids, user, previous=recall(context, user))
    if token:
        next_context[KEY] = token
    if len(steps) == 1 and steps[0]["operation"] == "result_detail":
        state = recall(next_context, user)
        if state and state.get("trail"):
            next_context["investigation_navigation"] = {"can_return": True, "comparison": any(
                step["operation"].endswith("_compare") for plan in state["trail"] for step in plan["steps"])}
    from .answer_overview import build_overview
    overview = build_overview(steps, unique_citations)
    return response("\n\n".join(f"{i}. {entry['operation'].replace('_', ' ').capitalize()} — {entry['status']}\n{entry['answer']}"
                               for i, entry in enumerate(steps, 1)),
                    context=next_context, citations=unique_citations, answer_overview=overview,
                    read_plan_spec=validated,
                    links=list({link["url"]: link for link in links}.values()),
                    read_plan={"read_only": True, "as_of": timezone.now().isoformat(), "steps": steps,
                               "partial": any(entry["status"] != "completed" for entry in steps),
                               "scope": "Each step reads current accessible records independently. This is not a single database snapshot. No scientific cause or approval is inferred."})
