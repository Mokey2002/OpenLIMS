import json
import os
import re
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.permissions import is_admin, is_tech
from custom_fields.models import FieldDefinition, FieldValue
from custom_fields.serializers import FieldValueSerializer
from events.models import Event
from projects.models import Project
from samples.access import (
    get_sample_access_queryset,
    require_sample_modify_access,
    validate_sample_project_assignment,
)
from samples.models import Sample, SampleBatch
from samples.workflows import can_transition


STATUS_ALIASES = {
    "RECEIVED": Sample.STATUS_RECEIVED,
    "PROCESSING": Sample.STATUS_IN_PROGRESS,
    "IN PROCESS": Sample.STATUS_IN_PROGRESS,
    "IN PROGRESS": Sample.STATUS_IN_PROGRESS,
    "IN_PROGRESS": Sample.STATUS_IN_PROGRESS,
    "QC": Sample.STATUS_QC,
    "REPORTED": Sample.STATUS_REPORTED,
    "CANCELLED": Sample.STATUS_CANCELLED,
    "CANCELED": Sample.STATUS_CANCELLED,
    "ARCHIVED": Sample.STATUS_ARCHIVED,
}

SAMPLE_CODE_RE = re.compile(
    r"\b[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+\b"
)


def assistant_bulk_max_records():
    configured = int(
        getattr(
            settings,
            "OPENLIMS_ASSISTANT_BULK_MAX_RECORDS",
            os.getenv("OPENLIMS_ASSISTANT_BULK_MAX_RECORDS", "100"),
        )
    )
    return max(1, configured)


def _write_user(user):
    return is_admin(user) or is_tech(user)


def _project_label(project):
    return {
        "id": project.id,
        "code": project.code,
        "name": project.name,
        "label": f"{project.code} — {project.name}",
    }


def _sample_link(sample):
    return {
        "label": f"Open {sample.sample_id}",
        "url": f"/samples/{sample.id}",
        "kind": "sample",
        "extra": {"id": sample.id, "sample_id": sample.sample_id},
    }


def _sample_queryset(user):
    queryset = Sample.objects.select_related(
        "project",
        "container",
        "container__location",
        "batch",
        "assigned_to",
        "created_by",
    ).prefetch_related("linked_projects")
    return get_sample_access_queryset(queryset, user)


def _strip_reference(value):
    cleaned = str(value or "").strip(" .?!,;:\t\n")
    return re.sub(r"^project\s+", "", cleaned, flags=re.IGNORECASE)


def _resolve_project(reference, user, *, write=False):
    cleaned = _strip_reference(reference)
    if not cleaned:
        return None, "Tell me which project to use."

    exact = list(
        Project.objects.filter(
            Q(code__iexact=cleaned) | Q(name__iexact=cleaned)
        ).distinct()[:2]
    )
    matches = exact

    if not matches:
        matches = list(
            Project.objects.filter(
                Q(code__icontains=cleaned) | Q(name__icontains=cleaned)
            ).distinct()[:3]
        )

    if not matches:
        return None, f"Project {cleaned} was not found."

    if len(matches) > 1:
        labels = ", ".join(project.code for project in matches)
        return None, f"Project {cleaned} is ambiguous. Matches: {labels}."

    project = matches[0]
    allowed = is_admin(user) or project.members.filter(id=user.id).exists()

    if not allowed:
        return None, f"You do not have access to project {project.code}."

    if write and not _write_user(user):
        return None, "Only tech or admin users can change samples."

    return project, None


def _resolve_sample(sample_code, user):
    code = str(sample_code or "").strip(" .?!,;:")
    sample = _sample_queryset(user).filter(sample_id__iexact=code).first()
    if sample:
        return sample, None
    return None, f"Sample {code} was not found or is not accessible."


def _normalize_status(value):
    normalized = re.sub(r"\s+", " ", str(value or "").strip()).upper()
    normalized = normalized.rstrip(" .?!,;:")
    return STATUS_ALIASES.get(normalized)


def _json_scalar(value):
    text = str(value or "").strip().strip("\"'")
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return text


def _parse_custom_fields(message):
    match = re.search(r"\swith\s+(.+)$", message, re.IGNORECASE)
    if not match:
        return {}

    values = {}
    for field_match in re.finditer(
        r"([A-Za-z][A-Za-z0-9_]*)\s*=\s*"
        r"(.*?)(?=\s*,\s*[A-Za-z][A-Za-z0-9_]*\s*=|$)",
        match.group(1).strip().rstrip(".?!"),
    ):
        values[field_match.group(1)] = _json_scalar(field_match.group(2))
    return values


def _field_error_text(detail):
    if isinstance(detail, dict):
        return "; ".join(
            f"{key}: {_field_error_text(value)}"
            for key, value in detail.items()
        )
    if isinstance(detail, (list, tuple)):
        return "; ".join(_field_error_text(value) for value in detail)
    return str(detail)


def _validate_custom_field_payload(values, *, require_all=True):
    definitions = list(
        FieldDefinition.objects.filter(entity_type="Sample").order_by("name")
    )
    definitions_by_name = {definition.name: definition for definition in definitions}
    errors = []
    normalized = {}

    unknown = sorted(set(values) - set(definitions_by_name))
    if unknown:
        errors.append(f"Unknown custom field(s): {', '.join(unknown)}")

    if require_all:
        for definition in definitions:
            if definition.required and definition.name not in values:
                errors.append(
                    f"Required custom field is missing: "
                    f"{definition.label or definition.name}"
                )

    for name, value in values.items():
        definition = definitions_by_name.get(name)
        if not definition:
            continue
        serializer = FieldValueSerializer(
            data={
                "field_definition": definition.id,
                "entity_type": "Sample",
                "entity_id": "preview",
                "value": value,
            }
        )
        if not serializer.is_valid():
            errors.append(
                f"{definition.label or definition.name}: "
                f"{_field_error_text(serializer.errors)}"
            )
            continue
        normalized[name] = serializer.validated_data["value"]

    return normalized, errors


def _required_metadata_errors(sample):
    definitions = list(
        FieldDefinition.objects.filter(
            entity_type="Sample",
            required=True,
        ).order_by("name")
    )
    if not definitions:
        return []

    values = {
        value.field_definition_id: value
        for value in FieldValue.objects.filter(
            entity_type="Sample",
            entity_id=str(sample.id),
            field_definition_id__in=[definition.id for definition in definitions],
        )
    }
    errors = []

    for definition in definitions:
        if definition.id not in values:
            errors.append(f"missing {definition.label or definition.name}")
            continue

        field_value = values[definition.id]
        serializer = FieldValueSerializer(
            instance=field_value,
            data={"value": field_value.value},
            partial=True,
        )
        if not serializer.is_valid():
            errors.append(
                f"invalid {definition.label or definition.name}: "
                f"{_field_error_text(serializer.errors)}"
            )

    return errors


def _sample_snapshot(sample):
    return {
        "status": sample.status,
        "project_id": sample.project_id,
        "batch_id": sample.batch_id,
        "assigned_to_id": sample.assigned_to_id,
    }


def _sample_preview_row(sample, proposed):
    current = {
        "status": sample.status,
        "batch": sample.batch.code if sample.batch else None,
        "assigned_to": (
            sample.assigned_to.username if sample.assigned_to else None
        ),
    }
    return {
        "id": sample.id,
        "sample_id": sample.sample_id,
        "current": current,
        "proposed": proposed,
    }


def _preview(
    *,
    operation,
    user,
    project,
    samples,
    excluded=None,
    warnings=None,
    validation_errors=None,
    current_values=None,
    proposed_values=None,
):
    excluded = excluded or []
    projects = project
    if isinstance(project, Project):
        projects = _project_label(project)

    return {
        "title": "Proposed bulk operation" if len(samples) != 1 else "Proposed operation",
        "operation": operation,
        "project": projects,
        "requested_user": {
            "id": user.id,
            "username": user.username,
        },
        "records_affected": len(samples),
        "matching_samples": len(samples) + len(excluded),
        "excluded_count": len(excluded),
        "current_values": current_values or {},
        "proposed_values": proposed_values or {},
        "samples": samples,
        "excluded": excluded,
        "warnings": warnings or [],
        "validation_errors": validation_errors or [],
        "maximum_records": assistant_bulk_max_records(),
    }


def _proposal_result(summary, preview, payload, *, context=None, links=None):
    lines = [
        preview["title"],
        "",
        f"Operation: {preview['operation']}",
        f"Matching samples: {preview['matching_samples']}",
        f"Samples affected: {preview['records_affected']}",
        f"Excluded samples: {preview['excluded_count']}",
        "",
        "Review the exact preview below and confirm before OpenLIMS changes anything.",
    ]
    return {
        "answer": "\n".join(lines),
        "links": links or [],
        "context": context or {},
        "skip_llm": True,
        "pending_action": {
            "type": payload.pop("action_type"),
            "summary": summary,
            "payload": {**payload, "preview": preview},
        },
    }


def _error_result(message, *, context=None, preview=None):
    result = {
        "answer": message,
        "links": [],
        "context": context or {},
        "skip_llm": True,
    }
    if preview:
        result["preview"] = preview
    return result


def _sample_codes_from_range(message):
    match = re.search(
        r"\b([A-Za-z][A-Za-z0-9]*[-_])(\d+)\s+"
        r"(?:through|to)\s+"
        r"(?:(?:[A-Za-z][A-Za-z0-9]*[-_])?)(\d+)\b",
        message,
        re.IGNORECASE,
    )
    if not match:
        return []

    prefix, start_text, end_text = match.groups()
    start = int(start_text)
    end = int(end_text)
    if end < start:
        return []
    width = max(len(start_text), len(end_text))
    return [f"{prefix}{value:0{width}d}" for value in range(start, end + 1)]


def _explicit_sample_codes(message, *, excluded_codes=None):
    codes = _sample_codes_from_range(message)
    if not codes:
        codes = SAMPLE_CODE_RE.findall(message)
    excluded = {str(value).upper() for value in (excluded_codes or [])}
    return list(
        dict.fromkeys(code for code in codes if code.upper() not in excluded)
    )


def _project_for_preview(samples):
    projects = {
        sample.project_id: sample.project
        for sample in samples
        if sample.project_id
    }
    if len(projects) == 1:
        return _project_label(next(iter(projects.values())))
    if not projects:
        return {"id": None, "code": None, "name": "Unassigned", "label": "Unassigned"}
    return {
        "id": None,
        "code": None,
        "name": "Multiple projects",
        "label": "Multiple projects",
    }


def _find_sample_read(message, user):
    match = re.search(
        r"\b(?:find|show|open)\s+sample\s+"
        r"([A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+)\b",
        message,
        re.IGNORECASE,
    )
    if not match:
        return None

    sample, error = _resolve_sample(match.group(1), user)
    if error:
        return _error_result(error)

    project = sample.project.code if sample.project else "Unassigned"
    batch = sample.batch.code if sample.batch else "No batch"
    answer = (
        f"Found sample {sample.sample_id}.\n\n"
        f"Status: {sample.status}\n"
        f"Project: {project}\n"
        f"Batch: {batch}"
    )
    return {
        "answer": answer,
        "links": [_sample_link(sample)],
        "context": {
            "sample_ids": [sample.id],
            "sample_codes": [sample.sample_id],
            "project_id": sample.project_id,
            "batch_code": sample.batch.code if sample.batch else None,
        },
        "suggestions": [
            f"Summarize sample {sample.sample_id}",
            f"Archive sample {sample.sample_id}",
        ],
        "skip_llm": True,
    }


def _summarize_sample_read(message, user):
    match = re.search(
        r"\bsummarize\s+sample\s+"
        r"([A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+)\b",
        message,
        re.IGNORECASE,
    )
    if not match:
        return None

    sample, error = _resolve_sample(match.group(1), user)
    if error:
        return _error_result(error)

    values = list(
        FieldValue.objects.select_related("field_definition")
        .filter(entity_type="Sample", entity_id=str(sample.id))
        .order_by("field_definition__name")
    )
    work_items = sample.work_items.all()
    project = (
        f"{sample.project.code} — {sample.project.name}"
        if sample.project
        else "Unassigned"
    )
    container = sample.container.container_id if sample.container else "Unassigned"
    location = (
        sample.container.location.name
        if sample.container and sample.container.location
        else "Unassigned"
    )
    missing = _required_metadata_errors(sample)
    lines = [
        f"Sample {sample.sample_id}",
        "",
        f"Status: {sample.status}",
        f"Project: {project}",
        f"Batch: {sample.batch.code if sample.batch else 'Unassigned'}",
        (
            f"Assigned to: {sample.assigned_to.username}"
            if sample.assigned_to
            else "Assigned to: Unassigned"
        ),
        f"Container: {container}",
        f"Location: {location}",
        f"Created: {sample.created_at.isoformat()}",
        f"Status last changed: {sample.status_changed_at.isoformat()}",
        f"Attachments: {sample.attachments.count()}",
        f"Work items: {work_items.count()}",
    ]
    if values:
        lines.extend(["", "Custom fields:"])
        for field_value in values:
            definition = field_value.field_definition
            lines.append(
                f"- {definition.label or definition.name}: {field_value.value}"
            )
    if missing:
        lines.extend(["", "Required metadata issues:"])
        lines.extend(f"- {error}" for error in missing)

    return {
        "answer": "\n".join(lines),
        "links": [_sample_link(sample)],
        "context": {
            "sample_ids": [sample.id],
            "sample_codes": [sample.sample_id],
            "project_id": sample.project_id,
            "batch_code": sample.batch.code if sample.batch else None,
        },
        "suggestions": [
            f"Change sample {sample.sample_id} to PROCESSING",
            f"Archive sample {sample.sample_id}",
        ],
        "skip_llm": True,
    }


def _received_today_read(message, user):
    if not re.search(
        r"\b(?:show|which|list)\s+samples?\s+received\s+today\b",
        message,
        re.IGNORECASE,
    ):
        return None

    today = timezone.localdate()
    start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    end = start + timedelta(days=1)
    samples = list(
        _sample_queryset(user)
        .filter(
            status=Sample.STATUS_RECEIVED,
            created_at__gte=start,
            created_at__lt=end,
        )
        .order_by("sample_id")
    )
    lines = [f"Samples received today ({today.isoformat()}): {len(samples)}"]
    lines.extend(
        f"- {sample.sample_id} — {sample.project.code if sample.project else 'Unassigned'}"
        for sample in samples
    )
    return {
        "answer": "\n".join(lines),
        "links": [_sample_link(sample) for sample in samples],
        "context": {
            "sample_ids": [sample.id for sample in samples],
            "sample_codes": [sample.sample_id for sample in samples],
        },
        "skip_llm": True,
    }


def _awaiting_processing_read(message, user):
    match = re.search(
        r"\bsamples?\s+in\s+project\s+(.+?)\s+"
        r"(?:are\s+)?awaiting\s+processing\b",
        message,
        re.IGNORECASE,
    )
    if not match:
        return None

    project, error = _resolve_project(match.group(1), user)
    if error:
        return _error_result(error)

    samples = list(
        _sample_queryset(user)
        .filter(project=project, status=Sample.STATUS_RECEIVED)
        .order_by("sample_id")
    )
    lines = [
        f"Samples awaiting processing in {project.code} — {project.name}: "
        f"{len(samples)}"
    ]
    lines.extend(f"- {sample.sample_id}" for sample in samples)
    return {
        "answer": "\n".join(lines),
        "links": [_sample_link(sample) for sample in samples],
        "context": {
            "sample_ids": [sample.id for sample in samples],
            "sample_codes": [sample.sample_id for sample in samples],
            "project_id": project.id,
        },
        "suggestions": [
            f"Move all received samples in Project {project.name} to PROCESSING"
        ],
        "skip_llm": True,
    }


def _generated_sample_codes(project, count):
    prefix = re.sub(r"[^A-Za-z0-9]+", "-", project.code).strip("-").upper()
    pattern = re.compile(rf"^{re.escape(prefix)}-S-(\d+)$", re.IGNORECASE)
    existing = set(
        Sample.objects.filter(sample_id__istartswith=f"{prefix}-S-")
        .values_list("sample_id", flat=True)
    )
    highest = 0
    for code in existing:
        match = pattern.match(code)
        if match:
            highest = max(highest, int(match.group(1)))
    return [f"{prefix}-S-{value:04d}" for value in range(highest + 1, highest + count + 1)]


def _propose_create_samples(message, user):
    match = re.search(
        r"\bcreate\s+(\d+)\s+samples?\s+(?:for|in)\s+"
        r"(?:project\s+)?(.+?)(?=\s+with\s+|[.?!]?$)",
        message,
        re.IGNORECASE,
    )
    if not match:
        return None

    count = int(match.group(1))
    maximum = assistant_bulk_max_records()
    if count < 1:
        return _error_result("Create at least one sample.")
    if count > maximum:
        return _error_result(
            f"The request contains {count} samples, which exceeds the configured "
            f"assistant maximum of {maximum}."
        )

    project, error = _resolve_project(match.group(2), user, write=True)
    if error:
        return _error_result(error)

    custom_fields, field_errors = _validate_custom_field_payload(
        _parse_custom_fields(message),
        require_all=True,
    )
    codes = _generated_sample_codes(project, count)
    rows = [
        {
            "id": None,
            "sample_id": code,
            "current": {"record": "Does not exist"},
            "proposed": {
                "status": Sample.STATUS_RECEIVED,
                "project": project.code,
                "custom_fields": custom_fields,
            },
        }
        for code in codes
    ]
    preview = _preview(
        operation="Create samples",
        user=user,
        project=project,
        samples=rows,
        validation_errors=field_errors,
        current_values={"record": "Does not exist"},
        proposed_values={
            "status": Sample.STATUS_RECEIVED,
            "project": project.code,
            "custom_fields": custom_fields,
        },
    )
    if field_errors:
        return _error_result(
            "The samples cannot be proposed until the required custom-field "
            "errors are corrected.",
            preview=preview,
        )

    summary = f"Create {count} samples for {project.code}"
    return _proposal_result(
        summary,
        preview,
        {
            "action_type": "CREATE_SAMPLES",
            "project_id": project.id,
            "sample_codes": codes,
            "custom_fields": custom_fields,
            "reason": str(message).strip(),
        },
        context={"project_id": project.id},
        links=[
            {
                "label": f"Open project {project.code}",
                "url": f"/projects/{project.id}",
            }
        ],
    )


def _preview_status_samples(samples, user, target_status):
    included = []
    excluded = []
    snapshots = {}

    for sample in samples:
        try:
            require_sample_modify_access(user, sample)
        except PermissionDenied as exc:
            excluded.append({"sample_id": sample.sample_id, "reason": str(exc)})
            continue

        if sample.status == target_status:
            excluded.append(
                {
                    "sample_id": sample.sample_id,
                    "reason": f"already in status {target_status}",
                }
            )
            continue
        if not can_transition(sample.status, target_status):
            excluded.append(
                {
                    "sample_id": sample.sample_id,
                    "reason": (
                        f"transition from {sample.status} to {target_status} "
                        "is not permitted"
                    ),
                }
            )
            continue
        if target_status != Sample.STATUS_ARCHIVED:
            metadata_errors = _required_metadata_errors(sample)
            if metadata_errors:
                excluded.append(
                    {
                        "sample_id": sample.sample_id,
                        "reason": "; ".join(metadata_errors),
                    }
                )
                continue

        included.append(
            _sample_preview_row(sample, {"status": target_status})
        )
        snapshots[str(sample.id)] = _sample_snapshot(sample)

    return included, excluded, snapshots


def _status_proposal(samples, user, target_status, message, *, project=None):
    maximum = assistant_bulk_max_records()
    if len(samples) > maximum:
        return _error_result(
            f"The request matches {len(samples)} samples, which exceeds the "
            f"configured assistant maximum of {maximum}. Narrow the request first."
        )

    included, excluded, snapshots = _preview_status_samples(
        samples,
        user,
        target_status,
    )
    operation = (
        "Archive samples"
        if target_status == Sample.STATUS_ARCHIVED
        else "Change status"
    )
    preview = _preview(
        operation=operation,
        user=user,
        project=project or _project_for_preview(samples),
        samples=included,
        excluded=excluded,
        current_values={
            "status": sorted({sample.status for sample in samples})
        },
        proposed_values={"status": target_status},
    )
    if not included:
        return _error_result(
            "No samples passed permission, required-metadata, and workflow "
            "validation. No action was proposed.",
            preview=preview,
        )

    sample_ids = [row["id"] for row in included]
    sample_codes = [row["sample_id"] for row in included]
    summary = f"{operation} for {len(sample_ids)} sample(s)"
    return _proposal_result(
        summary,
        preview,
        {
            "action_type": "BULK_SAMPLE_UPDATE",
            "operation": (
                "ARCHIVE" if target_status == Sample.STATUS_ARCHIVED else "CHANGE_STATUS"
            ),
            "sample_ids": sample_ids,
            "sample_codes": sample_codes,
            "snapshots": snapshots,
            "target_status": target_status,
            "reason": str(message).strip(),
        },
        context={
            "sample_ids": sample_ids,
            "sample_codes": sample_codes,
            "project_id": project.id if isinstance(project, Project) else None,
        },
        links=[_sample_link(sample) for sample in samples if sample.id in sample_ids],
    )


def _propose_single_status(message, user):
    match = re.search(
        r"\b(?:change|move|set)\s+sample\s+"
        r"([A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+)\s+"
        r"(?:status\s+)?to\s+([A-Za-z_ ]+?)(?=\s+because\b|[.?!]?$)",
        message,
        re.IGNORECASE,
    )
    if not match:
        return None

    target = _normalize_status(match.group(2))
    if not target:
        return _error_result(f"Unsupported sample status: {match.group(2).strip()}.")
    sample, error = _resolve_sample(match.group(1), user)
    if error:
        return _error_result(error)
    return _status_proposal([sample], user, target, message, project=sample.project)


def _propose_bulk_project_status(message, user):
    match = re.search(
        r"\bmove\s+all\s+([A-Za-z_ ]+?)\s+samples?\s+in\s+"
        r"project\s+(.+?)\s+to\s+([A-Za-z_ ]+?)(?=[.?!]?$)",
        message,
        re.IGNORECASE,
    )
    if not match:
        return None

    source_status = _normalize_status(match.group(1))
    target_status = _normalize_status(match.group(3))
    if not source_status or not target_status:
        return _error_result("Use a supported source and target sample status.")

    project, error = _resolve_project(match.group(2), user, write=True)
    if error:
        return _error_result(error)
    samples = list(
        _sample_queryset(user)
        .filter(project=project, status=source_status)
        .order_by("id")
    )
    return _status_proposal(
        samples,
        user,
        target_status,
        message,
        project=project,
    )


def _propose_archive(message, user):
    single = re.search(
        r"\barchive\s+sample\s+"
        r"([A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+)\b",
        message,
        re.IGNORECASE,
    )
    if single:
        sample, error = _resolve_sample(single.group(1), user)
        if error:
            return _error_result(error)
        return _status_proposal(
            [sample],
            user,
            Sample.STATUS_ARCHIVED,
            message,
            project=sample.project,
        )

    bulk = re.search(
        r"\barchive\s+cancelled\s+samples?\s+older\s+than\s+(\d+)\s+days\b",
        message,
        re.IGNORECASE,
    )
    if not bulk:
        return None

    days = int(bulk.group(1))
    cutoff = timezone.now() - timedelta(days=days)
    samples = list(
        _sample_queryset(user)
        .filter(
            status=Sample.STATUS_CANCELLED,
            status_changed_at__lte=cutoff,
        )
        .order_by("id")
    )
    return _status_proposal(
        samples,
        user,
        Sample.STATUS_ARCHIVED,
        message,
    )


def _samples_from_codes_or_context(message, user, context, *, excluded_codes=None):
    codes = _explicit_sample_codes(message, excluded_codes=excluded_codes)
    missing = []

    if codes:
        code_filter = Q()
        for code in codes:
            code_filter |= Q(sample_id__iexact=code)
        samples_by_code = {
            sample.sample_id.upper(): sample
            for sample in _sample_queryset(user)
            .filter(code_filter)
            .order_by("id")
        }
        samples = []
        for code in codes:
            sample = samples_by_code.get(code.upper())
            if sample:
                samples.append(sample)
            else:
                missing.append(
                    {
                        "sample_id": code,
                        "reason": "not found or not accessible",
                    }
                )
        return samples, missing

    context_ids = [int(value) for value in context.get("sample_ids", [])]
    samples_by_id = {
        sample.id: sample
        for sample in _sample_queryset(user)
        .filter(id__in=context_ids)
        .order_by("id")
    }
    return [samples_by_id[value] for value in context_ids if value in samples_by_id], []


def _propose_add_to_batch(message, user, context):
    if not re.search(r"\b(?:add|move)\b.*\bbatch\b", message, re.IGNORECASE):
        return None
    batch_match = re.search(
        r"\bbatch\s+([A-Za-z0-9][A-Za-z0-9_-]*)\b",
        message,
        re.IGNORECASE,
    )
    batch_code = batch_match.group(1) if batch_match else context.get("batch_code")
    if not batch_code:
        return _error_result("Tell me which batch to use, for example batch B-100.")

    samples, excluded = _samples_from_codes_or_context(
        message,
        user,
        context,
        excluded_codes=[batch_code],
    )
    if not samples:
        return _error_result(
            "Tell me the exact samples to add, use a sample range, or first "
            "select samples in the conversation."
        )
    if len(samples) + len(excluded) > assistant_bulk_max_records():
        return _error_result(
            f"The request exceeds the configured assistant maximum of "
            f"{assistant_bulk_max_records()} samples."
        )

    batch = SampleBatch.objects.select_related("project").filter(
        code__iexact=batch_code
    ).first()
    project_ids = {sample.project_id for sample in samples if sample.project_id}
    if batch:
        project = batch.project
    elif len(project_ids) == 1:
        project = Project.objects.get(id=next(iter(project_ids)))
    else:
        return _error_result(
            "A new batch requires samples from exactly one primary project."
        )

    _, project_error = _resolve_project(project.code, user, write=True)
    if project_error:
        return _error_result(project_error)

    included = []
    snapshots = {}
    for sample in samples:
        try:
            require_sample_modify_access(user, sample)
        except PermissionDenied as exc:
            excluded.append({"sample_id": sample.sample_id, "reason": str(exc)})
            continue
        if sample.project_id != project.id:
            excluded.append(
                {
                    "sample_id": sample.sample_id,
                    "reason": f"primary project is not {project.code}",
                }
            )
            continue
        if batch and sample.batch_id == batch.id:
            excluded.append(
                {
                    "sample_id": sample.sample_id,
                    "reason": f"already in batch {batch.code}",
                }
            )
            continue

        included.append(_sample_preview_row(sample, {"batch": batch_code}))
        snapshots[str(sample.id)] = _sample_snapshot(sample)

    preview = _preview(
        operation="Add to batch",
        user=user,
        project=project,
        samples=included,
        excluded=excluded,
        current_values={"batch": "See exact sample list"},
        proposed_values={"batch": batch_code},
        warnings=(
            [f"Batch {batch_code} will be created for {project.code}."]
            if not batch
            else []
        ),
    )
    if not included:
        return _error_result("No samples can be added to this batch.", preview=preview)

    sample_ids = [row["id"] for row in included]
    sample_codes = [row["sample_id"] for row in included]
    return _proposal_result(
        f"Add {len(included)} sample(s) to batch {batch_code}",
        preview,
        {
            "action_type": "BULK_SAMPLE_UPDATE",
            "operation": "ADD_TO_BATCH",
            "sample_ids": sample_ids,
            "sample_codes": sample_codes,
            "snapshots": snapshots,
            "batch_id": batch.id if batch else None,
            "batch_code": batch_code,
            "batch_project_id": project.id,
            "create_batch": batch is None,
            "reason": str(message).strip(),
        },
        context={
            "sample_ids": sample_ids,
            "sample_codes": sample_codes,
            "project_id": project.id,
            "batch_code": batch_code,
        },
    )


def _resolve_target_user(reference):
    cleaned = str(reference or "").strip(" .?!,;:")
    user_model = get_user_model()
    exact = list(
        user_model.objects.filter(
            Q(username__iexact=cleaned)
            | Q(email__iexact=cleaned)
            | Q(first_name__iexact=cleaned)
        ).distinct()[:3]
    )
    if not exact:
        return None, f"User {cleaned} was not found."
    if len(exact) > 1:
        return None, f"User {cleaned} is ambiguous; use the exact username."
    target = exact[0]
    if not target.is_active:
        return None, f"User {target.username} is inactive."
    if not (
        target.is_superuser
        or target.groups.filter(name__in=["admin", "tech"]).exists()
    ):
        return None, f"User {target.username} is not a tech or admin."
    return target, None


def _propose_assign_batch(message, user, context):
    match = re.search(
        r"\bassign\s+all\s+unassigned\s+samples?\s+in\s+"
        r"(?:(?:this\s+)?batch(?:\s+([A-Za-z0-9][A-Za-z0-9_-]*))?)\s+"
        r"to\s+(.+?)(?=[.?!]?$)",
        message,
        re.IGNORECASE,
    )
    if not match:
        return None

    batch_code = match.group(1) or context.get("batch_code")
    if not batch_code:
        return _error_result("Tell me which batch to use.")
    batch = SampleBatch.objects.select_related("project").filter(
        code__iexact=batch_code
    ).first()
    if not batch:
        return _error_result(f"Batch {batch_code} was not found.")

    project, project_error = _resolve_project(batch.project.code, user, write=True)
    if project_error:
        return _error_result(project_error)
    target, target_error = _resolve_target_user(match.group(2))
    if target_error:
        return _error_result(target_error)
    if not (
        target.is_superuser
        or is_admin(target)
        or project.members.filter(id=target.id).exists()
    ):
        return _error_result(
            f"User {target.username} is not a member of project {project.code}."
        )

    samples = list(
        _sample_queryset(user)
        .filter(batch=batch, assigned_to__isnull=True)
        .order_by("id")
    )
    if len(samples) > assistant_bulk_max_records():
        return _error_result(
            f"The request matches {len(samples)} samples, which exceeds the "
            f"configured assistant maximum of {assistant_bulk_max_records()}."
        )

    included = []
    excluded = []
    snapshots = {}
    for sample in samples:
        try:
            require_sample_modify_access(user, sample)
        except PermissionDenied as exc:
            excluded.append({"sample_id": sample.sample_id, "reason": str(exc)})
            continue
        included.append(
            _sample_preview_row(sample, {"assigned_to": target.username})
        )
        snapshots[str(sample.id)] = _sample_snapshot(sample)

    preview = _preview(
        operation="Assign samples",
        user=user,
        project=project,
        samples=included,
        excluded=excluded,
        current_values={"assigned_to": None, "batch": batch.code},
        proposed_values={"assigned_to": target.username},
    )
    if not included:
        return _error_result(
            f"Batch {batch.code} has no accessible unassigned samples.",
            preview=preview,
        )

    sample_ids = [row["id"] for row in included]
    sample_codes = [row["sample_id"] for row in included]
    return _proposal_result(
        f"Assign {len(included)} sample(s) in {batch.code} to {target.username}",
        preview,
        {
            "action_type": "BULK_SAMPLE_UPDATE",
            "operation": "ASSIGN",
            "sample_ids": sample_ids,
            "sample_codes": sample_codes,
            "snapshots": snapshots,
            "target_user_id": target.id,
            "batch_id": batch.id,
            "reason": str(message).strip(),
        },
        context={
            "sample_ids": sample_ids,
            "sample_codes": sample_codes,
            "project_id": project.id,
            "batch_code": batch.code,
        },
    )


def route_sample_management(message, user, context=None):
    text = str(message or "").strip()
    context = context or {}

    if re.search(
        r"\b(?:delete|destroy|permanently\s+remove)\b.*\bsamples?\b",
        text,
        re.IGNORECASE,
    ):
        return _error_result(
            "Permanent sample deletion is not supported through the assistant. "
            "Use an audited archive action instead."
        )

    for router in [
        _propose_create_samples,
        _propose_bulk_project_status,
        _propose_single_status,
        _propose_archive,
    ]:
        result = router(text, user)
        if result:
            return result

    for router in [_propose_add_to_batch, _propose_assign_batch]:
        result = router(text, user, context)
        if result:
            return result

    for router in [
        _summarize_sample_read,
        _received_today_read,
        _awaiting_processing_read,
        _find_sample_read,
    ]:
        result = router(text, user)
        if result:
            return result

    return None


def _event_for_sample(action, sample, event_action, before, after, changed_fields):
    Event.objects.create(
        entity_type="Sample",
        entity_id=str(sample.id),
        action=event_action,
        actor=action.requested_by,
        payload={
            "sample_id": sample.id,
            "sample_code": sample.sample_id,
            "actor_id": action.requested_by_id,
            "actor_username": action.requested_by.username,
            "before": before,
            "after": after,
            "changed_fields": changed_fields,
            "reason": action.payload.get("reason", ""),
            "source": "assistant_confirmation",
            "assistant_action_id": str(action.id),
            "idempotency_key": str(action.idempotency_key),
            "bulk": len(action.payload.get("sample_ids", [])) > 1,
        },
    )


def execute_create_samples(action):
    payload = action.payload or {}
    project = Project.objects.filter(id=payload.get("project_id")).first()
    if not project:
        raise ValueError("The selected project no longer exists.")
    validate_sample_project_assignment(action.requested_by, project)

    sample_codes = list(payload.get("sample_codes") or [])
    maximum = assistant_bulk_max_records()
    if len(sample_codes) > maximum:
        raise ValueError(
            f"The frozen sample set exceeds the configured maximum of {maximum}."
        )
    if len(sample_codes) != len(set(code.upper() for code in sample_codes)):
        raise ValueError("The frozen sample IDs contain duplicates.")

    custom_fields, field_errors = _validate_custom_field_payload(
        payload.get("custom_fields") or {},
        require_all=True,
    )
    if field_errors:
        raise ValueError("; ".join(field_errors))
    definitions = {
        definition.name: definition
        for definition in FieldDefinition.objects.filter(
            entity_type="Sample",
            name__in=custom_fields,
        )
    }

    succeeded = []
    failed = []
    for code in sample_codes:
        try:
            with transaction.atomic():
                if Sample.objects.filter(sample_id__iexact=code).exists():
                    raise ValueError("sample ID already exists")
                sample = Sample.objects.create(
                    sample_id=code,
                    status=Sample.STATUS_RECEIVED,
                    project=project,
                    created_by=action.requested_by,
                )
                for name, value in custom_fields.items():
                    FieldValue.objects.create(
                        field_definition=definitions[name],
                        entity_type="Sample",
                        entity_id=str(sample.id),
                        value=value,
                    )
                _event_for_sample(
                    action,
                    sample,
                    "SAMPLE_CREATED_BY_ASSISTANT",
                    {},
                    {
                        "status": sample.status,
                        "project_id": sample.project_id,
                        "custom_fields": custom_fields,
                    },
                    ["sample_id", "status", "project_id", "custom_fields"],
                )
                succeeded.append(
                    {"id": sample.id, "sample_id": sample.sample_id}
                )
        except (IntegrityError, ValueError) as exc:
            failed.append({"sample_id": code, "reason": str(exc)})

    return {
        "operation": "CREATE_SAMPLES",
        "requested_count": len(sample_codes),
        "succeeded_count": len(succeeded),
        "failed_count": len(failed),
        "succeeded": succeeded,
        "failed": failed,
        "context": {
            "sample_ids": [row["id"] for row in succeeded],
            "sample_codes": [row["sample_id"] for row in succeeded],
            "project_id": project.id,
        },
    }


def _snapshot_changed(sample, snapshot, operation):
    fields = {
        "CHANGE_STATUS": ["status", "project_id"],
        "ARCHIVE": ["status", "project_id"],
        "ADD_TO_BATCH": ["batch_id", "project_id"],
        "ASSIGN": ["assigned_to_id", "batch_id", "project_id"],
    }[operation]
    return any(getattr(sample, field) != snapshot.get(field) for field in fields)


def execute_bulk_sample_update(action):
    payload = action.payload or {}
    operation = payload.get("operation")
    supported = {"CHANGE_STATUS", "ARCHIVE", "ADD_TO_BATCH", "ASSIGN"}
    if operation not in supported:
        raise ValueError("Unsupported bulk sample operation.")

    sample_ids = [int(value) for value in payload.get("sample_ids") or []]
    maximum = assistant_bulk_max_records()
    if len(sample_ids) > maximum:
        raise ValueError(
            f"The frozen sample set exceeds the configured maximum of {maximum}."
        )
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("The frozen sample set contains duplicate record IDs.")

    batch = None
    if operation == "ADD_TO_BATCH":
        project = Project.objects.filter(
            id=payload.get("batch_project_id")
        ).first()
        if not project:
            raise ValueError("The batch project no longer exists.")
        validate_sample_project_assignment(action.requested_by, project)
        batch = SampleBatch.objects.select_for_update().filter(
            code__iexact=payload.get("batch_code")
        ).first()
        if batch and batch.project_id != project.id:
            raise ValueError(
                f"Batch {batch.code} now belongs to a different project."
            )
        if not batch:
            batch = SampleBatch.objects.create(
                code=payload.get("batch_code"),
                project=project,
                created_by=action.requested_by,
            )
            Event.objects.create(
                entity_type="SampleBatch",
                entity_id=str(batch.id),
                # Event.action is limited to 32 characters.
                action="SAMPLE_BATCH_CREATED_ASSISTANT",
                actor=action.requested_by,
                payload={
                    "batch_code": batch.code,
                    "project_id": project.id,
                    "assistant_action_id": str(action.id),
                },
            )

    target_user = None
    if operation == "ASSIGN":
        target_user = get_user_model().objects.filter(
            id=payload.get("target_user_id"),
            is_active=True,
        ).first()
        if not target_user:
            raise ValueError("The target user no longer exists or is inactive.")
        if not (
            target_user.is_superuser
            or is_admin(target_user)
            or is_tech(target_user)
        ):
            raise ValueError("The target user is no longer a tech or admin.")

    # Lock only Sample rows. PostgreSQL rejects FOR UPDATE when nullable
    # select_related() rows (project, batch, or assignee) are also locked.
    samples_by_id = {
        sample.id: sample
        for sample in Sample.objects.select_for_update(of=("self",))
        .select_related("project", "batch", "assigned_to")
        .filter(id__in=sample_ids)
    }
    snapshots = payload.get("snapshots") or {}
    succeeded = []
    failed = []

    for sample_id in sample_ids:
        sample = samples_by_id.get(sample_id)
        if not sample:
            failed.append(
                {"id": sample_id, "sample_id": None, "reason": "record no longer exists"}
            )
            continue
        snapshot = snapshots.get(str(sample.id)) or {}

        try:
            require_sample_modify_access(action.requested_by, sample)
        except (PermissionDenied, ValidationError) as exc:
            failed.append(
                {"id": sample.id, "sample_id": sample.sample_id, "reason": str(exc)}
            )
            continue
        if _snapshot_changed(sample, snapshot, operation):
            failed.append(
                {
                    "id": sample.id,
                    "sample_id": sample.sample_id,
                    "reason": "record changed after preview; no update was applied",
                }
            )
            continue

        before = _sample_snapshot(sample)
        if operation in {"CHANGE_STATUS", "ARCHIVE"}:
            target_status = payload.get("target_status")
            if not can_transition(sample.status, target_status):
                failed.append(
                    {
                        "id": sample.id,
                        "sample_id": sample.sample_id,
                        "reason": (
                            f"transition from {sample.status} to {target_status} "
                            "is no longer permitted"
                        ),
                    }
                )
                continue
            if target_status != Sample.STATUS_ARCHIVED:
                metadata_errors = _required_metadata_errors(sample)
                if metadata_errors:
                    failed.append(
                        {
                            "id": sample.id,
                            "sample_id": sample.sample_id,
                            "reason": "; ".join(metadata_errors),
                        }
                    )
                    continue
            sample.status = target_status
            sample.status_changed_at = timezone.now()
            sample.save(
                update_fields=["status", "status_changed_at", "updated_at"]
            )
            event_action = (
                "SAMPLE_ARCHIVED"
                if target_status == Sample.STATUS_ARCHIVED
                else (
                    "BULK_SAMPLE_STATUS_CHANGED"
                    if len(sample_ids) > 1
                    else "SAMPLE_STATUS_CHANGED"
                )
            )
            changed_fields = ["status"]
        elif operation == "ADD_TO_BATCH":
            if sample.project_id != batch.project_id:
                failed.append(
                    {
                        "id": sample.id,
                        "sample_id": sample.sample_id,
                        "reason": "sample primary project no longer matches the batch",
                    }
                )
                continue
            sample.batch = batch
            sample.save(update_fields=["batch", "updated_at"])
            event_action = "SAMPLE_BATCH_CHANGED"
            changed_fields = ["batch_id"]
        else:
            if sample.batch_id != payload.get("batch_id"):
                failed.append(
                    {
                        "id": sample.id,
                        "sample_id": sample.sample_id,
                        "reason": "sample is no longer in the frozen batch",
                    }
                )
                continue
            if not (
                target_user.is_superuser
                or is_admin(target_user)
                or sample.project.members.filter(id=target_user.id).exists()
            ):
                failed.append(
                    {
                        "id": sample.id,
                        "sample_id": sample.sample_id,
                        "reason": "target user is no longer a project member",
                    }
                )
                continue
            sample.assigned_to = target_user
            sample.save(update_fields=["assigned_to", "updated_at"])
            event_action = "SAMPLE_ASSIGNED"
            changed_fields = ["assigned_to_id"]

        after = _sample_snapshot(sample)
        _event_for_sample(
            action,
            sample,
            event_action,
            before,
            after,
            changed_fields,
        )
        succeeded.append({"id": sample.id, "sample_id": sample.sample_id})

    context = {
        "sample_ids": [row["id"] for row in succeeded],
        "sample_codes": [row["sample_id"] for row in succeeded],
    }
    if batch:
        context["batch_code"] = batch.code
        context["project_id"] = batch.project_id

    return {
        "operation": operation,
        "frozen_sample_ids": sample_ids,
        "requested_count": len(sample_ids),
        "succeeded_count": len(succeeded),
        "failed_count": len(failed),
        "succeeded": succeeded,
        "failed": failed,
        "context": context,
    }
