import re
from collections import Counter

from django.db.models import Q

from migration_toolkit.models import MigrationJob, MigrationRowRecord
from projects.models import Project
from samples.access import get_sample_access_queryset
from samples.models import Sample
from .action_routes import route_confirmed_action_proposal
from .attention import build_attention_summary, route_attention_summary
from .calculations import route_worklist_or_calculation
from .charts import route_assistant_chart
from .clarifications import route_assistant_clarification
from .comparisons import route_comparison_analytics
from .conversation import general_question_result, route_conversation_utility
from .investigations import route_investigation_workbench
from .inventory_operations import route_inventory_operations
from .intent_matching import contains_any_intent_phrase
from .barcode_operations import route_barcode_operations
from .monitoring import route_system_monitoring
from .notification_operations import route_notification_operations
from .reporting_operations import route_reporting_operations
from .sop_operations import route_sop_assistant
from .workitem_operations import route_workitem_operations
from .qc_operations import route_qc_operations
from .sample_operations import route_sample_management
from .sequences import route_assistant_sequence
from .suggestions import (
    batch_prompt,
    comparison_prompt,
    project_prompt,
    sample_prompt,
    without_empty,
)


def make_link(label, url, kind="record", extra=None):
    return {
        "label": label,
        "url": url,
        "kind": kind,
        "extra": extra or {},
    }


def clean_query(message):
    return str(message or "").strip()


def extract_record_id(message):
    match = re.search(r"#?(\d+)", message or "")
    if not match:
        return None

    try:
        return int(match.group(1))
    except ValueError:
        return None


def extract_sample_like_tokens(message):
    return re.findall(r"\b[A-Za-z]+[-_][A-Za-z0-9][A-Za-z0-9\-_]*\b", message or "")


def summarize_project(project, user):
    samples = get_sample_access_queryset(
        Sample.objects.filter(
            Q(project=project) | Q(linked_projects=project)
        ).distinct(),
        user,
    )

    status_counts = Counter(samples.values_list("status", flat=True))

    migration_jobs = MigrationJob.objects.filter(project=project).order_by("-created_at")[:5]
    migration_rows = MigrationRowRecord.objects.filter(project=project)

    answer = (
        f"{project.code} — {project.name}\n\n"
        f"This project has {samples.count()} visible sample(s). "
        f"Migration review has {migration_rows.count()} row record(s) linked to this project."
    )

    if status_counts:
        status_text = ", ".join(
            f"{status}: {count}" for status, count in sorted(status_counts.items())
        )
        answer += f"\n\nSample statuses: {status_text}."

    links = [
        make_link(
            f"Open project {project.code}",
            f"/projects/{project.id}",
            "project",
            {"id": project.id, "code": project.code},
        )
    ]

    for job in migration_jobs:
        links.append(
            make_link(
                f"Migration job #{job.id} — {job.status}",
                f"/data-migration/jobs/{job.id}",
                "migration_job",
                {"id": job.id, "status": job.status},
            )
        )

    return {
        "answer": answer,
        "links": links,
    }


def get_sample_detail(sample):
    project_text = (
        f"{sample.project.code} — {sample.project.name}"
        if sample.project_id
        else "Unassigned"
    )

    answer = (
        f"Sample {sample.sample_id}\n\n"
        f"Status: {sample.status}\n"
        f"Project: {project_text}"
    )

    return {
        "answer": answer,
        "links": [
            make_link(
                f"Open sample {sample.sample_id}",
                f"/samples/{sample.id}",
                "sample",
                {"id": sample.id, "sample_id": sample.sample_id},
            )
        ],
    }


def search_samples(message, user, limit=10):
    query = clean_query(message)

    sample_query = query
    for phrase in [
        "find sample",
        "show sample",
        "search sample",
        "open sample",
        "sample",
        "find",
        "show",
        "search",
        "open",
    ]:
        sample_query = sample_query.replace(phrase, "", 1)
        sample_query = sample_query.replace(phrase.title(), "", 1)

    sample_query = sample_query.strip()

    base_queryset = Sample.objects.all().select_related(
        "project",
        "container",
        "created_by",
    )

    queryset = get_sample_access_queryset(base_queryset, user)

    filters = Q()

    if sample_query:
        filters |= Q(sample_id__icontains=sample_query)
        filters |= Q(status__icontains=sample_query)
        filters |= Q(external_ids__external_id__icontains=sample_query)
        filters |= Q(external_ids__label__icontains=sample_query)

        if sample_query.isdigit():
            filters |= Q(id=int(sample_query))

    for token in extract_sample_like_tokens(query):
        filters |= Q(sample_id__icontains=token)
        filters |= Q(external_ids__external_id__icontains=token)

    if not filters:
        return None

    samples = list(queryset.filter(filters).distinct()[:limit])

    if not samples:
        return None

    lines = [f"Found {len(samples)} matching sample(s):"]
    links = []

    for sample in samples:
        project = getattr(sample, "project", None)
        container = getattr(sample, "container", None)

        project_text = getattr(project, "code", None) or "No project"
        container_text = (
            getattr(container, "name", None)
            or getattr(container, "label", None)
            or getattr(container, "barcode", None)
            or (f"Container #{sample.container_id}" if sample.container_id else "No container")
        )

        lines.append(
            f"- {sample.sample_id} — status: {sample.status}, project: {project_text}, container: {container_text}"
        )

        links.append({
            "label": f"Open {sample.sample_id}",
            "url": f"/samples/{sample.id}",
        })

    return {
        "answer": "\n".join(lines),
        "links": links,
        "suggestions": without_empty(
            project_prompt(user),
            "Show failed migration jobs",
            "Show skipped migration rows",
        ),
    }

def search_projects(message, user, limit=10):
    query = clean_query(message)

    queryset = Project.objects.filter(
        Q(code__icontains=query) | Q(name__icontains=query)
    ).order_by("code")

    exact_project = Project.objects.filter(
        Q(code__iexact=query) | Q(name__iexact=query)
    ).first()

    if exact_project:
        return summarize_project(exact_project, user)

    projects = list(queryset[:limit])

    if not projects:
        return None

    if len(projects) == 1:
        return summarize_project(projects[0], user)

    links = []
    lines = [f"I found {len(projects)} matching project(s):"]

    for project in projects:
        lines.append(f"- {project.code} — {project.name}")
        links.append(
            make_link(
                f"{project.code} — {project.name}",
                f"/projects/{project.id}",
                "project",
                {"id": project.id, "code": project.code},
            )
        )

    return {
        "answer": "\n".join(lines),
        "links": links,
    }


def summarize_migration_job(job):
    summary = job.summary or {}
    progress = summary.get("progress") or {}

    lines = [
        f"Migration job #{job.id}",
        "",
        f"Status: {job.status}",
        f"Profile: {job.profile.name}",
        f"Rows processed: {summary.get('rows_processed', progress.get('processed_rows', 0))}",
        f"Row records: {job.row_records.count()}",
        f"Samples created: {len(summary.get('samples_created', []))}",
        f"Samples matched: {len(summary.get('samples_matched', []))}",
        f"Results created: {summary.get('results_created', 0)}",
        f"Skipped/warnings: {len(summary.get('skipped_rows', []))}",
    ]

    if summary.get("error"):
        lines.extend(["", f"Error: {summary['error']}"])

    return {
        "answer": "\n".join(lines),
        "links": [
            make_link(
                f"Open migration job #{job.id}",
                f"/data-migration/jobs/{job.id}",
                "migration_job",
                {"id": job.id, "status": job.status},
            )
        ],
    }


def search_migration_jobs(message):
    record_id = extract_record_id(message)

    if record_id:
        job = MigrationJob.objects.select_related("profile", "project").filter(id=record_id).first()
        if job:
            return summarize_migration_job(job)

    query = clean_query(message).lower()
    queryset = MigrationJob.objects.select_related("profile", "project").all()

    if "failed" in query or "error" in query:
        queryset = queryset.filter(status__in=[
            MigrationJob.STATUS_FAILED,
            MigrationJob.STATUS_PARTIAL_FAILED,
        ])
    elif "running" in query:
        queryset = queryset.filter(status=MigrationJob.STATUS_RUNNING)
    elif "pending" in query:
        queryset = queryset.filter(status=MigrationJob.STATUS_PENDING)
    elif "completed" in query:
        queryset = queryset.filter(status=MigrationJob.STATUS_COMPLETED)

    jobs = list(queryset.order_by("-created_at")[:10])

    if not jobs:
        return None

    links = []
    lines = [f"I found {len(jobs)} migration job(s):"]

    for job in jobs:
        rows = (job.summary or {}).get("rows_processed", 0)
        lines.append(f"- Job #{job.id} — {job.status} — {rows} row(s)")
        links.append(
            make_link(
                f"Migration job #{job.id}",
                f"/data-migration/jobs/{job.id}",
                "migration_job",
                {"id": job.id, "status": job.status},
            )
        )

    return {
        "answer": "\n".join(lines),
        "links": links,
    }


def search_migration_rows(message, limit=10):
    query = clean_query(message)
    lower = query.lower()

    queryset = MigrationRowRecord.objects.select_related(
        "migration_job",
        "project",
        "sample",
    ).all()

    if "skipped" in lower or "skip" in lower:
        queryset = queryset.filter(status=MigrationRowRecord.STATUS_SKIPPED)
    elif "failed" in lower or "error" in lower:
        queryset = queryset.filter(status=MigrationRowRecord.STATUS_ERROR)

    tokens = extract_sample_like_tokens(query)

    if tokens:
        token_filter = Q()
        for token in tokens:
            token_filter |= Q(sample_code__icontains=token)
            token_filter |= Q(project_code__icontains=token)
            token_filter |= Q(project_name__icontains=token)
            token_filter |= Q(raw_row_text__icontains=token)

        queryset = queryset.filter(token_filter)
    elif query:
        queryset = queryset.filter(
            Q(sample_code__icontains=query)
            | Q(project_code__icontains=query)
            | Q(project_name__icontains=query)
            | Q(raw_row_text__icontains=query)
        )

    rows = list(queryset.order_by("-created_at", "row_number")[:limit])

    if not rows:
        return None

    links = []
    lines = [f"I found {len(rows)} migration row record(s):"]

    for row in rows:
        sample_code = row.sample_code or "-"
        project_code = row.project_code or "-"
        lines.append(
            f"- Job #{row.migration_job_id}, row {row.row_number}: "
            f"{row.status} — {sample_code} — {project_code}"
        )
        links.append(
            make_link(
                f"Job #{row.migration_job_id}, row {row.row_number}",
                f"/data-migration/jobs/{row.migration_job_id}",
                "migration_row",
                {
                    "job_id": row.migration_job_id,
                    "row_number": row.row_number,
                    "status": row.status,
                    "sample_code": sample_code,
                    "project_code": project_code,
                },
            )
        )

    return {
        "answer": "\n".join(lines),
        "links": links,
    }



def answer_current_user(message, user):
    lower = str(message or "").strip().lower()

    identity_phrases = [
        "what is my name",
        "what's my name",
        "whats my name",
        "who am i",
        "who am i logged in as",
        "who i am logged in as",
        "which user am i logged in as",
        "what user am i",
        "my username",
    ]

    if not contains_any_intent_phrase(message, identity_phrases):
        return None

    username = getattr(user, "username", "") or "Unknown"
    roles = getattr(user, "roles", None)

    role_text = ""
    if roles:
        try:
            role_text = f" Your role(s): {', '.join(roles)}."
        except Exception:
            role_text = ""

    return {
        "answer": f"You are logged in as {username}.{role_text}",
        "links": [],
        "suggestions": without_empty(
            sample_prompt(user),
            "Show failed migration jobs",
            project_prompt(user),
        ),
        "skip_llm": True,
    }


def _route_from_hint(message, user, context, route_hint):
    route = str((route_hint or {}).get("route") or "").strip().lower()
    contextual_routers = {
        "barcode": route_barcode_operations,
        "comparison": route_comparison_analytics,
        "investigation": route_investigation_workbench,
        "inventory": route_inventory_operations,
        "notifications": route_notification_operations,
        "qc": route_qc_operations,
        "reporting": route_reporting_operations,
        "samples": route_sample_management,
        "sequences": route_assistant_sequence,
        "sop": route_sop_assistant,
        "work_items": route_workitem_operations,
    }
    if route == "identity":
        return answer_current_user(message, user) or answer_current_user("Who am I?", user)
    if route == "general":
        return general_question_result()
    if route == "monitoring":
        return route_system_monitoring(message, user, context=context) or route_system_monitoring(
            "Show system status",
            user,
            context=context,
        )
    if route == "attention":
        return route_attention_summary(message, user) or build_attention_summary(user)
    if route == "clarification":
        return route_assistant_clarification(message, context=context)
    if route == "confirmed_action":
        return route_confirmed_action_proposal(message, user)
    if route == "chart":
        return route_assistant_chart(message, user)
    if route == "calculation":
        return route_worklist_or_calculation(message, user)
    router = contextual_routers.get(route)
    if router:
        return router(message, user, context=context)
    return None


def _hint_clarification(route_hint, user):
    route = str((route_hint or {}).get("route") or "unknown").strip().lower()
    suggestions = {
        "barcode": without_empty(batch_prompt(user)),
        "calculation": ["Count samples by status", "How many samples need QC?"],
        "chart": ["Graph sample status counts", "Graph QC failure rates by sample"],
        "comparison": without_empty(
            comparison_prompt(user, "project"),
            comparison_prompt(user, "sample", chart_type="bar"),
        ),
        "confirmed_action": ["Find sample sequences", "Show prepared imports"],
        "investigation": without_empty(
            sample_prompt(user, "Investigate sample"),
            "Open the Investigation Workbench",
        ),
        "inventory": ["Show inventory below its reorder level", "Which reagents expire in the next 30 days?"],
        "migration": ["Show failed migration jobs", "Show failed migration rows"],
        "notifications": ["List notification subscriptions"],
        "qc": ["Show samples needing QC review", "Show samples that failed QC"],
        "record_search": without_empty(sample_prompt(user), project_prompt(user)),
        "reporting": without_empty(
            project_prompt(user, "Generate an audit report for project")
        ),
        "samples": without_empty("Show samples received today", sample_prompt(user)),
        "sequences": ["Find sample sequences", "Summarize BLAST results"],
        "sop": ["Which SOP covers QC review?"],
        "work_items": ["Show overdue work", "Show unassigned work today"],
    }.get(route, [])
    if not suggestions:
        return None
    label = route.replace("_", " ")
    return {
        "answer": (
            f"I interpreted this as a {label} request, but I need a more specific "
            "target or operation before OpenLIMS runs anything."
        ),
        "links": [],
        "suggestions": suggestions,
        "skip_llm": True,
    }


def route_assistant_message(message, user, context=None, route_hint=None):
    context = context or {}
    query = clean_query(message)
    lower = query.lower()

    if route_hint:
        hinted_result = _route_from_hint(query, user, context, route_hint)
        if hinted_result:
            return hinted_result
        hinted_clarification = _hint_clarification(route_hint, user)
        if hinted_clarification:
            return hinted_clarification

    current_user_result = answer_current_user(query, user)
    if current_user_result:
        return current_user_result

    conversation_result = route_conversation_utility(query, user=user)
    if conversation_result:
        return conversation_result

    monitoring_result = route_system_monitoring(query, user, context=context)
    if monitoring_result:
        return monitoring_result

    clarification_result = route_assistant_clarification(query, context=context)
    if clarification_result:
        return clarification_result

    sop_result = route_sop_assistant(query, user, context=context)
    if sop_result:
        return sop_result

    qc_result = route_qc_operations(query, user, context=context)
    if qc_result:
        return qc_result

    investigation_result = route_investigation_workbench(
        query,
        user,
        context=context,
    )
    if investigation_result:
        return investigation_result

    comparison_result = route_comparison_analytics(
        query,
        user,
        context=context,
    )
    if comparison_result:
        return comparison_result

    sample_management_result = route_sample_management(
        query,
        user,
        context=context,
    )
    if sample_management_result:
        return sample_management_result

    inventory_result = route_inventory_operations(query, user, context=context)
    if inventory_result:
        return inventory_result

    workitem_result = route_workitem_operations(query, user, context=context)
    if workitem_result:
        return workitem_result

    barcode_result = route_barcode_operations(query, user, context=context)
    if barcode_result:
        return barcode_result

    notification_result = route_notification_operations(query, user, context=context)
    if notification_result:
        return notification_result

    reporting_result = route_reporting_operations(query, user, context=context)
    if reporting_result:
        return reporting_result

    confirmed_action_result = route_confirmed_action_proposal(query, user)
    if confirmed_action_result:
        return confirmed_action_result

    attention_result = route_attention_summary(query, user)
    if attention_result:
        return attention_result

    sequence_result = route_assistant_sequence(
        query,
        user,
        context=context,
    )
    if sequence_result:
        return sequence_result

    chart_result = route_assistant_chart(query, user)
    if chart_result:
        return chart_result

    worklist_or_calculation_result = route_worklist_or_calculation(query, user)
    if worklist_or_calculation_result:
        return worklist_or_calculation_result

    if not query:
        return {
            "answer": "Ask me about samples, projects, migration jobs, skipped rows, failed imports, or where a sample is located.",
            "links": [],
            "suggestions": without_empty(
                project_prompt(user),
                sample_prompt(user),
                "Show failed migration jobs",
                "Show skipped migration rows",
            ),
        }

    if "migration" in lower or "import" in lower or "skipped" in lower or "failed" in lower or "error" in lower:
        if "row" in lower or "skipped" in lower or "failed" in lower or "error" in lower:
            row_result = search_migration_rows(query)
            if row_result:
                row_result["suggestions"] = [
                    "Show failed migration jobs",
                    "Show skipped migration rows",
                ]
                return row_result

        job_result = search_migration_jobs(query)
        if job_result:
            job_result["suggestions"] = [
                "Show skipped rows for this import",
                "Show failed migration jobs",
                "Find samples created by this import",
            ]
            return job_result

    if "project" in lower or "prj-" in lower:
        project_result = search_projects(query, user)
        if project_result:
            project_result["suggestions"] = [
                "Show samples in this project",
                "Show migration rows for this project",
                "Show failed imports",
            ]
            return project_result

    sample_result = search_samples(query, user)
    if sample_result:
        sample_result["suggestions"] = [
            "Summarize this sample",
            "Show related migration rows",
            "Search another sample ID",
        ]
        return sample_result

    project_result = search_projects(query, user)
    if project_result:
        project_result["suggestions"] = [
            "Summarize this project",
            "Show samples in this project",
            "Show migration jobs",
        ]
        return project_result

    return {
        "answer": (
            "I couldn't determine which OpenLIMS operation or record you meant. "
            "No attention check, record search, or workflow action was run. "
            "Try a more specific request or choose one of the suggestions below."
        ),
        "links": [],
        "suggestions": without_empty(
            sample_prompt(user),
            project_prompt(user),
            "Show failed migration jobs",
            "Show skipped migration rows",
        ),
        "skip_llm": True,
        "route_unmatched": True,
    }
