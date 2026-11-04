"""Bounded project QC evidence and reports with explicit denominators and scope."""
import csv
import io
import math
import re
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import is_admin
from projects.models import Project
from results.models import Result, WorkItem
from .lab_helpers import response
from .natural_requests import normalize_request
from .project_conversation import project_samples
from .result_queries import PERIODS, period_dates

KEY = "project_investigation"
REPORT_TYPE = "PROJECT_QC_INVESTIGATION"
MAX_RESULTS = 5000
GROUPS = {"key": "Result key", "instrument": "Linked instrument", "operator": "Result entered by", "workflow": "Work type"}


class ProjectQCSerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    period = serializers.ChoiceField(choices=sorted(PERIODS), required=False)
    group_by = serializers.ChoiceField(choices=list(GROUPS), default="key")
    key = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise ValidationError({"detail": "Use only the displayed investigation filters."})
        return super().to_internal_value(data)

    def validate(self, data):
        if "period" in data and "days" in data:
            raise ValidationError({"detail": "Choose one calendar period or a rolling day count."})
        if not ("period" in data or "days" in data):
            data["days"] = 90
        return data


def project_for_user(pk, user):
    projects = Project.objects.all() if is_admin(user) else Project.objects.filter(members=user)
    project = projects.filter(pk=pk).first()
    if not project or not user.is_active:
        raise ValueError("Project unavailable. Use one exact accessible project code.")
    return project


def resolve_project(code, user):
    projects = Project.objects.all() if is_admin(user) else Project.objects.filter(members=user)
    matches = list(projects.filter(code__iexact=code)[:2])
    if len(matches) != 1:
        raise ValueError("Project unavailable. Use one exact accessible project code.")
    return project_for_user(matches[0].pk, user)


def resolve_window(spec, now):
    if "date_from" in spec or "date_before" in spec:
        start, end = (datetime.fromisoformat(spec[key]) for key in ["date_from", "date_before"])
        if timezone.is_naive(start) or timezone.is_naive(end) or start >= end:
            raise ValueError("The frozen report window is invalid. Request a fresh export preview.")
    elif spec.get("period"):
        start_date, end_date = period_dates(spec["period"])
        start, end = (timezone.make_aware(datetime.combine(day, datetime.min.time())) for day in [start_date, end_date])
    else:
        end, start = now, now - timedelta(days=spec.get("days", 90))
    return start, end


def investigate_project(spec, user, *, complete=False):
    project = project_for_user(spec["project_id"], user)
    public = {key: value for key, value in spec.items() if key in ProjectQCSerializer().fields}
    serializer = ProjectQCSerializer(data=public)
    serializer.is_valid(raise_exception=True)
    public = serializer.validated_data
    now = timezone.now()
    start, end = resolve_window({**public, **{key: value for key, value in spec.items() if key in {"date_from", "date_before"}}}, now)
    records = Result.objects.filter(work_item__sample__in=project_samples(project, user), created_at__gte=start, created_at__lt=end)
    if public["key"]:
        records = records.filter(key__iexact=public["key"])
    count = records.count()
    if count > MAX_RESULTS:
        raise ValueError(f"This scope exceeds {MAX_RESULTS} results. Narrow the time window or exact result key before investigating/exporting; no partial failure rate is reported.")
    records = list(records.select_related("work_item__sample", "entered_by", "work_item__source_import_job__instrument").order_by("-created_at", "-pk")[:MAX_RESULTS + 1])
    if len(records) > MAX_RESULTS:
        raise ValueError(f"This scope exceeds {MAX_RESULTS} results. Narrow the window or result key before exporting.")
    gates = []
    if not public["key"]:
        gates = list(WorkItem.objects.filter(sample__in=project_samples(project, user), qc_status__in=["REJECTED", "RERUN_REQUIRED"],
            reviewed_at__gte=start, reviewed_at__lt=end).select_related("sample", "reviewed_by").order_by("-reviewed_at", "-pk")[:MAX_RESULTS + 1])
        if len(records) + len(gates) > MAX_RESULTS:
            raise ValueError(f"The combined result/work-item review scope exceeds {MAX_RESULTS} records. Narrow the window or exact result key before exporting.")
    groups, failed_rows, included_samples = {}, [], set()
    totals = {"results": len(records), "assessed_checks": 0, "failed_checks": 0, "rejected_reviews": 0, "pending_reviews": 0, "flagged_results": 0}
    for record in records:
        included_samples.add(record.work_item.sample_id)
        job = record.work_item.source_import_job
        label = {"key": record.key, "operator": record.entered_by.username if record.entered_by_id else "Unrecorded operator",
            "instrument": job.instrument.code if job else "No linked instrument", "workflow": record.work_item.work_type}[public["group_by"]]
        group = groups.setdefault(label, {"label": label, "results": 0, "assessed_checks": 0, "failed_checks": 0, "rejected_reviews": 0, "flagged_results": 0})
        group["results"] += 1
        assessed, auto_failed, rejected = record.qc_passed is not None, record.qc_passed is False, record.qc_status == "REJECTED"
        for key, condition in [("assessed_checks", assessed), ("failed_checks", auto_failed), ("rejected_reviews", rejected), ("flagged_results", auto_failed or rejected)]:
            totals[key] += int(condition)
            group[key] += int(condition)
        totals["pending_reviews"] += int(record.qc_status in {"PENDING_REVIEW", "REOPENED"})
        if auto_failed or rejected:
            value = record.value
            invalid_value = isinstance(value, float) and not math.isfinite(value)
            failed_rows.append({"id": record.pk, "sample_id": record.work_item.sample_id, "sample": record.work_item.sample.sample_id,
                "work_item_id": record.work_item_id, "key": record.key, "value": None if invalid_value else value,
                "value_warning": "Non-finite numeric value; correct the source record." if invalid_value else "", "unit": record.unit,
                "qc_passed": record.qc_passed, "qc_status": record.qc_status, "qc_failure_reason": record.qc_failure_reason,
                "review_note": record.qc_review_note, "operator": record.entered_by.username if record.entered_by_id else "",
                "instrument": job.instrument.code if job else "", "run_id": job.run_id if job else "",
                "created_at": record.created_at.isoformat(), "url": f"/samples/{record.work_item.sample_id}#result-{record.pk}"})
    def rates(row):
        return {**row, "failure_rate": round(row["failed_checks"] * 100 / row["assessed_checks"], 2) if row["assessed_checks"] else None}
    totals = rates(totals)
    totals.update(rejected_work_gates=sum(work.qc_status == "REJECTED" for work in gates), rerun_work_gates=sum(work.qc_status == "RERUN_REQUIRED" for work in gates))
    gate_rows = [{"id": work.pk, "sample_id": work.sample_id, "sample": work.sample.sample_id, "work": work.name, "qc_status": work.qc_status,
        "reason": work.review_note, "reviewed_by": work.reviewed_by.username if work.reviewed_by_id else "", "reviewed_at": work.reviewed_at.isoformat(),
        "url": f"/samples/{work.sample_id}"} for work in gates]
    included_samples.update(work.sample_id for work in gates)
    grouped = sorted((rates(row) for row in groups.values()), key=lambda row: (-row["flagged_results"], row["label"]))
    summary = (f"{project.code}: {totals['flagged_results']} distinct result{'s' if totals['flagged_results'] != 1 else ''} with failed checks or rejected reviews out of {totals['results']} recorded result{'s' if totals['results'] != 1 else ''}. "
        f"Automated checks: {totals['failed_checks']} failed of {totals['assessed_checks']} assessed. "
        f"Human result reviews: {totals['rejected_reviews']} rejected; {totals['pending_reviews']} pending/reopened. These categories can overlap. "
        f"Separate work-item QC decisions: {totals['rejected_work_gates']} rejected; {totals['rerun_work_gates']} requiring rerun.")
    normalized = {"project_id": project.pk, **public}
    report = {"project_id": project.pk, "project": project.code, "project_name": project.name, "as_of": now.isoformat(),
        "spec": normalized, "window": {"start": start.isoformat(), "end_exclusive": end.isoformat(), "timezone": timezone.get_current_timezone_name()},
        "summary": totals, "answer": summary, "group_by": public["group_by"], "group_label": GROUPS[public["group_by"]],
        "groups": grouped if complete else grouped[:50], "group_count": len(grouped),
        "failures": failed_rows if complete else failed_rows[:50], "failure_count": len(failed_rows), "sample_count": len(included_samples),
        "work_gates": gate_rows if complete else gate_rows[:50], "work_gate_count": len(gate_rows),
        "notes": ["Failure rate = failed automated checks / assessed automated checks. Unevaluated checks are excluded from that denominator.",
            "Flagged results count the union of failed checks and rejected reviews once. Individual result reviews and workflow work-item QC gates are separate.",
            "Instrument groups use the work item's direct import-job relation; unlinked results stay in an explicit unknown group.",
            "Operator groups provide traceability, not evidence of responsibility or scientific causation.",
            "This review uses result creation timestamps within the half-open window. It does not include every historical review action or infer root cause.",
            "Separate rejected/rerun work-item gates use their recorded review timestamp in the window; undated reviews are excluded. Gate summaries are omitted when filtering by a result key.",
            "The chat shows up to 50 groups/failure records. CSV includes the complete bounded evidence; PDF includes up to 200 failure details with its limit disclosed."]}
    if complete:
        report["evidence_sample_ids"] = sorted(included_samples)
    return report


def investigation_reply(spec, user, export_format=None):
    report = investigate_project(spec, user)
    result = response(report["answer"], project_investigation=report, context={KEY: report["spec"]},
        suggestions=["Group by instrument", "Group by operator", "Refresh this investigation", "Export this investigation as PDF", "Export this investigation as CSV"])
    if export_format:
        frozen = {**report["spec"], "date_from": report["window"]["start"], "date_before": report["window"]["end_exclusive"]}
        filters = {"report_type": REPORT_TYPE, "project_id": report["project_id"], "project_qc_spec": frozen, "output_format": export_format,
            "timezone": report["window"]["timezone"]}
        preview = {"title": "Review project QC report scope", "operation": "GENERATE_PROJECT_QC_REPORT", "project": {"label": report["project"]}, "records_affected": 1,
            "current_values": {"window": report["window"], "counts": report["summary"]}, "proposed_values": {"format": export_format, "scope": frozen},
            "warnings": ["The exact project, filters and window are frozen; accessible evidence is reread at confirmation and counts can change.",
                "PDF shows up to 200 failure details; CSV contains the complete bounded result evidence. Access is rechecked on download."]}
        result["pending_action"] = {"type": "COMPLIANCE_REPORT", "summary": f"Export {report['project']} QC investigation as {export_format}",
            "payload": {"operation": "GENERATE_REPORT", "filters": filters, "preview": preview}}
    return result


def csv_report(report):
    out = io.StringIO()
    writer = csv.writer(out)
    def write(values):
        writer.writerow(["'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for value in values])
    write(["OpenLIMS project QC investigation", report["project"], report["as_of"]])
    write(["Window", report["window"]["start"], report["window"]["end_exclusive"], report["window"]["timezone"]])
    for key, value in report["summary"].items():
        write([key, value])
    write(["GROUPS", report["group_label"]])
    columns = ["label", "results", "assessed_checks", "failed_checks", "rejected_reviews", "flagged_results", "failure_rate"]
    write(columns)
    for row in report["groups"]:
        write([row.get(key, "") for key in columns])
    write(["FLAGGED RESULT EVIDENCE"])
    columns = ["id", "sample", "work_item_id", "key", "value", "value_warning", "unit", "qc_passed", "qc_status", "qc_failure_reason", "review_note", "operator", "instrument", "run_id", "created_at"]
    write(columns)
    for row in report["failures"]:
        write([row.get(key, "") for key in columns])
    write(["WORK-ITEM QC GATE EVIDENCE"])
    columns = ["id", "sample", "work", "qc_status", "reason", "reviewed_by", "reviewed_at"]
    write(columns)
    for row in report["work_gates"]:
        write([row.get(key, "") for key in columns])
    for note in report["notes"]:
        write([note])
    return out.getvalue().encode("utf-8-sig")


def pdf_report(report):
    out = io.BytesIO()
    styles = getSampleStyleSheet()
    style = styles["BodyText"]
    style.fontSize, style.leading = 8, 10
    def paragraph(value):
        return Paragraph(escape(str(value)), style)
    doc = SimpleDocTemplate(out, pagesize=landscape(letter), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = [Paragraph(escape(f"Project QC investigation: {report['project']}"), styles["Title"]), paragraph(report["answer"]),
        paragraph(f"Window: {report['window']}; generated {report['as_of']}"), Spacer(1, 12)]
    def table(rows, widths):
        result = Table([[paragraph(cell) for cell in row] for row in rows], colWidths=widths, repeatRows=1)
        result.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), .25, colors.grey)]))
        return result
    story.append(table([[report["group_label"], "Results", "Assessed", "Failed", "Rejected", "Flagged", "Failure %"]] +
        [[row["label"], row["results"], row["assessed_checks"], row["failed_checks"], row["rejected_reviews"], row["flagged_results"], row["failure_rate"]] for row in report["groups"][:100]], [235, 70, 70, 70, 70, 70, 65]))
    story += [Spacer(1, 12), paragraph(f"Showing {min(100, report['group_count'])} of {report['group_count']} groups and {min(200, report['failure_count'])} of {report['failure_count']} failure records. CSV contains all bounded evidence.")]
    story.append(table([["Result / sample", "Value", "QC / provenance", "Recorded reason"]] +
        [[f"R-{row['id']} / {row['sample']} / {row['key']}", f"{row['value']} {row['unit']} {row['value_warning']}",
          f"Check: {row['qc_passed']}; review: {row['qc_status']}; instrument: {row['instrument'] or 'unlinked'}; run: {row['run_id']}",
          (row["qc_failure_reason"] + " " + row["review_note"])[:1000]] for row in report["failures"][:200]], [180, 130, 170, 200]))
    story += [Spacer(1, 12), paragraph(f"Work-item QC gates: showing {min(200, report['work_gate_count'])} of {report['work_gate_count']}. Reasons are excerpts of up to 1000 characters; CSV includes complete text.")]
    story.append(table([["Work / sample", "Decision / reviewer", "Reason"]] + [[f"#{row['id']} / {row['sample']} / {row['work']}",
        f"{row['qc_status']} / {row['reviewed_by']} / {row['reviewed_at']}", row["reason"][:1000]] for row in report["work_gates"][:200]], [220, 220, 240]))
    story.extend(paragraph(note) for note in report["notes"])
    doc.build(story)
    return out.getvalue()


def artifact_accessible(artifact, user):
    if artifact.parameters.get("report_type") != REPORT_TYPE:
        return True
    try:
        project = project_for_user(artifact.parameters["project_id"], user)
        ids = artifact.parameters["evidence_sample_ids"]
        return isinstance(ids, list) and len(ids) <= MAX_RESULTS and project_samples(project, user).filter(pk__in=ids).count() == len(set(ids))
    except (ValueError, KeyError, TypeError):
        return False


class ProjectQCView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk):
        if any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
            raise ValidationError({"detail": "Supply each investigation filter once."})
        serializer = ProjectQCSerializer(data=request.query_params.dict())
        serializer.is_valid(raise_exception=True)
        try:
            return Response(investigation_reply({"project_id": pk, **serializer.validated_data}, request.user))
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc


class ProjectQCExportSerializer(ProjectQCSerializer):
    output_format = serializers.ChoiceField(choices=["PDF", "CSV"])


class ProjectQCExportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ProjectQCExportSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request, pk):
        serializer = ProjectQCExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        output_format = data.pop("output_format")
        try:
            reply = investigation_reply({"project_id": pk, **data}, request.user, output_format)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        from .actions import propose_action, serialize_action
        pending = reply["pending_action"]
        reply["pending_action"] = serialize_action(propose_action(request.user, pending["type"], pending["summary"], pending["payload"]))
        return Response(reply, status=201)


def explain_failures(reply):
    report = reply["project_investigation"]
    lines = []
    for row in report["failures"][:10]:
        reason = row["qc_failure_reason"] or row["review_note"] or "No failure/rejection reason is recorded."
        check = "failed" if row["qc_passed"] is False else "passed" if row["qc_passed"] is True else "not assessed"
        value = row["value"] if row["value"] is not None else "no usable value"
        notes = str(reason)[:500]
        if row["qc_failure_reason"] and row["review_note"]:
            notes += f" Review note: {str(row['review_note'])[:500]}"
        lines.append(f"R-{row['id']} — {row['sample']} / {row['key']}: {value} {row['unit']}; check {check}; review {row['qc_status']}. {notes}")
    for row in report["work_gates"][:5]:
        lines.append(f"Work #{row['id']} — {row['sample']}: {row['qc_status']}; {str(row['reason'] or 'No review reason is recorded.')[:500]}")
    reply["answer"] += "\n\n" + ("Recorded flagged evidence:\n" + "\n".join(lines) if lines else "No failed/rejected results or rejected/rerun work gates are recorded in this scope.")
    if report["failure_count"] > 10 or report["work_gate_count"] > 5:
        reply["answer"] += "\nThese are evidence excerpts; inspect the investigation panel or preview a CSV export for the remaining records."
    reply["answer"] += "\nRecorded flags and review notes do not establish the scientific root cause."
    return reply


def route_project_investigation(message, user, context=None):
    text = normalize_request(message)
    prior = (context or {}).get(KEY)
    if text.lower() in {"investigate project qc failures", "investigate a project's qc failures"}:
        return response("Which project should I investigate? Reply with its exact project code.", context={KEY: {"awaiting_project": True}}, clarification={"required": True})
    if prior == {"awaiting_project": True}:
        from .conversation import is_courtesy_reply
        if is_courtesy_reply(text):
            return None
        if re.fullmatch(r"[\w.:/-]{1,64}", text) and text.lower() not in {"cancel", "stop", "thanks"}:
            return route_project_investigation(f"Investigate project {text} QC failures", user)
        if text.lower() in {"cancel", "stop", "never mind"}:
            return response("Investigation request closed. No report was generated.")
        return None
    export = re.fullmatch(r"(?:export|download)(?:(?: this)? (?:investigation|report))?(?: as (PDF|CSV))?", text, re.I)
    if isinstance(prior, dict):
        spec = {**prior}
        group = re.fullmatch(r"(?:group|graph failures) by (key|instrument|operator|workflow)", text, re.I)
        correction = re.fullmatch(r"(?:actually[, ]+)?(?:use|switch to|I meant|same for)(?: project)? ([\w.:/-]{1,64})", text, re.I)
        evidence = bool(re.fullmatch(r"why|why (?:did (?:they|these|those) fail|these failures)|which (?:ones|results) failed|show (?:me )?(?:the )?(?:failed|flagged) results|explain (?:that|these failures)(?: more simply)?", text, re.I))
        if group:
            spec["group_by"] = group[1].lower()
        elif correction or export or evidence:
            pass
        elif text.lower() not in {"refresh this investigation", "refresh investigation"}:
            spec = None
        if spec is not None:
            project_id = prior.get("project_id")
            if (set(prior) - {"project_id", *ProjectQCSerializer().fields}
                    or type(project_id) is not int or not 0 < project_id < 2**63):
                return response("The investigation filters are unavailable. Start a new project investigation.", replace_context=True)
            try:
                if correction:
                    spec["project_id"] = resolve_project(correction[1], user).pk
                reply = investigation_reply(spec, user, (export[1] or "PDF").upper() if export else None)
                if text.lower().startswith("graph"):
                    report = reply["project_investigation"]
                    reply["chart"] = {"chartType": "bar", "xKey": "label", "xAxisLabel": report["group_label"],
                        "meta": {"title": f"{report['project']}: flagged results by {report['group_label']}", "description": "Union of failed checks/rejected reviews; categories can overlap. These counts do not establish cause."},
                        "data": report["groups"][:20], "series": [{"dataKey": "flagged_results", "label": "Distinct flagged results", "axisLabel": "Results"}]}
                return explain_failures(reply) if evidence else reply
            except (ValueError, KeyError, ValidationError) as exc:
                return response(str(exc), replace_context=True)
    pattern = (r"(?:investigate|review) (?:project )?([\w.:/-]{1,64})(?:'s)? QC failures?"
        r"(?: (?:from|for|in|over) (today|yesterday|this week|last week|this month|last month|last \d{1,3} days))?"
        r"(?: and export(?: (?:a|this))? (?:report|investigation)(?: as (PDF|CSV))?)?")
    match = re.fullmatch(pattern, text, re.I)
    reverse = re.fullmatch(r"(?:investigate|review) QC failures? (?:in|for) project ([\w.:/-]{1,64})", text, re.I)
    if not match and not reverse:
        if re.match(r"(?:investigate|review)\b", text, re.I) and re.search(r"\bQC failures?\b", text, re.I) and not re.search(r"\b(?:sample|result)\b", text, re.I):
            return response("Use one exact project and a supported window, for example: Investigate project ALPHA QC failures for last 30 days and export a report as CSV.", clarification={"required": True})
        return None
    try:
        project = resolve_project((match or reverse)[1], user)
        spec = {"project_id": project.pk}
        if match and match[2]:
            window = match[2].lower()
            if re.fullmatch(r"last \d+ days", window):
                spec["days"] = int(re.search(r"\d+", window)[0])
            else:
                spec["period"] = window.replace(" ", "_")
        format_requested = match and " and export" in text.lower()
        return investigation_reply(spec, user, (match[3] or "PDF").upper() if format_requested else None)
    except (ValueError, ValidationError) as exc:
        return response(str(exc), clarification={"required": True})
