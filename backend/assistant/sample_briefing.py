"""Recorded work and result evidence for an already authorized sample."""

from django.db.models import Count, Q
from django.utils import timezone

from results.models import Result, WorkItem


RECENT_RESULT_LIMIT = 5


def sample_briefing(sample):
    unfinished = ~Q(status__in=[WorkItem.STATUS_COMPLETED, WorkItem.STATUS_CANCELLED])
    work = sample.work_items.aggregate(
        total=Count("pk"),
        unfinished=Count("pk", filter=unfinished),
        overdue=Count("pk", filter=unfinished & Q(due_at__lt=timezone.now())),
        unassigned=Count("pk", filter=unfinished & Q(assigned_to__isnull=True)),
        failed=Count("pk", filter=unfinished & Q(status=WorkItem.STATUS_FAILED)),
        qc_review=Count("pk", filter=unfinished & Q(
            qc_status__in=[WorkItem.QC_REJECTED, WorkItem.QC_RERUN_REQUIRED]
        )),
    )
    results = Result.objects.filter(work_item__sample=sample)
    totals = results.aggregate(
        total=Count("pk"),
        failed_checks=Count("pk", filter=Q(qc_passed=False)),
        awaiting_review=Count("pk", filter=Q(
            qc_status__in=[Result.QC_PENDING_REVIEW, Result.QC_REOPENED]
        )),
        rejected=Count("pk", filter=Q(qc_status=Result.QC_REJECTED)),
    )
    recent = [
        {
            "id": result.pk,
            "key": result.key,
            "value": result.value,
            "unit": result.unit,
            "work_item": result.work_item.name,
            "qc_passed": result.qc_passed,
            "qc_status": result.qc_status,
            "created_at": result.created_at.isoformat(),
        }
        for result in results.select_related("work_item").order_by("-created_at", "-pk")[:RECENT_RESULT_LIMIT]
    ]
    return {"work": work, "results": totals, "recent_results": recent}


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
            "",
            f"Most recently recorded results (showing {len(briefing['recent_results'])} "
            f"of {results['total']}, newest first):",
        ])
        for result in briefing["recent_results"]:
            value = "not recorded" if result["value"] in (None, "") else str(result["value"])
            if result["unit"] and result["value"] not in (None, ""):
                value += f" {result['unit']}"
            check = {True: "passed", False: "failed", None: "not evaluated"}[result["qc_passed"]]
            lines.append(
                f"- R-{result['id']} / {result['key']} ({result['work_item']}): {value}; "
                f"QC check: {check}; review: {result['qc_status']}; recorded: {result['created_at']}"
            )
    else:
        lines.append("No results are recorded for this sample; QC outcome is unknown.")

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
