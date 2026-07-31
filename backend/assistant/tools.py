import re
from collections import Counter

from django.db.models import Q

from migration_toolkit.models import MigrationJob, MigrationRowRecord
from projects.models import Project
from samples.access import get_sample_access_queryset
from samples.models import Sample


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
        "suggestions": [
            "Summarize project PRJ-UW-PILOT",
            "Show failed migration jobs",
            "Show skipped migration rows",
        ],
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
        "what user am i",
        "my username",
    ]

    if not any(phrase in lower for phrase in identity_phrases):
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
        "suggestions": [
            "Find sample S-UW-101",
            "Show failed migration jobs",
            "Summarize project PRJ-UW-PILOT",
        ],
        "skip_llm": True,
    }


def route_assistant_message(message, user):
    query = clean_query(message)
    lower = query.lower()

    current_user_result = answer_current_user(query, user)
    if current_user_result:
        return current_user_result

    if not query:
        return {
            "answer": "Ask me about samples, projects, migration jobs, skipped rows, failed imports, or where a sample is located.",
            "links": [],
            "suggestions": [
                "Summarize project PRJ-UW-PILOT",
                "Find sample S-UW-101",
                "Show failed migration jobs",
                "Show skipped migration rows",
            ],
        }

    if "migration" in lower or "import" in lower or "skipped" in lower or "failed" in lower or "error" in lower:
        if "row" in lower or "skipped" in lower or "failed" in lower or "error" in lower:
            row_result = search_migration_rows(query)
            if row_result:
                row_result["suggestions"] = [
                    "Show failed migration jobs",
                    "Show skipped migration rows",
                    "Summarize migration job #1",
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
            "I couldn't find a matching sample, project, migration job, or migration row. "
            "Try using a sample ID, project code, migration job number, or a phrase like "
            "'show failed migration rows'."
        ),
        "links": [],
        "suggestions": [
            "Find sample S-UW-101",
            "Summarize project PRJ-UW-PILOT",
            "Show failed migration jobs",
            "Show skipped migration rows",
        ],
    }
