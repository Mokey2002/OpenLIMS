import re
from collections import defaultdict
from datetime import timedelta

from django.apps import apps
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from samples.access import get_sample_access_queryset
from samples.models import Sample


def apply_sample_access(user):
    base_queryset = Sample.objects.all().select_related(
        "project",
        "container",
        "created_by",
    )

    try:
        return get_sample_access_queryset(base_queryset, user)
    except TypeError:
        return get_sample_access_queryset(user).select_related(
            "project",
            "container",
            "created_by",
        )


def get_model_safe(app_label, model_name):
    try:
        return apps.get_model(app_label, model_name)
    except Exception:
        return None


def extract_job_id(message):
    text = str(message or "")

    patterns = [
        r"migration\s+job\s*#?\s*(\d+)",
        r"job\s*#?\s*(\d+)",
        r"#\s*(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))

    return None


def extract_project_code(message):
    text = str(message or "")

    match = re.search(r"\b(PRJ-[A-Za-z0-9_-]+)\b", text, re.IGNORECASE)
    if match:
        return match.group(1)

    match = re.search(r"\bproject\s+([A-Za-z0-9_-]+)\b", text, re.IGNORECASE)
    if match:
        return match.group(1)

    return ""


def format_day(day):
    return f"{day.strftime('%b')} {day.day}"


def normalize_label(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def chart_response(answer, chart, suggestions=None, links=None):
    return {
        "answer": answer,
        "chart": chart,
        "links": links or [],
        "suggestions": suggestions or [
            "Chart samples by status",
            "Show sample creation trend",
            "Chart migration errors",
            "Count samples by status",
        ],
        "skip_llm": True,
    }


def sample_status_chart(message, user):
    queryset = apply_sample_access(user)
    project_code = extract_project_code(message)

    if project_code:
        queryset = queryset.filter(project__code__iexact=project_code)

    rows = list(
        queryset.values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    )

    if not rows:
        scope = f" for project {project_code}" if project_code else ""
        return {
            "answer": f"No accessible samples were found{scope}.",
            "links": [],
            "suggestions": [
                "Which samples need QC?",
                "Show sample creation trend",
                "Find sample",
            ],
            "skip_llm": True,
        }

    total = sum(row["count"] for row in rows)
    data = []

    lines = [f"Sample status chart: {total} accessible sample(s)."]

    for row in rows:
        status = row["status"] or "UNKNOWN"
        count = row["count"]
        percent = (count / total * 100) if total else 0

        data.append({
            "status": status,
            "count": count,
        })

        lines.append(f"- {status}: {count} ({percent:.1f}%)")

    title = "Samples by status"
    description = "Accessible sample counts grouped by workflow status."

    if project_code:
        title = f"Samples by status — {project_code}"
        description = f"Accessible sample counts for project {project_code}."

    chart = {
        "chartType": "bar",
        "meta": {
            "title": title,
            "description": description,
        },
        "xKey": "status",
        "xAxisLabel": "Status",
        "series": [
            {
                "dataKey": "count",
                "label": "Samples",
                "axisLabel": "Count",
                "valueFormat": "integer",
            }
        ],
        "data": data,
    }

    return chart_response(
        answer="\n".join(lines),
        chart=chart,
        suggestions=[
            "Which samples need QC?",
            "Show sample creation trend",
            "What percentage of migration rows failed?",
        ],
    )


def sample_creation_trend_chart(message, user, days=30):
    queryset = apply_sample_access(user)
    project_code = extract_project_code(message)

    if project_code:
        queryset = queryset.filter(project__code__iexact=project_code)

    today = timezone.localdate()
    start_day = today - timedelta(days=days - 1)

    rows = list(
        queryset.filter(created_at__date__gte=start_day)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )

    counts_by_day = {
        row["day"]: row["count"]
        for row in rows
        if row["day"] is not None
    }

    data = []
    total = 0

    for offset in range(days):
        day = start_day + timedelta(days=offset)
        count = counts_by_day.get(day, 0)
        total += count

        data.append({
            "day": format_day(day),
            "count": count,
        })

    title = f"Sample creation trend — last {days} days"
    description = "Accessible samples created per day."

    if project_code:
        title = f"Sample creation trend — {project_code}"
        description = f"Accessible samples created per day for project {project_code}."

    chart = {
        "chartType": "line",
        "meta": {
            "title": title,
            "description": description,
        },
        "xKey": "day",
        "xAxisLabel": "Day",
        "series": [
            {
                "dataKey": "count",
                "label": "Samples created",
                "axisLabel": "Count",
                "valueFormat": "integer",
            }
        ],
        "data": data,
    }

    return chart_response(
        answer=f"Found {total} accessible sample(s) created in the last {days} days.",
        chart=chart,
        suggestions=[
            "Chart samples by status",
            "Which samples need QC?",
            "Count samples by status",
        ],
    )


def migration_error_chart(message, user):
    MigrationJob = get_model_safe("migration_toolkit", "MigrationJob")
    MigrationRowRecord = get_model_safe("migration_toolkit", "MigrationRowRecord")

    if MigrationJob is None or MigrationRowRecord is None:
        return {
            "answer": "Migration toolkit models are not available in this OpenLIMS deployment.",
            "links": [],
            "suggestions": [
                "Chart samples by status",
                "Show sample creation trend",
            ],
            "skip_llm": True,
        }

    job_id = extract_job_id(message)

    job = None
    if job_id:
        try:
            job = MigrationJob.objects.get(id=job_id)
        except MigrationJob.DoesNotExist:
            return {
                "answer": f"I could not find migration job #{job_id}.",
                "links": [],
                "suggestions": [
                    "Show failed migration jobs",
                    "Chart migration errors",
                ],
                "skip_llm": True,
            }
    else:
        job = MigrationJob.objects.order_by("-created_at").first()

    if not job:
        return {
            "answer": "No migration jobs were found.",
            "links": [],
            "suggestions": [
                "Chart samples by status",
                "Show sample creation trend",
            ],
            "skip_llm": True,
        }

    rows = list(
        MigrationRowRecord.objects.filter(job=job)
        .values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    )

    data = []
    total = 0

    for row in rows:
        status = row["status"] or "UNKNOWN"
        count = row["count"]
        total += count

        data.append({
            "status": status,
            "count": count,
        })

    if not data:
        summary = getattr(job, "summary", {}) or {}
        skipped = summary.get("skipped_rows") or []
        processed = int(summary.get("rows_processed") or 0)

        if processed:
            imported = max(processed - len(skipped), 0)
            data = [
                {"status": "IMPORTED", "count": imported},
                {"status": "SKIPPED/FAILED", "count": len(skipped)},
            ]
            total = processed

    if not data:
        return {
            "answer": f"Migration job #{job.id} does not have row records to chart yet.",
            "links": [
                {
                    "label": f"Open migration job #{job.id}",
                    "url": f"/data-migration/jobs/{job.id}",
                }
            ],
            "suggestions": [
                "Show failed migration jobs",
                "Show skipped migration rows",
            ],
            "skip_llm": True,
        }

    chart = {
        "chartType": "bar",
        "meta": {
            "title": f"Migration row status — job #{job.id}",
            "description": "Migration rows grouped by row status.",
        },
        "xKey": "status",
        "xAxisLabel": "Row status",
        "series": [
            {
                "dataKey": "count",
                "label": "Rows",
                "axisLabel": "Count",
                "valueFormat": "integer",
            }
        ],
        "data": data,
    }

    lines = [f"Migration job #{job.id} row status chart: {total} row(s)."]
    for row in data:
        percent = (row["count"] / total * 100) if total else 0
        lines.append(f"- {row['status']}: {row['count']} ({percent:.1f}%)")

    return chart_response(
        answer="\n".join(lines),
        chart=chart,
        links=[
            {
                "label": f"Open migration job #{job.id}",
                "url": f"/data-migration/jobs/{job.id}",
            }
        ],
        suggestions=[
            "What percentage of migration rows failed?",
            "Show failed migration jobs",
            "Chart samples by status",
        ],
    )


def parse_xy_fields(message):
    text = str(message or "").strip()

    patterns = [
        r"(?:plot|graph|scatter)\s+(.+?)\s+(?:vs|versus|against)\s+(.+?)(?:\s+(?:for|in|on)\s+|$)",
        r"using\s+(.+?)\s+as\s+x\s+and\s+(.+?)\s+as\s+y",
        r"x\s*=\s*(.+?)\s+(?:and\s+)?y\s*=\s*(.+?)(?:\s|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            x_field = match.group(1).strip(" .,:;")
            y_field = match.group(2).strip(" .,:;")
            return x_field, y_field

    return "", ""


def parse_float(value):
    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        pass

    text = str(value).strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)

    if not match:
        return None

    try:
        return float(match.group(0))
    except Exception:
        return None


def get_result_sample(result):
    sample = getattr(result, "sample", None)
    if sample is not None:
        return sample

    work_item = getattr(result, "work_item", None)
    if work_item is not None:
        return getattr(work_item, "sample", None)

    return None


def result_scatter_chart(message, user):
    Result = get_model_safe("results", "Result")

    if Result is None:
        return {
            "answer": (
                "Scatter charts need the results app to expose structured Result records. "
                "I could not find the Result model in this deployment."
            ),
            "links": [],
            "suggestions": [
                "Chart samples by status",
                "Show sample creation trend",
            ],
            "skip_llm": True,
        }

    x_field, y_field = parse_xy_fields(message)

    if not x_field or not y_field:
        return {
            "answer": (
                "Tell me which numeric result fields to use for X and Y. "
                "Example: Plot concentration vs response for PRJ-ABC."
            ),
            "links": [],
            "suggestions": [
                "Plot concentration vs response",
                "Chart samples by status",
            ],
            "skip_llm": True,
        }

    accessible_samples = apply_sample_access(user)
    project_code = extract_project_code(message)

    if project_code:
        accessible_samples = accessible_samples.filter(project__code__iexact=project_code)

    accessible_sample_ids = set(accessible_samples.values_list("id", flat=True))

    if not accessible_sample_ids:
        return {
            "answer": "No accessible samples were found for that scatter plot.",
            "links": [],
            "suggestions": [
                "Chart samples by status",
                "Find sample",
            ],
            "skip_llm": True,
        }

    model_fields = {
        field.name: field
        for field in Result._meta.get_fields()
        if hasattr(field, "name")
    }

    label_field = None
    for candidate in [
        "name",
        "key",
        "result_name",
        "analyte",
        "measurement",
        "field_name",
        "label",
    ]:
        if candidate in model_fields:
            label_field = candidate
            break

    value_field = None
    for candidate in [
        "numeric_value",
        "result_value",
        "value_number",
        "number_value",
        "value",
        "raw_value",
    ]:
        if candidate in model_fields:
            value_field = candidate
            break

    if not label_field or not value_field:
        return {
            "answer": (
                "I found the Result model, but I could not detect result name/value fields "
                "for building an XY scatter plot yet."
            ),
            "links": [],
            "suggestions": [
                "Chart samples by status",
                "Show sample creation trend",
            ],
            "skip_llm": True,
        }

    wanted_x = normalize_label(x_field)
    wanted_y = normalize_label(y_field)

    per_sample = defaultdict(dict)
    sample_labels = {}

    for result in Result.objects.all()[:5000]:
        sample = get_result_sample(result)

        if sample is None or sample.id not in accessible_sample_ids:
            continue

        label = normalize_label(getattr(result, label_field, ""))
        value = parse_float(getattr(result, value_field, None))

        if not label or value is None:
            continue

        sample_labels[sample.id] = sample.sample_id

        if wanted_x in label or label in wanted_x:
            per_sample[sample.id]["x"] = value

        if wanted_y in label or label in wanted_y:
            per_sample[sample.id]["y"] = value

    data = []

    for sample_id, values in per_sample.items():
        if "x" in values and "y" in values:
            data.append({
                "sample": sample_labels.get(sample_id, f"Sample #{sample_id}"),
                "x": values["x"],
                "y": values["y"],
            })

    data = data[:100]

    if not data:
        return {
            "answer": (
                f"I could not find matching numeric result pairs for "
                f"X='{x_field}' and Y='{y_field}'."
            ),
            "links": [],
            "suggestions": [
                "Chart samples by status",
                "Show sample creation trend",
            ],
            "skip_llm": True,
        }

    title = f"{x_field} vs {y_field}"
    description = "Accessible samples with matching numeric result pairs."

    if project_code:
        title = f"{x_field} vs {y_field} — {project_code}"
        description = f"Accessible samples in project {project_code} with matching numeric result pairs."

    chart = {
        "chartType": "scatter",
        "meta": {
            "title": title,
            "description": description,
        },
        "xKey": "x",
        "xAxisLabel": x_field,
        "series": [
            {
                "dataKey": "y",
                "label": y_field,
                "axisLabel": y_field,
                "valueFormat": "raw",
            }
        ],
        "data": data,
    }

    return chart_response(
        answer=f"Built a scatter plot with {len(data)} sample(s).",
        chart=chart,
        suggestions=[
            "Chart samples by status",
            "Show sample creation trend",
            "Count samples by status",
        ],
    )


def route_assistant_chart(message, user):
    text = str(message or "").strip()
    lower = text.lower()

    chart_terms = [
        "chart",
        "plot",
        "graph",
        "trend",
        "scatter",
        "bar chart",
        "line chart",
    ]

    if not any(term in lower for term in chart_terms):
        return None

    if "migration" in lower and any(term in lower for term in ["error", "failed", "fail", "skipped", "skip", "status"]):
        return migration_error_chart(text, user)

    if "status" in lower and "sample" in lower:
        return sample_status_chart(text, user)

    if "sample" in lower and any(term in lower for term in ["created", "creation", "trend", "over time", "by day"]):
        return sample_creation_trend_chart(text, user)

    if any(term in lower for term in [" vs ", " versus ", " against ", "scatter", "x=", "as x"]):
        return result_scatter_chart(text, user)

    if "sample" in lower:
        return sample_status_chart(text, user)

    return None
