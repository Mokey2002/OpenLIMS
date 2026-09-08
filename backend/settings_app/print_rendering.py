"""Safe PDF layout primitives: no user HTML, URLs, scripts, or executable templates."""
import base64
from io import BytesIO
from xml.sax.saxutils import escape
from functools import lru_cache
from pathlib import Path
import reportlab

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


@lru_cache(maxsize=1)
def print_fonts():
    directory = Path(reportlab.__file__).parent / "fonts"
    pdfmetrics.registerFont(TTFont("OpenLIMSSans", str(directory / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("OpenLIMSSansBold", str(directory / "VeraBd.ttf")))
    return "OpenLIMSSans", "OpenLIMSSansBold"


def page_size(config):
    size = A4 if config.get("page_size") == "A4" else letter
    return landscape(size) if config.get("orientation") == "landscape" else size


def logo_stream(config):
    return BytesIO(base64.b64decode(config["logo"].split(",", 1)[1]))


def render_report(rows, filters, template):
    config = template["config"]
    stream = BytesIO()
    size = page_size(config)
    doc = SimpleDocTemplate(stream, pagesize=size, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=48)
    styles = getSampleStyleSheet()
    regular, bold = print_fonts()
    for style in styles.byName.values():
        style.fontName = bold if style.name in ["Title", "Heading2"] else regular
    styles["BodyText"].fontSize = 8
    styles["BodyText"].leading = 11
    para = lambda text: Paragraph(escape(str(text)), styles["BodyText"])
    story = []
    if config.get("logo"):
        logo = Image(logo_stream(config))
        logo._restrictSize(100, 45)
        logo.hAlign = "LEFT"
        story.extend([logo, Spacer(1, 8)])
    story.extend([Paragraph(escape(config.get("title") or "OpenLIMS Compliance Report"), styles["Title"]),
                  para(filters.get("report_type", "PROJECT_REPORT")),
                  para(f"Project / Proyecto: {filters.get('project_label', 'All accessible projects')}"),
                  para(f"Range / Periodo: {filters.get('date_from') or 'All'} - {filters.get('date_to_exclusive') or 'Now'} ({filters.get('timezone', 'UTC')})"),
                  para(f"Template / Plantilla: {template['name']} v{template['revision']}"), Spacer(1, 12)])
    summary = [para(f"Matching audit events / Eventos coincidentes: {len(rows)}"), Spacer(1, 8)] if config.get("show_summary", True) else []
    if config.get("summary_position", "before") == "before":
        story.extend(summary)
    story.append(Paragraph("Audit history / Historial de auditoría", styles["Heading2"]))
    if len(rows) > 250:
        story.append(para("First 250 events shown; use CSV for the full filtered export. / Se muestran los primeros 250 eventos; use CSV para la exportación completa."))
    cells = [[para(x) for x in ["Time / Fecha", "Actor", "Action / Acción", "Record / Registro"]]]
    for row in rows[:250]:
        cells.append([para(row.get("timestamp", "")), para(row.get("actor") or "-"), para(row.get("action", "")), para(f"{row.get('entity_type', '')} {row.get('entity_id', '')}")])
    width = size[0] - 72
    table = Table(cells, colWidths=[width * n for n in [.24, .16, .32, .28]], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), .3, colors.grey), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story.append(table)
    if config.get("summary_position") == "after":
        story.extend(summary)
    def footer(pdf, document):
        pdf.saveState()
        pdf.setFont(regular, 7)
        pdf.drawString(36, 28, "OpenLIMS | Permission-filtered audit report / Informe de auditoría filtrado")
        pdf.drawRightString(size[0] - 36, 28, str(document.page))
        pdf.drawString(36, 17, config.get("footer", ""))
        pdf.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()


def draw_label_logo(pdf, config, x, y):
    if config.get("logo"):
        pdf.drawImage(ImageReader(logo_stream(config)), x, y, width=42, height=18, preserveAspectRatio=True, mask="auto")


def render_analysis(result, filters, template, kind):
    """Apply a frozen layout while retaining evidence, scope and limitations."""
    from assistant.reporting_operations import _comparison_chart_drawing, _comparison_value
    config = template["config"]
    data = result.get(kind) or {}
    stream = BytesIO()
    size = page_size(config)
    doc = SimpleDocTemplate(stream, pagesize=size, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=48)
    styles = getSampleStyleSheet()
    regular, bold = print_fonts()
    for style in styles.byName.values():
        style.fontName = bold if style.name.startswith("Heading") or style.name == "Title" else regular
    styles["BodyText"].fontSize = 8
    styles["BodyText"].leading = 11
    para = lambda text: Paragraph(escape(str(text if text is not None else "—")), styles["BodyText"])
    heading = lambda text: Paragraph(escape(str(text)), styles["Heading2"])
    story = []
    if config.get("logo"):
        logo = Image(logo_stream(config))
        logo._restrictSize(100, 45)
        logo.hAlign = "LEFT"
        story.extend([logo, Spacer(1, 8)])
    story.extend([Paragraph(escape(config.get("title") or f"OpenLIMS {kind.title()} Report"), styles["Title"]),
                  heading(data.get("title") or kind.title()),
                  para(f"Stored filters: {filters.get(kind + '_spec') or {}}"),
                  para(f"Timezone: {filters.get('timezone', 'UTC')}"),
                  para(f"Template: {template['name']} v{template['revision']}"), Spacer(1, 12)])
    summary = [para(result.get("answer") or ""), Spacer(1, 10)] if config.get("show_summary", True) else []
    chart = []
    if config.get("show_chart", True):
        drawing = _comparison_chart_drawing(result.get("chart") or {})
        if drawing:
            for item in drawing.contents:
                if hasattr(item, "fontName"):
                    item.fontName = regular
            ratio = min(1, doc.width / drawing.width, (doc.height * .6) / drawing.height)
            drawing.scale(ratio, ratio)
            drawing.width *= ratio
            drawing.height *= ratio
            chart = [drawing, Spacer(1, 12)]
    if config.get("summary_position", "before") == "before":
        story.extend(summary)
    if config.get("chart_position", "before") == "before":
        story.extend(chart)

    def add_table(title, labels, values, total, limit, weights=None):
        story.append(heading(title))
        if total > limit:
            story.append(para(f"First {limit} of {total} records shown; use CSV for the full filtered export."))
        if not values:
            story.append(para("No records."))
            return
        weights = weights or [1] * len(labels)
        cells = [[para(x) for x in labels]] + [[para(x) for x in row] for row in values]
        table = Table(cells, repeatRows=1, colWidths=[doc.width * w / sum(weights) for w in weights])
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
                                  ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), .3, colors.grey),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
        story.extend([table, Spacer(1, 12)])

    if kind == "comparison":
        columns, rows = data.get("columns") or [], data.get("rows") or []
        if columns:
            add_table("Comparison data", [c.get("label", c.get("key")) for c in columns],
                      [[_comparison_value(r.get(c.get("key")), c.get("format")) for c in columns] for r in rows[:250]], len(rows), 250)
        notes = data.get("notes") or []
        notes_title = "Method notes"
    else:
        findings = data.get("findings") or []
        keys = ["severity", "confidence", "evidence_type", "title", "detail"]
        add_table("Ranked findings", ["Severity", "Confidence", "Evidence", "Finding", "Detail"],
                  [[r.get(k, "") for k in keys] for r in findings[:100]], len(findings), 100, [1, 1, 1, 2, 4])
        rows = data.get("results") or []
        add_table("Subject results", ["Result", "Analyte", "Value", "Reference", "QC", "Entered by", "Created"],
                  [[r.get("id"), r.get("key"), r.get("display_value"),
                    f"{r.get('reference_min', '—')} to {r.get('reference_max', '—')} {r.get('unit', '')}",
                    r.get("qc_status"), r.get("entered_by"), str(r.get("created_at", ""))[:19]] for r in rows[:100]], len(rows), 100)
        notes = data.get("disclaimers") or []
        notes_title = "Context and limitations"
    if config.get("chart_position") == "after":
        story.extend(chart)
    if config.get("summary_position") == "after":
        story.extend(summary)
    story.append(heading(notes_title))
    story.extend(para(note) for note in notes)

    def footer(pdf, document):
        pdf.saveState()
        pdf.setFont(regular, 7)
        pdf.drawString(36, 28, "OpenLIMS | Permission-filtered; recalculated at confirmation")
        pdf.drawRightString(size[0] - 36, 28, str(document.page))
        pdf.drawString(36, 17, config.get("footer", ""))
        pdf.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
