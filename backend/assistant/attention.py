from datetime import timedelta

from django.utils import timezone

from alignments.models import AlignmentJob
from blast.models import BlastJob
from core.health import build_health_status
from core.permissions import is_admin
from custom_fields.models import FieldDefinition, FieldValue
from events.models import Event
from imports.models import ImportJob
from projects.access import get_project_access_queryset
from results.models import WorkItem
from samples.access import get_sample_access_queryset
from samples.models import Sample


ATTENTION_AGE_DAYS = 3
LINK_LIMIT_PER_CATEGORY = 5

SAMPLE_STATUS_EVENT_ACTIONS = [
    "SAMPLE_STATUS_CHANGED",
    "BULK_SAMPLE_STATUS_CHANGED",
    "UPDATED",
    "BULK_SAMPLE_UPDATED",
]

HEALTH_COMPONENTS = [
    ("db_ok", "Database"),
    ("redis_ok", "Redis / cache"),
    ("clustalo_ok", "Clustal Omega"),
    ("blastn_ok", "BLASTN"),
    ("blastp_ok", "BLASTP"),
    ("makeblastdb_ok", "makeblastdb"),
    ("pyopenms_ok", "pyOpenMS"),
]


def attention_link(label, url, kind, extra=None):
    return {
        "label": label,
        "url": url,
        "kind": kind,
        "extra": extra or {},
    }


def detect_attention_scope(message):
    lower = str(message or "").strip().lower()

    if any(
        phrase in lower
        for phrase in [
            "what needs attention",
            "needs attention",
            "attention summary",
            "what should i review",
            "what should we review",
            "operational warnings",
        ]
    ):
        if "qc" in lower:
            return "qc"
        if "sample" in lower:
            return "samples"
        return "all"

    if any(
        phrase in lower
        for phrase in [
            "show stuck samples",
            "which samples are stuck",
            "stale samples",
        ]
    ):
        return "stuck_samples"

    if any(
        phrase in lower
        for phrase in [
            "samples missing information",
            "missing sample information",
            "missing required information",
        ]
    ):
        return "missing_sample_information"

    if any(
        phrase in lower
        for phrase in [
            "qc reviews",
            "qc failures",
            "failed qc",
            "pending qc",
        ]
    ):
        return "qc"

    if any(
        phrase in lower
        for phrase in [
            "overdue work",
            "old work items",
            "stale work items",
        ]
    ):
        return "overdue_work_items"

    if any(
        phrase in lower
        for phrase in [
            "show failed jobs",
            "failed background jobs",
            "failed import blast alignment",
        ]
    ):
        return "failed_jobs"

    if any(
        phrase in lower
        for phrase in [
            "system warnings",
            "system health warnings",
            "health warnings",
        ]
    ):
        return "system_health"

    if any(
        phrase in lower
        for phrase in [
            "inventory warnings",
            "low stock",
            "expiring inventory",
        ]
    ):
        return "inventory"

    return None


def _is_blank_value(value):
    return value is None or value == "" or value == [] or value == {}


def _stuck_samples(samples, cutoff):
    candidates = [
        sample
        for sample in samples
        if sample.status not in [Sample.STATUS_REPORTED, Sample.STATUS_ARCHIVED]
        and sample.created_at <= cutoff
    ]

    if not candidates:
        return []

    candidate_ids = {sample.id for sample in candidates}
    latest_status_events = {}

    events = (
        Event.objects.filter(
            entity_type="Sample",
            entity_id__in=[str(sample_id) for sample_id in candidate_ids],
            action__in=SAMPLE_STATUS_EVENT_ACTIONS,
        )
        .values("entity_id", "action", "timestamp", "payload")
        .order_by("entity_id", "-timestamp")
    )

    for event in events:
        try:
            sample_id = int(event["entity_id"])
        except (TypeError, ValueError):
            continue

        if sample_id in latest_status_events:
            continue

        changed_fields = (event.get("payload") or {}).get("changed_fields", [])
        is_status_event = event["action"] in [
            "SAMPLE_STATUS_CHANGED",
            "BULK_SAMPLE_STATUS_CHANGED",
        ]

        if is_status_event or "status" in changed_fields:
            latest_status_events[sample_id] = event["timestamp"]

    return [
        sample
        for sample in candidates
        if latest_status_events.get(sample.id, sample.created_at) <= cutoff
    ]


def _samples_missing_information(samples):
    required_fields = list(
        FieldDefinition.objects.filter(
            entity_type="Sample",
            required=True,
        ).order_by("name")
    )

    sample_ids = [str(sample.id) for sample in samples]
    present_values = set()

    if required_fields and sample_ids:
        values = FieldValue.objects.filter(
            entity_type="Sample",
            entity_id__in=sample_ids,
            field_definition__in=required_fields,
        ).values("entity_id", "field_definition_id", "value")

        for value in values:
            if not _is_blank_value(value["value"]):
                present_values.add(
                    (value["entity_id"], value["field_definition_id"])
                )

    missing = []

    for sample in samples:
        missing_fields = []

        if sample.project_id is None:
            missing_fields.append("project")

        if sample.container_id is None:
            missing_fields.append("container")

        for field in required_fields:
            if (str(sample.id), field.id) not in present_values:
                missing_fields.append(field.label or field.name)

        if missing_fields:
            missing.append((sample, missing_fields))

    return missing


def _visible_jobs(queryset, user, owner_lookup):
    return get_project_access_queryset(
        queryset,
        user,
        project_lookup="project",
        owner_lookup=owner_lookup,
    )


def _health_warnings():
    health = build_health_status()
    warnings = []

    for key, label in HEALTH_COMPONENTS:
        if health.get(key):
            continue

        error_key = key.replace("_ok", "_error")
        warnings.append({
            "component": label,
            "error": health.get(error_key, "Unavailable"),
        })

    return warnings


def _deduplicate_links(links):
    seen = set()
    output = []

    for link in links:
        key = (link["url"], link["label"])
        if key in seen:
            continue

        seen.add(key)
        output.append(link)

    return output


def build_attention_summary(user, scope="all", now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(days=ATTENTION_AGE_DAYS)

    sample_queryset = get_sample_access_queryset(
        Sample.objects.select_related(
            "project",
            "container",
            "created_by",
        ).all(),
        user,
    )
    samples = list(sample_queryset.order_by("created_at", "id"))
    sample_ids = [sample.id for sample in samples]

    stuck_samples = _stuck_samples(samples, cutoff)
    missing_samples = _samples_missing_information(samples)

    work_items = WorkItem.objects.filter(sample_id__in=sample_ids).select_related(
        "sample",
        "sample__project",
    )
    pending_qc = list(
        work_items.filter(
            status=WorkItem.STATUS_COMPLETED,
            qc_status=WorkItem.QC_PENDING_REVIEW,
        ).order_by("created_at", "id")
    )
    failed_qc = list(
        work_items.filter(
            qc_status__in=[
                WorkItem.QC_REJECTED,
                WorkItem.QC_RERUN_REQUIRED,
            ]
        ).order_by("created_at", "id")
    )
    overdue_work_items = list(
        work_items.filter(
            status__in=[
                WorkItem.STATUS_PENDING,
                WorkItem.STATUS_IN_PROGRESS,
            ],
            created_at__lte=cutoff,
        ).order_by("created_at", "id")
    )

    failed_imports = list(
        _visible_jobs(
            ImportJob.objects.filter(status="FAILED").select_related(
                "instrument",
                "project",
                "uploaded_by",
            ),
            user,
            "uploaded_by",
        ).order_by("-created_at", "-id")
    )
    failed_blast_jobs = list(
        _visible_jobs(
            BlastJob.objects.filter(status=BlastJob.STATUS_FAILED).select_related(
                "project",
                "created_by",
            ),
            user,
            "created_by",
        ).order_by("-created_at", "-id")
    )
    failed_alignments = list(
        _visible_jobs(
            AlignmentJob.objects.filter(status="FAILED").select_related(
                "project",
                "created_by",
            ),
            user,
            "created_by",
        ).order_by("-created_at", "-id")
    )

    system_health_restricted = not is_admin(user)
    system_warnings = []

    if not system_health_restricted and scope in ["all", "system_health"]:
        system_warnings = _health_warnings()

    counts = {
        "stuck_samples": len(stuck_samples),
        "missing_sample_information": len(missing_samples),
        "pending_qc_reviews": len(pending_qc),
        "failed_qc_reviews": len(failed_qc),
        "overdue_work_items": len(overdue_work_items),
        "failed_imports": len(failed_imports),
        "failed_blast_jobs": len(failed_blast_jobs),
        "failed_alignments": len(failed_alignments),
        "system_warnings": len(system_warnings),
    }

    section_keys = {
        "all": list(counts.keys()),
        "samples": ["stuck_samples", "missing_sample_information"],
        "stuck_samples": ["stuck_samples"],
        "missing_sample_information": ["missing_sample_information"],
        "qc": ["pending_qc_reviews", "failed_qc_reviews"],
        "overdue_work_items": ["overdue_work_items"],
        "failed_jobs": [
            "failed_imports",
            "failed_blast_jobs",
            "failed_alignments",
        ],
        "system_health": ["system_warnings"],
        "inventory": [],
    }
    included_keys = section_keys.get(scope, section_keys["all"])
    total = sum(counts[key] for key in included_keys)

    lines = [f"What needs attention: {total} attention item(s).", ""]
    links = []

    if "stuck_samples" in included_keys:
        lines.append(
            f"- Samples in the same active status for more than "
            f"{ATTENTION_AGE_DAYS} days: {counts['stuck_samples']}"
        )
        for sample in stuck_samples[:LINK_LIMIT_PER_CATEGORY]:
            links.append(
                attention_link(
                    f"Stuck sample: {sample.sample_id}",
                    f"/samples/{sample.id}",
                    "sample",
                    {
                        "id": sample.id,
                        "sample_id": sample.sample_id,
                        "status": sample.status,
                    },
                )
            )

    if "missing_sample_information" in included_keys:
        lines.append(
            "- Samples missing project, container, or required fields: "
            f"{counts['missing_sample_information']}"
        )
        for sample, missing_fields in missing_samples[:LINK_LIMIT_PER_CATEGORY]:
            links.append(
                attention_link(
                    f"Missing information: {sample.sample_id}",
                    f"/samples/{sample.id}",
                    "sample",
                    {
                        "id": sample.id,
                        "sample_id": sample.sample_id,
                        "missing_fields": missing_fields,
                    },
                )
            )

    if "pending_qc_reviews" in included_keys:
        lines.append(
            f"- Completed work items pending QC review: "
            f"{counts['pending_qc_reviews']}"
        )
        for work_item in pending_qc[:LINK_LIMIT_PER_CATEGORY]:
            links.append(
                attention_link(
                    f"Pending QC: {work_item.sample.sample_id} — {work_item.name}",
                    f"/samples/{work_item.sample_id}",
                    "work_item",
                    {
                        "id": work_item.id,
                        "sample_id": work_item.sample_id,
                        "qc_status": work_item.qc_status,
                    },
                )
            )

    if "failed_qc_reviews" in included_keys:
        lines.append(
            "- QC rejected or requiring a re-run: "
            f"{counts['failed_qc_reviews']}"
        )
        for work_item in failed_qc[:LINK_LIMIT_PER_CATEGORY]:
            links.append(
                attention_link(
                    f"QC {work_item.qc_status}: "
                    f"{work_item.sample.sample_id} — {work_item.name}",
                    f"/samples/{work_item.sample_id}",
                    "work_item",
                    {
                        "id": work_item.id,
                        "sample_id": work_item.sample_id,
                        "qc_status": work_item.qc_status,
                    },
                )
            )

    if "overdue_work_items" in included_keys:
        lines.append(
            f"- Open work items older than {ATTENTION_AGE_DAYS} days: "
            f"{counts['overdue_work_items']}"
        )
        for work_item in overdue_work_items[:LINK_LIMIT_PER_CATEGORY]:
            links.append(
                attention_link(
                    f"Old work item: {work_item.sample.sample_id} — {work_item.name}",
                    f"/samples/{work_item.sample_id}",
                    "work_item",
                    {
                        "id": work_item.id,
                        "sample_id": work_item.sample_id,
                        "status": work_item.status,
                    },
                )
            )

    if "failed_imports" in included_keys:
        lines.append(f"- Failed instrument imports: {counts['failed_imports']}")
        for job in failed_imports[:LINK_LIMIT_PER_CATEGORY]:
            links.append(
                attention_link(
                    f"Failed import #{job.id}",
                    f"/imports/{job.id}",
                    "import_job",
                    {"id": job.id, "status": job.status},
                )
            )

    if "failed_blast_jobs" in included_keys:
        lines.append(f"- Failed BLAST jobs: {counts['failed_blast_jobs']}")
        for job in failed_blast_jobs[:LINK_LIMIT_PER_CATEGORY]:
            links.append(
                attention_link(
                    f"Failed BLAST: {job.name}",
                    "/blast",
                    "blast_job",
                    {"id": job.id, "status": job.status},
                )
            )

    if "failed_alignments" in included_keys:
        lines.append(f"- Failed alignment jobs: {counts['failed_alignments']}")
        for job in failed_alignments[:LINK_LIMIT_PER_CATEGORY]:
            links.append(
                attention_link(
                    f"Failed alignment: {job.name}",
                    "/alignments",
                    "alignment_job",
                    {"id": job.id, "status": job.status},
                )
            )

    if "system_warnings" in included_keys:
        if system_health_restricted:
            lines.append("- System health warnings: admin access required")
        else:
            lines.append(f"- System health warnings: {counts['system_warnings']}")

            if system_warnings:
                links.append(
                    attention_link(
                        "Open system status",
                        "/system-status",
                        "system_status",
                        {"warnings": system_warnings},
                    )
                )

    if total == 0 and scope != "inventory":
        lines.extend([
            "",
            "No accessible records matched the selected attention checks.",
        ])

    if scope in ["all", "inventory"]:
        lines.extend([
            "",
            (
                "Coverage note: low-stock and expiry checks are not available "
                "because the current inventory schema stores locations and "
                "containers, but not quantities or expiration dates."
            ),
        ])

    suggestions = [
        "Show stuck samples",
        "Show samples missing information",
        "Which QC reviews need attention?",
        "Show failed jobs",
    ]

    if is_admin(user):
        suggestions.append("Show system health warnings")

    details = {
        "stuck_sample_ids": [sample.id for sample in stuck_samples],
        "missing_sample_ids": [sample.id for sample, _fields in missing_samples],
        "pending_qc_work_item_ids": [item.id for item in pending_qc],
        "failed_qc_work_item_ids": [item.id for item in failed_qc],
        "overdue_work_item_ids": [item.id for item in overdue_work_items],
        "failed_import_ids": [job.id for job in failed_imports],
        "failed_blast_job_ids": [job.id for job in failed_blast_jobs],
        "failed_alignment_job_ids": [job.id for job in failed_alignments],
        "system_warnings": system_warnings,
    }

    return {
        "answer": "\n".join(lines),
        "links": _deduplicate_links(links),
        "suggestions": suggestions,
        "attention": {
            "scope": scope,
            "generated_at": now.isoformat(),
            "threshold_days": ATTENTION_AGE_DAYS,
            "total": total,
            "counts": counts,
            "details": details,
            "inventory_checks_available": False,
            "system_health_restricted": system_health_restricted,
        },
        "skip_llm": True,
    }


def route_attention_summary(message, user):
    scope = detect_attention_scope(message)
    if scope is None:
        return None

    return build_attention_summary(user, scope=scope)
