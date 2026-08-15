import math
import re
from collections import Counter, defaultdict
from datetime import timedelta
from statistics import mean, pstdev

from django.db.models import Q
from django.utils import timezone

from core.permissions import is_admin
from custom_fields.models import FieldDefinition, FieldValue
from projects.models import Project
from results.models import Result, WorkItem
from samples.access import get_sample_access_queryset
from samples.models import Sample, SampleBatch

from .intent_matching import contains_any_intent_phrase
from .entity_resolution import entity_clarification, resolve_entities
from .suggestions import (
    accessible_batch_codes,
    accessible_project_codes,
    accessible_sample_ids,
)


MAX_COMPARISON_ENTITIES = 10
MAX_ANALYSIS_ROWS = 100
TERMINAL_SAMPLE_STATUSES = {
    Sample.STATUS_REPORTED,
    Sample.STATUS_CANCELLED,
    Sample.STATUS_ARCHIVED,
}
OPEN_WORK_STATUSES = {
    WorkItem.STATUS_PENDING,
    WorkItem.STATUS_IN_PROGRESS,
}
STATUS_ORDER = [choice[0] for choice in Sample.STATUS_CHOICES]
COMPARISON_CHART_TYPES = {"auto", "bar", "line", "scatter", "dot"}


def _safe_days(value, default=None):
    if value in (None, "", 0, "0"):
        return default
    try:
        return min(max(int(value), 1), 3650)
    except (TypeError, ValueError):
        return default


def _cutoff(days):
    return timezone.now() - timedelta(days=days) if days else None


def _accessible_samples(user):
    return get_sample_access_queryset(
        Sample.objects.select_related(
            "project",
            "batch",
            "container",
            "container__location",
            "assigned_to",
        ).all(),
        user,
    )


def _accessible_projects(user):
    queryset = Project.objects.all().order_by("code")
    if is_admin(user):
        return queryset
    return queryset.filter(members=user).distinct()


def _accessible_batches(user):
    queryset = SampleBatch.objects.select_related("project").order_by("code")
    if is_admin(user):
        return queryset
    return queryset.filter(project__members=user).distinct()


def _normal(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _entity_key(kind, entity):
    if kind == "sample":
        return entity.sample_id
    return entity.code


def _entity_label(kind, entity):
    if kind == "project":
        return f"{entity.code} — {entity.name}"
    return _entity_key(kind, entity)


def _resolve_entities(kind, identifiers, user):
    resolution = resolve_entities(
        kind,
        identifiers,
        user,
        limit=MAX_COMPARISON_ENTITIES,
    )
    unresolved = [
        *resolution["missing"],
        *resolution["ambiguous"].keys(),
    ]
    return resolution["entities"], unresolved


def _explicit_identifier_candidates(message, kind):
    """Extract code-like identifiers even when they are not accessible records.

    ``_find_mentions`` intentionally searches only permission-filtered records. That
    is correct for resolution, but it used to make an unavailable identifier look
    exactly like a request that contained no identifiers at all.
    """
    noun = {"sample": "sample", "project": "project", "batch": "batch"}.get(
        kind
    )
    if not noun:
        return []
    text = str(message or "")
    pattern = (
        rf"\b{noun}s?\b\s+(.+?)"
        rf"(?=\s+(?:using|with|as|for|over|during|from|by|on)\b|[?.!]|$)"
    )
    candidates = []
    for match in re.finditer(pattern, text, re.IGNORECASE):
        for value in re.split(
            r"\s*(?:,|\band\b|\bversus\b|\bvs\.?\b)\s*",
            match.group(1),
            flags=re.IGNORECASE,
        ):
            value = re.sub(
                rf"^(?:the\s+)?{noun}\s+",
                "",
                value.strip(),
                flags=re.IGNORECASE,
            )
            value = value.strip(" \t\r\n'\"()[]{}:;")
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", value or ""):
                candidates.append(value)
    return list(dict.fromkeys(candidates))[:MAX_COMPARISON_ENTITIES]


def _requested_identifiers(message, kind, user):
    identifiers = list(_find_mentions(message, kind, user))
    seen = {value.lower() for value in identifiers}
    for value in _explicit_identifier_candidates(message, kind):
        if value.lower() not in seen:
            identifiers.append(value)
            seen.add(value.lower())
    return identifiers[:MAX_COMPARISON_ENTITIES]


def _human_join(values):
    values = [str(value) for value in values if str(value)]
    if len(values) < 2:
        return "".join(values)
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _comparison_suggestions(kind, user):
    if kind == "sample":
        identifiers = accessible_sample_ids(user, limit=3)
        plural = "samples"
    elif kind == "project":
        identifiers = accessible_project_codes(user, limit=3)
        plural = "projects"
    elif kind == "batch":
        identifiers = accessible_batch_codes(user, limit=3)
        plural = "batches"
    else:
        return []
    if len(identifiers) < 2:
        return [f"Show accessible {plural}"]
    request = f"Compare {plural} {_human_join(identifiers)}"
    suggestions = [request]
    if kind == "sample":
        pair = f"Compare samples {_human_join(identifiers[:2])}"
        suggestions.extend(
            [
                f"{pair} using a bar chart",
                f"{pair} using a dot plot",
            ]
        )
    return suggestions


def _find_mentions(message, kind, user):
    text = str(message or "")
    lower = text.lower()
    if kind == "sample":
        candidates = list(_accessible_samples(user).order_by("sample_id")[:2000])
        values = [(sample, [sample.sample_id]) for sample in candidates]
    elif kind == "project":
        candidates = list(_accessible_projects(user)[:500])
        values = [(project, [project.code, project.name]) for project in candidates]
    else:
        candidates = list(_accessible_batches(user)[:1000])
        values = [(batch, [batch.code]) for batch in candidates]

    positions = []
    for entity, labels in values:
        matches = []
        for label in labels:
            pattern = rf"(?<![a-z0-9_-]){re.escape(label.lower())}(?![a-z0-9_-])"
            match = re.search(pattern, lower)
            if match:
                matches.append(match.start())
        if matches:
            positions.append((min(matches), _entity_key(kind, entity)))
    positions.sort(key=lambda item: item[0])
    return [value for _, value in positions[:MAX_COMPARISON_ENTITIES]]


def _extract_days(message, default=None):
    text = str(message or "").lower()
    match = re.search(r"(?:last|past|previous|only)\s+(\d+)\s+days?", text)
    if match:
        return _safe_days(match.group(1), default)
    if "this week" in text:
        return 7
    if "this month" in text:
        return timezone.localdate().day
    if "last month" in text:
        return 30
    return default


def _metric_from_message(message, default="overview"):
    lower = str(message or "").lower()
    if any(word in lower for word in ["qc", "failure rate", "pass rate"]):
        return "qc"
    if any(word in lower for word in ["status", "statuses", "workflow stage"]):
        return "status"
    if any(word in lower for word in ["work", "overdue", "unassigned", "workload"]):
        return "work"
    if any(word in lower for word in ["turnaround", "completion time", "cycle time"]):
        return "turnaround"
    if any(word in lower for word in ["metadata", "incomplete", "missing field"]):
        return "metadata"
    if any(word in lower for word in ["result", "measurement", "analyte"]):
        return "results"
    return default or "overview"


def _extract_chart_type(message, default=None):
    lower = str(message or "").lower()
    if re.search(r"\bscatter(?:\s+(?:plot|chart|graph))?\b", lower):
        return "scatter"
    if re.search(
        r"\b(?:plot|graph|chart)\b.*\b(?:vs\.?|versus|against)\b",
        lower,
    ):
        return "scatter"
    if (
        re.search(r"\bdot\s+(?:plot|chart|graph)\b", lower)
        or re.search(r"\bplotted\s+(?:dots|points)\b", lower)
        or re.search(
            r"\b(?:plot|show|display|graph|render|use)\b.*"
            r"\b(?:as|with|using)\s+(?:plotted\s+)?(?:dots|points)\b",
            lower,
        )
    ):
        return "dot"
    if re.search(r"\bbar\s+(?:chart|graph|plot)\b|\bshow\b.*\bas\s+bars\b", lower):
        return "bar"
    if re.search(r"\bline\s+(?:chart|graph|plot)\b", lower):
        return "line"
    return default


def _extract_result_key_candidates(message):
    text = str(message or "").strip()
    patterns = [
        (
            r"\b(?:plot|chart|graph)\b.*?\b(?:using|with)\s+"
            r"(?:the\s+)?([A-Za-z0-9][A-Za-z0-9_.:/-]*)\s*$"
        ),
        (
            r"(?:scatter\s+(?:plot|chart|graph)|"
            r"(?:bar|line|dot)\s+(?:chart|graph|plot))\s+"
            r"(?:of|for)\s+(.+?)"
            r"(?=\s+(?:for|in|across)\s+(?:samples?|projects?|batches?)\b|$)"
        ),
        (
            r"(?:plot|graph|chart)\s+(?:the\s+)?(.+?)"
            r"(?=\s+(?:for|in|across)\s+(?:samples?|projects?|batches?)\b|$)"
        ),
    ]
    payload = ""
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            payload = match.group(1)
            break
    if not payload:
        return []
    payload = re.sub(
        r"\s+as\s+(?:a\s+)?(?:bar|line|scatter|dot)\s+"
        r"(?:chart|graph|plot)\s*$",
        "",
        payload,
        flags=re.IGNORECASE,
    )
    values = re.split(
        r"\s+(?:vs\.?|versus|against|and)\s+|\s*,\s*",
        payload,
        flags=re.IGNORECASE,
    )
    return [
        value.strip(" \t\r\n.,;:!?'\"")
        for value in values
        if value.strip(" \t\r\n.,;:!?'\"")
    ][:10]


def _resolve_requested_result_keys(requested_result_keys, results):
    canonical = {}
    for result in results:
        if result.value_type != Result.VALUE_TYPE_NUMBER or result.value_number is None:
            continue
        canonical.setdefault(_normal(result.key), result.key.strip())
    resolved = []
    for value in requested_result_keys or []:
        key = canonical.get(_normal(value))
        if key and key not in resolved:
            resolved.append(key)
    return resolved


def _unresolved_result_keys(requested_result_keys, resolved_result_keys):
    resolved = {_normal(key) for key in resolved_result_keys}
    return [
        str(value).strip()
        for value in requested_result_keys or []
        if str(value).strip() and _normal(value) not in resolved
    ]


def _mentioned_numeric_result_keys(message, results):
    normalized_message = _normal(message)
    if not normalized_message:
        return []
    candidates = {}
    for result in results:
        if result.value_type != Result.VALUE_TYPE_NUMBER or result.value_number is None:
            continue
        normalized_key = _normal(result.key)
        if normalized_key:
            candidates.setdefault(normalized_key, result.key.strip())

    matches = []
    for normalized_key, key in candidates.items():
        key_pattern = r"\s+".join(
            re.escape(part) for part in normalized_key.split()
        )
        match = re.search(
            rf"(?<![a-z0-9]){key_pattern}(?![a-z0-9])",
            normalized_message,
        )
        if match:
            matches.append((match.start(), match.end(), key))

    selected = []
    occupied = []
    for start, end, key in sorted(
        matches,
        key=lambda item: (item[0], -(item[1] - item[0])),
    ):
        if any(start < used_end and end > used_start for used_start, used_end in occupied):
            continue
        occupied.append((start, end))
        selected.append((start, key))
    return [key for _, key in sorted(selected)]


def _result_value(result):
    if result.value_type == Result.VALUE_TYPE_NUMBER:
        return result.value_number
    if result.value_type == Result.VALUE_TYPE_BOOLEAN:
        return result.value_boolean
    return result.value_string


def _field_value(value):
    raw = value.value
    if isinstance(raw, dict) and set(raw).intersection({"value", "raw", "text"}):
        for key in ["value", "raw", "text"]:
            if key in raw:
                return raw[key]
    return raw


def _metadata_for_samples(samples):
    sample_ids = [str(sample.id) for sample in samples]
    values = FieldValue.objects.filter(
        entity_type__iexact="Sample",
        entity_id__in=sample_ids,
    ).select_related("field_definition")
    by_sample = defaultdict(dict)
    for value in values:
        by_sample[value.entity_id][value.field_definition.name] = _field_value(value)
    required = list(
        FieldDefinition.objects.filter(
            entity_type__iexact="Sample",
            required=True,
        ).values_list("name", flat=True)
    )
    return by_sample, required


def _scope_samples(kind, entity, user, cutoff=None):
    queryset = _accessible_samples(user)
    if kind == "project":
        queryset = queryset.filter(
            Q(project=entity) | Q(linked_projects=entity)
        ).distinct()
    elif kind == "batch":
        queryset = queryset.filter(batch=entity)
    elif kind == "sample":
        queryset = queryset.filter(id=entity.id)
    if cutoff:
        queryset = queryset.filter(created_at__gte=cutoff)
    return queryset


def _work_and_results(sample_ids, cutoff=None):
    work = WorkItem.objects.filter(sample_id__in=sample_ids)
    results = Result.objects.filter(work_item__sample_id__in=sample_ids)
    if cutoff:
        work = work.filter(created_at__gte=cutoff)
        results = results.filter(created_at__gte=cutoff)
    return work, results


def _status_counts(samples):
    counts = Counter(samples.values_list("status", flat=True))
    return {status: counts.get(status, 0) for status in STATUS_ORDER}


def _turnaround_days(samples):
    values = []
    for sample in samples:
        if sample.status not in {Sample.STATUS_REPORTED, Sample.STATUS_ARCHIVED}:
            continue
        delta = sample.status_changed_at - sample.created_at
        if delta.total_seconds() >= 0:
            values.append(delta.total_seconds() / 86400)
    return round(mean(values), 2) if values else None


def _metric_snapshot(kind, entity, user, days=None, required_fields=None):
    cutoff = _cutoff(days)
    samples = _scope_samples(kind, entity, user, cutoff=cutoff)
    sample_list = list(samples)
    sample_ids = [sample.id for sample in sample_list]
    work, results = _work_and_results(sample_ids, cutoff=cutoff)
    now = timezone.now()
    result_total = results.count()
    qc_passed = results.filter(qc_passed=True).count()
    qc_failed = results.filter(qc_passed=False).count()
    qc_known = qc_passed + qc_failed
    required_fields = required_fields or []
    missing_metadata = 0
    if required_fields and sample_ids:
        metadata, _ = _metadata_for_samples(sample_list)
        for sample in sample_list:
            present = metadata.get(str(sample.id), {})
            if any(present.get(field) in (None, "", [], {}) for field in required_fields):
                missing_metadata += 1
    status_counts = Counter(sample.status for sample in sample_list)
    stale_samples = [
        sample
        for sample in sample_list
        if sample.status not in TERMINAL_SAMPLE_STATUSES
        and (now - sample.status_changed_at).total_seconds() >= 7 * 86400
    ]
    row = {
        "entity": _entity_key(kind, entity),
        "label": _entity_label(kind, entity),
        "sample_count": len(sample_list),
        "received": status_counts.get(Sample.STATUS_RECEIVED, 0),
        "in_progress": status_counts.get(Sample.STATUS_IN_PROGRESS, 0),
        "qc_samples": status_counts.get(Sample.STATUS_QC, 0),
        "reported": status_counts.get(Sample.STATUS_REPORTED, 0),
        "cancelled": status_counts.get(Sample.STATUS_CANCELLED, 0),
        "archived": status_counts.get(Sample.STATUS_ARCHIVED, 0),
        "open_work": work.filter(status__in=OPEN_WORK_STATUSES).count(),
        "overdue_work": work.filter(
            status__in=OPEN_WORK_STATUSES,
            due_at__lt=now,
        ).count(),
        "unassigned_work": work.filter(
            status__in=OPEN_WORK_STATUSES,
            assigned_to__isnull=True,
        ).count(),
        "result_count": result_total,
        "qc_passed": qc_passed,
        "qc_failed": qc_failed,
        "qc_pending": results.filter(qc_status=Result.QC_PENDING_REVIEW).count(),
        "qc_pass_rate": round(qc_passed / qc_known * 100, 1) if qc_known else None,
        "qc_failure_rate": round(qc_failed / qc_known * 100, 1) if qc_known else None,
        "turnaround_days": _turnaround_days(sample_list),
        "missing_metadata": missing_metadata,
        "stale_samples": len(stale_samples),
    }
    if kind == "project":
        row["name"] = entity.name
    if kind == "batch":
        row["project"] = entity.project.code
    return row


def _chart_for_scope(kind, rows, metric, chart_type="bar"):
    if metric == "status":
        series = [
            ("received", "Received"),
            ("in_progress", "In progress"),
            ("qc_samples", "QC"),
            ("reported", "Reported"),
            ("cancelled", "Cancelled"),
            ("archived", "Archived"),
        ]
        title = f"{kind.title()} sample status comparison"
        stacked = True
    elif metric == "qc":
        series = [
            ("qc_pass_rate", "QC pass rate (%)"),
            ("qc_failure_rate", "QC failure rate (%)"),
        ]
        title = f"{kind.title()} QC rate comparison"
        stacked = False
    elif metric == "work":
        series = [
            ("open_work", "Open work"),
            ("overdue_work", "Overdue work"),
            ("unassigned_work", "Unassigned work"),
        ]
        title = f"{kind.title()} workload comparison"
        stacked = False
    elif metric == "turnaround":
        series = [("turnaround_days", "Average turnaround (days)")]
        title = f"{kind.title()} turnaround comparison"
        stacked = False
    elif metric == "metadata":
        series = [("missing_metadata", "Samples missing required metadata")]
        title = f"{kind.title()} metadata completeness comparison"
        stacked = False
    else:
        series = [
            ("sample_count", "Samples"),
            ("qc_failed", "Failed QC results"),
            ("overdue_work", "Overdue work"),
            ("stale_samples", "Stale samples"),
        ]
        title = f"{kind.title()} operational comparison"
        stacked = False
    return {
        "chartType": chart_type if chart_type in {"bar", "line", "dot"} else "bar",
        "meta": {
            "title": title,
            "description": "Calculated from records currently accessible to the requesting user.",
        },
        "xKey": "entity",
        "xAxisLabel": kind.title(),
        "stacked": stacked,
        "series": [
            {
                "dataKey": data_key,
                "label": label,
                "axisLabel": label,
                "valueFormat": "percent" if "rate" in data_key else "number",
            }
            for data_key, label in series
        ],
        "data": rows,
    }


def _scope_columns(kind):
    columns = [
        {"key": "entity", "label": kind.title()},
    ]
    if kind == "project":
        columns.append({"key": "name", "label": "Name"})
    if kind == "batch":
        columns.append({"key": "project", "label": "Project"})
    columns.extend([
        {"key": "sample_count", "label": "Samples", "format": "integer"},
        {"key": "open_work", "label": "Open work", "format": "integer"},
        {"key": "overdue_work", "label": "Overdue", "format": "integer"},
        {"key": "qc_failure_rate", "label": "QC failure", "format": "percent"},
        {"key": "turnaround_days", "label": "Turnaround (days)", "format": "number"},
        {"key": "missing_metadata", "label": "Missing metadata", "format": "integer"},
    ])
    return columns


def _numeric_result_chart(
    samples,
    results,
    result_keys=None,
    chart_type="bar",
):
    values = defaultdict(lambda: defaultdict(list))
    units = {}
    sample_keys = {sample.id: f"sample_{index}" for index, sample in enumerate(samples)}
    selected = {_normal(key) for key in (result_keys or [])}
    for result in results:
        if result.value_type != Result.VALUE_TYPE_NUMBER or result.value_number is None:
            continue
        if selected and _normal(result.key) not in selected:
            continue
        sample_id = result.work_item.sample_id
        if sample_id not in sample_keys:
            continue
        normalized_key = result.key.strip()
        values[normalized_key][sample_id].append(result.value_number)
        units[normalized_key] = result.unit
    data = []
    for key in sorted(values)[:20]:
        row = {
            "measurement": f"{key} ({units[key]})" if units.get(key) else key,
        }
        for sample in samples:
            collected = values[key].get(sample.id, [])
            row[sample_keys[sample.id]] = round(mean(collected), 4) if collected else None
        data.append(row)
    if not data:
        return None
    return {
        "chartType": chart_type if chart_type in {"bar", "line", "dot"} else "bar",
        "meta": {
            "title": "Numeric result comparison",
            "description": "Mean numeric value for each measurement and sample in the selected window.",
        },
        "xKey": "measurement",
        "xAxisLabel": "Measurement",
        "series": [
            {
                "dataKey": sample_keys[sample.id],
                "label": sample.sample_id,
                "axisLabel": "Result value",
                "valueFormat": "number",
            }
            for sample in samples
        ],
        "data": data,
    }


def _result_axis_label(result_key, units):
    nonempty_units = sorted({unit for unit in units if unit})
    if len(nonempty_units) == 1:
        return f"{result_key} ({nonempty_units[0]})"
    return result_key


def _scatter_result_chart(samples, results, result_keys):
    if len(result_keys) < 2:
        return None, (
            "A scatter plot needs two numeric result names for its X and Y axes. "
            "For example: ‘Plot concentration versus purity for these samples.’"
        )

    x_key, y_key = result_keys[:2]
    normalized_axes = {_normal(x_key): "x", _normal(y_key): "y"}
    values = defaultdict(lambda: defaultdict(list))
    units = defaultdict(set)
    for result in results:
        axis = normalized_axes.get(_normal(result.key))
        if (
            not axis
            or result.value_type != Result.VALUE_TYPE_NUMBER
            or result.value_number is None
        ):
            continue
        values[result.work_item.sample_id][axis].append(result.value_number)
        units[axis].add(result.unit)

    for axis, key in [("x", x_key), ("y", y_key)]:
        nonempty_units = {unit for unit in units[axis] if unit}
        if len(nonempty_units) > 1:
            return None, (
                f"I could not plot {key} because its accessible results use multiple units. "
                "Choose results with consistent units or normalize them first."
            )

    data = []
    missing = []
    for sample in samples:
        sample_values = values.get(sample.id, {})
        if not sample_values.get("x") or not sample_values.get("y"):
            missing.append(sample.sample_id)
            continue
        data.append({
            "sample": sample.sample_id,
            "x": round(mean(sample_values["x"]), 4),
            "y": round(mean(sample_values["y"]), 4),
        })
    if not data:
        return None, (
            f"None of the selected samples has both numeric {x_key} and {y_key} results "
            "in the selected date window."
        )

    x_label = _result_axis_label(x_key, units["x"])
    y_label = _result_axis_label(y_key, units["y"])
    warning = ""
    if missing:
        warning = (
            f"Excluded {len(missing)} sample(s) without both plotted results: "
            f"{', '.join(missing)}."
        )
    return {
        "chartType": "scatter",
        "meta": {
            "title": f"{y_key} versus {x_key}",
            "description": (
                "Each dot represents one sample using the mean accessible value "
                "for each selected result."
            ),
        },
        "xKey": "x",
        "xAxisLabel": x_label,
        "series": [
            {
                "dataKey": "y",
                "label": y_key,
                "axisLabel": y_label,
                "valueFormat": "number",
            }
        ],
        "data": data,
    }, warning


def _compare_samples(
    samples,
    user,
    days=None,
    metric="overview",
    chart_type="auto",
    result_keys=None,
    request_text="",
):
    cutoff = _cutoff(days)
    sample_ids = [sample.id for sample in samples]
    work, results = _work_and_results(sample_ids, cutoff=cutoff)
    result_list = list(results.select_related("work_item", "work_item__sample"))
    metadata, required_fields = _metadata_for_samples(samples)
    custom_field_names = sorted({
        field_name
        for values in metadata.values()
        for field_name in values
    })[:8]
    now = timezone.now()
    rows = []
    links = []
    result_by_sample = defaultdict(list)
    work_by_sample = defaultdict(list)
    for result in result_list:
        result_by_sample[result.work_item.sample_id].append(result)
    for item in work.select_related("assigned_to"):
        work_by_sample[item.sample_id].append(item)
    for sample in samples:
        sample_results = result_by_sample[sample.id]
        sample_work = work_by_sample[sample.id]
        known_qc = [result for result in sample_results if result.qc_passed is not None]
        failed_qc = [result for result in known_qc if result.qc_passed is False]
        fields = metadata.get(str(sample.id), {})
        missing = [
            field
            for field in required_fields
            if fields.get(field) in (None, "", [], {})
        ]
        container = sample.container
        location = None
        if container:
            location = getattr(getattr(container, "location", None), "name", None)
            location = location or getattr(container, "name", None) or f"Container #{container.id}"
        status_age = max((now - sample.status_changed_at).total_seconds() / 86400, 0)
        row = {
            "entity": sample.sample_id,
            "sample_count": 1,
            "project": sample.project.code if sample.project else None,
            "batch": sample.batch.code if sample.batch else None,
            "status": sample.status,
            "location": location,
            "assigned_to": sample.assigned_to.username if sample.assigned_to else None,
            "status_age_days": round(status_age, 1),
            "stale_samples": int(
                sample.status not in TERMINAL_SAMPLE_STATUSES and status_age >= 7
            ),
            "open_work": sum(item.status in OPEN_WORK_STATUSES for item in sample_work),
            "overdue_work": sum(
                item.status in OPEN_WORK_STATUSES
                and item.due_at is not None
                and item.due_at < now
                for item in sample_work
            ),
            "result_count": len(sample_results),
            "qc_failed": len(failed_qc),
            "qc_failure_rate": round(len(failed_qc) / len(known_qc) * 100, 1) if known_qc else None,
            "missing_metadata": len(missing),
            "missing_fields": ", ".join(missing) if missing else "None",
        }
        for field_index, field_name in enumerate(custom_field_names):
            row[f"custom_{field_index}"] = fields.get(field_name)
        rows.append(row)
        links.append({
            "label": f"Open {sample.sample_id}",
            "url": f"/samples/{sample.id}",
            "kind": "sample",
        })
    extracted_result_keys = (
        _extract_result_key_candidates(request_text)
        if metric in {"overview", "results"} or chart_type == "scatter"
        else []
    )
    requested_result_keys = extracted_result_keys or list(result_keys or [])
    selected_result_keys = _resolve_requested_result_keys(
        requested_result_keys,
        result_list,
    )
    if not requested_result_keys:
        selected_result_keys = _mentioned_numeric_result_keys(
            request_text,
            result_list,
        )
    unresolved_result_keys = _unresolved_result_keys(
        requested_result_keys,
        selected_result_keys,
    )
    context_result_keys = requested_result_keys or selected_result_keys
    chart_warning = ""
    if unresolved_result_keys:
        chart_warning = (
            "No accessible numeric result matched: "
            f"{', '.join(unresolved_result_keys)}."
        )
    if chart_type == "scatter":
        chart, scatter_warning = _scatter_result_chart(
            samples,
            result_list,
            selected_result_keys,
        )
        if scatter_warning:
            chart_warning = " ".join(
                warning for warning in [chart_warning, scatter_warning] if warning
            )
    else:
        rendered_chart_type = chart_type if chart_type != "auto" else "bar"
        result_chart = None
        if selected_result_keys or not requested_result_keys:
            result_chart = _numeric_result_chart(
                samples,
                result_list,
                result_keys=selected_result_keys,
                chart_type=rendered_chart_type,
            )
        if metric in {"results", "overview"} and result_chart:
            chart = result_chart
        elif requested_result_keys and metric in {"results", "overview"}:
            chart = None
        else:
            chart = _chart_for_scope(
                "sample",
                rows,
                metric,
                chart_type=rendered_chart_type,
            )
    columns = [
        {"key": "entity", "label": "Sample"},
        {"key": "project", "label": "Project"},
        {"key": "batch", "label": "Batch"},
        {"key": "status", "label": "Status"},
        {"key": "location", "label": "Location"},
        {"key": "assigned_to", "label": "Assigned to"},
        {"key": "status_age_days", "label": "Days in status", "format": "number"},
        {"key": "open_work", "label": "Open work", "format": "integer"},
        {"key": "result_count", "label": "Results", "format": "integer"},
        {"key": "qc_failed", "label": "Failed QC", "format": "integer"},
        {"key": "missing_metadata", "label": "Missing fields", "format": "integer"},
    ]
    columns.extend([
        {"key": f"custom_{index}", "label": field_name}
        for index, field_name in enumerate(custom_field_names)
    ])
    return (
        rows,
        columns,
        chart,
        links,
        context_result_keys,
        chart_warning,
    )


def _comparison_answer(kind, rows, days, missing):
    window = f" from the last {days} days" if days else " across all available dates"
    lines = [f"Compared {len(rows)} accessible {kind}(s){window}."]
    if rows:
        highest_samples = max(rows, key=lambda row: row.get("sample_count", 1) or 0)
        if kind != "sample":
            lines.append(
                f"- Largest visible sample count: {highest_samples['entity']} "
                f"({highest_samples['sample_count']})."
            )
        failed = [row for row in rows if row.get("qc_failed")]
        if failed:
            highest_failed = max(failed, key=lambda row: row.get("qc_failed", 0))
            lines.append(
                f"- Most failed QC results: {highest_failed['entity']} "
                f"({highest_failed['qc_failed']})."
            )
        overdue = [row for row in rows if row.get("overdue_work")]
        if overdue:
            highest_overdue = max(overdue, key=lambda row: row.get("overdue_work", 0))
            lines.append(
                f"- Most overdue work: {highest_overdue['entity']} "
                f"({highest_overdue['overdue_work']})."
            )
    if missing:
        lines.append(
            f"- {len(missing)} requested identifier(s) were unavailable or outside your access scope."
        )
    lines.append("All values were calculated by OpenLIMS from permission-filtered records.")
    return "\n".join(lines)


def compare_entities(
    kind,
    identifiers,
    user,
    days=None,
    metric="overview",
    chart_type="auto",
    result_keys=None,
    request_text="",
):
    entities, missing = _resolve_entities(kind, identifiers, user)
    if len(entities) < 2:
        requested = list(
            dict.fromkeys(
                str(value).strip()
                for value in (identifiers or [])
                if str(value).strip()
            )
        )
        plural = "batches" if kind == "batch" else f"{kind}s"
        if requested:
            answer = (
                f"I need at least two accessible {plural} to compare. "
                f"I found {len(entities)} of {len(requested)} requested identifiers "
                "in the records you can access. Choose at least two from the suggestions below."
            )
        else:
            answer = (
                f"Which {plural} would you like to compare? "
                f"Choose at least two accessible {plural}."
            )
        return {
            "answer": answer,
            "links": [],
            "context": {
                "comparison": {
                    "analysis": "compare",
                    "kind": kind,
                    "identifiers": [],
                    "days": _safe_days(days),
                    "metric": metric or "overview",
                    "chart_type": (
                        chart_type
                        if chart_type in COMPARISON_CHART_TYPES
                        else "auto"
                    ),
                    "result_keys": list(result_keys or []),
                    "awaiting_identifiers": True,
                }
            },
            "suggestions": _comparison_suggestions(kind, user),
            "skip_llm": True,
        }
    days = _safe_days(days)
    metric = metric or "overview"
    chart_type = chart_type if chart_type in COMPARISON_CHART_TYPES else "auto"
    selected_result_keys = list(result_keys or [])
    chart_warning = ""
    if kind == "sample":
        (
            rows,
            columns,
            chart,
            links,
            selected_result_keys,
            chart_warning,
        ) = _compare_samples(
            entities,
            user,
            days=days,
            metric=metric,
            chart_type=chart_type,
            result_keys=result_keys,
            request_text=request_text,
        )
    else:
        required_fields = list(
            FieldDefinition.objects.filter(
                entity_type__iexact="Sample",
                required=True,
            ).values_list("name", flat=True)
        )
        rows = [
            _metric_snapshot(
                kind,
                entity,
                user,
                days=days,
                required_fields=required_fields,
            )
            for entity in entities
        ]
        columns = _scope_columns(kind)
        if chart_type == "scatter":
            chart = None
            chart_warning = (
                "Scatter plots currently require two numeric result names and a sample "
                "comparison. Use a bar, line, or dot chart for project and batch summaries."
            )
        else:
            rendered_chart_type = chart_type if chart_type != "auto" else "bar"
            chart = _chart_for_scope(
                kind,
                rows,
                metric,
                chart_type=rendered_chart_type,
            )
        links = [
            {
                "label": f"Open {_entity_key(kind, entity)}",
                "url": f"/projects/{entity.id}" if kind == "project" else "/batches",
                "kind": kind,
            }
            for entity in entities
        ]
    context = {
        "comparison": {
            "analysis": "compare",
            "kind": kind,
            "identifiers": [_entity_key(kind, entity) for entity in entities],
            "days": days,
            "metric": metric,
            "chart_type": chart_type,
            "result_keys": selected_result_keys,
        }
    }
    answer = _comparison_answer(kind, rows, days, missing)
    if chart_warning:
        answer += f"\n\n{chart_warning}"
    return {
        "answer": answer,
        "comparison": {
            "title": f"{kind.title()} comparison",
            "kind": kind,
            "columns": columns,
            "rows": rows,
            "filters": context["comparison"],
            "notes": [
                "Linked-project samples may appear in more than one project comparison.",
                "A blank rate means there were no pass/fail QC decisions in the selected window.",
            ] if kind == "project" else [],
        },
        "chart": chart,
        "links": links,
        "context": context,
        "suggestions": [
            "Only show the last 30 days",
            "Graph the QC failure rates",
            "Graph overdue and unassigned work",
            "Use a dot plot",
            "Export this comparison as PDF",
        ],
        "skip_llm": True,
    }


def _extract_result_key(message):
    text = str(message or "").strip()
    patterns = [
        r"(?:graph|plot|trend|chart)\s+(?:the\s+)?(.+?)\s+results?\s+(?:for|in|across)",
        r"(?:graph|plot|trend|chart)\s+(?:results?\s+for\s+)?(.+?)\s+(?:for|in|across)\s+(?:project|projects|sample|samples)",
        r"(?:outlier|unusual|anomalous)\s+(.+?)\s+results?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = re.sub(r"\b(?:the|all|numeric)\b", "", match.group(1), flags=re.IGNORECASE)
            return re.sub(r"\s+", " ", value).strip(" .,:;")
    return ""


def result_trend(identifiers, user, kind="project", days=90, result_key=""):
    days = _safe_days(days, 90)
    entities, missing = _resolve_entities(kind, identifiers, user)
    if not entities:
        return {
            "answer": f"I could not resolve an accessible {kind} for that result trend.",
            "links": [],
            "skip_llm": True,
        }
    cutoff = _cutoff(days)
    series_by_entity = defaultdict(lambda: defaultdict(list))
    links = []
    for entity in entities:
        samples = _scope_samples(kind, entity, user)
        queryset = Result.objects.filter(
            work_item__sample__in=samples,
            value_type=Result.VALUE_TYPE_NUMBER,
            value_number__isnull=False,
            created_at__gte=cutoff,
        )
        if result_key:
            queryset = queryset.filter(key__icontains=result_key)
        for result in queryset.order_by("created_at")[:5000]:
            day = timezone.localtime(result.created_at).date().isoformat()
            series_by_entity[_entity_key(kind, entity)][day].append(result.value_number)
        if kind == "project":
            url = f"/projects/{entity.id}"
        elif kind == "sample":
            url = f"/samples/{entity.id}"
        else:
            url = "/batches"
        links.append({
            "label": f"Open {_entity_key(kind, entity)}",
            "url": url,
            "kind": kind,
        })
    all_days = sorted({day for values in series_by_entity.values() for day in values})
    data = []
    series = []
    for index, entity in enumerate(entities):
        key = _entity_key(kind, entity)
        data_key = f"entity_{index}"
        series.append({
            "dataKey": data_key,
            "label": key,
            "axisLabel": result_key or "Numeric result",
            "valueFormat": "number",
        })
        for day in all_days:
            if len(data) < len(all_days):
                data.append({"day": day})
            values = series_by_entity[key].get(day, [])
            data[all_days.index(day)][data_key] = round(mean(values), 4) if values else None
    data = [row for row in data if any(row.get(item["dataKey"]) is not None for item in series)]
    if not data:
        return {
            "answer": (
                f"No accessible numeric results matching '{result_key or 'any result'}' "
                f"were found in the last {days} days."
            ),
            "links": links,
            "skip_llm": True,
        }
    rows = []
    for entity in entities:
        key = _entity_key(kind, entity)
        values = [value for day_values in series_by_entity[key].values() for value in day_values]
        rows.append({
            "entity": key,
            "measurements": len(values),
            "average": round(mean(values), 4) if values else None,
            "minimum": round(min(values), 4) if values else None,
            "maximum": round(max(values), 4) if values else None,
        })
    context = {
        "comparison": {
            "analysis": "trend",
            "kind": kind,
            "identifiers": [_entity_key(kind, entity) for entity in entities],
            "days": days,
            "metric": "results",
            "result_key": result_key,
        }
    }
    return {
        "answer": (
            f"Graphed {sum(row['measurements'] for row in rows)} numeric measurement(s) "
            f"across {len(entities)} {kind}(s) for the last {days} days."
            + (f" {len(missing)} identifier(s) were unavailable." if missing else "")
        ),
        "comparison": {
            "title": f"{result_key or 'Numeric result'} trend summary",
            "kind": "trend",
            "columns": [
                {"key": "entity", "label": kind.title()},
                {"key": "measurements", "label": "Measurements", "format": "integer"},
                {"key": "average", "label": "Average", "format": "number"},
                {"key": "minimum", "label": "Minimum", "format": "number"},
                {"key": "maximum", "label": "Maximum", "format": "number"},
            ],
            "rows": rows,
            "filters": context["comparison"],
            "notes": ["Each point is the arithmetic mean of matching measurements recorded that day."],
        },
        "chart": {
            "chartType": "line",
            "meta": {
                "title": f"{result_key or 'Numeric results'} over time",
                "description": f"Daily mean across the last {days} days.",
            },
            "xKey": "day",
            "xAxisLabel": "Day",
            "series": series,
            "data": data,
        },
        "links": links,
        "context": context,
        "suggestions": [
            "Only show the last 30 days",
            "Find unusual results in this comparison",
            "Export this comparison as PDF",
        ],
        "skip_llm": True,
    }


def find_outliers(identifiers, user, kind="project", days=90, result_key=""):
    days = _safe_days(days, 90)
    entities, _ = _resolve_entities(kind, identifiers, user)
    if identifiers and not entities:
        return {
            "answer": f"I could not resolve an accessible {kind} for that outlier review.",
            "links": [],
            "skip_llm": True,
        }
    if not entities:
        entities = list(_accessible_projects(user)[:MAX_COMPARISON_ENTITIES])
        kind = "project"
    cutoff = _cutoff(days)
    sample_entity = {}
    allowed_sample_ids = set()
    for entity in entities:
        for sample_id in _scope_samples(kind, entity, user).values_list("id", flat=True):
            allowed_sample_ids.add(sample_id)
            sample_entity.setdefault(sample_id, _entity_key(kind, entity))
    queryset = Result.objects.select_related(
        "work_item",
        "work_item__sample",
    ).filter(
        work_item__sample_id__in=allowed_sample_ids,
        value_type=Result.VALUE_TYPE_NUMBER,
        value_number__isnull=False,
        created_at__gte=cutoff,
    )
    if result_key:
        queryset = queryset.filter(key__icontains=result_key)
    groups = defaultdict(list)
    results = list(queryset.order_by("created_at")[:5000])
    for result in results:
        groups[(result.key, result.unit)].append(result)
    rows = []
    for (key, unit), group in groups.items():
        values = [result.value_number for result in group]
        average = mean(values)
        deviation = pstdev(values) if len(values) >= 4 else 0
        for result in group:
            z_score = (result.value_number - average) / deviation if deviation else 0
            reference = result.reference_comparison
            reasons = []
            if reference in {"above", "below"}:
                reasons.append(f"{reference} reference range")
            if len(values) >= 4 and abs(z_score) >= 2.5:
                reasons.append(f"z-score {z_score:.2f}")
            if not reasons:
                continue
            sample = result.work_item.sample
            rows.append({
                "entity": f"{sample.sample_id} · {key}",
                "sample": sample.sample_id,
                "scope": sample_entity.get(sample.id),
                "result": key,
                "value": result.value_number,
                "unit": unit,
                "reason": "; ".join(reasons),
                "deviation_score": round(abs(z_score), 2),
                "result_id": result.id,
            })
    rows.sort(key=lambda row: (row["deviation_score"], row["sample"]), reverse=True)
    rows = rows[:MAX_ANALYSIS_ROWS]
    context = {
        "comparison": {
            "analysis": "outliers",
            "kind": kind,
            "identifiers": [_entity_key(kind, entity) for entity in entities],
            "days": days,
            "metric": "results",
            "result_key": result_key,
        }
    }
    return {
        "answer": (
            f"Found {len(rows)} unusual numeric result(s) in the last {days} days. "
            "Outliers are flagged by configured reference limits or an absolute z-score of at least 2.5."
        ),
        "comparison": {
            "title": "Outlier review",
            "kind": "outliers",
            "columns": [
                {"key": "sample", "label": "Sample"},
                {"key": "scope", "label": kind.title()},
                {"key": "result", "label": "Result"},
                {"key": "value", "label": "Value", "format": "number"},
                {"key": "unit", "label": "Unit"},
                {"key": "reason", "label": "Reason"},
            ],
            "rows": rows,
            "filters": context["comparison"],
            "notes": [
                "This is a review aid, not an automatic QC decision.",
                "Small groups use reference ranges only because z-scores are unstable with fewer than four values.",
            ],
        },
        "chart": {
            "chartType": "bar",
            "meta": {
                "title": "Largest outlier scores",
                "description": "Absolute z-score; reference-only flags may have a score of zero.",
            },
            "xKey": "entity",
            "xAxisLabel": "Sample and result",
            "series": [{
                "dataKey": "deviation_score",
                "label": "Absolute z-score",
                "axisLabel": "Score",
                "valueFormat": "number",
            }],
            "data": rows[:20],
        },
        "links": [
            {
                "label": f"Open result R-{row['result_id']}",
                "url": "/qc-review",
                "kind": "result",
            }
            for row in rows[:20]
        ],
        "context": context,
        "suggestions": [
            "Only show the last 30 days",
            "Compare the projects in this analysis",
            "Export this comparison as CSV",
        ],
        "skip_llm": True,
    }


def find_bottlenecks(identifiers, user, kind="project", days=7):
    stale_days = _safe_days(days, 7)
    entities, _ = _resolve_entities(kind, identifiers, user)
    if not entities:
        entities = list(_accessible_projects(user)[:MAX_COMPARISON_ENTITIES])
        kind = "project"
    threshold = timezone.now() - timedelta(days=stale_days)
    rows = []
    links = []
    for entity in entities:
        samples = _scope_samples(kind, entity, user)
        stale = samples.exclude(status__in=TERMINAL_SAMPLE_STATUSES).filter(
            status_changed_at__lt=threshold,
        )
        work = WorkItem.objects.filter(
            sample__in=samples,
            status__in=OPEN_WORK_STATUSES,
        )
        counts = Counter(stale.values_list("status", flat=True))
        ages = [
            max((timezone.now() - sample.status_changed_at).total_seconds() / 86400, 0)
            for sample in stale
        ]
        row = {
            "entity": _entity_key(kind, entity),
            "stale_samples": len(ages),
            "average_stale_days": round(mean(ages), 1) if ages else None,
            "oldest_stale_days": round(max(ages), 1) if ages else None,
            "overdue_work": work.filter(due_at__lt=timezone.now()).count(),
            "unassigned_work": work.filter(assigned_to__isnull=True).count(),
        }
        for status in STATUS_ORDER:
            row[f"status_{status.lower()}"] = counts.get(status, 0)
        rows.append(row)
        links.append({
            "label": f"Open {_entity_key(kind, entity)}",
            "url": f"/projects/{entity.id}" if kind == "project" else "/batches",
            "kind": kind,
        })
    context = {
        "comparison": {
            "analysis": "bottleneck",
            "kind": kind,
            "identifiers": [_entity_key(kind, entity) for entity in entities],
            "days": stale_days,
            "metric": "work",
        }
    }
    chart_series = []
    for status in STATUS_ORDER:
        chart_series.append({
            "dataKey": f"status_{status.lower()}",
            "label": status.replace("_", " ").title(),
            "axisLabel": "Stale samples",
            "valueFormat": "integer",
        })
    return {
        "answer": (
            f"Bottleneck review used a {stale_days}-day status threshold across "
            f"{len(entities)} accessible {kind}(s). "
            f"Found {sum(row['stale_samples'] for row in rows)} stale sample(s) and "
            f"{sum(row['overdue_work'] for row in rows)} overdue work item(s)."
        ),
        "comparison": {
            "title": "Workflow bottleneck review",
            "kind": "bottleneck",
            "columns": [
                {"key": "entity", "label": kind.title()},
                {"key": "stale_samples", "label": "Stale samples", "format": "integer"},
                {"key": "average_stale_days", "label": "Average days", "format": "number"},
                {"key": "oldest_stale_days", "label": "Oldest days", "format": "number"},
                {"key": "overdue_work", "label": "Overdue work", "format": "integer"},
                {"key": "unassigned_work", "label": "Unassigned work", "format": "integer"},
            ],
            "rows": rows,
            "filters": context["comparison"],
            "notes": ["Terminal samples are excluded from stale-status calculations."],
        },
        "chart": {
            "chartType": "bar",
            "meta": {
                "title": "Stale samples by workflow status",
                "description": f"Samples unchanged for at least {stale_days} days.",
            },
            "xKey": "entity",
            "xAxisLabel": kind.title(),
            "stacked": True,
            "series": chart_series,
            "data": rows,
        },
        "links": links,
        "context": context,
        "suggestions": [
            "Use a 14 day bottleneck threshold",
            "Graph overdue and unassigned work",
            "Export this comparison as PDF",
        ],
        "skip_llm": True,
    }


def _comparison_export(context, output_format):
    spec = dict(context.get("comparison") or {})
    output_format = "CSV" if str(output_format).upper() == "CSV" else "PDF"
    title = spec.get("analysis", "comparison").replace("_", " ").title()
    filters = {
        "report_type": "COMPARISON_ANALYSIS",
        "comparison_spec": spec,
        "output_format": output_format,
        "timezone": str(timezone.get_current_timezone()),
    }
    preview = {
        "title": "Comparison artifact preview",
        "operation": "GENERATE_COMPARISON_ARTIFACT",
        "project": "Permission-filtered comparison",
        "records_affected": len(spec.get("identifiers") or []),
        "excluded_count": 0,
        "records": [{
            "id": title,
            "label": title,
            "current": spec,
            "proposed": {"output": output_format},
        }],
        "current_values": spec,
        "proposed_values": {
            "format": output_format,
            "recalculate_at_confirmation": True,
            "audited": True,
        },
    }
    return {
        "answer": "Review the comparison filters below. Access and metrics will be recalculated when you confirm.",
        "links": [],
        "skip_llm": True,
        "pending_action": {
            "type": "COMPLIANCE_REPORT",
            "summary": f"Export {title.lower()} as {output_format}",
            "payload": {
                "operation": "GENERATE_REPORT",
                "filters": filters,
                "preview": preview,
            },
        },
    }


def run_comparison_spec(spec, user):
    spec = dict(spec or {})
    analysis = str(spec.get("analysis") or "compare").lower()
    kind = str(spec.get("kind") or "project").lower().rstrip("s")
    identifiers = list(spec.get("identifiers") or [])
    days = _safe_days(spec.get("days"))
    metric = str(spec.get("metric") or "overview").lower()
    result_key = str(spec.get("result_key") or "").strip()
    chart_type = str(spec.get("chart_type") or "auto").lower()
    if chart_type not in COMPARISON_CHART_TYPES:
        chart_type = "auto"
    result_keys = [
        str(value).strip()
        for value in (spec.get("result_keys") or [])
        if str(value).strip()
    ][:10]
    request_text = str(spec.get("_request_text") or "")
    if analysis == "trend":
        return result_trend(
            identifiers,
            user,
            kind=kind,
            days=days or 90,
            result_key=result_key,
        )
    if analysis in {"outlier", "outliers"}:
        return find_outliers(
            identifiers,
            user,
            kind=kind,
            days=days or 90,
            result_key=result_key,
        )
    if analysis in {"bottleneck", "bottlenecks"}:
        return find_bottlenecks(
            identifiers,
            user,
            kind=kind,
            days=days or 7,
        )
    return compare_entities(
        kind,
        identifiers,
        user,
        days=days,
        metric=metric,
        chart_type=chart_type,
        result_keys=result_keys,
        request_text=request_text,
    )


def _why_comparison(result, metric, user):
    comparison = result.get("comparison") or {}
    rows = comparison.get("rows") or []
    if not rows:
        return result
    metric_keys = {
        "qc": ("qc_failure_rate", "QC failure rate", "%"),
        "work": ("overdue_work", "overdue work", ""),
        "turnaround": ("turnaround_days", "average turnaround", " days"),
        "metadata": ("missing_metadata", "samples missing metadata", ""),
        "overview": ("sample_count", "visible sample count", ""),
    }
    key, label, suffix = metric_keys.get(metric, metric_keys["overview"])
    available = [row for row in rows if row.get(key) is not None]
    if not available:
        result["answer"] += f"\n\nThere is not enough data to rank {label}."
        return result
    highest = max(available, key=lambda row: row.get(key) or 0)
    lowest = min(available, key=lambda row: row.get(key) or 0)
    result["answer"] += (
        f"\n\nFor {label}, {highest['entity']} is highest at "
        f"{highest[key]}{suffix}; {lowest['entity']} is lowest at {lowest[key]}{suffix}. "
        "This identifies the records contributing to the difference, but does not claim a biological cause."
    )
    filters = comparison.get("filters") or {}
    kind = filters.get("kind")
    entities, _ = _resolve_entities(kind, [highest["entity"]], user)
    if not entities:
        return result
    samples = _scope_samples(kind, entities[0], user)
    cutoff = _cutoff(_safe_days(filters.get("days")))
    if metric == "qc":
        failures = Result.objects.filter(
            work_item__sample__in=samples,
            qc_passed=False,
        )
        if cutoff:
            failures = failures.filter(created_at__gte=cutoff)
        contributors = Counter(failures.values_list("key", flat=True)).most_common(3)
        if contributors:
            detail = ", ".join(f"{name}: {count}" for name, count in contributors)
            result["answer"] += f" Top failed-result contributors in {highest['entity']}: {detail}."
    elif metric == "work":
        overdue = WorkItem.objects.filter(
            sample__in=samples,
            status__in=OPEN_WORK_STATUSES,
            due_at__lt=timezone.now(),
        )
        if cutoff:
            overdue = overdue.filter(created_at__gte=cutoff)
        contributors = Counter(overdue.values_list("work_type", flat=True)).most_common(3)
        if contributors:
            detail = ", ".join(f"{name}: {count}" for name, count in contributors)
            result["answer"] += f" Top overdue work types in {highest['entity']}: {detail}."
    elif metric == "metadata":
        sample_list = list(samples)
        metadata, required_fields = _metadata_for_samples(sample_list)
        missing_counts = Counter()
        for sample in sample_list:
            present = metadata.get(str(sample.id), {})
            for field in required_fields:
                if present.get(field) in (None, "", [], {}):
                    missing_counts[field] += 1
        if missing_counts:
            detail = ", ".join(
                f"{name}: {count}" for name, count in missing_counts.most_common(3)
            )
            result["answer"] += f" Most commonly missing fields in {highest['entity']}: {detail}."
    return result


def route_comparison_analytics(message, user, context=None):
    context = context or {}
    previous = dict(context.get("comparison") or {})
    text = str(message or "").strip()
    lower = text.lower()
    requested_chart_type = _extract_chart_type(text)
    if previous and contains_any_intent_phrase(
        text,
        ["export this", "download this"],
    ):
        return _comparison_export(context, "CSV" if "csv" in lower else "PDF")

    visualization_follow_up = bool(previous) and (
        any(word in lower for word in ["graph", "plot", "chart"])
        and any(
            term in lower
            for term in [
                "qc",
                "failure",
                "pass rate",
                "status",
                "work",
                "turnaround",
                "metadata",
                "result",
                "trend",
            ]
        )
    )
    filter_only_follow_up = bool(previous) and bool(
        re.fullmatch(
            r"\s*(?:(?:only\s+)?show\s+)?(?:the\s+)?"
            r"(?:(?:last|past|previous)\s+\d+\s+days?|this\s+month)"
            r"(?:\s+(?:only|please))?[.!?]?\s*",
            lower,
        )
    )
    explanation_follow_up = bool(previous) and (
        contains_any_intent_phrase(text, ["why is", "why are"])
        and (
            any(
                word in lower
                for word in ["higher", "lower", "more", "fewer", "different", "worse", "better"]
            )
            or any(str(identifier).lower() in lower for identifier in previous.get("identifiers", []))
        )
    )
    awaiting_identifiers = bool(previous.get("awaiting_identifiers"))
    requested_kind = str(previous.get("kind") or "sample")
    identifier_follow_up_values = (
        _requested_identifiers(text, requested_kind, user)
        if awaiting_identifiers
        else []
    )
    identifier_follow_up = awaiting_identifiers and bool(identifier_follow_up_values)
    style_follow_up = bool(previous) and requested_chart_type is not None
    previous_kind = str(previous.get("kind") or "sample")
    mentioned_follow_up_values = (
        _requested_identifiers(text, previous_kind, user) if previous else []
    )
    selection_edit_follow_up = bool(previous) and bool(mentioned_follow_up_values) and bool(
        re.search(r"\b(?:add|also|exclude|include|remove|without)\b", lower)
    )
    metric_follow_up = bool(previous) and bool(
        re.search(r"\b(?:compare|show|use|using)\b", lower)
        and (
            re.search(r"\b(?:it|them|these|those|same)\b", lower)
            or not re.search(r"\b(?:samples?|projects?|batches?)\b", lower)
        )
    )
    follow_up = any(
        [
            visualization_follow_up,
            filter_only_follow_up,
            explanation_follow_up,
            style_follow_up,
            identifier_follow_up,
            selection_edit_follow_up,
            metric_follow_up,
        ]
    )

    unsupported_domain = bool(
        re.search(r"\b(?:inventory|reagents?|lots?|instruments?)\b", lower)
    ) and not bool(
        re.search(r"\b(?:samples?|projects?|batches?|results?)\b", lower)
    )
    if unsupported_domain:
        return None

    analysis = None
    if any(word in lower for word in ["outlier", "outliers", "unusual", "anomalous"]):
        analysis = "outliers"
    elif any(word in lower for word in ["bottleneck", "getting stuck", "samples stuck", "workflow delay"]):
        analysis = "bottleneck"
    elif "compare" in lower or "difference between" in lower or follow_up:
        analysis = previous.get("analysis", "compare") if follow_up else "compare"
    elif requested_chart_type == "scatter":
        analysis = "compare"
    elif requested_chart_type:
        if "batch" in lower:
            requested_kind = "batch"
        elif "project" in lower:
            requested_kind = "project"
        else:
            requested_kind = "sample"
        if len(_find_mentions(text, requested_kind, user)) >= 2:
            analysis = "compare"
    elif any(word in lower for word in ["trend", "graph", "plot", "chart"]):
        if "result" in lower or _extract_result_key(text):
            analysis = "trend"
    if analysis is None:
        return None

    if follow_up:
        spec = previous
        if identifier_follow_up:
            spec["identifiers"] = identifier_follow_up_values
            spec.pop("awaiting_identifiers", None)
        elif selection_edit_follow_up:
            current = list(spec.get("identifiers") or [])
            if re.search(r"\b(?:exclude|remove|without)\b", lower):
                remove = {value.casefold() for value in mentioned_follow_up_values}
                spec["identifiers"] = [
                    value for value in current if str(value).casefold() not in remove
                ]
            else:
                seen = {str(value).casefold() for value in current}
                spec["identifiers"] = current + [
                    value
                    for value in mentioned_follow_up_values
                    if value.casefold() not in seen
                ]
    else:
        if "batch" in lower:
            kind = "batch"
        elif "project" in lower:
            kind = "project"
        elif "sample" in lower:
            kind = "sample"
        else:
            kind = "project" if analysis in {"outliers", "bottleneck"} else "sample"
        identifiers = _requested_identifiers(text, kind, user)
        if not identifiers and analysis == "compare" and kind in {"project", "batch"}:
            queryset = _accessible_projects(user) if kind == "project" else _accessible_batches(user)
            identifiers = [_entity_key(kind, entity) for entity in queryset[:MAX_COMPARISON_ENTITIES]]
        spec = {
            "analysis": analysis,
            "kind": kind,
            "identifiers": identifiers,
            "days": None,
            "metric": "overview",
            "chart_type": requested_chart_type or "auto",
            "result_keys": [],
        }
    spec["analysis"] = analysis
    spec["days"] = _extract_days(text, spec.get("days"))
    spec["metric"] = _metric_from_message(text, spec.get("metric", "overview"))
    extracted_key = _extract_result_key(text)
    if extracted_key:
        spec["result_key"] = extracted_key
    if requested_chart_type:
        spec["chart_type"] = requested_chart_type
    spec["_request_text"] = text
    if analysis == "outliers" and previous and not spec.get("identifiers"):
        spec["identifiers"] = previous.get("identifiers", [])
    if "find unusual" in lower and previous:
        spec["analysis"] = "outliers"
    if spec.get("identifiers"):
        resolution = resolve_entities(
            spec["kind"],
            spec["identifiers"],
            user,
            limit=MAX_COMPARISON_ENTITIES,
        )
        clarification = entity_clarification(spec["kind"], resolution)
        if clarification:
            clarification["context"] = {
                "comparison": {
                    **spec,
                    "awaiting_identifiers": True,
                }
            }
            return clarification
        if resolution["corrected"]:
            spec["identifiers"] = [
                *[_entity_key(spec["kind"], entity) for entity in resolution["entities"]],
                *resolution["missing"],
            ]
    result = run_comparison_spec(spec, user)
    if contains_any_intent_phrase(text, ["why is", "why are"]):
        result = _why_comparison(
            result,
            spec.get("metric", "overview"),
            user,
        )
    return result
