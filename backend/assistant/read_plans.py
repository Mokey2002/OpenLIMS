"""Bounded, typed read plans. No command router or action executor is reachable."""
import math
import re

from django.db.models import Q
from django.utils import timezone

from .lab_helpers import response

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
    if not isinstance(steps, list) or not 2 <= len(steps) <= MAX_STEPS:
        return None
    clean = []
    for step in steps:
        if not isinstance(step, dict) or set(step) != {"operation", "arguments"}:
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
        clean.append({"operation": operation, "arguments": {k: v.strip() for k, v in args.items()}})
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
            return None
        steps.append(step)
    return validate_read_plan({"route": "read_plan", "steps": steps, "confidence": 1.0})


def _grounded(plan, message):
    # Models may rearrange reads, but cannot invent record identities or silently
    # add hidden targets. This first version requires identifiers in this turn.
    return all(re.search(r"(?<!\w)" + re.escape(value.rstrip('.!?')) + r"(?!\w)", message, re.I)
               for step in plan["steps"] for value in step["arguments"].values())


def _read(step, user):
    operation, args = step["operation"], step["arguments"]
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
                            context={"sample_id": sample.pk}, failure_results=rows)
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
        return result
    from .sop_operations import search_sops
    return search_sops(args["question"], user)


def handle_read_plan(message, user, plan=None):
    if plan is None and not is_compound_read(message):
        return None
    validated = validate_read_plan(plan) if plan is not None else parse_read_plan(message)
    # Never let a classifier drop a requested mutation/negation and execute a
    # convenient read-only subset. Single-action flows remain in their own path.
    unquoted = re.sub(r'"[^"\n]*"', '', message)
    prohibited = any(re.match(r"(?:please\s+)?(?:approve|reject|assign|delete|archive|create|run|import|update|move)\b", clause, re.I)
                     for clause in _clauses(unquoted)) or re.search(r"\b(?:do not|don't|except|excluding|without)\b", unquoted, re.I)
    if prohibited:
        return response("Please separate changes or exclusions from this combined read request. "
                        "I have not run any part of it.", clarification={"required": True}, requires_read_plan=True)
    if not validated or not _grounded(validated, message):
        return response("I need two to four complete supported read requests with exact sample IDs, project codes, or run IDs/titles. "
                        "Include the SOP topic explicitly. I have not run any part of this request. Changes must be requested separately.",
                        clarification={"required": True}, route_unmatched=plan is None,
                        requires_read_plan=True)
    steps, citations, links = [], [], []
    context = {}
    for step in validated["steps"]:
        result = _read(step, user)
        unavailable = result.get("unavailable", False)
        entry = {**step, "status": "unavailable" if unavailable else "completed", "answer": result["answer"],
                 "citations": result.get("citations", []), "comparison": result.get("comparison")}
        steps.append(entry)
        citations.extend(entry["citations"])
        links.extend(result.get("links", []))
        if not unavailable:
            context = result.get("context") or context
    # Ambiguous multi-record follow-ups must ask again instead of picking the last record.
    sample_ids = {entry["arguments"]["sample"].casefold() for entry in steps if "sample" in entry["arguments"]}
    project_ids = {entry["arguments"]["project"].casefold() for entry in steps if "project" in entry["arguments"]}
    if len(sample_ids) > 1 or len(project_ids) > 1 or (sample_ids and project_ids):
        context = {}
    unique_citations = list({(c.get("kind"), c.get("url"), c.get("label")): c for c in citations}.values())
    return response("\n\n".join(f"{i}. {entry['operation'].replace('_', ' ').capitalize()} — {entry['status']}\n{entry['answer']}"
                               for i, entry in enumerate(steps, 1)),
                    context=context, citations=unique_citations,
                    links=list({link["url"]: link for link in links}.values()),
                    read_plan={"read_only": True, "as_of": timezone.now().isoformat(), "steps": steps,
                               "partial": any(entry["status"] != "completed" for entry in steps),
                               "scope": "Each step reads current accessible records independently. This is not a single database snapshot. No scientific cause or approval is inferred."})
