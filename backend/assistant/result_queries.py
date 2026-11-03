"""Typed result filters and comparisons; all calculations stay in the backend."""
import re
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from results.models import Result
from .lab_helpers import response
from .sample_briefing import _result_evidence, _result_line, _reference_evidence
from .sample_operations import _sample_queryset

QUERY_OPERATIONS = {
    "project_results": ("project",), "sample_results": ("sample",),
    "project_results_compare": ("project",), "sample_results_compare": ("sample",),
    "result_detail": ("result_id",),
}
PERIODS = {"today", "yesterday", "this_week", "last_week", "last_7_days", "this_month", "last_month"}
QC_FILTERS = {"failed", "passed", "pending", "rejected", "approved", "all"}
FILTER_KEYS = {"period", "created_from", "created_before", "qc", "keys", "exclude_keys", "compare_period", "instrument", "operator"}
ROW_LIMIT = 20


def validate_filters(filters, operation):
    if not isinstance(filters, dict) or set(filters) - FILTER_KEYS:
        return None
    if operation not in QUERY_OPERATIONS and filters:
        return None
    clean = {}
    for key, value in filters.items():
        if key in {"period", "compare_period"}:
            if not isinstance(value, str) or value not in PERIODS:
                return None
        elif key == "qc":
            if not isinstance(value, str) or value not in QC_FILTERS:
                return None
        elif key in {"instrument", "operator"}:
            if not isinstance(value, str) or not re.fullmatch(r"[\w.@+:/-]{1,128}", value):
                return None
        elif key in {"keys", "exclude_keys"}:
            if (not isinstance(value, list) or not 1 <= len(value) <= 10
                    or any(not isinstance(item, str) or not re.fullmatch(r"[\w.:/-]{1,64}", item) for item in value)):
                return None
            value = list(dict.fromkeys(value))
        else:
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return None
            try:
                date.fromisoformat(value)
            except ValueError:
                return None
        clean[key] = value
    if "period" in clean and ({"created_from", "created_before"} & clean.keys()):
        return None
    if clean.get("created_from", "") >= clean.get("created_before", "9999-12-31"):
        return None
    if bool(clean.get("compare_period")) != operation.endswith("_compare"):
        return None
    if operation == "result_detail" and clean:
        return None
    return clean


def period_dates(period):
    today = timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)
    return {
        "today": (today, today + timedelta(days=1)),
        "yesterday": (today - timedelta(days=1), today),
        "this_week": (monday, today + timedelta(days=1)),
        "last_week": (monday - timedelta(days=7), monday),
        "last_7_days": (today - timedelta(days=6), today + timedelta(days=1)),
        "this_month": (month_start, today + timedelta(days=1)),
        "last_month": (last_month_start, month_start),
    }[period]


def absolute_filters(filters):
    filters = dict(filters)
    if "period" in filters:
        start, end = period_dates(filters.pop("period"))
        filters.update(created_from=start.isoformat(), created_before=end.isoformat())
    return filters


def apply_filters(queryset, filters):
    filters = absolute_filters(filters)
    zone = timezone.get_current_timezone()
    for key, lookup in [("created_from", "created_at__gte"), ("created_before", "created_at__lt")]:
        if key in filters:
            boundary = timezone.make_aware(datetime.combine(date.fromisoformat(filters[key]), time.min), zone)
            queryset = queryset.filter(**{lookup: boundary})
    condition = {
        "failed": Q(qc_passed=False) | Q(qc_status=Result.QC_REJECTED),
        "passed": Q(qc_passed=True), "pending": Q(qc_status__in=[Result.QC_PENDING_REVIEW, Result.QC_REOPENED]),
        "rejected": Q(qc_status=Result.QC_REJECTED), "approved": Q(qc_status=Result.QC_APPROVED),
    }.get(filters.get("qc"))
    if condition is not None:
        queryset = queryset.filter(condition)
    if filters.get("keys"):
        queryset = queryset.filter(key__in=filters["keys"])
    if filters.get("exclude_keys"):
        queryset = queryset.exclude(key__in=filters["exclude_keys"])
    if filters.get("instrument"):
        queryset = queryset.filter(work_item__source_import_job__instrument__code=filters["instrument"])
    if filters.get("operator"):
        queryset = queryset.filter(entered_by__username=filters["operator"])
    return queryset, filters


def _window_label(filters):
    start = filters.get("created_from", "any start date")
    end = filters.get("created_before", "no end date")
    return f"{start} to {end} (end exclusive; {timezone.get_current_timezone_name()})"


def explain_result(row):
    """Explain recorded evidence, keeping automated checks and human review separate."""
    lines = [_result_line(row).removeprefix("- "), _reference_evidence(row)]
    missing = []
    for key, label in [("qc_failure_reason", "QC reason"), ("qc_review_note", "review note")]:
        if row[key]:
            excerpt = " (excerpt)" if row[key + "_truncated"] else ""
            lines.append(f"Recorded {label}{excerpt}: {row[key]}")
        elif key == "qc_failure_reason" and row["qc_passed"] is False:
            missing.append("No QC failure reason is recorded.")
        elif key == "qc_review_note" and row["qc_status"] == Result.QC_REJECTED:
            missing.append("No QC review note is recorded.")
    source = row.get("source_import")
    lines.append(f"Provenance: instrument {source['instrument']}, run {source['run_id']}, import #{source['id']}."
                 if source else "No instrument import is linked to this work item.")
    if row["qc_passed"] is None:
        missing.append("The QC check has not been evaluated.")
    if row["reference_comparison"] in {"invalid_limits", "not_numeric", "not_configured"}:
        missing.append("A valid numeric reference comparison is unavailable.")
    lines.append("A recorded QC reason is not independent proof of a scientific cause. QC checks and review decisions are separate; no release approval is inferred.")
    return "\n".join(lines), missing


def read_results(step, user):
    operation, args, filters = step["operation"], step["arguments"], step.get("filters", {})
    samples = _sample_queryset(user)
    context, target = {}, None
    if operation == "result_detail":
        queryset = Result.objects.filter(work_item__sample__in=samples, pk=int(args["result_id"]))
        target_label = f"R-{args['result_id']}"
    elif operation.startswith("project_"):
        from .lab_reviews import _projects
        from .project_conversation import project_samples
        matches = list(_projects(user).filter(code__iexact=args["project"])[:2])
        if len(matches) != 1:
            return response("Project not found, not accessible, or ambiguous.", unavailable=True)
        target = matches[0]
        queryset = Result.objects.filter(work_item__sample__in=project_samples(target, user))
        context, target_label = {"project_id": target.pk}, target.code
    else:
        matches = list(samples.filter(sample_id__iexact=args["sample"])[:2])
        if len(matches) != 1:
            return response("Sample not found, not accessible, or ambiguous.", unavailable=True)
        target = matches[0]
        queryset = Result.objects.filter(work_item__sample=target)
        context, target_label = {"sample_id": target.pk}, target.sample_id
    base_queryset = queryset
    queryset, resolved = apply_filters(queryset, filters)
    total = queryset.count()
    if operation == "result_detail" and not total:
        return response("Result not found or not accessible.", unavailable=True)
    records = list(queryset.select_related("work_item__sample", "work_item__source_import_job__instrument")
                   .order_by("-created_at", "-pk")[:ROW_LIMIT])
    rows = [{**_result_evidence(row), "sample_code": row.work_item.sample.sample_id,
             "sample_pk": row.work_item.sample_id} for row in records]
    citations = [{"kind": "result", "id": row["id"], "label": f"R-{row['id']} · {row['sample_code']} · {row['key']}",
                  "url": f"/samples/{row['sample_pk']}#result-{row['id']}",
                  "scope": "Current recorded result. QC checks and review decisions are separate."} for row in rows]
    totals = queryset.aggregate(failed=Count("pk", filter=Q(qc_passed=False)),
                                rejected=Count("pk", filter=Q(qc_status=Result.QC_REJECTED)))
    answer = (f"{target_label}: showing {len(rows)} of {total} matching results. "
              f"{totals['failed']} failed checks; {totals['rejected']} rejected reviews.\n"
              f"Window: {_window_label(resolved)}.\n" + "\n".join(f"{index}. {_result_line(row).removeprefix('- ')}" for index, row in enumerate(rows, 1)))
    facts = {"target": target_label, "total": total, "shown": len(rows), **totals, "filters": resolved,
             "window": _window_label(resolved), "rows": rows}
    facts["filter_summary"] = f"QC: {resolved.get('qc', 'all')}; keys: {', '.join(resolved.get('keys', [])) or 'all'}; excluded keys: {', '.join(resolved.get('exclude_keys', [])) or 'none'}"
    facts["filter_summary"] += f"; instrument: {resolved.get('instrument', 'all')}; result entered by: {resolved.get('operator', 'all')}"
    answer += "\n" + facts["filter_summary"] + "."
    table = None
    statistics_tables = []
    if operation.endswith("_compare"):
        other_filters = {k: v for k, v in resolved.items() if k not in {"created_from", "created_before", "compare_period"}}
        other_filters["period"] = resolved["compare_period"]
        # Reconstruct the same permission-scoped base before changing only time.
        other, other_filters = apply_filters(base_queryset, other_filters)
        left = {row["key"]: row["count"] for row in queryset.values("key").annotate(count=Count("pk"))}
        right = {row["key"]: row["count"] for row in other.values("key").annotate(count=Count("pk"))}
        differences = sorted([{"key": key, "selected": left.get(key, 0), "comparison": right.get(key, 0),
                               "difference": left.get(key, 0) - right.get(key, 0)} for key in left.keys() | right.keys()],
                             key=lambda row: (-abs(row["difference"]), row["key"]))
        facts.update(comparison_total=other.count(), comparison_window=_window_label(other_filters), differences=differences[:20])
        comparison_records = list(other.select_related("work_item__sample", "work_item__source_import_job__instrument")
                                  .order_by("-created_at", "-pk")[:ROW_LIMIT])
        comparison_rows = [{**_result_evidence(row), "sample_code": row.work_item.sample.sample_id,
                            "sample_pk": row.work_item.sample_id} for row in comparison_records]
        facts["comparison_rows"] = comparison_rows
        citations.extend({"kind": "result", "id": row["id"], "label": f"R-{row['id']} · comparison · {row['sample_code']} · {row['key']}",
                          "url": f"/samples/{row['sample_pk']}#result-{row['id']}",
                          "scope": "Displayed result from the comparison window; see its exact window and filter scope."} for row in comparison_rows)
        table = {"title": f"Recorded result counts: {target_label}", "columns": [
            {"key": "key", "label": "Result key"}, {"key": "selected", "label": "Selected window"},
            {"key": "comparison", "label": "Comparison window"}, {"key": "difference", "label": "Count difference"}],
            "rows": differences[:20], "notes": [f"Selected: {_window_label(resolved)}", f"Comparison: {_window_label(other_filters)}",
                "Counts, not failure rates. Windows can have different durations. Missing counts are zero; recorded differences do not establish causes.",
                f"Showing {min(20, len(differences))} of {len(differences)} result keys, ranked by absolute count difference."]}
        answer += f"\nComparison window: {_window_label(other_filters)}; {facts['comparison_total']} matching results."
        if differences:
            largest = differences[0]
            answer += f"\nLargest absolute count difference: {largest['key']}: {largest['selected']} versus {largest['comparison']} ({largest['difference']:+d}). This does not establish a cause."
        from .result_statistics import compare_statistics
        facts["statistics"], statistics_tables = compare_statistics(base_queryset, resolved, other_filters)
        from .comparison_explanations import explain_comparison, window_scope
        facts["comparison_scope"] = window_scope(resolved, other_filters)
        facts["comparison_explanation"] = explain_comparison(facts, step.get("focus", "overview"))
        explanation = facts["comparison_explanation"]
        answer += "\n\n" + explanation["text"] + "\nWhat remains unknown: " + " ".join(explanation["unknowns"])
        kind = "project" if operation.startswith("project_") else "sample"
        citations.append({"kind": kind, "id": target.pk, "label": f"{target_label} · comparison aggregate scope",
                          "url": f"/{'projects' if kind == 'project' else 'samples'}/{target.pk}",
                          "scope": "Aggregates use all currently accessible matching records, not just the displayed result examples. "
                                   f"Selected: {_window_label(resolved)}. Comparison: {_window_label(other_filters)}. "
                                   f"{facts['filter_summary']}. QC rates remove only the QC status filter; numeric summaries retain it."})
    if operation == "result_detail":
        detail, missing = explain_result(rows[0])
        answer = detail + ("\nWhat remains unknown: " + " ".join(missing) if missing else "")
    else:
        context["result_query_context"] = {"kind": "project" if operation.startswith("project_") else "sample",
                                            "target": target_label, "filters": filters}
        if operation.endswith("_compare"):
            context["result_query_context"]["focus"] = step.get("focus", "overview")
    answer += "\nQC checks and review decisions are separate. This does not establish scientific causality or release approval."
    return response(answer, context=context, result_query=facts, citations=citations, comparison=table, statistics_tables=statistics_tables,
                    selected_result_ids=[row["id"] for row in rows])
