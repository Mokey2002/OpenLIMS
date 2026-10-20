"""Recorded work and result evidence for an already authorized sample."""

import math

from django.db.models import Case, Count, F, IntegerField, Q, Value, When
from django.utils import timezone

from results.models import Result, WorkItem


RECENT_RESULT_LIMIT = 5
ATTENTION_LIMIT = 3
REASON_LIMIT = 240


def _result_evidence(result):
    value = result.value
    invalid_value = isinstance(value, float) and not math.isfinite(value)
    invalid_limits = any(
        limit is not None and not math.isfinite(limit)
        for limit in [result.reference_min, result.reference_max]
    ) or (
        result.reference_min is not None and result.reference_max is not None
        and result.reference_min > result.reference_max
    )
    return {
        "id": result.pk,
        "key": result.key,
        "value": None if invalid_value else value,
        "value_invalid": invalid_value,
        "unit": result.unit,
        "work_item": result.work_item.name,
        "qc_passed": result.qc_passed,
        "qc_status": result.qc_status,
        "created_at": result.created_at.isoformat(),
        "reference_min": None if invalid_limits else result.reference_min,
        "reference_max": None if invalid_limits else result.reference_max,
        "reference_comparison": (
            "invalid_limits" if invalid_limits else "not_numeric" if invalid_value
            else result.reference_comparison
        ),
        "qc_failure_reason": result.qc_failure_reason[:REASON_LIMIT],
        "qc_failure_reason_truncated": len(result.qc_failure_reason) > REASON_LIMIT,
        "qc_review_note": result.qc_review_note[:REASON_LIMIT],
        "qc_review_note_truncated": len(result.qc_review_note) > REASON_LIMIT,
    }


def sample_briefing(sample):
    now = timezone.now()
    unfinished = ~Q(status__in=[WorkItem.STATUS_COMPLETED, WorkItem.STATUS_CANCELLED])
    work_failure = Q(status=WorkItem.STATUS_FAILED) | Q(
        qc_status__in=[WorkItem.QC_REJECTED, WorkItem.QC_RERUN_REQUIRED]
    )
    overdue = Q(due_at__lt=now)
    work_flags = unfinished & (work_failure | overdue | Q(assigned_to__isnull=True))
    work = sample.work_items.aggregate(
        total=Count("pk"),
        unfinished=Count("pk", filter=unfinished),
        overdue=Count("pk", filter=unfinished & overdue),
        unassigned=Count("pk", filter=unfinished & Q(assigned_to__isnull=True)),
        failed=Count("pk", filter=unfinished & Q(status=WorkItem.STATUS_FAILED)),
        qc_review=Count("pk", filter=unfinished & Q(
            qc_status__in=[WorkItem.QC_REJECTED, WorkItem.QC_RERUN_REQUIRED]
        )),
        flagged=Count("pk", filter=work_flags),
    )
    work_total = work.pop("flagged")
    work_items = []
    for item in sample.work_items.filter(work_flags).select_related("assigned_to").order_by(
        Case(When(work_failure, then=Value(0)), When(overdue, then=Value(1)),
             default=Value(2), output_field=IntegerField()),
        F("due_at").asc(nulls_last=True), "pk",
    )[:ATTENTION_LIMIT]:
        reasons = []
        if item.status == WorkItem.STATUS_FAILED:
            reasons.append("work failed")
        if item.qc_status in [WorkItem.QC_REJECTED, WorkItem.QC_RERUN_REQUIRED]:
            reasons.append(f"QC {item.qc_status}")
        if item.due_at and item.due_at < now:
            reasons.append("overdue")
        if item.assigned_to_id is None:
            reasons.append("unassigned")
        work_items.append({
            "id": item.pk, "name": item.name, "status": item.status,
            "assigned_to": item.assigned_to.username if item.assigned_to else None,
            "due_at": item.due_at.isoformat() if item.due_at else None,
            "reasons": reasons,
        })
    results = Result.objects.filter(work_item__sample=sample)
    result_failure = Q(qc_passed=False) | Q(qc_status=Result.QC_REJECTED)
    result_flags = result_failure | Q(qc_status__in=[Result.QC_PENDING_REVIEW, Result.QC_REOPENED])
    totals = results.aggregate(
        total=Count("pk"),
        failed_checks=Count("pk", filter=Q(qc_passed=False)),
        awaiting_review=Count("pk", filter=Q(
            qc_status__in=[Result.QC_PENDING_REVIEW, Result.QC_REOPENED]
        )),
        rejected=Count("pk", filter=Q(qc_status=Result.QC_REJECTED)),
        flagged=Count("pk", filter=result_flags),
    )
    result_total = totals.pop("flagged")
    recent = [
        _result_evidence(result)
        for result in results.select_related("work_item").order_by("-created_at", "-pk")[:RECENT_RESULT_LIMIT]
    ]
    priority_results = [
        _result_evidence(result)
        for result in results.filter(result_flags).select_related("work_item").order_by(
            Case(When(result_failure, then=Value(0)), default=Value(1), output_field=IntegerField()),
            "created_at", "pk",
        )[:ATTENTION_LIMIT]
    ]
    return {
        "work": work, "results": totals, "recent_results": recent,
        "attention": {"work_items": work_items, "work_total": work_total,
                      "results": priority_results, "result_total": result_total},
    }


def _result_line(result):
    value = (
        "invalid numeric value recorded" if result["value_invalid"] else
        "not recorded" if result["value"] in (None, "") else str(result["value"])
    )
    if result["unit"] and result["value"] not in (None, ""):
        value += f" {result['unit']}"
    check = {True: "passed", False: "failed", None: "not evaluated"}[result["qc_passed"]]
    return (
        f"- R-{result['id']} / {result['key']} ({result['work_item']}): {value}; "
        f"QC check: {check}; review: {result['qc_status']}; recorded: {result['created_at']}"
    )


def _reference_evidence(result):
    low, high = result["reference_min"], result["reference_max"]
    if result["reference_comparison"] == "invalid_limits":
        return "Configured reference limits are invalid; comparison is unavailable."
    if low is None and high is None:
        return "Reference range not configured."
    unit = f" {result['unit']}" if result["unit"] else ""
    if low is None:
        limits = f"at most {high}{unit}"
    elif high is None:
        limits = f"at least {low}{unit}"
    else:
        limits = f"{low} to {high}{unit} (inclusive)"
    comparison = {
        "below": "below the configured minimum",
        "above": "above the configured maximum",
        "within": "within the configured limits",
        "not_numeric": "no numeric value to compare",
    }.get(result["reference_comparison"], "comparison unavailable")
    return f"Configured reference: {limits}; {comparison}."


def _attention_lines(attention):
    lines = []
    if attention["work_total"]:
        lines.extend(["", f"Work needing attention (showing {len(attention['work_items'])} "
                      f"of {attention['work_total']}; failures/QC flags first, then deadlines):"])
        for item in attention["work_items"]:
            lines.append(
                f"- Work #{item['id']} / {item['name']}: {', '.join(item['reasons'])}; "
                f"owner: {item['assigned_to'] or 'Unassigned'}; "
                f"due: {item['due_at'] or 'no deadline recorded'}"
            )
    if attention["result_total"]:
        lines.extend(["", f"Results needing attention (showing {len(attention['results'])} "
                      f"of {attention['result_total']}; failed/rejected first, oldest first within each group):"])
        for result in attention["results"]:
            lines.append(_result_line(result))
            if result["qc_failure_reason"]:
                excerpt = " (excerpt)" if result["qc_failure_reason_truncated"] else ""
                lines.append(f"  Recorded QC reason{excerpt}: {result['qc_failure_reason']}")
            elif result["qc_passed"] is False:
                lines.append("  No QC failure reason is recorded.")
            if result["qc_review_note"]:
                excerpt = " (excerpt)" if result["qc_review_note_truncated"] else ""
                lines.append(f"  Recorded review note{excerpt}: {result['qc_review_note']}")
            elif result["qc_status"] == Result.QC_REJECTED:
                lines.append("  No QC review note is recorded.")
            lines.append("  " + _reference_evidence(result))
    return lines


def briefing_suggestions(sample_code, briefing):
    suggestions = []
    if briefing["attention"]["results"]:
        result = briefing["attention"]["results"][0]
        if result["qc_passed"] is False:
            suggestions.append(f"Why did result R-{result['id']} fail QC?")
        if result["reference_comparison"] in {"below", "within", "above"}:
            suggestions.append(f"Compare result R-{result['id']} with its reference range")
    return suggestions + [
        f"What next for sample {sample_code}?",
        f"What happened to sample {sample_code}?",
    ]


def briefing_lines(briefing):
    work, results = briefing["work"], briefing["results"]
    lines = [
        "",
        f"Work: {work['unfinished']} unfinished, {work['overdue']} overdue, "
        f"{work['unassigned']} unassigned, {work['failed']} failed, "
        f"{work['qc_review']} rejected or requiring a rerun.",
        "Work attention counts exclude completed/cancelled items and may overlap.",
    ]
    if results["total"]:
        lines.extend([
            f"Results: {results['total']} recorded, {results['failed_checks']} with failed QC checks, "
            f"{results['awaiting_review']} awaiting review, {results['rejected']} rejected.",
            "QC check outcomes and review decisions are separate; counts may overlap. "
            "Results include completed/cancelled work and may be historical.",
        ])
    else:
        lines.append("No results are recorded for this sample; QC outcome is unknown.")

    lines.extend(_attention_lines(briefing["attention"]))
    if results["total"]:
        lines.extend([
            "", f"Most recently recorded results (showing {len(briefing['recent_results'])} "
            f"of {results['total']}, newest first):",
        ])
        lines.extend(_result_line(result) for result in briefing["recent_results"])

    next_steps = []
    if results["failed_checks"] or results["rejected"] or work["failed"] or work["qc_review"]:
        next_steps.append("review the recorded failures and QC decisions")
    if results["awaiting_review"]:
        next_steps.append("have an authorized reviewer assess pending or reopened results")
    if work["overdue"]:
        next_steps.append("review overdue work")
    if work["unassigned"]:
        next_steps.append("check who should own the unassigned work")
    if next_steps:
        lines.extend(["", "Next: " + "; ".join(next_steps) + "."])
    else:
        lines.extend(["", "Next: check the sample's workflow guidance and history. "
                      "These recorded counts do not establish that the sample is ready for release."])
    return lines
