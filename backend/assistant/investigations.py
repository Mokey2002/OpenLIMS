import math
import re
from collections import defaultdict
from datetime import timedelta
from statistics import mean, median, pstdev

from django.db.models import Q
from django.utils import timezone

from events.models import Event
from imports.models import ImportJob
from inventory.models import InventoryLot, InventoryReservation
from results.models import Result, WorkItem
from samples.access import get_sample_access_queryset
from samples.models import Sample


MAX_COHORT_SAMPLES = 250
MAX_TIMELINE_EVENTS = 100


def _safe_days(value, default=90):
    try:
        return min(max(int(value or default), 1), 3650)
    except (TypeError, ValueError):
        return default


def _accessible_samples(user):
    return get_sample_access_queryset(
        Sample.objects.select_related(
            "project",
            "batch",
            "assigned_to",
            "created_by",
        ),
        user,
    )


def _resolve_subject(spec, user):
    subject_type = str(spec.get("subject_type") or "sample").lower()
    identifier = str(spec.get("identifier") or "").strip()
    samples = _accessible_samples(user)

    if subject_type == "result":
        match = re.search(r"(\d+)$", identifier)
        if not match:
            return None, None
        result = Result.objects.select_related(
            "work_item__sample__project",
            "work_item__sample__batch",
            "entered_by",
        ).filter(id=int(match.group(1))).first()
        if not result or not samples.filter(id=result.work_item.sample_id).exists():
            return None, None
        return result.work_item.sample, result

    sample = samples.filter(sample_id__iexact=identifier).first()
    return sample, None


def _cohort_samples(sample, user, cutoff):
    queryset = _accessible_samples(user)
    if sample.batch_id:
        queryset = queryset.filter(batch_id=sample.batch_id)
        label = f"batch {sample.batch.code}"
    elif sample.project_id:
        queryset = queryset.filter(project_id=sample.project_id)
        label = f"project {sample.project.code}"
    else:
        queryset = queryset.filter(id=sample.id)
        label = "this unassigned sample"
    if cutoff:
        queryset = queryset.filter(Q(created_at__gte=cutoff) | Q(id=sample.id))
    return list(queryset.order_by("created_at", "id")[:MAX_COHORT_SAMPLES]), label


def _display_value(result):
    value = result.value
    if value is None:
        return "—"
    if isinstance(value, float):
        value = round(value, 4)
    return f"{value} {result.unit}".strip()


def _result_row(result, subject_result_id=None):
    comparison = result.reference_comparison
    return {
        "id": result.id,
        "key": result.key,
        "value": result.value,
        "display_value": _display_value(result),
        "unit": result.unit,
        "reference_min": result.reference_min,
        "reference_max": result.reference_max,
        "reference_comparison": comparison,
        "qc_passed": result.qc_passed,
        "qc_status": result.qc_status,
        "qc_failure_reason": result.qc_failure_reason,
        "entered_by": result.entered_by.username if result.entered_by else "",
        "created_at": result.created_at.isoformat(),
        "is_subject_result": result.id == subject_result_id,
    }


def _finding(finding_id, title, detail, severity, confidence, evidence_type, **extra):
    return {
        "id": finding_id,
        "title": title,
        "detail": detail,
        "severity": severity,
        "confidence": confidence,
        "evidence_type": evidence_type,
        **extra,
    }


def _direct_findings(subject_results, subject_result):
    findings = []
    selected = [subject_result] if subject_result else subject_results
    for result in selected:
        if not result:
            continue
        outside_reference = result.reference_comparison in {"above", "below"}
        failed = result.qc_passed is False or result.qc_status == Result.QC_REJECTED
        if failed:
            reason = result.qc_failure_reason.strip()
            detail = f"{result.key} is recorded as failed QC at {_display_value(result)}."
            if reason:
                detail += f" Recorded reason: {reason}"
            findings.append(_finding(
                f"result-{result.id}-qc",
                f"QC failure: {result.key}",
                detail,
                "high",
                "high",
                "direct",
                result_id=result.id,
            ))
        if outside_reference:
            boundary = result.reference_max if result.reference_comparison == "above" else result.reference_min
            findings.append(_finding(
                f"result-{result.id}-reference",
                f"{result.key} is {result.reference_comparison} its reference range",
                f"Observed {_display_value(result)}; applicable boundary is {boundary} {result.unit}.".strip(),
                "high" if failed else "medium",
                "high",
                "direct",
                result_id=result.id,
            ))
    return findings


def _numeric_findings(sample, subject_results, cohort_results, subject_result):
    findings = []
    cohort_by_key = defaultdict(list)
    for result in cohort_results:
        if result.work_item.sample_id == sample.id:
            continue
        if result.value_type == Result.VALUE_TYPE_NUMBER and result.value_number is not None:
            cohort_by_key[result.key.lower()].append(result.value_number)

    selected = [subject_result] if subject_result else subject_results
    for result in selected:
        if not result or result.value_type != Result.VALUE_TYPE_NUMBER or result.value_number is None:
            continue
        peers = cohort_by_key[result.key.lower()]
        if len(peers) < 2:
            continue
        peer_median = median(peers)
        peer_mean = mean(peers)
        deviation = result.value_number - peer_median
        standard_deviation = pstdev(peers) if len(peers) > 1 else 0
        z_score = deviation / standard_deviation if standard_deviation else None
        unusual = abs(z_score) >= 2 if z_score is not None else (
            peer_median != 0 and abs(deviation / peer_median) >= 0.5
        )
        if unusual:
            z_text = f" (z-score {z_score:.2f})" if z_score is not None else ""
            findings.append(_finding(
                f"result-{result.id}-cohort",
                f"{result.key} differs from its peer cohort",
                (
                    f"Observed {_display_value(result)} versus peer median {peer_median:.4g} "
                    f"{result.unit} across {len(peers)} other samples{z_text}."
                ).strip(),
                "high" if abs(z_score or 0) >= 3 else "medium",
                "high" if len(peers) >= 5 else "medium",
                "comparative",
                result_id=result.id,
                peer_count=len(peers),
                peer_mean=round(peer_mean, 6),
                peer_median=round(peer_median, 6),
                z_score=round(z_score, 4) if z_score is not None and math.isfinite(z_score) else None,
            ))
    return findings


def _workflow_evidence(sample, cohort_samples):
    now = timezone.now()
    subject_work = list(
        WorkItem.objects.filter(sample=sample)
        .select_related("assigned_to", "created_by", "reviewed_by")
        .order_by("created_at", "id")
    )
    peer_ages = [
        max((now - other.created_at).total_seconds() / 86400, 0)
        for other in cohort_samples
        if other.id != sample.id
    ]
    sample_age = max((now - sample.created_at).total_seconds() / 86400, 0)
    peer_median_age = median(peer_ages) if peer_ages else None
    rows = []
    findings = []
    for work in subject_work:
        overdue = bool(
            work.due_at
            and work.due_at < now
            and work.status in {WorkItem.STATUS_PENDING, WorkItem.STATUS_IN_PROGRESS}
        )
        rows.append({
            "id": work.id,
            "name": work.name,
            "work_type": work.work_type,
            "status": work.status,
            "qc_status": work.qc_status,
            "assigned_to": work.assigned_to.username if work.assigned_to else "",
            "due_at": work.due_at.isoformat() if work.due_at else None,
            "overdue": overdue,
            "created_at": work.created_at.isoformat(),
            "updated_at": work.updated_at.isoformat(),
        })
        if overdue:
            overdue_days = max((now - work.due_at).total_seconds() / 86400, 0)
            findings.append(_finding(
                f"work-{work.id}-overdue",
                f"Overdue work: {work.name}",
                f"This {work.work_type} work item is {overdue_days:.1f} days overdue and remains {work.status.lower().replace('_', ' ')}.",
                "high",
                "high",
                "direct",
                work_item_id=work.id,
            ))
        if work.status == WorkItem.STATUS_FAILED:
            findings.append(_finding(
                f"work-{work.id}-failed",
                f"Failed workflow step: {work.name}",
                f"The {work.work_type} work item is recorded as failed.",
                "high",
                "high",
                "direct",
                work_item_id=work.id,
            ))
    if peer_median_age and sample_age > max(peer_median_age * 1.5, peer_median_age + 2):
        findings.append(_finding(
            "sample-age-cohort",
            "Sample has remained in the workflow longer than peers",
            f"Sample age is {sample_age:.1f} days versus a peer median of {peer_median_age:.1f} days.",
            "medium",
            "medium" if len(peer_ages) < 5 else "high",
            "comparative",
            peer_count=len(peer_ages),
        ))
    return rows, findings, {
        "sample_age_days": round(sample_age, 2),
        "peer_median_age_days": round(peer_median_age, 2) if peer_median_age is not None else None,
    }


def _reagent_context(sample, cutoff):
    if not sample.project_id:
        return []
    reservations = InventoryReservation.objects.filter(
        project_id=sample.project_id,
        lot__item__category="REAGENT",
    ).select_related("lot__item", "created_by")
    if cutoff:
        reservations = reservations.filter(created_at__gte=cutoff)
    rows = []
    today = timezone.localdate()
    for reservation in reservations.order_by("-created_at", "id")[:100]:
        lot = reservation.lot
        expired = bool(lot.expiration_date and lot.expiration_date < today)
        rows.append({
            "reservation_id": reservation.id,
            "item_code": lot.item.code,
            "item_name": lot.item.name,
            "lot_code": lot.lot_code,
            "lot_status": lot.status,
            "expiration_date": lot.expiration_date.isoformat() if lot.expiration_date else None,
            "expired": expired,
            "quantity": float(reservation.quantity),
            "unit": reservation.unit,
            "reservation_status": reservation.status,
            "created_at": reservation.created_at.isoformat(),
        })
    return rows


def _instrument_context(sample, cutoff):
    direct_job_ids = set(
        WorkItem.objects.filter(
            sample=sample,
            source_import_job__isnull=False,
        ).values_list("source_import_job_id", flat=True)
    )
    legacy_job_ids = set()
    for name, notes in WorkItem.objects.filter(
        sample=sample,
        source_import_job__isnull=True,
    ).values_list("name", "notes"):
        for text in [name, notes]:
            match = re.search(r"Import Job\s+#?(\d+)", str(text or ""), re.IGNORECASE)
            if match:
                legacy_job_ids.add(int(match.group(1)))
    for payload in Event.objects.filter(
        entity_type__iexact="Sample",
        entity_id=str(sample.id),
    ).values_list("payload", flat=True):
        job_id = (payload or {}).get("import_job_id")
        try:
            if job_id:
                legacy_job_ids.add(int(job_id))
        except (TypeError, ValueError):
            continue
    all_linked_job_ids = direct_job_ids | legacy_job_ids
    job_scope = Q(id__in=all_linked_job_ids)
    if sample.project_id:
        job_scope |= Q(project_id=sample.project_id)
    jobs = ImportJob.objects.filter(job_scope).select_related(
        "instrument", "uploaded_by"
    )
    if cutoff:
        jobs = jobs.filter(Q(created_at__gte=cutoff) | Q(id__in=all_linked_job_ids))
    return [{
        "id": job.id,
        "instrument_code": job.instrument.code,
        "instrument_name": job.instrument.name,
        "run_id": job.run_id or "",
        "status": job.status,
        "uploaded_by": job.uploaded_by.username if job.uploaded_by else "",
        "created_at": job.created_at.isoformat(),
        "summary": job.summary,
        "direct_sample_link": job.id in all_linked_job_ids,
        "provenance_source": (
            "database_relation"
            if job.id in direct_job_ids
            else "legacy_audit_or_text"
            if job.id in legacy_job_ids
            else "project_time_context"
        ),
    } for job in jobs.order_by("-created_at", "id")[:100]]


def _context_findings(reagent_rows, instrument_rows):
    findings = []
    concerning_lots = [
        row for row in reagent_rows
        if row["expired"] or row["lot_status"] in {InventoryLot.STATUS_EXPIRED, InventoryLot.STATUS_DEPLETED}
    ]
    if concerning_lots:
        labels = ", ".join(sorted({row["lot_code"] for row in concerning_lots})[:5])
        findings.append(_finding(
            "reagent-context",
            "Reagent lot context needs review",
            f"Project reservations include expired or depleted lot(s): {labels}. No record directly links these lots to this sample.",
            "medium",
            "low",
            "contextual",
        ))
    linked_jobs = [row for row in instrument_rows if row["direct_sample_link"]]
    if linked_jobs:
        labels = ", ".join(sorted({
            f"{row['instrument_code']} / {row['run_id'] or 'job ' + str(row['id'])}"
            for row in linked_jobs
        })[:5])
        findings.append(_finding(
            "instrument-provenance",
            "Instrument import provenance identified",
            f"This sample has results recorded through {labels}. This proves data provenance, not that the instrument caused the QC outcome.",
            "low",
            "high",
            "direct",
        ))
    failed_jobs = [row for row in instrument_rows if row["status"] == "FAILED"]
    if failed_jobs:
        labels = ", ".join(sorted({row["instrument_code"] for row in failed_jobs})[:5])
        findings.append(_finding(
            "instrument-context",
            "Failed instrument imports occurred in the project window",
            f"Failed import jobs were recorded for {labels}. Jobs without a direct sample link are project/time context only.",
            "medium",
            "low",
            "contextual",
        ))
    return findings


def _timeline(sample, subject_results, subject_work):
    entity_filters = Q(entity_type__iexact="Sample", entity_id=str(sample.id))
    work_ids = [str(row["id"]) for row in subject_work]
    result_ids = [str(result.id) for result in subject_results]
    if work_ids:
        entity_filters |= Q(entity_type__iexact="WorkItem", entity_id__in=work_ids)
    if result_ids:
        entity_filters |= Q(entity_type__iexact="Result", entity_id__in=result_ids)
    events = Event.objects.filter(entity_filters).select_related("actor").order_by("-timestamp", "-id")[:MAX_TIMELINE_EVENTS]
    rows = [{
        "timestamp": sample.created_at.isoformat(),
        "actor": sample.created_by.username if sample.created_by else "",
        "entity_type": "Sample",
        "entity_id": str(sample.id),
        "action": "CREATED",
        "detail": f"Sample {sample.sample_id} created",
    }]
    for event in events:
        rows.append({
            "timestamp": event.timestamp.isoformat(),
            "actor": event.actor.username if event.actor else "",
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "action": event.action,
            "detail": str(event.payload or {}),
        })
    rows.sort(key=lambda row: row["timestamp"], reverse=True)
    return rows[:MAX_TIMELINE_EVENTS]


def _similar_failures(sample, subject_results, cohort_results, subject_result):
    target_keys = {
        result.key.lower()
        for result in ([subject_result] if subject_result else subject_results)
        if result and (result.qc_passed is False or result.qc_status == Result.QC_REJECTED)
    }
    if not target_keys:
        target_keys = {result.key.lower() for result in subject_results[:5]}
    rows = []
    for result in cohort_results:
        if result.work_item.sample_id == sample.id or result.key.lower() not in target_keys:
            continue
        if result.qc_passed is not False and result.qc_status != Result.QC_REJECTED:
            continue
        rows.append({
            "result_id": result.id,
            "sample_id": result.work_item.sample.sample_id,
            "sample_pk": result.work_item.sample_id,
            "key": result.key,
            "display_value": _display_value(result),
            "qc_status": result.qc_status,
            "failure_reason": result.qc_failure_reason,
            "created_at": result.created_at.isoformat(),
        })
    return rows[:50]


def _chart(group_by, cohort_results, reagent_rows, instrument_rows):
    group_by = group_by if group_by in {"overview", "operator", "workflow", "reagent", "instrument"} else "overview"
    counters = defaultdict(lambda: {"total": 0, "failures": 0})
    x_label = "Result"
    title = "QC failure rate by result"
    note = "Calculated from results in the permission-filtered peer cohort."
    if group_by == "operator":
        x_label = "Operator"
        title = "QC failure rate by result entrant"
        for result in cohort_results:
            label = result.entered_by.username if result.entered_by else "Unrecorded"
            counters[label]["total"] += 1
            counters[label]["failures"] += int(result.qc_passed is False or result.qc_status == Result.QC_REJECTED)
    elif group_by == "workflow":
        x_label = "Work type"
        title = "QC failure rate by work type"
        for result in cohort_results:
            label = result.work_item.work_type
            counters[label]["total"] += 1
            counters[label]["failures"] += int(result.qc_passed is False or result.qc_status == Result.QC_REJECTED)
    elif group_by == "instrument":
        x_label = "Instrument"
        title = "Import job status by instrument (context only)"
        note = "These project-level import jobs are not directly linked to the investigated sample."
        for row in instrument_rows:
            counters[row["instrument_code"]]["total"] += 1
            counters[row["instrument_code"]]["failures"] += int(row["status"] == "FAILED")
    elif group_by == "reagent":
        x_label = "Reagent lot"
        title = "Project reagent reservations (context only)"
        note = "Reservations are project-level and do not prove that a lot was used for this sample."
        for row in reagent_rows:
            counters[row["lot_code"]]["total"] += 1
            counters[row["lot_code"]]["failures"] += int(row["expired"] or row["lot_status"] != InventoryLot.STATUS_ACTIVE)
    else:
        for result in cohort_results:
            counters[result.key]["total"] += 1
            counters[result.key]["failures"] += int(result.qc_passed is False or result.qc_status == Result.QC_REJECTED)

    data = []
    for label, counts in sorted(counters.items(), key=lambda item: (-item[1]["failures"], item[0]))[:20]:
        rate = counts["failures"] * 100 / counts["total"] if counts["total"] else 0
        data.append({"group": label, "total": counts["total"], "failures": counts["failures"], "failure_rate": round(rate, 2)})
    return {
        "chartType": "bar",
        "meta": {"title": title, "description": note},
        "xKey": "group",
        "xAxisLabel": x_label,
        "series": [
            {"dataKey": "failure_rate", "label": "Failure or concern rate (%)", "axisLabel": "Rate (%)", "valueFormat": "percent"},
        ],
        "data": data,
    }


def run_investigation_spec(spec, user):
    normalized = {
        "subject_type": str(spec.get("subject_type") or "sample").lower(),
        "identifier": str(spec.get("identifier") or "").strip(),
        "days": _safe_days(spec.get("days"), 90),
        "result_key": str(spec.get("result_key") or "").strip(),
        "group_by": str(spec.get("group_by") or "overview").lower(),
    }
    sample, subject_result = _resolve_subject(normalized, user)
    if not sample:
        return {
            "answer": "The requested sample or result was not found in your accessible records.",
            "links": [],
            "suggestions": ["Investigate sample S-1042", "Open the Investigation Workbench"],
            "skip_llm": True,
        }

    cutoff = timezone.now() - timedelta(days=normalized["days"])
    cohort_samples, cohort_label = _cohort_samples(sample, user, cutoff)
    cohort_ids = [row.id for row in cohort_samples]
    results_queryset = Result.objects.filter(
        work_item__sample_id__in=cohort_ids,
    ).select_related("work_item__sample", "entered_by", "qc_reviewed_by")
    if normalized["result_key"]:
        results_queryset = results_queryset.filter(key__iexact=normalized["result_key"])
    cohort_results = list(results_queryset.order_by("created_at", "id")[:5000])
    subject_queryset = Result.objects.filter(work_item__sample=sample).select_related(
        "work_item__sample", "entered_by", "qc_reviewed_by"
    )
    if normalized["result_key"]:
        subject_queryset = subject_queryset.filter(key__iexact=normalized["result_key"])
    subject_results = list(subject_queryset.order_by("created_at", "id"))
    if subject_result and subject_result not in subject_results:
        subject_results.append(subject_result)
    cohort_result_ids = {result.id for result in cohort_results}
    cohort_results.extend(
        result for result in subject_results if result.id not in cohort_result_ids
    )

    findings = _direct_findings(subject_results, subject_result)
    findings.extend(_numeric_findings(sample, subject_results, cohort_results, subject_result))
    workflow_rows, workflow_findings, timing = _workflow_evidence(sample, cohort_samples)
    findings.extend(workflow_findings)
    reagent_rows = _reagent_context(sample, cutoff)
    instrument_rows = _instrument_context(sample, cutoff)
    findings.extend(_context_findings(reagent_rows, instrument_rows))
    severity_order = {"high": 0, "medium": 1, "low": 2}
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda row: (severity_order[row["severity"]], confidence_order[row["confidence"]], row["title"]))

    failures = [
        result for result in subject_results
        if result.qc_passed is False or result.qc_status == Result.QC_REJECTED
    ]
    direct_count = sum(1 for row in findings if row["evidence_type"] == "direct")
    comparative_count = sum(1 for row in findings if row["evidence_type"] == "comparative")
    contextual_count = sum(1 for row in findings if row["evidence_type"] == "contextual")
    if findings:
        answer = (
            f"Investigation of {sample.sample_id} found {direct_count} direct, "
            f"{comparative_count} comparative, and {contextual_count} contextual finding(s) "
            f"using {len(cohort_samples)} sample(s) from {cohort_label}."
        )
    else:
        answer = (
            f"No specific failure signal was identified for {sample.sample_id} in the available records. "
            f"The review used {len(cohort_samples)} sample(s) from {cohort_label}."
        )

    investigation = {
        "title": f"Investigation: {sample.sample_id}",
        "subject": {
            "type": normalized["subject_type"],
            "identifier": normalized["identifier"],
            "sample_id": sample.sample_id,
            "sample_pk": sample.id,
            "result_id": subject_result.id if subject_result else None,
            "status": sample.status,
            "project": sample.project.code if sample.project else "",
            "batch": sample.batch.code if sample.batch else "",
            "assigned_to": sample.assigned_to.username if sample.assigned_to else "",
        },
        "scope": {
            "days": normalized["days"],
            "cohort": cohort_label,
            "cohort_sample_count": len(cohort_samples),
            "cohort_result_count": len(cohort_results),
            "result_key": normalized["result_key"],
            "group_by": normalized["group_by"],
        },
        "summary": {
            "subject_result_count": len(subject_results),
            "subject_qc_failures": len(failures),
            "direct_findings": direct_count,
            "comparative_findings": comparative_count,
            "contextual_findings": contextual_count,
            **timing,
        },
        "findings": findings,
        "results": [_result_row(result, subject_result.id if subject_result else None) for result in subject_results],
        "workflow": workflow_rows,
        "similar_failures": _similar_failures(sample, subject_results, cohort_results, subject_result),
        "reagent_context": reagent_rows,
        "instrument_context": instrument_rows,
        "timeline": _timeline(sample, subject_results, workflow_rows),
        "disclaimers": [
            "Findings are decision support, not a causal determination. Review source records before taking corrective action.",
            "Instrument imports generated by the connector are linked through their work-item provenance. Other import jobs and all reagent reservations are project/time context only.",
            "Operator names are shown for traceability, not as evidence of responsibility.",
        ],
        "confidence_legend": {
            "high": "Direct stored evidence or a comparison supported by at least five peers.",
            "medium": "A smaller peer comparison or indirect operational signal.",
            "low": "Contextual association without a direct sample-level link.",
        },
    }
    return {
        "answer": answer,
        "investigation": investigation,
        "chart": _chart(normalized["group_by"], cohort_results, reagent_rows, instrument_rows),
        "links": [{"label": f"Open {sample.sample_id}", "url": f"/samples/{sample.id}"}],
        "suggestions": [
            "Graph failures by operator",
            "Show reagent lot context",
            "Show instrument import context",
            "Export this investigation as PDF",
        ],
        "context": {"investigation": normalized},
    }


def _extract_days(message, default=90):
    match = re.search(r"(?:last|past|previous|within)\s+(\d+)\s+days?", str(message), re.IGNORECASE)
    return _safe_days(match.group(1), default) if match else default


def _identifier_from_message(message, subject_type, user):
    if subject_type == "result":
        match = re.search(r"\bresult\s*#?\s*(\d+)\b", message, re.IGNORECASE)
        return f"R-{match.group(1)}" if match else ""
    lower = str(message).lower()
    for sample_id in _accessible_samples(user).order_by("sample_id").values_list("sample_id", flat=True)[:2000]:
        if re.search(rf"(?<![a-z0-9_-]){re.escape(sample_id.lower())}(?![a-z0-9_-])", lower):
            return sample_id
    return ""


def _export_investigation(context, output_format):
    spec = dict(context.get("investigation") or {})
    output_format = "CSV" if str(output_format).upper() == "CSV" else "PDF"
    filters = {
        "report_type": "INVESTIGATION_REPORT",
        "investigation_spec": spec,
        "output_format": output_format,
        "timezone": str(timezone.get_current_timezone()),
    }
    preview = {
        "title": "Investigation artifact preview",
        "operation": "GENERATE_INVESTIGATION_ARTIFACT",
        "project": "Permission-filtered investigation",
        "records_affected": 1,
        "excluded_count": 0,
        "records": [{
            "id": spec.get("identifier", "investigation"),
            "label": "Investigation evidence package",
            "current": spec,
            "proposed": {"output": output_format},
        }],
        "current_values": spec,
        "proposed_values": {
            "format": output_format,
            "recalculate_at_confirmation": True,
            "audited": True,
        },
    }
    return {
        "answer": "Review the investigation scope below. Access and evidence will be recalculated when you confirm.",
        "links": [],
        "skip_llm": True,
        "pending_action": {
            "type": "COMPLIANCE_REPORT",
            "summary": f"Export investigation as {output_format}",
            "payload": {"operation": "GENERATE_REPORT", "filters": filters, "preview": preview},
        },
        "context": {"investigation": spec},
    }


def route_investigation_workbench(message, user, context=None):
    context = context or {}
    previous = dict(context.get("investigation") or {})
    text = str(message or "").strip()
    lower = text.lower()
    if previous and any(phrase in lower for phrase in ["export this", "download this"]):
        return _export_investigation(context, "CSV" if "csv" in lower else "PDF")

    visualization_requested = any(
        word in lower for word in ["graph", "plot", "chart", "visualize"]
    )
    evidence_terms = (
        "failure",
        "failures",
        "finding",
        "findings",
        "evidence",
        "operator",
        "instrument",
        "reagent",
        "workflow",
        "similar",
    )
    explicit_context_reference = any(
        phrase in lower
        for phrase in [
            "this investigation",
            "the investigation",
            "this failure",
            "these findings",
            "this sample",
            "this result",
        ]
    )
    focused_follow_up = any(
        phrase in lower
        for phrase in [
            "show reagent lot context",
            "show instrument import context",
            "show instrument evidence",
            "show workflow evidence",
            "show similar failures",
            "compare this failure",
            "compare this sample",
            "group by operator",
            "group by instrument",
            "group by reagent",
            "group by workflow",
        ]
    )
    follow_up = bool(previous) and (
        focused_follow_up
        or (
            visualization_requested
            and any(term in lower for term in evidence_terms)
        )
        or (
            explicit_context_reference
            and any(term in lower for term in evidence_terms)
        )
    )

    subject_signal = bool(
        re.search(r"\b(?:sample|result)\b", lower)
        or re.search(r"\bR-?\d+\b", text, re.IGNORECASE)
    )
    trigger = (
        any(word in lower for word in ["investigate", "investigation", "root cause"])
        and subject_signal
    )
    if not trigger and "sample" in lower:
        trigger = bool(
            any(phrase in lower for phrase in ["why did", "why has", "why is"])
            and re.search(r"\b(?:fail(?:ed|ing)?\s+qc|qc\s+failure)\b", lower)
        )
    if not trigger and not follow_up:
        return None

    spec = previous if follow_up else {
        "subject_type": "result" if re.search(r"\bresult\s*#?\s*\d+\b", text, re.IGNORECASE) else "sample",
        "identifier": "",
        "days": 90,
        "result_key": "",
        "group_by": "overview",
    }
    identifier = _identifier_from_message(text, spec.get("subject_type", "sample"), user)
    if identifier:
        spec["identifier"] = identifier
    spec["days"] = _extract_days(text, spec.get("days", 90))
    if "operator" in lower:
        spec["group_by"] = "operator"
    elif "instrument" in lower:
        spec["group_by"] = "instrument"
    elif "reagent" in lower or "lot" in lower:
        spec["group_by"] = "reagent"
    elif "workflow" in lower or "timing" in lower:
        spec["group_by"] = "workflow"
    result = run_investigation_spec(spec, user)
    if follow_up and not visualization_requested:
        result.pop("chart", None)
    return result
