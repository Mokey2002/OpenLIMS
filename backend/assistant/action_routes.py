import re

from imports.models import ImportJob
from migration_toolkit.models import MigrationJob
from sequences.models import Sequence

from samples.access import get_sample_access_queryset
from samples.models import Sample


def _extract_id(message, noun):
    match = re.search(rf"\b{noun}\s*(?:job)?\s*#?\s*(\d+)\b", message, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _accessible_sequence_ids(user):
    sample_ids = get_sample_access_queryset(
        Sample.objects.all(),
        user,
    ).values_list("id", flat=True)

    return Sequence.objects.filter(sample_id__in=sample_ids).values_list("id", flat=True)


def propose_alignment(message, user):
    lower = message.lower()

    if "alignment" not in lower and "align " not in lower:
        return None

    if not any(word in lower for word in ["run", "queue", "start", "align"]):
        return None

    match = re.search(r"sequences?\s+([0-9,\s]+)", message, re.IGNORECASE)
    sequence_ids = [
        int(value)
        for value in re.findall(r"\d+", match.group(1) if match else "")
    ]
    sequence_ids = list(dict.fromkeys(sequence_ids))

    if len(sequence_ids) < 2:
        return {
            "answer": "Choose at least two sequence record IDs. Example: Run alignment for sequences 12, 13.",
            "links": [],
            "skip_llm": True,
        }

    allowed_ids = set(_accessible_sequence_ids(user).filter(id__in=sequence_ids))
    missing_ids = [value for value in sequence_ids if value not in allowed_ids]

    if missing_ids:
        return {
            "answer": f"I cannot access sequence ID(s): {missing_ids}. No alignment was proposed.",
            "links": [],
            "skip_llm": True,
        }

    summary = f"Run Clustal Omega alignment for sequence IDs {', '.join(map(str, sequence_ids))}"

    return {
        "answer": f"{summary}. Review the details below and confirm to queue it.",
        "links": [{"label": "Open alignments", "url": "/alignments"}],
        "skip_llm": True,
        "pending_action": {
            "type": "RUN_ALIGNMENT",
            "summary": summary,
            "payload": {
                "name": f"Assistant alignment ({', '.join(map(str, sequence_ids))})",
                "sequence_ids": sequence_ids,
                "tool": "CLUSTAL_OMEGA",
            },
        },
    }


def propose_migration_mappings(message, user):
    lower = message.lower()

    if "migration" not in lower or "mapping" not in lower:
        return None

    if not any(word in lower for word in ["create", "suggest", "generate"]):
        return None

    job_id = _extract_id(message, "migration")

    if not job_id:
        return {
            "answer": "Tell me which migration job to use. Example: Create migration mappings for migration job #12.",
            "links": [],
            "skip_llm": True,
        }

    job = MigrationJob.objects.select_related("profile").filter(id=job_id).first()

    if not job or not job.uploaded_file:
        return {
            "answer": f"Migration job #{job_id} was not found or has no uploaded file.",
            "links": [],
            "skip_llm": True,
        }

    summary = f"Create suggested field mappings for migration job #{job.id} ({job.profile.name})"

    return {
        "answer": f"{summary}. Review and confirm before any mappings are created.",
        "links": [{"label": f"Open migration job #{job.id}", "url": f"/data-migration/jobs/{job.id}"}],
        "skip_llm": True,
        "pending_action": {
            "type": "CREATE_MIGRATION_MAPPINGS",
            "summary": summary,
            "payload": {"migration_job_id": job.id},
        },
    }


def propose_import(message, user):
    lower = message.lower()

    if "import" not in lower or not any(word in lower for word in ["queue", "run", "start"]):
        return None

    job_id = _extract_id(message, "import")

    if not job_id:
        return {
            "answer": "Tell me which prepared import job to queue. Example: Queue import job #12.",
            "links": [],
            "skip_llm": True,
        }

    job = ImportJob.objects.select_related("instrument", "project").filter(id=job_id).first()

    if not job:
        return {
            "answer": f"Import job #{job_id} was not found.",
            "links": [],
            "skip_llm": True,
        }

    summary = f"Queue import job #{job.id} for {job.instrument.name}"

    return {
        "answer": f"{summary}. Review and confirm before it is queued.",
        "links": [{"label": "Open imports", "url": "/imports"}],
        "skip_llm": True,
        "pending_action": {
            "type": "QUEUE_IMPORT",
            "summary": summary,
            "payload": {"import_job_id": job.id},
        },
    }


def propose_report(message, user):
    lower = message.lower()

    if "report" not in lower or not any(word in lower for word in ["queue", "generate", "create", "run"]):
        return None

    project_id = _extract_id(message, "project")
    report_type = "OPERATIONS_SUMMARY"

    if "audit" in lower:
        report_type = "AUDIT_SUMMARY"
    elif "qc" in lower:
        report_type = "QC_SUMMARY"
    elif "blast" in lower:
        report_type = "BLAST_SUMMARY"

    filters = {}
    if project_id:
        filters["project_id"] = project_id

    summary = f"Queue {report_type.replace('_', ' ').title()}"
    if project_id:
        summary += f" for project #{project_id}"

    return {
        "answer": f"{summary}. Review and confirm before report generation is queued.",
        "links": [{"label": "Open reports", "url": "/reports"}],
        "skip_llm": True,
        "pending_action": {
            "type": "QUEUE_REPORT",
            "summary": summary,
            "payload": {
                "report_type": report_type,
                "filters": filters,
            },
        },
    }


def route_confirmed_action_proposal(message, user):
    text = str(message or "").strip()

    for router in [
        propose_alignment,
        propose_migration_mappings,
        propose_import,
        propose_report,
    ]:
        result = router(text, user)
        if result:
            return result

    return None
