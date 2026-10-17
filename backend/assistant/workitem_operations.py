import re
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from core.permissions import is_admin, is_tech
from events.models import Event
from results.models import WorkItem
from samples.access import get_sample_access_queryset
from samples.models import Sample, SampleBatch

from .suggestions import batch_prompt
from .entity_resolution import accessible_entity_queryset


def personal_work_summary(message, user):
    """Personal-priority questions do not require a model or special commands."""
    text = str(message).strip().lower().replace("’", "'")
    text = re.sub(r"[?!¿¡.,]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:please |hey |hi )", "", text)
    text = re.sub(r" (?:please|smh|shm)$", "", text)
    if not re.fullmatch(r"(?:what (?:do i need to|should i|can i|am i supposed to) work on(?: today| next)?|what should i do next|what(?:'s| is) on my plate(?: today)?|(?:show|list)(?: me)? my (?:work|tasks|assignments)|what (?:are my tasks|is assigned to me)|(?:en )?qu[eé] (?:debo|tengo que) trabajar(?: hoy)?)", text):
        return None
    from django.db.models import F
    from .lab_helpers import response
    now = timezone.now()
    queryset = _accessible_work(user).filter(assigned_to=user).exclude(status__in=LOCKED_STATUSES)
    items = list(queryset.select_related("sample").order_by(F("due_at").asc(nulls_last=True), "pk")[:101])
    rows = [{"sample": item.sample.sample_id, "work": item.name, "status": item.status,
             "due": item.due_at.isoformat() if item.due_at else "No deadline recorded",
             "review": "Failed work—review before proceeding" if item.status == "FAILED" else
                       "QC needs review" if item.qc_status in {"REJECTED", "RERUN_REQUIRED"} else
                       "Overdue" if item.due_at and item.due_at < now else "Check the next step"}
            for item in items[:100]]
    answer = ("Here's your unfinished assigned work, with the earliest deadlines first. Open a sample to check its next step before proceeding."
              if rows else "I couldn't find any unfinished work assigned to you in the records you can access. You can check the team's attention summary for unassigned work and other issues.")
    if len(items) > 100:
        answer += " I'm showing the first 100 items; open My Work for the rest."
    return response(answer, personal_work={"username": user.username, "truncated": len(items) > 100},
                    comparison={"title": "Your work priorities", "rows": rows,
                                "columns": [{"key": key, "label": label} for key, label in [("sample", "Sample"), ("work", "Work"), ("status", "Status"), ("due", "Deadline"), ("review", "What to check")]],
                                "notes": ["Only unfinished work assigned to you and currently accessible. This is not a full dependency or QC task assessment; future and undated work are included."]},
                    links=[{"label": item.sample.sample_id, "url": f"/samples/{item.sample_id}"} for item in items[:10]],
                    suggestions=([f"What next for sample {items[0].sample.sample_id}"] if items else []) + ["What needs attention?"])


ACTIVE_STATUSES = [WorkItem.STATUS_PENDING, WorkItem.STATUS_IN_PROGRESS]
LOCKED_STATUSES = [WorkItem.STATUS_COMPLETED, WorkItem.STATUS_CANCELLED]
MAX_WORK_ITEMS = 100


class WorkItemOperationError(ValueError):
    pass


def _is_admin(user):
    return is_admin(user)


def _can_write(user):
    return is_admin(user) or is_tech(user)


def _can_access_project(user, project):
    return bool(
        _is_admin(user)
        or (project and project.members.filter(id=user.id).exists())
    )


def _resolve_user(label):
    value = str(label or "").strip()
    if not value:
        return None, "A user is required."
    users = list(
        get_user_model()
        .objects.filter(
            Q(username__iexact=value)
            | Q(first_name__iexact=value)
            | Q(last_name__iexact=value)
        )
        .order_by("id")[:3]
    )
    if not users:
        return None, f"User {value} was not found."
    if len(users) > 1:
        return None, f"User {value} is ambiguous; use the exact username."
    return users[0], None


def _extract_person_after(message, marker):
    match = re.search(
        rf"\b{marker}\s+([A-Za-z0-9_.@+-]+)",
        message,
        re.IGNORECASE,
    )
    return match.group(1) if match else ""


def _work_type(message):
    lower = message.lower()
    for label in ["sequencing", "extraction", "pcr", "analysis"]:
        if label in lower:
            return label.upper()
    return None


def _record(item, proposed):
    return {
        "id": item.id,
        "label": f"Work #{item.id} - {item.sample.sample_id}",
        "current": {
            "status": item.status,
            "assigned_to": item.assigned_to.username if item.assigned_to else None,
            "due_at": item.due_at.isoformat() if item.due_at else None,
            "sample_id": item.sample_id,
            "project_id": item.sample.project_id,
            "work_type": item.work_type,
        },
        "proposed": proposed,
    }


def _accessible_work(user):
    samples = get_sample_access_queryset(Sample.objects.all(), user)
    return WorkItem.objects.filter(sample__in=samples)


def _project_scope(message, user, queryset):
    """Resolve an explicit project exactly; never widen an unresolved scope."""
    mentions = re.findall(r"\bprojects?\b", message, re.I)
    if not mentions:
        return queryset, None, None
    match = re.search(
        r"\bproject\s+(.+?)(?=\s+(?:to|from|today|please)\b|$)",
        message.strip(), re.I,
    )
    label = match.group(1).strip().rstrip(".!?").strip("\"'") if match and len(mentions) == 1 else ""
    projects = list(accessible_entity_queryset("project", user).filter(
        Q(code__iexact=label) | Q(name__iexact=label),
    )[:2]) if label else []
    if len(projects) != 1:
        return queryset.none(), None, {
            "answer": "Please specify one accessible project using its exact code or name.",
            "links": [], "skip_llm": True,
        }
    project = projects[0]
    return queryset.filter(sample__project=project), project, None


def _unsupported_work_request(message):
    """Fail closed for modifiers that these work handlers cannot represent."""
    lower = message.lower()
    reason = None
    if re.search(r"\b(?:not|never|except|excluding|exclude|without)\b|\bdon['’]t\b", lower):
        reason = "Negative and exclusion filters are not supported for work requests yet."
    elif re.search(r"\b(?:tomorrow|yesterday|last|past|next|between|before|after)\b|\b\d{4}-\d{2}-\d{2}\b", lower):
        reason = "That date filter is not supported for work requests yet; only an explicit today filter is supported."
    elif re.search(r"\b(?:assign|reassign|create)\b", lower) and (
        re.search(r"\bor\b", lower)
        or len(re.findall(r"\b(?:assign|reassign|create|delete)\b", lower)) > 1
    ):
        reason = "Please submit one work action with one unambiguous set of conditions."
    if reason:
        return {"answer": reason + " Please rephrase; no work was changed.", "links": [], "skip_llm": True}
    return None


def _read_work_items(message, user):
    lower = message.lower()
    work_type = _work_type(message)
    queryset = (
        _accessible_work(user)
        .select_related("sample", "sample__project", "assigned_to")
        .order_by("due_at", "id")
    )
    if work_type:
        queryset = queryset.filter(work_type=work_type)
    queryset, project, error = _project_scope(message, user, queryset)
    if error:
        return error
    heading_type = work_type.lower() if work_type else ""
    now = timezone.now()
    overdue = bool(re.search(r"\boverdue\b", lower))
    unassigned = bool(re.search(r"\bunassigned\b", lower))
    if overdue and unassigned:
        overdue_filter = Q(due_at__lt=now)
        unassigned_filter = Q(assigned_to__isnull=True)
        either = bool(re.search(r"\bor\b", lower))
        queryset = queryset.filter(status__in=ACTIVE_STATUSES).filter(
            overdue_filter | unassigned_filter if either else overdue_filter & unassigned_filter
        )
        heading = f"Overdue {'or' if either else 'and'} unassigned {heading_type} work".replace("  ", " ")
    elif overdue:
        queryset = queryset.filter(
            due_at__lt=now,
            status__in=ACTIVE_STATUSES,
        )
        heading = f"Overdue {heading_type} work".replace("  ", " ")
    elif unassigned:
        queryset = queryset.filter(
            assigned_to__isnull=True,
            status__in=ACTIVE_STATUSES,
        )
        heading = f"Unassigned {heading_type} work".replace("  ", " ")
    else:
        return None

    if re.search(r"\btoday\b", lower):
        today_start = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))
        queryset = queryset.filter(due_at__gte=today_start, due_at__lt=today_start + timedelta(days=1))
        heading += " today"
    if project:
        heading += f" in project {project.code}"

    total = queryset.count()
    items = list(queryset[:MAX_WORK_ITEMS])
    lines = [f"{heading}: {total} item(s)."]
    if total > MAX_WORK_ITEMS:
        lines.append(f"Showing the first {MAX_WORK_ITEMS}; narrow the project or work-type filter to see fewer items.")
    links = []
    for item in items:
        assignee = item.assigned_to.username if item.assigned_to else "unassigned"
        due = item.due_at.isoformat() if item.due_at else "no due date"
        lines.append(
            f"- Work #{item.id}: {item.sample.sample_id} - {item.status} - {assignee} - due {due}"
        )
        links.append({"label": f"Open {item.sample.sample_id}", "url": f"/samples/{item.sample_id}"})
    return {
        "answer": "\n".join(lines),
        "links": links,
        "skip_llm": True,
    }


def _propose_create(message, user):
    lower = message.lower()
    if "create" not in lower or "work" not in lower or "batch" not in lower:
        return None
    match = re.search(r"\bbatch\s+([A-Za-z0-9_.-]+)", message, re.IGNORECASE)
    if not match:
        example = batch_prompt(
            user,
            "Create sequencing work for samples in batch",
        )
        answer = "Specify an accessible batch code."
        if example:
            answer += f" For example: {example}."
        return {
            "answer": answer,
            "links": [],
            "skip_llm": True,
        }
    batch = SampleBatch.objects.select_related("project").filter(code__iexact=match.group(1)).first()
    if not batch or not _can_access_project(user, batch.project):
        return {"answer": "That batch was not found or is not accessible.", "links": [], "skip_llm": True}

    work_type = _work_type(message) or "GENERAL"
    samples = list(
        get_sample_access_queryset(
            Sample.objects.filter(batch=batch).select_related("project"),
            user,
        ).order_by("id")[: MAX_WORK_ITEMS + 1]
    )
    if len(samples) > MAX_WORK_ITEMS:
        return {
            "answer": f"The batch contains more than the {MAX_WORK_ITEMS}-item work-creation limit. Narrow the request.",
            "links": [],
            "skip_llm": True,
        }
    active_sample_ids = set(
        WorkItem.objects.filter(
            sample__in=samples,
            work_type=work_type,
            status__in=ACTIVE_STATUSES,
        ).values_list("sample_id", flat=True)
    )
    records = []
    excluded = []
    for sample in samples:
        if sample.id in active_sample_ids:
            excluded.append({"id": sample.id, "label": sample.sample_id, "reason": "duplicate active work exists"})
            continue
        records.append({
            "id": sample.id,
            "label": sample.sample_id,
            "current": {"work_item": None},
            "proposed": {"work_type": work_type, "status": WorkItem.STATUS_PENDING},
        })
    preview = {
        "title": "Proposed work-item creation",
        "operation": "CREATE_WORK_ITEMS",
        "project": {"id": batch.project_id, "label": batch.project.code},
        "records_affected": len(records),
        "excluded_count": len(excluded),
        "records": records,
        "excluded": excluded,
        "current_values": {"batch": batch.code},
        "proposed_values": {"work_type": work_type, "status": WorkItem.STATUS_PENDING},
    }
    return {
        "answer": f"Create {len(records)} {work_type.lower()} work item(s) for batch {batch.code}. Review the exact sample list and confirm.",
        "links": [],
        "skip_llm": True,
        "pending_action": {
            "type": "WORK_ITEM_OPERATION",
            "summary": f"Create {work_type.lower()} work for batch {batch.code}",
            "payload": {
                "operation": "CREATE",
                "work_type": work_type,
                "batch_id": batch.id,
                "sample_ids": [record["id"] for record in records],
                "preview": preview,
            },
        },
    }


def _propose_assignment(message, user):
    lower = message.lower()
    if not re.search(r"\b(?:assign|reassign)\b", lower):
        return None
    if re.search(r"\b(?:to|from)\s+[A-Za-z0-9_.@+-]+\s*(?:,|\band\b)", message, re.I) or len(re.findall(r"\bto\b", lower)) > 1:
        return {
            "answer": "Specify one assignee per request (and one source user for reassignment). Please rephrase.",
            "links": [], "skip_llm": True,
        }
    target_label = _extract_person_after(message, "to")
    target, error = _resolve_user(target_label)
    if error:
        return {"answer": error, "links": [], "skip_llm": True}
    if not target.is_active:
        return {"answer": "The selected assignee is inactive. Choose an active user.", "links": [], "skip_llm": True}

    work_type = _work_type(message) or "GENERAL"
    queryset = (
        _accessible_work(user)
        .select_related("sample", "sample__project", "assigned_to")
        .filter(work_type=work_type, status__in=ACTIVE_STATUSES)
    )
    queryset, project, error = _project_scope(message, user, queryset)
    if error:
        return error
    operation = "ASSIGN"
    if "reassign" in lower:
        operation = "REASSIGN"
        source_label = _extract_person_after(message, "from")
        source, source_error = _resolve_user(source_label)
        if source_error:
            return {"answer": source_error, "links": [], "skip_llm": True}
        queryset = queryset.filter(assigned_to=source)
    else:
        queryset = queryset.filter(assigned_to__isnull=True)

    now = timezone.now()
    if "overdue" in lower:
        queryset = queryset.filter(due_at__lt=now)
    if "today" in lower:
        start = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))
        queryset = queryset.filter(due_at__gte=start, due_at__lt=start + timedelta(days=1))

    items = list(queryset.order_by("id")[:MAX_WORK_ITEMS + 1])
    if len(items) > MAX_WORK_ITEMS:
        return {
            "answer": f"This request exceeds the {MAX_WORK_ITEMS}-item assignment limit. Narrow the project, work type, or date filter and try again. No assignment was proposed.",
            "links": [], "skip_llm": True,
        }
    records = []
    excluded = []
    for item in items:
        item_project = item.sample.project
        if item_project and not item_project.members.filter(id=target.id).exists() and not _is_admin(target):
            excluded.append({"id": item.id, "label": f"Work #{item.id}", "reason": f"{target.username} is not a project member"})
            continue
        records.append(_record(item, {"assigned_to": target.username}))
    workload = _accessible_work(user).filter(assigned_to=target, status__in=ACTIVE_STATUSES).count()
    preview = {
        "title": "Proposed work assignment",
        "operation": operation,
        "project": project.code if project else "Multiple accessible projects",
        "records_affected": len(records),
        "excluded_count": len(excluded),
        "records": records,
        "excluded": excluded,
        "current_values": {"target_workload": workload},
        "proposed_values": {"assigned_to": target.username},
    }
    return {
        "answer": f"{operation.title()} {len(records)} {work_type.lower()} work item(s) to {target.username}. Current active workload visible to you: {workload}. Review and confirm.",
        "links": [],
        "skip_llm": True,
        "pending_action": {
            "type": "WORK_ITEM_OPERATION",
            "summary": f"{operation.title()} {work_type.lower()} work to {target.username}",
            "payload": {
                "operation": operation,
                "work_type": work_type,
                "work_item_ids": [record["id"] for record in records],
                "target_user_id": target.id,
                "project_id": project.id if project else None,
                "snapshots": {str(record["id"]): record["current"] for record in records},
                "preview": preview,
            },
        },
    }


def route_workitem_operations(message, user, context=None):
    del context
    personal = personal_work_summary(message, user)
    if personal:
        return personal
    lower = str(message or "").lower()
    if "work" not in lower:
        return None
    clarification = _unsupported_work_request(message)
    if clarification:
        return clarification
    if re.search(r"\b(?:create|assign|reassign)\b", lower) and not _can_write(user):
        return {
            "answer": "Only Tech or Director users can create or assign work items.",
            "links": [],
            "skip_llm": True,
        }
    return (
        _propose_create(message, user)
        or _propose_assignment(message, user)
        or _read_work_items(message, user)
    )


def execute_workitem_operation(action):
    payload = action.payload or {}
    operation = payload.get("operation")
    if not _can_write(action.requested_by):
        raise WorkItemOperationError(
            "Only Tech or Director users can create or assign work items."
        )
    if operation in {"GUIDED_ASSIGN", "GUIDED_RESULT"}:
        from .guided_actions import execute_guided_action
        return execute_guided_action(action)
    succeeded = []
    failed = []

    if operation == "CREATE":
        batch = SampleBatch.objects.select_related("project").filter(id=payload.get("batch_id")).first()
        if not batch or not _can_access_project(action.requested_by, batch.project):
            raise WorkItemOperationError("Batch access is no longer permitted.")
        work_type = payload.get("work_type", "GENERAL")
        samples = {
            item.id: item
            for item in Sample.objects.select_for_update().filter(id__in=payload.get("sample_ids", []), batch=batch)
        }
        for sample_id in payload.get("sample_ids", []):
            sample = samples.get(sample_id)
            if not sample:
                failed.append({"id": sample_id, "reason": "sample changed or left the frozen batch"})
                continue
            if not get_sample_access_queryset(Sample.objects.filter(id=sample.id), action.requested_by).exists():
                failed.append({"id": sample_id, "label": sample.sample_id, "reason": "project access denied"})
                continue
            try:
                # Isolate each insert behind a savepoint so a concurrent duplicate
                # can be reported without breaking the rest of the frozen batch.
                with transaction.atomic():
                    item = WorkItem.objects.create(
                        sample=sample,
                        name=f"{work_type.title()} work",
                        work_type=work_type,
                        status=WorkItem.STATUS_PENDING,
                        created_by=action.requested_by,
                    )
            except IntegrityError:
                failed.append({"id": sample_id, "label": sample.sample_id, "reason": "duplicate active work exists"})
                continue
            succeeded.append({"id": item.id, "sample_id": sample.sample_id})
            Event.objects.create(
                entity_type="WorkItem",
                entity_id=str(item.id),
                action="WORK_ITEM_CREATED",
                actor=action.requested_by,
                payload={"sample_id": sample.id, "sample_code": sample.sample_id, "project_id": sample.project_id, "work_type": work_type, "assistant_action_id": str(action.id)},
            )
    elif operation in {"ASSIGN", "REASSIGN"}:
        target = get_user_model().objects.filter(id=payload.get("target_user_id"), is_active=True).first()
        if not target:
            raise WorkItemOperationError("The selected assignee is no longer active.")
        items = {
            item.id: item
            for item in WorkItem.objects.select_for_update().filter(
                id__in=payload.get("work_item_ids", [])
            )
        }
        snapshots = payload.get("snapshots") or {}
        for item_id in payload.get("work_item_ids", []):
            item = items.get(item_id)
            if not item:
                failed.append({"id": item_id, "reason": "work item no longer exists"})
                continue
            if payload.get("project_id") is not None and item.sample.project_id != payload["project_id"]:
                failed.append({"id": item_id, "reason": "work item left the selected project"})
                continue
            if item.status in LOCKED_STATUSES:
                failed.append({"id": item_id, "label": f"Work #{item.id}", "reason": f"{item.status} work cannot be reassigned"})
                continue
            expected = snapshots.get(str(item_id), {})
            current_assignee = item.assigned_to.username if item.assigned_to else None
            if expected.get("status") != item.status or expected.get("assigned_to") != current_assignee:
                failed.append({"id": item_id, "label": f"Work #{item.id}", "reason": "assignment or status changed after preview"})
                continue
            current = _record(item, {})["current"]
            if any(key not in expected or expected[key] != current[key] for key in ("due_at", "sample_id", "project_id", "work_type")):
                failed.append({"id": item_id, "label": f"Work #{item.id}", "reason": "work details changed or preview is outdated; generate a new preview"})
                continue
            if not _can_access_project(action.requested_by, item.sample.project):
                failed.append({"id": item_id, "reason": "project access denied"})
                continue
            if item.sample.project and not (_is_admin(target) or item.sample.project.members.filter(id=target.id).exists()):
                failed.append({"id": item_id, "reason": "assignee is no longer a project member"})
                continue
            before = current_assignee
            item.assigned_to = target
            item.save(update_fields=["assigned_to", "updated_at"])
            succeeded.append({"id": item.id, "sample_id": item.sample.sample_id, "assigned_to": target.username})
            Event.objects.create(
                entity_type="WorkItem",
                entity_id=str(item.id),
                action="WORK_ITEM_REASSIGNED" if before else "WORK_ITEM_ASSIGNED",
                actor=action.requested_by,
                payload={"project_id": item.sample.project_id, "sample_id": item.sample_id, "before": {"assigned_to": before}, "after": {"assigned_to": target.username}, "assistant_action_id": str(action.id)},
            )
    else:
        raise WorkItemOperationError("Unsupported work-item operation.")

    return {
        "operation": operation,
        "succeeded": succeeded,
        "failed": failed,
        "succeeded_count": len(succeeded),
        "failed_count": len(failed),
    }
