import re
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from results.models import Result
from samples.access import get_sample_access_queryset
from samples.models import Sample


MAX_ANALYTICS_ROWS = 100


def _days(message):
    text = str(message or "")
    match = re.search(r"\b(?:last|past|previous)\s+(\d+)\s+days?\b", text, re.I)
    if match:
        return min(max(int(match.group(1)), 1), 3650)
    if re.search(r"\bthis week\b", text, re.I):
        return 7
    if re.search(r"\bthis month\b", text, re.I):
        return timezone.localdate().day
    return None


def _explicit_visual(message):
    return bool(re.search(r"\b(?:chart|graph|plot|visuali[sz]e|bars?)\b", str(message or ""), re.I))


def _group_dimension(message):
    lower = str(message or "").lower()
    dimensions = [
        ("instrument", r"\b(?:instrument|instruments|instrumento|instrumentos)\b"),
        ("project", r"\b(?:project|projects|proyecto|proyectos)\b"),
        ("batch", r"\b(?:batch|batches|lote|lotes)\b"),
        ("status", r"\b(?:status|statuses|workflow stage|estado|estados)\b"),
        ("result", r"\b(?:result key|result type|analyte|measurement|resultado|medici[oó]n)\b"),
        ("qc_status", r"\b(?:qc status|estado de qc)\b"),
        ("assignee", r"\b(?:assignee|operator|assigned user|asignado|operador)\b"),
    ]
    for dimension, pattern in dimensions:
        if re.search(rf"\b(?:by|per|por)\b[^.!?]*{pattern}", lower) or (
            re.search(r"\b(?:highest|lowest|mayor|menor)\b", lower)
            and re.search(pattern, lower)
        ):
            return dimension
    return None


def _is_analytics_request(message):
    lower = str(message or "").lower()
    return bool(
        re.search(r"\b(?:group|agrupa|agrupar|break down|aggregate)\b.*\b(?:by|per|por)\b", lower)
        or re.search(r"\b(?:count|how many|rate|average|highest|lowest)\b.*\b(?:by|per|instrument|project|batch|status)\b", lower)
        or re.search(r"\b(?:instrument|project|batch|status)\b.*\b(?:count|rate|average|highest|lowest)\b", lower)
        or (
            re.search(r"\b(?:failed|rejected|pending|approved)\b", lower)
            and re.search(r"\bqc\b", lower)
            and re.search(r"\b(?:last|past|previous|this week|this month)\b", lower)
        )
    )


def _chart(title, rows, value_key="count"):
    return {
        "chartType": "bar",
        "meta": {
            "title": title,
            "description": "Permission-filtered OpenLIMS aggregate.",
        },
        "xKey": "group",
        "xAxisLabel": "Group",
        "series": [{
            "dataKey": value_key,
            "label": value_key.replace("_", " ").title(),
            "valueFormat": "number",
        }],
        "data": rows,
    }


def _comparison(title, rows, columns, filters):
    return {
        "title": title,
        "kind": "analytics",
        "columns": columns,
        "rows": rows,
        "filters": filters,
        "notes": [
            "All counts are permission-filtered.",
            "Rates describe recorded results and do not establish causation.",
        ],
    }


def _sample_aggregate(message, user, dimension, days):
    fields = {
        "project": "project__code",
        "batch": "batch__code",
        "status": "status",
        "assignee": "assigned_to__username",
    }
    field = fields.get(dimension)
    if not field:
        return None
    queryset = get_sample_access_queryset(Sample.objects.all(), user)
    if days:
        queryset = queryset.filter(created_at__gte=timezone.now() - timedelta(days=days))
    lower = str(message or "").lower()
    if "pending" in lower or "open" in lower:
        queryset = queryset.exclude(
            status__in=[Sample.STATUS_REPORTED, Sample.STATUS_CANCELLED, Sample.STATUS_ARCHIVED]
        )
    for status_value, status_label in Sample.STATUS_CHOICES:
        if status_label.lower() in lower or status_value.lower() in lower:
            queryset = queryset.filter(status=status_value)
            break
    values = list(
        queryset.values(field).annotate(count=Count("id")).order_by("-count", field)[:MAX_ANALYTICS_ROWS]
    )
    rows = [{"group": item.get(field) or "Unassigned", "count": item["count"]} for item in values]
    title = f"Samples by {dimension.replace('_', ' ')}"
    filters = {"entity": "samples", "group_by": dimension, "days": days}
    detail = ", ".join(f"{row['group']}: {row['count']}" for row in rows)
    answer = f"Found {sum(row['count'] for row in rows)} accessible sample(s) across {len(rows)} group(s)."
    if detail:
        answer += f" Breakdown: {detail}."
    return {
        "answer": answer,
        "comparison": _comparison(
            title,
            rows,
            [
                {"key": "group", "label": dimension.replace("_", " ").title()},
                {"key": "count", "label": "Samples", "format": "integer"},
            ],
            filters,
        ),
        "chart": _chart(title, rows),
        "links": [],
        "context": {"analytics": filters},
        "suggestions": ["Show this as a bar chart", "Only include the last 30 days"],
    }


def _result_queryset(user, days=None):
    samples = get_sample_access_queryset(Sample.objects.all(), user)
    queryset = Result.objects.filter(work_item__sample__in=samples)
    if days:
        queryset = queryset.filter(created_at__gte=timezone.now() - timedelta(days=days))
    return queryset


def _failed_result_rows(message, user, days):
    lower = str(message or "").lower()
    queryset = _result_queryset(user, days).select_related(
        "work_item__sample",
        "work_item__sample__project",
    )
    if "failed" in lower:
        queryset = queryset.filter(qc_passed=False)
    elif "rejected" in lower:
        queryset = queryset.filter(qc_status=Result.QC_REJECTED)
    elif "approved" in lower:
        queryset = queryset.filter(qc_status=Result.QC_APPROVED)
    elif "pending" in lower:
        queryset = queryset.filter(qc_status=Result.QC_PENDING_REVIEW)
    else:
        return None
    results = list(queryset.order_by("-created_at")[:MAX_ANALYTICS_ROWS])
    rows = [{
        "result_id": result.id,
        "sample": result.work_item.sample.sample_id,
        "project": getattr(result.work_item.sample.project, "code", None) or "Unassigned",
        "result": result.key,
        "value": result.value,
        "qc_status": result.qc_status,
        "qc_passed": result.qc_passed,
    } for result in results]
    filters = {"entity": "results", "qc": lower, "days": days}
    return {
        "answer": f"Found {len(rows)} accessible QC result(s) matching that request.",
        "comparison": _comparison(
            "QC result review",
            rows,
            [
                {"key": "result_id", "label": "Result", "format": "integer"},
                {"key": "sample", "label": "Sample"},
                {"key": "project", "label": "Project"},
                {"key": "result", "label": "Measurement"},
                {"key": "value", "label": "Value"},
                {"key": "qc_status", "label": "QC status"},
            ],
            filters,
        ),
        "links": [
            {"label": f"Open {row['sample']}", "url": f"/samples/{result.work_item.sample_id}", "kind": "sample"}
            for row, result in zip(rows[:20], results[:20])
        ],
        "context": {"analytics": filters},
        "suggestions": ["Group these results by project", "Group QC failures by instrument"],
    }


def _result_aggregate(message, user, dimension, days):
    fields = {
        "instrument": "work_item__source_import_job__instrument__code",
        "project": "work_item__sample__project__code",
        "batch": "work_item__sample__batch__code",
        "result": "key",
        "qc_status": "qc_status",
    }
    field = fields.get(dimension)
    if not field:
        return None
    queryset = _result_queryset(user, days)
    values = list(
        queryset.values(field).annotate(
            count=Count("id"),
            failures=Count("id", filter=Q(qc_passed=False)),
            reviewed=Count("id", filter=Q(qc_passed__isnull=False)),
        ).order_by(field)[:MAX_ANALYTICS_ROWS]
    )
    rows = []
    for item in values:
        reviewed = item["reviewed"]
        rows.append({
            "group": item.get(field) or "Unknown",
            "count": item["count"],
            "failures": item["failures"],
            "failure_rate": round(item["failures"] * 100 / reviewed, 2) if reviewed else None,
        })
    if "highest" in str(message or "").lower():
        rows.sort(key=lambda row: (row["failure_rate"] is not None, row["failure_rate"] or -1), reverse=True)
    filters = {"entity": "results", "group_by": dimension, "days": days}
    title = f"QC results by {dimension.replace('_', ' ')}"
    highest = next((row for row in rows if row["failure_rate"] is not None), None)
    answer = f"Calculated recorded QC outcomes across {len(rows)} group(s)."
    if highest and "highest" in str(message or "").lower():
        answer += f" {highest['group']} has the highest recorded failure rate at {highest['failure_rate']}%."
    return {
        "answer": answer,
        "comparison": _comparison(
            title,
            rows,
            [
                {"key": "group", "label": dimension.replace("_", " ").title()},
                {"key": "count", "label": "Results", "format": "integer"},
                {"key": "failures", "label": "Failures", "format": "integer"},
                {"key": "failure_rate", "label": "Failure rate", "format": "percent"},
            ],
            filters,
        ),
        "chart": _chart(title, rows, value_key="failure_rate"),
        "links": [],
        "context": {"analytics": filters},
        "suggestions": ["Only include the last 30 days", "Show failed QC results"],
    }


def route_safe_analytics(message, user, context=None):
    if not _is_analytics_request(message):
        return None
    days = _days(message)
    dimension = _group_dimension(message)
    lower = str(message or "").lower()
    result_domain = bool(re.search(r"\b(?:qc|result|resultado|failure rate|tasa de fallos?|instrument|instrumento|analyte|measurement|medici[oó]n)\b", lower))

    if dimension and result_domain:
        result = _result_aggregate(message, user, dimension, days)
    elif dimension:
        result = _sample_aggregate(message, user, dimension, days)
    elif result_domain:
        result = _failed_result_rows(message, user, days)
    else:
        result = None

    if not result:
        return None
    result["analytics"] = {
        "safe_query": True,
        "group_by": dimension,
        "days": days,
        "visual_requested": _explicit_visual(message),
    }
    return result
