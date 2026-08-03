import re
from django.db.models import Count, Q

from samples.access import get_sample_access_queryset
from samples.models import Sample

try:
    from migration_toolkit.models import MigrationJob, MigrationRowRecord
except Exception:
    MigrationJob = None
    MigrationRowRecord = None


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


def sample_link(sample):
    return {
        "label": f"Open {sample.sample_id}",
        "url": f"/samples/{sample.id}",
    }


def sample_line(sample):
    project = getattr(sample, "project", None)
    container = getattr(sample, "container", None)

    project_text = getattr(project, "code", None) or "No project"
    container_text = (
        getattr(container, "name", None)
        or getattr(container, "label", None)
        or getattr(container, "barcode", None)
        or (f"Container #{sample.container_id}" if sample.container_id else "No container")
    )

    return (
        f"- {sample.sample_id} — status: {sample.status}, "
        f"project: {project_text}, container: {container_text}"
    )


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


def get_qc_worklist(message, user, limit=25):
    queryset = apply_sample_access(user)

    samples = list(
        queryset.filter(status__iexact="QC")
        .order_by("-created_at", "sample_id")
        .distinct()[:limit]
    )

    total = queryset.filter(status__iexact="QC").distinct().count()

    if not samples:
        return {
            "answer": "No accessible samples are currently in QC.",
            "links": [],
            "suggestions": [
                "Count samples by status",
                "Show failed migration jobs",
                "Show skipped migration rows",
            ],
            "skip_llm": True,
        }

    lines = [f"You have {total} accessible sample(s) in QC."]
    lines.extend(sample_line(sample) for sample in samples)

    if total > len(samples):
        lines.append(f"...showing first {len(samples)} of {total}.")

    return {
        "answer": "\n".join(lines),
        "links": [sample_link(sample) for sample in samples],
        "suggestions": [
            "Count samples by status",
            "What percentage of migration rows failed?",
            "Show failed migration jobs",
        ],
    }


def count_samples_in_qc(message, user):
    queryset = apply_sample_access(user)
    count = queryset.filter(status__iexact="QC").distinct().count()

    return {
        "answer": f"You have {count} accessible sample(s) in QC.",
        "links": [],
        "suggestions": [
            "Which samples need QC?",
            "Count samples by status",
            "Show failed migration jobs",
        ],
        "skip_llm": True,
    }


def count_samples_by_status(message, user):
    queryset = apply_sample_access(user)

    rows = list(
        queryset.values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    )

    if not rows:
        return {
            "answer": "No accessible samples were found.",
            "links": [],
            "suggestions": [
                "Find sample",
                "Show failed migration jobs",
            ],
            "skip_llm": True,
        }

    total = sum(row["count"] for row in rows)
    lines = [f"Accessible samples by status ({total} total):"]

    for row in rows:
        status = row["status"] or "UNKNOWN"
        count = row["count"]
        percent = (count / total * 100) if total else 0
        lines.append(f"- {status}: {count} ({percent:.1f}%)")

    return {
        "answer": "\n".join(lines),
        "links": [],
        "suggestions": [
            "Which samples need QC?",
            "How many samples are in QC?",
            "Show failed migration jobs",
        ],
        "skip_llm": True,
    }


def migration_row_percent(message, metric="failed"):
    if MigrationJob is None or MigrationRowRecord is None:
        return {
            "answer": "Migration toolkit models are not available in this OpenLIMS deployment.",
            "links": [],
            "suggestions": [
                "Count samples by status",
                "Which samples need QC?",
            ],
            "skip_llm": True,
        }

    job_id = extract_job_id(message)

    row_queryset = MigrationRowRecord.objects.all()

    job = None
    if job_id:
        try:
            job = MigrationJob.objects.get(id=job_id)
            row_queryset = row_queryset.filter(job_id=job_id)
        except MigrationJob.DoesNotExist:
            return {
                "answer": f"I could not find migration job #{job_id}.",
                "links": [],
                "suggestions": [
                    "Show failed migration jobs",
                    "Show skipped migration rows",
                ],
                "skip_llm": True,
            }
    else:
        job = MigrationJob.objects.order_by("-created_at").first()
        if job:
            row_queryset = row_queryset.filter(job=job)

    if not job:
        return {
            "answer": "No migration jobs were found.",
            "links": [],
            "suggestions": [
                "Count samples by status",
                "Which samples need QC?",
            ],
            "skip_llm": True,
        }

    total_rows = row_queryset.count()

    failed_rows = row_queryset.filter(
        Q(status__iexact="ERROR")
        | Q(status__iexact="FAILED")
        | Q(status__icontains="error")
        | Q(status__icontains="fail")
    ).count()

    skipped_rows = row_queryset.filter(
        Q(status__iexact="SKIPPED")
        | Q(status__icontains="skip")
    ).count()

    if total_rows == 0:
        summary = getattr(job, "summary", {}) or {}
        processed = int(summary.get("rows_processed") or 0)
        skipped = summary.get("skipped_rows") or []

        if processed:
            total_rows = processed
            skipped_rows = len(skipped)
            failed_rows = len(skipped)

    if total_rows == 0:
        return {
            "answer": f"Migration job #{job.id} does not have row records to calculate from yet.",
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

    if metric == "skipped":
        count = skipped_rows
        label = "skipped"
    else:
        count = failed_rows
        label = "failed"

    percent = count / total_rows * 100

    return {
        "answer": (
            f"Migration job #{job.id} had {count} {label} row(s) out of "
            f"{total_rows} total row(s), which is {percent:.1f}%."
        ),
        "links": [
            {
                "label": f"Open migration job #{job.id}",
                "url": f"/data-migration/jobs/{job.id}",
            }
        ],
        "suggestions": [
            "Show failed migration jobs",
            "Show skipped migration rows",
            "Count samples by status",
        ],
        "skip_llm": True,
    }


def route_worklist_or_calculation(message, user):
    text = str(message or "").strip()
    lower = text.lower()

    qc_terms = ["qc", "quality control", "review"]
    sample_terms = ["sample", "samples", "worklist", "work list"]

    if any(term in lower for term in qc_terms):
        if any(term in lower for term in ["which", "show", "list", "need", "needs", "waiting", "worklist", "work list"]):
            return get_qc_worklist(text, user)

        if any(term in lower for term in ["how many", "count", "number of"]):
            return count_samples_in_qc(text, user)

    if "count samples by status" in lower:
        return count_samples_by_status(text, user)

    if "samples by status" in lower:
        return count_samples_by_status(text, user)

    if "how many samples" in lower and "status" in lower:
        return count_samples_by_status(text, user)

    if "percentage" in lower or "percent" in lower:
        if "migration" in lower and ("failed" in lower or "fail" in lower or "error" in lower):
            return migration_row_percent(text, metric="failed")

        if "migration" in lower and ("skipped" in lower or "skip" in lower):
            return migration_row_percent(text, metric="skipped")

    if "how many" in lower and "samples" in lower and "qc" in lower:
        return count_samples_in_qc(text, user)

    return None
