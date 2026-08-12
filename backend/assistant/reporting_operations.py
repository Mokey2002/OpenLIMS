import csv
import hashlib
import re
from datetime import datetime
from io import BytesIO, StringIO
from xml.sax.saxutils import escape

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db.models import Count, Q
from django.utils import timezone
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String

from events.models import Event
from projects.models import Project
from results.models import Result, WorkItem
from samples.access import get_sample_access_queryset
from samples.models import Sample

from .models import GeneratedArtifact
from .comparisons import run_comparison_spec
from .investigations import run_investigation_spec


MONTHS = {name.lower(): number for number, name in enumerate([
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]) if name}


class ComplianceReportError(ValueError):
    pass


def _is_admin(user):
    return user.is_superuser or user.groups.filter(name="admin").exists()


def _project_from_message(message):
    lower = message.lower()
    for project in Project.objects.all().order_by("id"):
        if project.code.lower() in lower or project.name.lower() in lower:
            return project
    match = re.search(r"\bproject\s+#?(\d+)\b", message, re.IGNORECASE)
    return Project.objects.filter(id=int(match.group(1))).first() if match else None


def _date_filters(message):
    lower = message.lower()
    year = timezone.localdate().year
    for name, month in MONTHS.items():
        if re.search(rf"\b{name}\b", lower):
            start = timezone.make_aware(datetime(year, month, 1))
            if month == 12:
                end = timezone.make_aware(datetime(year + 1, 1, 1))
            else:
                end = timezone.make_aware(datetime(year, month + 1, 1))
            return start, end
    if "this month" in lower:
        today = timezone.localdate()
        start = timezone.make_aware(datetime(today.year, today.month, 1))
        end = timezone.make_aware(datetime(today.year + (today.month == 12), 1 if today.month == 12 else today.month + 1, 1))
        return start, end
    return None, None


def _report_type(message):
    lower = message.lower()
    if "status change" in lower:
        return "SAMPLE_STATUS_CHANGES"
    if "handled sample" in lower or "person who handled" in lower or "every person" in lower:
        return "CHAIN_OF_CUSTODY"
    if "qc approval" in lower:
        return "QC_APPROVAL_HISTORY"
    if "after results were approved" in lower or "after approval" in lower:
        return "POST_APPROVAL_CHANGES"
    if "assistant action" in lower:
        return "ASSISTANT_ACTION_HISTORY"
    return "PROJECT_REPORT"


def route_reporting_operations(message, user, context=None):
    del context
    lower = str(message or "").lower()
    if not any(word in lower for word in ["export", "report", "handled", "approvals", "approved"]):
        return None
    if not any(word in lower for word in ["export", "generate", "create", "show", "list"]):
        return None

    report_type = _report_type(message)
    project = _project_from_message(message)
    if project and not (_is_admin(user) or project.members.filter(id=user.id).exists()):
        return {"answer": "That project is not accessible.", "links": [], "skip_llm": True}
    start, end = _date_filters(message)
    sample_match = re.search(r"\b([A-Za-z]+[-_][A-Za-z0-9_-]+)\b", message)
    actor_match = re.search(r"\b(?:by|performed by)\s+([A-Za-z0-9_.@+-]+)", message, re.IGNORECASE)
    actor = None
    if actor_match:
        actor = get_user_model().objects.filter(username__iexact=actor_match.group(1)).first()
        if not actor:
            return {"answer": "The requested user was not found; use the exact username.", "links": [], "skip_llm": True}

    output_format = "CSV" if "csv" in lower or "export" in lower else "PDF"
    filters = {
        "report_type": report_type,
        "project_id": project.id if project else None,
        "project_label": project.code if project else "All accessible projects",
        "date_from": start.isoformat() if start else None,
        "date_to_exclusive": end.isoformat() if end else None,
        "timezone": str(timezone.get_current_timezone()),
        "sample_code": sample_match.group(1) if sample_match else None,
        "actor_id": actor.id if actor else None,
        "actor_username": actor.username if actor else None,
        "output_format": output_format,
    }
    preview = {
        "title": "Interpreted compliance report filters",
        "operation": "GENERATE_COMPLIANCE_REPORT",
        "project": filters["project_label"],
        "records_affected": 1,
        "excluded_count": 0,
        "records": [{"id": report_type, "label": report_type.replace("_", " ").title(), "current": filters, "proposed": {"output": output_format}}],
        "current_values": filters,
        "proposed_values": {"format": output_format, "audited": True, "reproducible": True},
    }
    return {
        "answer": "I interpreted the filters shown below. Confirm to generate the reproducible, audited report.",
        "links": [],
        "skip_llm": True,
        "pending_action": {
            "type": "COMPLIANCE_REPORT",
            "summary": f"Generate {report_type.replace('_', ' ').lower()} as {output_format}",
            "payload": {"operation": "GENERATE_REPORT", "filters": filters, "preview": preview},
        },
    }


def _parse_time(value):
    return datetime.fromisoformat(value) if value else None


def _accessible_project_ids(user):
    if _is_admin(user):
        return set(Project.objects.values_list("id", flat=True))
    return set(Project.objects.filter(members=user).values_list("id", flat=True))


def _event_rows(filters, user):
    queryset = Event.objects.select_related("actor").order_by("timestamp", "id")
    start = _parse_time(filters.get("date_from"))
    end = _parse_time(filters.get("date_to_exclusive"))
    if start:
        queryset = queryset.filter(timestamp__gte=start)
    if end:
        queryset = queryset.filter(timestamp__lt=end)
    if filters.get("actor_id"):
        queryset = queryset.filter(actor_id=filters["actor_id"])
    report_type = filters.get("report_type")
    if report_type == "SAMPLE_STATUS_CHANGES":
        queryset = queryset.filter(action__in=["STATUS_CHANGED", "BULK_STATUS_CHANGED", "SAMPLE_STATUS_CHANGED"])
    elif report_type == "QC_APPROVAL_HISTORY":
        queryset = queryset.filter(action__in=["QC_APPROVED", "QC_RESULT_APPROVED"])
    elif report_type == "POST_APPROVAL_CHANGES":
        queryset = queryset.filter(Q(action__icontains="REOPEN") | Q(action__icontains="POST_APPROVAL"))
    elif report_type == "ASSISTANT_ACTION_HISTORY":
        queryset = queryset.filter(entity_type="AssistantAction")
    elif report_type == "CHAIN_OF_CUSTODY":
        queryset = queryset.filter(Q(action__icontains="MOVED") | Q(action__icontains="ASSIGNED") | Q(action__icontains="STATUS") | Q(action__icontains="RECEIVED"))

    project_id = filters.get("project_id")
    sample_code = filters.get("sample_code")
    allowed_projects = _accessible_project_ids(user)
    admin_user = _is_admin(user)
    allowed_samples = {
        str(sample.id): sample
        for sample in get_sample_access_queryset(Sample.objects.select_related("project"), user)
    }
    rows = []
    for event in queryset[:10000]:
        payload = event.payload or {}
        event_project = payload.get("project_id")
        if project_id and event_project not in [project_id, str(project_id)]:
            continue
        if event_project:
            try:
                normalized_project_id = int(event_project)
            except (TypeError, ValueError):
                if not admin_user:
                    continue
            else:
                if normalized_project_id not in allowed_projects:
                    continue
        if event.entity_type == "Sample" and event.entity_id not in allowed_samples:
            continue
        if not admin_user and not event_project and event.entity_type != "Sample":
            if event.actor_id != user.id:
                continue
        if sample_code:
            code = str(payload.get("sample_code") or "")
            sample = allowed_samples.get(event.entity_id)
            if code.lower() != sample_code.lower() and (not sample or sample.sample_id.lower() != sample_code.lower()):
                continue
        rows.append({
            "timestamp": event.timestamp.isoformat(),
            "actor": event.actor.username if event.actor else "",
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "action": event.action,
            "project_id": event_project or "",
            "detail": str(payload),
        })
    return rows


def _csv_bytes(rows, filters):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["OpenLIMS report", filters.get("report_type")])
    writer.writerow(["Stored filters", str(filters)])
    writer.writerow([])
    writer.writerow(["timestamp", "actor", "entity_type", "entity_id", "action", "project_id", "detail"])
    for row in rows:
        writer.writerow([row[key] for key in ["timestamp", "actor", "entity_type", "entity_id", "action", "project_id", "detail"]])
    return output.getvalue().encode("utf-8")


def _comparison_value(value, value_format=None):
    if value is None or value == "":
        return "—"
    if value_format == "percent":
        try:
            return f"{float(value):.1f}%"
        except (TypeError, ValueError):
            return str(value)
    if value_format == "integer":
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return str(value)
    if value_format == "number":
        try:
            numeric = float(value)
            return f"{numeric:,.2f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _comparison_csv_bytes(result, filters):
    comparison = result.get("comparison") or {}
    columns = comparison.get("columns") or []
    rows = comparison.get("rows") or []
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["OpenLIMS comparison analysis", comparison.get("title", "Comparison")])
    writer.writerow(["Stored filters", str(filters)])
    writer.writerow([])
    writer.writerow([column.get("label", column.get("key")) for column in columns])
    for row in rows:
        writer.writerow([
            _comparison_value(row.get(column.get("key")), column.get("format"))
            for column in columns
        ])
    notes = comparison.get("notes") or []
    if notes:
        writer.writerow([])
        writer.writerow(["Notes"])
        for note in notes:
            writer.writerow([note])
    return output.getvalue().encode("utf-8")


def _comparison_chart_drawing(chart):
    data = list((chart or {}).get("data") or [])[:12]
    series = list((chart or {}).get("series") or [])[:5]
    if not data or not series:
        return None
    width = 700
    height = 260
    left = 48
    right = 16
    top = 42
    bottom = 50
    inner_width = width - left - right
    inner_height = height - top - bottom
    palette = ["#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c"]
    drawing = Drawing(width, height)
    drawing.add(Line(left, bottom, left, bottom + inner_height, strokeColor=colors.grey))
    drawing.add(Line(left, bottom, left + inner_width, bottom, strokeColor=colors.grey))
    values = []
    for row in data:
        for item in series:
            value = row.get(item.get("dataKey"))
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
    if not values:
        return None
    maximum = max(max(values), 1)
    minimum = min(min(values), 0)
    value_range = maximum - minimum or 1
    x_key = chart.get("xKey") or "entity"
    chart_type = chart.get("chartType")
    for index, item in enumerate(series):
        legend_x = left + index * 126
        color = colors.HexColor(palette[index % len(palette)])
        drawing.add(Rect(legend_x, height - 18, 9, 9, fillColor=color, strokeColor=color))
        drawing.add(String(
            legend_x + 13,
            height - 17,
            str(item.get("label") or item.get("dataKey"))[:18],
            fontSize=7,
        ))
    category_width = inner_width / max(len(data), 1)
    if chart_type == "line":
        for series_index, item in enumerate(series):
            points = []
            color = colors.HexColor(palette[series_index % len(palette)])
            for row_index, row in enumerate(data):
                try:
                    value = float(row.get(item.get("dataKey")))
                except (TypeError, ValueError):
                    continue
                x = left + category_width * row_index + category_width / 2
                y = bottom + ((value - minimum) / value_range) * inner_height
                points.extend([x, y])
                drawing.add(Circle(x, y, 2.2, fillColor=color, strokeColor=color))
            if len(points) >= 4:
                drawing.add(PolyLine(points, strokeColor=color, strokeWidth=1.5))
    else:
        bar_group = category_width * 0.76
        bar_width = bar_group / max(len(series), 1)
        for row_index, row in enumerate(data):
            group_x = left + category_width * row_index + (category_width - bar_group) / 2
            for series_index, item in enumerate(series):
                try:
                    value = float(row.get(item.get("dataKey")))
                except (TypeError, ValueError):
                    continue
                color = colors.HexColor(palette[series_index % len(palette)])
                y_zero = bottom + ((0 - minimum) / value_range) * inner_height
                y_value = bottom + ((value - minimum) / value_range) * inner_height
                drawing.add(Rect(
                    group_x + series_index * bar_width,
                    min(y_zero, y_value),
                    max(bar_width - 1, 1),
                    max(abs(y_value - y_zero), 0.5),
                    fillColor=color,
                    strokeColor=color,
                ))
    for row_index, row in enumerate(data):
        label = str(row.get(x_key, ""))[:12]
        drawing.add(String(
            left + category_width * row_index + 2,
            bottom - 15,
            label,
            fontSize=6,
        ))
    drawing.add(String(4, bottom + inner_height - 2, _comparison_value(maximum, "number"), fontSize=7))
    drawing.add(String(4, bottom, _comparison_value(minimum, "number"), fontSize=7))
    return drawing


def _comparison_pdf_bytes(result, filters):
    comparison = result.get("comparison") or {}
    chart = result.get("chart") or {}
    columns = comparison.get("columns") or []
    rows = comparison.get("rows") or []
    stream = BytesIO()
    page_size = landscape(letter)
    document = SimpleDocTemplate(
        stream,
        pagesize=page_size,
        rightMargin=0.45 * inch,
        leftMargin=0.45 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("OpenLIMS Comparison Analysis", styles["Title"]),
        Paragraph(escape(comparison.get("title") or "Comparison"), styles["Heading2"]),
        Paragraph(escape(result.get("answer") or ""), styles["BodyText"]),
        Paragraph(
            f"Stored filters: {escape(str(filters.get('comparison_spec') or {}))}",
            styles["BodyText"],
        ),
        Spacer(1, 10),
    ]
    drawing = _comparison_chart_drawing(chart)
    if drawing:
        story.extend([drawing, Spacer(1, 12)])
    if columns:
        table_rows = [
            [Paragraph(escape(str(column.get("label", column.get("key")))), styles["BodyText"]) for column in columns]
        ]
        for row in rows[:250]:
            table_rows.append([
                Paragraph(
                    escape(_comparison_value(row.get(column.get("key")), column.get("format"))),
                    styles["BodyText"],
                )
                for column in columns
            ])
        usable_width = page_size[0] - document.leftMargin - document.rightMargin
        table = Table(
            table_rows,
            repeatRows=1,
            colWidths=[usable_width / max(len(columns), 1)] * len(columns),
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 6.5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        story.extend([table, Spacer(1, 10)])
    notes = comparison.get("notes") or []
    if notes:
        story.append(Paragraph("Method notes", styles["Heading3"]))
        for note in notes:
            story.append(Paragraph(f"• {escape(str(note))}", styles["BodyText"]))

    def draw_footer(pdf_canvas, doc):
        pdf_canvas.saveState()
        pdf_canvas.setTitle("OpenLIMS Comparison Analysis")
        pdf_canvas.setAuthor("OpenLIMS")
        pdf_canvas.setFont("Helvetica", 7)
        pdf_canvas.setFillColor(colors.grey)
        pdf_canvas.drawString(doc.leftMargin, 0.25 * inch, "Permission-filtered OpenLIMS comparison")
        pdf_canvas.drawRightString(page_size[0] - doc.rightMargin, 0.25 * inch, f"Page {doc.page}")
        pdf_canvas.restoreState()

    document.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return stream.getvalue()


def _investigation_csv_bytes(result, filters):
    investigation = result.get("investigation") or {}
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["OpenLIMS investigation", investigation.get("title", "Investigation")])
    writer.writerow(["Stored filters", str(filters.get("investigation_spec") or {})])
    writer.writerow(["Summary", result.get("answer", "")])
    writer.writerow([])
    writer.writerow(["FINDINGS"])
    writer.writerow(["severity", "confidence", "evidence_type", "title", "detail"])
    for row in investigation.get("findings") or []:
        writer.writerow([row.get(key, "") for key in ["severity", "confidence", "evidence_type", "title", "detail"]])
    writer.writerow([])
    writer.writerow(["SUBJECT RESULTS"])
    writer.writerow(["result_id", "key", "value", "unit", "reference_min", "reference_max", "qc_passed", "qc_status", "entered_by", "created_at"])
    for row in investigation.get("results") or []:
        writer.writerow([row.get(key, "") for key in ["id", "key", "value", "unit", "reference_min", "reference_max", "qc_passed", "qc_status", "entered_by", "created_at"]])
    writer.writerow([])
    writer.writerow(["SIMILAR FAILURES"])
    writer.writerow(["sample_id", "result_id", "key", "value", "qc_status", "failure_reason", "created_at"])
    for row in investigation.get("similar_failures") or []:
        writer.writerow([row.get(key, "") for key in ["sample_id", "result_id", "key", "display_value", "qc_status", "failure_reason", "created_at"]])
    writer.writerow([])
    writer.writerow(["TIMELINE"])
    writer.writerow(["timestamp", "actor", "entity_type", "entity_id", "action", "detail"])
    for row in investigation.get("timeline") or []:
        writer.writerow([row.get(key, "") for key in ["timestamp", "actor", "entity_type", "entity_id", "action", "detail"]])
    writer.writerow([])
    writer.writerow(["CONTEXT AND LIMITATIONS"])
    for note in investigation.get("disclaimers") or []:
        writer.writerow([note])
    return output.getvalue().encode("utf-8")


def _investigation_pdf_bytes(result, filters):
    investigation = result.get("investigation") or {}
    stream = BytesIO()
    page_size = landscape(letter)
    document = SimpleDocTemplate(
        stream,
        pagesize=page_size,
        rightMargin=0.45 * inch,
        leftMargin=0.45 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("OpenLIMS Investigation Evidence Package", styles["Title"]),
        Paragraph(escape(investigation.get("title") or "Investigation"), styles["Heading2"]),
        Paragraph(escape(result.get("answer") or ""), styles["BodyText"]),
        Paragraph(
            f"Stored filters: {escape(str(filters.get('investigation_spec') or {}))}",
            styles["BodyText"],
        ),
        Spacer(1, 10),
    ]
    drawing = _comparison_chart_drawing(result.get("chart") or {})
    if drawing:
        story.extend([drawing, Spacer(1, 12)])

    findings = investigation.get("findings") or []
    story.append(Paragraph("Ranked findings", styles["Heading2"]))
    finding_rows = [["Severity", "Confidence", "Evidence", "Finding", "Detail"]]
    for row in findings[:100]:
        finding_rows.append([
            row.get("severity", "").title(),
            row.get("confidence", "").title(),
            row.get("evidence_type", "").title(),
            Paragraph(escape(str(row.get("title", ""))), styles["BodyText"]),
            Paragraph(escape(str(row.get("detail", ""))), styles["BodyText"]),
        ])
    if len(finding_rows) == 1:
        finding_rows.append(["—", "—", "—", "No specific findings", "Review source records."])
    table = Table(finding_rows, repeatRows=1, colWidths=[0.7 * inch, 0.8 * inch, 0.8 * inch, 2.1 * inch, 5.0 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([table, Spacer(1, 12)])

    results = investigation.get("results") or []
    if results:
        story.append(Paragraph("Subject results", styles["Heading2"]))
        result_rows = [["Result", "Analyte", "Value", "Reference", "QC", "Entered by", "Created"]]
        for row in results[:100]:
            reference = f"{row.get('reference_min', '—')} to {row.get('reference_max', '—')} {row.get('unit', '')}"
            result_rows.append([
                row.get("id"), row.get("key"), row.get("display_value"), reference,
                row.get("qc_status"), row.get("entered_by") or "—", str(row.get("created_at", ""))[:19],
            ])
        table = Table(result_rows, repeatRows=1, colWidths=[0.6 * inch, 1.5 * inch, 1.2 * inch, 1.6 * inch, 1.2 * inch, 1.2 * inch, 1.4 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#374151")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        story.extend([table, Spacer(1, 12)])

    story.append(Paragraph("Context and limitations", styles["Heading2"]))
    for note in investigation.get("disclaimers") or []:
        story.append(Paragraph(f"• {escape(str(note))}", styles["BodyText"]))

    def draw_footer(pdf_canvas, doc):
        pdf_canvas.saveState()
        pdf_canvas.setTitle("OpenLIMS Investigation Evidence Package")
        pdf_canvas.setAuthor("OpenLIMS")
        pdf_canvas.setFont("Helvetica", 7)
        pdf_canvas.setFillColor(colors.grey)
        pdf_canvas.drawString(doc.leftMargin, 0.25 * inch, "Permission-filtered; recalculated at confirmation")
        pdf_canvas.drawRightString(page_size[0] - doc.rightMargin, 0.25 * inch, f"Page {doc.page}")
        pdf_canvas.restoreState()

    document.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return stream.getvalue()


def _pdf_bytes(rows, filters, project):
    stream = BytesIO()
    document = SimpleDocTemplate(stream, pagesize=letter, rightMargin=0.55 * inch, leftMargin=0.55 * inch, topMargin=0.55 * inch, bottomMargin=0.55 * inch)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("OpenLIMS Compliance Report", styles["Title"]),
        Paragraph(filters.get("report_type", "PROJECT_REPORT").replace("_", " ").title(), styles["Heading2"]),
        Paragraph(f"Project scope: {filters.get('project_label')}", styles["BodyText"]),
        Paragraph(f"Date range: {filters.get('date_from') or 'All'} to {filters.get('date_to_exclusive') or 'Now'} ({filters.get('timezone')})", styles["BodyText"]),
        Spacer(1, 12),
    ]
    if project:
        samples = Sample.objects.filter(project=project)
        work = WorkItem.objects.filter(sample__project=project)
        results = Result.objects.filter(work_item__sample__project=project)
        summary = [
            ["Metric", "Value"],
            ["Samples", samples.count()],
            ["Open work items", work.filter(status__in=[WorkItem.STATUS_PENDING, WorkItem.STATUS_IN_PROGRESS]).count()],
            ["QC pending results", results.filter(qc_status=Result.QC_PENDING_REVIEW).count()],
            ["Audit rows", len(rows)],
        ]
        table = Table(summary, colWidths=[3.2 * inch, 2 * inch])
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("PADDING", (0, 0), (-1, -1), 6)]))
        story.extend([table, Spacer(1, 16)])
    story.append(Paragraph("Audit history", styles["Heading2"]))
    if not rows:
        story.append(Paragraph("No matching audit events.", styles["BodyText"]))
    else:
        table_rows = [["Time", "Actor", "Action", "Record"]]
        for row in rows[:250]:
            table_rows.append([row["timestamp"][:19], row["actor"] or "-", row["action"], f"{row['entity_type']} {row['entity_id']}"])
        table = Table(table_rows, repeatRows=1, colWidths=[1.25 * inch, 1.1 * inch, 2.0 * inch, 2.2 * inch])
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.35, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 4)]))
        story.append(table)
    def draw_footer(pdf_canvas, doc):
        pdf_canvas.saveState()
        pdf_canvas.setTitle("OpenLIMS Compliance Report")
        pdf_canvas.setAuthor("OpenLIMS")
        pdf_canvas.setFont("Helvetica", 7)
        pdf_canvas.setFillColor(colors.grey)
        pdf_canvas.drawString(
            doc.leftMargin,
            0.3 * inch,
            "Generated by OpenLIMS from stored report filters",
        )
        pdf_canvas.drawRightString(
            letter[0] - doc.rightMargin,
            0.3 * inch,
            f"Page {doc.page}",
        )
        pdf_canvas.restoreState()

    document.build(
        story,
        onFirstPage=draw_footer,
        onLaterPages=draw_footer,
    )
    return stream.getvalue()


def execute_compliance_report(action):
    filters = dict((action.payload or {}).get("filters") or {})
    project = None
    if filters.get("project_id"):
        project = Project.objects.filter(id=filters["project_id"]).first()
        if not project or not (_is_admin(action.requested_by) or project.members.filter(id=action.requested_by_id).exists()):
            raise ComplianceReportError("Project access changed before report generation.")
    output_format = filters.get("output_format", "PDF")
    if filters.get("report_type") == "INVESTIGATION_REPORT":
        investigation_result = run_investigation_spec(
            filters.get("investigation_spec") or {},
            action.requested_by,
        )
        investigation = investigation_result.get("investigation") or {}
        rows = investigation.get("findings") or []
        if not investigation:
            raise ComplianceReportError(
                investigation_result.get("answer") or "The investigation could not be recalculated."
            )
        if output_format == "CSV":
            content = _investigation_csv_bytes(investigation_result, filters)
            kind = GeneratedArtifact.KIND_REPORT_CSV
            extension = "csv"
            content_type = "text/csv"
        else:
            content = _investigation_pdf_bytes(investigation_result, filters)
            kind = GeneratedArtifact.KIND_REPORT_PDF
            extension = "pdf"
            content_type = "application/pdf"
    elif filters.get("report_type") == "COMPARISON_ANALYSIS":
        comparison_result = run_comparison_spec(
            filters.get("comparison_spec") or {},
            action.requested_by,
        )
        comparison = comparison_result.get("comparison") or {}
        rows = comparison.get("rows") or []
        if not comparison:
            raise ComplianceReportError(
                comparison_result.get("answer") or "The comparison could not be recalculated."
            )
        if output_format == "CSV":
            content = _comparison_csv_bytes(comparison_result, filters)
            kind = GeneratedArtifact.KIND_REPORT_CSV
            extension = "csv"
            content_type = "text/csv"
        else:
            content = _comparison_pdf_bytes(comparison_result, filters)
            kind = GeneratedArtifact.KIND_REPORT_PDF
            extension = "pdf"
            content_type = "application/pdf"
    else:
        rows = _event_rows(filters, action.requested_by)
        if output_format == "CSV":
            content = _csv_bytes(rows, filters)
            kind = GeneratedArtifact.KIND_REPORT_CSV
            extension = "csv"
            content_type = "text/csv"
        else:
            content = _pdf_bytes(rows, filters, project)
            kind = GeneratedArtifact.KIND_REPORT_PDF
            extension = "pdf"
            content_type = "application/pdf"
    filename = f"openlims-{filters.get('report_type', 'report').lower()}-{timezone.now():%Y%m%d-%H%M%S}.{extension}"
    checksum = hashlib.sha256(content).hexdigest()
    artifact = GeneratedArtifact.objects.create(
        kind=kind,
        filename=filename,
        content_type=content_type,
        checksum_sha256=checksum,
        parameters=filters,
        project=project,
        created_by=action.requested_by,
    )
    artifact.file.save(filename, ContentFile(content), save=True)
    Event.objects.create(
        entity_type="GeneratedArtifact",
        entity_id=str(artifact.id),
        action="REPORT_GENERATED",
        actor=action.requested_by,
        payload={"report_type": filters.get("report_type"), "filters": filters, "checksum_sha256": checksum, "assistant_action_id": str(action.id)},
    )
    return {
        "operation": "GENERATE_COMPLIANCE_REPORT",
        "succeeded_count": 1,
        "failed_count": 0,
        "artifact_id": str(artifact.id),
        "row_count": len(rows),
        "stored_filters": filters,
        "download_url": f"/api/assistant/artifacts/{artifact.id}/download/",
        "checksum_sha256": checksum,
    }
