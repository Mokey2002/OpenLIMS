import re
from datetime import timedelta

from core.permissions import is_admin, is_qc_reviewer, is_tech
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from events.models import Event
from rest_framework.exceptions import PermissionDenied, ValidationError
from results.models import Result
from samples.access import get_sample_access_queryset, user_can_modify_sample
from samples.models import Sample
from settings_app.models import SystemSettings

from .models import AssistantAction
from .sample_operations import assistant_bulk_max_records
from .suggestions import accessible_result_references

RESULT_REFERENCE_RE = re.compile(r"\bR-?(\d+)\b", re.IGNORECASE)


def _result_request_help(user, instruction, example, *, failed_only=False):
    references = accessible_result_references(
        user,
        limit=1,
        failed_only=failed_only,
    )
    if not references:
        return instruction
    return f"{instruction} For example: {example.format(result=references[0])}."


def _result_queryset(user):
    allowed_samples = get_sample_access_queryset(Sample.objects.all(), user)
    return (
        Result.objects.select_related(
            "work_item",
            "work_item__sample",
            "work_item__sample__project",
            "entered_by",
            "qc_assigned_to",
            "qc_reviewed_by",
        )
        .filter(work_item__sample__in=allowed_samples)
        .order_by("id")
    )


def _result_link(result):
    sample = result.work_item.sample
    return {
        "label": f"Open {sample.sample_id}",
        "url": f"/samples/{sample.id}",
        "kind": "result",
        "extra": {"result_id": result.id, "sample_id": sample.sample_id},
    }


def _result_label(result):
    return f"R-{result.id} — {result.work_item.sample.sample_id} / {result.key}"


def _group_results_by_sample(results):
    grouped = {}
    for result in results:
        sample = result.work_item.sample
        grouped.setdefault(sample.id, {"sample": sample, "results": []})[
            "results"
        ].append(result)
    return list(grouped.values())


def _sample_result_links(groups):
    return [
        {
            "label": f"Open {group['sample'].sample_id}",
            "url": f"/samples/{group['sample'].id}",
            "kind": "sample",
        }
        for group in groups[:20]
    ]


def _sample_result_list_answer(groups, heading, detail):
    lines = [heading]
    for group in groups:
        sample = group["sample"]
        results = group["results"]
        result_labels = ", ".join(f"R-{result.id} ({result.key})" for result in results)
        lines.append(
            f"- {sample.sample_id} — {len(results)} {detail}: {result_labels}"
        )
    return "\n".join(lines)


def _result_snapshot(result):
    return {
        "value_type": result.value_type,
        "value": result.value,
        "unit": result.unit,
        "reference_min": result.reference_min,
        "reference_max": result.reference_max,
        "qc_rule": result.qc_rule,
        "qc_status": result.qc_status,
        "entered_by_id": result.entered_by_id,
        "qc_assigned_to_id": result.qc_assigned_to_id,
        "qc_reviewed_by_id": result.qc_reviewed_by_id,
        "qc_reviewed_at": (
            result.qc_reviewed_at.isoformat() if result.qc_reviewed_at else None
        ),
        "qc_passed": result.qc_passed,
        "qc_failure_reason": result.qc_failure_reason,
        "qc_review_note": result.qc_review_note,
    }


def _result_row(result, proposed):
    return {
        "id": result.id,
        "label": _result_label(result),
        "current": {
            "qc_status": result.qc_status,
            "qc_passed": result.qc_passed,
            "assigned_to": (
                result.qc_assigned_to.username if result.qc_assigned_to else None
            ),
            "value": result.value,
            "reference_range": _reference_range(result),
        },
        "proposed": proposed,
    }


def _reference_range(result):
    if result.reference_min is None and result.reference_max is None:
        return None
    low = "-∞" if result.reference_min is None else result.reference_min
    high = "∞" if result.reference_max is None else result.reference_max
    suffix = f" {result.unit}" if result.unit else ""
    return f"{low} to {high}{suffix}"


def _preview(user, operation, rows, excluded=None, warnings=None):
    excluded = excluded or []
    return {
        "title": "Proposed QC review operation",
        "operation": operation,
        "project": _project_summary(rows),
        "requested_user": {"id": user.id, "username": user.username},
        "records_affected": len(rows),
        "matching_records": len(rows) + len(excluded),
        "excluded_count": len(excluded),
        "records": rows,
        "excluded": excluded,
        "warnings": warnings or [],
        "validation_errors": [],
        "maximum_records": assistant_bulk_max_records(),
    }


def _project_summary(rows):
    projects = {}
    for row in rows:
        result = row.get("_result")
        project = result.work_item.sample.project if result else None
        if project:
            projects[project.id] = project
    if len(projects) == 1:
        project = next(iter(projects.values()))
        return {
            "id": project.id,
            "code": project.code,
            "name": project.name,
            "label": f"{project.code} — {project.name}",
        }
    if not projects:
        return {"label": "Unassigned"}
    return {"label": "Multiple projects"}


def _clean_rows(rows):
    return [
        {key: value for key, value in row.items() if key != "_result"} for row in rows
    ]


def _proposal(
    user, operation, results, proposed, reason="", excluded=None, warnings=None
):
    rows = []
    for result in results:
        row = _result_row(result, proposed(result))
        row["_result"] = result
        rows.append(row)
    preview = _preview(user, operation, rows, excluded=excluded, warnings=warnings)
    preview["records"] = _clean_rows(preview["records"])
    result_ids = [result.id for result in results]
    return {
        "answer": (
            f"{preview['title']}\n\n"
            f"Operation: {operation}\n"
            f"Results affected: {len(result_ids)}\n"
            f"Excluded results: {len(excluded or [])}\n\n"
            "Review the exact preview and explicitly confirm before OpenLIMS changes anything."
        ),
        "links": [_result_link(result) for result in results[:10]],
        "context": {"result_ids": result_ids},
        "skip_llm": True,
        "pending_action": {
            "type": AssistantAction.ACTION_QC_REVIEW,
            "summary": f"{operation} for {len(result_ids)} result(s)",
            "payload": {
                "operation": operation,
                "result_ids": result_ids,
                "snapshots": {
                    str(result.id): _result_snapshot(result) for result in results
                },
                "reason": reason,
                "preview": preview,
            },
        },
    }


def _error(message, *, context=None):
    return {
        "answer": message,
        "links": [],
        "context": context or {},
        "skip_llm": True,
    }


def _result_id_from_message(message):
    match = RESULT_REFERENCE_RE.search(message)
    return int(match.group(1)) if match else None


def _result_ids_from_range(message):
    match = re.search(
        r"\b(?:results?\s+)?(?:R-?)?(\d+)\s+(?:through|to)\s+(?:R-?)?(\d+)\b",
        message,
        re.IGNORECASE,
    )
    if match:
        start, end = (int(value) for value in match.groups())
        if end < start:
            return []
        return list(range(start, end + 1))
    result_id = _result_id_from_message(message)
    return [result_id] if result_id else []


def _reason_from_message(message):
    match = re.search(
        r"\b(?:because|reason\s*:|comment\s*:|with\s+comment)\s+(.+)$",
        message,
        re.IGNORECASE,
    )
    return match.group(1).strip().rstrip(".") if match else ""


def _get_result(result_id, user):
    result = _result_queryset(user).filter(id=result_id).first()
    if result:
        return result, None
    return None, f"Result R-{result_id} was not found or is not accessible."


def _format_result(result):
    value = result.value
    unit = f" {result.unit}" if result.unit else ""
    return (
        f"{_result_label(result)}\n"
        f"Value: {value}{unit}\n"
        f"Reference range: {_reference_range(result) or 'not configured'}\n"
        f"Reference comparison: {result.reference_comparison}\n"
        f"QC rule: {result.qc_rule or 'not configured'}\n"
        f"QC evaluation: {'pass' if result.qc_passed is True else 'fail' if result.qc_passed is False else 'not evaluated'}\n"
        f"Review state: {result.qc_status}"
    )


def _read_failed_this_week(message, user):
    if not re.search(r"\bresults?\b.*\bfailed\s+QC\b.*\bthis\s+week\b", message, re.I):
        return None
    today = timezone.localdate()
    start = today - timedelta(days=today.weekday())
    results = list(
        _result_queryset(user).filter(qc_passed=False, created_at__date__gte=start)[
            :100
        ]
    )
    if not results:
        return _error("No accessible results failed QC this week.")
    lines = [f"{len(results)} accessible result(s) failed QC this week:"]
    lines.extend(
        f"- {_result_label(result)}: {result.qc_failure_reason or result.reference_comparison}"
        for result in results
    )
    return {
        "answer": "\n".join(lines),
        "links": [_result_link(result) for result in results[:20]],
        "context": {"result_ids": [result.id for result in results]},
        "skip_llm": True,
    }


def _read_samples_needing_qc(message, user):
    lower = str(message or "").lower()
    has_sample = re.search(r"\bsamples?\b", lower)
    has_qc = re.search(r"\b(?:qc|quality\s+control|qc\s+review)\b", lower)
    needs_review = re.search(
        r"\b(?:need|needs|needing|awaiting|waiting|pending)\b",
        lower,
    )
    if not (has_sample and has_qc and needs_review):
        return None

    results = list(
        _result_queryset(user).filter(
            qc_status__in=[Result.QC_PENDING_REVIEW, Result.QC_REOPENED]
        )[:500]
    )
    groups = _group_results_by_sample(results)
    if not groups:
        return _error("No accessible samples currently have results needing QC review.")

    answer = _sample_result_list_answer(
        groups,
        (
            f"{len(groups)} accessible sample(s) have {len(results)} result(s) "
            "needing QC review:"
        ),
        "result(s) needing review",
    )
    return {
        "answer": answer,
        "links": _sample_result_links(groups),
        "context": {
            "sample_ids": [group["sample"].id for group in groups],
            "result_ids": [result.id for result in results],
        },
        "skip_llm": True,
    }


def _read_samples_failed_qc(message, user):
    lower = str(message or "").lower()
    has_sample = re.search(r"\bsamples?\b", lower)
    failed_qc = (
        re.search(r"\bfail(?:ed|ing)?\s+qc\b", lower)
        or re.search(r"\bqc\s+fail(?:ure|ures|ed)?\b", lower)
    )
    if not (has_sample and failed_qc):
        return None

    results = list(_result_queryset(user).filter(qc_passed=False)[:500])
    groups = _group_results_by_sample(results)
    if not groups:
        return _error("No accessible samples have results that failed QC.")

    answer = _sample_result_list_answer(
        groups,
        (
            f"{len(groups)} accessible sample(s) have {len(results)} result(s) "
            "that failed QC:"
        ),
        "failed result(s)",
    )
    return {
        "answer": answer,
        "links": _sample_result_links(groups),
        "context": {
            "sample_ids": [group["sample"].id for group in groups],
            "result_ids": [result.id for result in results],
        },
        "skip_llm": True,
    }


def _read_results_needing_qc(message, user):
    lower = str(message or "").lower()
    has_result = re.search(r"\bresults?\b", lower)
    review_request = (
        re.search(r"\bawaiting\s+approval\b", lower)
        or (
            re.search(r"\b(?:need|needs|needing|awaiting|waiting|pending)\b", lower)
            and re.search(r"\b(?:qc|quality\s+control|review|approval)\b", lower)
        )
    )
    if not (has_result and review_request):
        return None

    results = list(
        _result_queryset(user).filter(
            qc_status__in=[Result.QC_PENDING_REVIEW, Result.QC_REOPENED]
        )[:100]
    )
    if not results:
        return _error("No accessible results are awaiting QC review.")
    lines = [f"{len(results)} accessible result(s) are awaiting QC review:"]
    lines.extend(f"- {_result_label(result)} — {result.qc_status}" for result in results)
    return {
        "answer": "\n".join(lines),
        "links": [_result_link(result) for result in results[:20]],
        "context": {"result_ids": [result.id for result in results]},
        "skip_llm": True,
    }


def _read_failed_results(message, user):
    lower = str(message or "").lower()
    if not re.search(r"\bresults?\b", lower):
        return None
    if not (
        re.search(r"\bfail(?:ed|ing)?\s+qc\b", lower)
        or re.search(r"\bqc\s+fail(?:ure|ures|ed)?\b", lower)
    ):
        return None
    if re.search(r"\bthis\s+week\b", lower):
        return None

    results = list(_result_queryset(user).filter(qc_passed=False)[:100])
    if not results:
        return _error("No accessible results have failed QC.")
    lines = [f"{len(results)} accessible result(s) failed QC:"]
    lines.extend(
        f"- {_result_label(result)}: "
        f"{result.qc_failure_reason or result.reference_comparison or 'No reason recorded'}"
        for result in results
    )
    return {
        "answer": "\n".join(lines),
        "links": [_result_link(result) for result in results[:20]],
        "context": {"result_ids": [result.id for result in results]},
        "skip_llm": True,
    }


def _read_approved_results(message, user):
    lower = str(message or "").lower()
    if not (
        re.search(r"\b(?:show|list|which)\b.*\bapproved\s+results?\b", lower)
        or re.search(r"\bresults?\b.*\bapproved\b", lower)
    ):
        return None
    results = list(
        _result_queryset(user).filter(qc_status=Result.QC_APPROVED)[:100]
    )
    if not results:
        return _error("No accessible results are approved.")
    lines = [f"{len(results)} accessible result(s) are approved:"]
    lines.extend(f"- {_result_label(result)}" for result in results)
    return {
        "answer": "\n".join(lines),
        "links": [_result_link(result) for result in results[:20]],
        "context": {"result_ids": [result.id for result in results]},
        "skip_llm": True,
    }


def _read_awaiting_approval(message, user):
    if not re.search(r"\bresults?\b.*\bawaiting\s+approval\b", message, re.I):
        return None
    results = list(
        _result_queryset(user).filter(
            qc_status__in=[Result.QC_PENDING_REVIEW, Result.QC_REOPENED]
        )[:100]
    )
    if not results:
        return _error("No accessible results are awaiting approval.")
    lines = [f"{len(results)} accessible result(s) are awaiting approval:"]
    lines.extend(f"- {_result_label(result)}" for result in results)
    return {
        "answer": "\n".join(lines),
        "links": [_result_link(result) for result in results[:20]],
        "context": {"result_ids": [result.id for result in results]},
        "skip_llm": True,
    }


def _read_failure_reason(message, user):
    if not re.search(r"\bwhy\b.*\bresult\b.*\bfail(?:ed)?\s+QC\b", message, re.I):
        return None
    result_id = _result_id_from_message(message)
    if not result_id:
        return _error(
            _result_request_help(
                user,
                "Tell me the result ID.",
                "Why did result {result} fail QC?",
                failed_only=True,
            )
        )
    result, error = _get_result(result_id, user)
    if error:
        return _error(error)
    reason = result.qc_failure_reason or (
        f"the value is {result.reference_comparison} its configured reference range"
        if result.reference_comparison in {"below", "above"}
        else "no failure reason is recorded"
    )
    return {
        "answer": f"{_format_result(result)}\nFailure reason: {reason}",
        "links": [_result_link(result)],
        "context": {"result_id": result.id, "result_ids": [result.id]},
        "skip_llm": True,
    }


def _read_reference_comparison(message, user, context):
    if not re.search(r"\bcompare\b.*\breference\s+range\b", message, re.I):
        return None
    result_id = _result_id_from_message(message) or context.get("result_id")
    if not result_id:
        return _error(
            _result_request_help(
                user,
                "Tell me which result to compare.",
                "Compare result {result} with its reference range",
            )
        )
    result, error = _get_result(int(result_id), user)
    if error:
        return _error(error)
    return {
        "answer": _format_result(result),
        "links": [_result_link(result)],
        "context": {"result_id": result.id, "result_ids": [result.id]},
        "skip_llm": True,
    }


def _audit_denied(user, operation, result_ids, reason):
    for result_id in result_ids or ["unknown"]:
        Event.objects.create(
            entity_type="Result",
            entity_id=str(result_id),
            action="QC_AUTHORIZATION_DENIED",
            actor=user,
            payload={
                "operation": operation,
                "reason": reason,
                "source": "assistant",
            },
        )


def _propose_review_decision(message, user):
    match = re.search(r"\b(approve|reject|reopen)\s+results?\b", message, re.I)
    if not match:
        return None
    operation = match.group(1).upper()
    result_ids = _result_ids_from_range(message)
    if not result_ids:
        return _error("Tell me which result or result range to review.")
    if len(result_ids) > assistant_bulk_max_records():
        return _error(
            f"That range exceeds the configured assistant maximum of {assistant_bulk_max_records()}."
        )
    reason = _reason_from_message(message)
    if not reason:
        return _error(
            f"{operation.title()} requires an explicit reason or comment. "
            f"For example: {operation.title()} result R-{result_ids[0]} because the control passed."
        )
    if not is_qc_reviewer(user):
        denial = "Only QC reviewers or admins can approve, reject, or reopen results."
        _audit_denied(user, operation, result_ids, denial)
        return _error(denial)

    found = {
        result.id: result for result in _result_queryset(user).filter(id__in=result_ids)
    }
    included = []
    excluded = []
    settings_obj = SystemSettings.load()
    for result_id in result_ids:
        result = found.get(result_id)
        if not result:
            excluded.append(
                {
                    "id": result_id,
                    "label": f"R-{result_id}",
                    "reason": "not found or inaccessible",
                }
            )
            continue
        if operation in {"APPROVE", "REJECT"} and result.qc_status not in {
            Result.QC_PENDING_REVIEW,
            Result.QC_REOPENED,
        }:
            excluded.append(
                {
                    "id": result.id,
                    "label": _result_label(result),
                    "reason": f"current state is {result.qc_status}",
                }
            )
            continue
        if operation == "REOPEN" and result.qc_status not in {
            Result.QC_APPROVED,
            Result.QC_REJECTED,
        }:
            excluded.append(
                {
                    "id": result.id,
                    "label": _result_label(result),
                    "reason": "only approved or rejected results can be reopened",
                }
            )
            continue
        if (
            operation == "APPROVE"
            and settings_obj.qc_separation_of_duties
            and result.entered_by_id == user.id
        ):
            _audit_denied(
                user,
                operation,
                [result.id],
                "separation of duties prevents self-approval",
            )
            excluded.append(
                {
                    "id": result.id,
                    "label": _result_label(result),
                    "reason": "separation of duties prevents the result entrant from approving it",
                }
            )
            continue
        included.append(result)

    if not included:
        return _error("No results are eligible for that QC operation.")
    target_status = {
        "APPROVE": Result.QC_APPROVED,
        "REJECT": Result.QC_REJECTED,
        "REOPEN": Result.QC_REOPENED,
    }[operation]
    warnings = []
    if operation == "APPROVE" and any(result.qc_passed is False for result in included):
        warnings.append(
            "One or more results failed automated QC. The reviewer must make the approval decision."
        )
    return _proposal(
        user,
        operation,
        included,
        lambda result: {"qc_status": target_status, "reason": reason},
        reason=reason,
        excluded=excluded,
        warnings=warnings,
    )


def _propose_flag(message, user):
    if not re.search(r"\bflag\s+result\b.*\bfor\s+review\b", message, re.I):
        return None
    result_id = _result_id_from_message(message)
    if not result_id:
        return _error(
            _result_request_help(
                user,
                "Tell me which result to flag.",
                "Flag result {result} for review",
            )
        )
    result, error = _get_result(result_id, user)
    if error:
        return _error(error)
    if not (is_admin(user) or is_tech(user) or is_qc_reviewer(user)):
        return _error("Only tech, QC reviewer, or admin users can flag a result.")
    if not user_can_modify_sample(user, result.work_item.sample) and not is_qc_reviewer(
        user
    ):
        return _error("You can view this result but cannot change its QC workflow.")
    if result.qc_status in {Result.QC_APPROVED, Result.QC_REJECTED}:
        return _error(
            "Approved or rejected results must be explicitly reopened with a reason."
        )
    return _proposal(
        user,
        "FLAG_FOR_REVIEW",
        [result],
        lambda _result: {"qc_status": Result.QC_PENDING_REVIEW},
    )


def _propose_assign_failed(message, user):
    match = re.search(r"\bassign\s+failed\s+QC\s+results?\s+to\s+(.+)$", message, re.I)
    if not match:
        return None
    if not (is_admin(user) or is_tech(user) or is_qc_reviewer(user)):
        return _error("Only tech, QC reviewer, or admin users can assign QC work.")
    username = match.group(1).strip().rstrip(".")
    candidates = list(
        get_user_model()
        .objects.filter(is_active=True)
        .filter(username__iexact=username)[:2]
    )
    if not candidates:
        candidates = list(
            get_user_model()
            .objects.filter(is_active=True)
            .filter(first_name__iexact=username)[:3]
        )
    if len(candidates) != 1:
        return _error(
            f"Could not uniquely resolve active user {username}. Use the exact username."
        )
    target = candidates[0]
    if not is_qc_reviewer(target):
        return _error(f"{target.username} is not an authorized QC reviewer.")
    results = list(
        _result_queryset(user)
        .filter(qc_passed=False)
        .exclude(qc_assigned_to=target)[: assistant_bulk_max_records() + 1]
    )
    if len(results) > assistant_bulk_max_records():
        return _error(
            f"The match exceeds the configured assistant maximum of {assistant_bulk_max_records()}."
        )
    if not results:
        return _error("No accessible failed QC results need that assignment.")
    proposal = _proposal(
        user,
        "ASSIGN_QC",
        results,
        lambda _result: {"qc_assigned_to": target.username},
    )
    proposal["pending_action"]["payload"]["target_user_id"] = target.id
    return proposal


def route_qc_operations(message, user, context=None):
    text = str(message or "").strip()
    lower = text.lower()
    context = context or {}
    if any(term in lower for term in ["investigate", "investigation", "root cause"]):
        return None
    for router in [_propose_review_decision, _propose_flag, _propose_assign_failed]:
        result = router(text, user)
        if result:
            return result
    for router in [
        _read_failed_this_week,
        _read_failure_reason,
        _read_samples_needing_qc,
        _read_samples_failed_qc,
        _read_results_needing_qc,
        _read_failed_results,
        _read_approved_results,
        _read_awaiting_approval,
    ]:
        result = router(text, user)
        if result:
            return result
    return _read_reference_comparison(text, user, context)


def _snapshot_matches(result, snapshot):
    current = _result_snapshot(result)
    return all(current.get(key) == snapshot.get(key) for key in current)


def _audit_result(action, result, event_action, before, after, reason):
    Event.objects.create(
        entity_type="Result",
        entity_id=str(result.id),
        action=event_action,
        actor=action.requested_by,
        payload={
            "result_id": result.id,
            "sample_id": result.work_item.sample_id,
            "sample_code": result.work_item.sample.sample_id,
            "project_id": result.work_item.sample.project_id,
            "before": before,
            "after": after,
            "reason": reason,
            "assistant_action_id": str(action.id),
            "idempotency_key": str(action.idempotency_key),
            "source": "assistant_confirmation",
        },
    )


def execute_qc_review(action):
    payload = action.payload or {}
    operation = payload.get("operation")
    supported = {"FLAG_FOR_REVIEW", "ASSIGN_QC", "APPROVE", "REJECT", "REOPEN"}
    if operation not in supported:
        raise ValueError("Unsupported QC operation.")
    result_ids = [int(value) for value in payload.get("result_ids") or []]
    if len(result_ids) > assistant_bulk_max_records():
        raise ValueError("The frozen QC result set exceeds the configured maximum.")
    if len(result_ids) != len(set(result_ids)):
        raise ValueError("The frozen QC result set contains duplicate IDs.")
    if operation in {"APPROVE", "REJECT", "REOPEN"} and not is_qc_reviewer(
        action.requested_by
    ):
        _audit_denied(
            action.requested_by,
            operation,
            result_ids,
            "confirmation requires the QC reviewer role",
        )
        raise PermissionDenied(
            "Only QC reviewers or admins can confirm this operation."
        )

    reason = str(payload.get("reason") or "").strip()
    if operation in {"APPROVE", "REJECT", "REOPEN"} and not reason:
        raise ValueError("An explicit QC reason or comment is required.")
    target = None
    if operation == "ASSIGN_QC":
        target = (
            get_user_model()
            .objects.filter(id=payload.get("target_user_id"), is_active=True)
            .first()
        )
        if not target or not is_qc_reviewer(target):
            raise ValueError("The selected QC reviewer is no longer eligible.")

    succeeded = []
    failed = []
    snapshots = payload.get("snapshots") or {}
    settings_obj = SystemSettings.load()
    for result_id in result_ids:
        try:
            with transaction.atomic():
                result = Result.objects.select_for_update().filter(id=result_id).first()
                if not result:
                    raise ValueError("record no longer exists")
                result = Result.objects.select_related(
                    "work_item__sample__project",
                    "qc_assigned_to",
                    "qc_reviewed_by",
                    "entered_by",
                ).get(id=result_id)
                allowed = (
                    _result_queryset(action.requested_by).filter(id=result_id).exists()
                )
                if not allowed:
                    raise PermissionDenied("result is no longer accessible")
                if not _snapshot_matches(result, snapshots.get(str(result_id)) or {}):
                    raise ValueError(
                        "record changed after preview; no update was applied"
                    )
                if operation in {"APPROVE", "REJECT", "REOPEN"}:
                    if operation in {"APPROVE", "REJECT"} and result.qc_status not in {
                        Result.QC_PENDING_REVIEW,
                        Result.QC_REOPENED,
                    }:
                        raise ValueError(
                            f"current state {result.qc_status} cannot be reviewed"
                        )
                    if operation == "REOPEN" and result.qc_status not in {
                        Result.QC_APPROVED,
                        Result.QC_REJECTED,
                    }:
                        raise ValueError(
                            "only approved or rejected results can be reopened"
                        )
                    if (
                        operation == "APPROVE"
                        and settings_obj.qc_separation_of_duties
                        and result.entered_by_id == action.requested_by_id
                    ):
                        raise PermissionDenied(
                            "separation of duties prevents the result entrant from approving it"
                        )

                before = _result_snapshot(result)
                if operation == "FLAG_FOR_REVIEW":
                    if result.qc_status in {Result.QC_APPROVED, Result.QC_REJECTED}:
                        raise ValueError(
                            "approved or rejected results must be reopened"
                        )
                    result.qc_status = Result.QC_PENDING_REVIEW
                    event_action = "QC_FLAGGED_FOR_REVIEW"
                    fields = ["qc_status", "updated_at"]
                elif operation == "ASSIGN_QC":
                    result.qc_assigned_to = target
                    event_action = "QC_ASSIGNED"
                    fields = ["qc_assigned_to", "updated_at"]
                else:
                    result.qc_status = {
                        "APPROVE": Result.QC_APPROVED,
                        "REJECT": Result.QC_REJECTED,
                        "REOPEN": Result.QC_REOPENED,
                    }[operation]
                    result.qc_reviewed_by = action.requested_by
                    result.qc_reviewed_at = timezone.now()
                    result.qc_review_note = reason
                    event_action = {
                        "APPROVE": "QC_RESULT_APPROVED",
                        "REJECT": "QC_RESULT_REJECTED",
                        "REOPEN": "QC_RESULT_REOPENED",
                    }[operation]
                    fields = [
                        "qc_status",
                        "qc_reviewed_by",
                        "qc_reviewed_at",
                        "qc_review_note",
                        "updated_at",
                    ]
                result.save(update_fields=fields)
                after = _result_snapshot(result)
                _audit_result(action, result, event_action, before, after, reason)
                succeeded.append({"id": result.id, "label": _result_label(result)})
        except PermissionDenied as exc:
            _audit_denied(action.requested_by, operation, [result_id], str(exc))
            failed.append(
                {"id": result_id, "label": f"R-{result_id}", "reason": str(exc)}
            )
        except (ValidationError, ValueError) as exc:
            failed.append(
                {"id": result_id, "label": f"R-{result_id}", "reason": str(exc)}
            )

    return {
        "operation": operation,
        "frozen_result_ids": result_ids,
        "requested_count": len(result_ids),
        "succeeded_count": len(succeeded),
        "failed_count": len(failed),
        "succeeded": succeeded,
        "failed": failed,
        "context": {"result_ids": [row["id"] for row in succeeded]},
    }
