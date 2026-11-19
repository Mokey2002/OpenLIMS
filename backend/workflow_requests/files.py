from io import BytesIO
from pathlib import PurePosixPath

from django.http import FileResponse, HttpResponse
from rest_framework.exceptions import NotFound


def report_download(report):
    try:
        file = report.file.open("rb")
    except FileNotFoundError as exc:
        raise NotFound("Report file unavailable.") from exc
    response = FileResponse(
        file, as_attachment=True, filename=PurePosixPath(report.file.name).name,
        content_type="application/octet-stream",
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def submission_labels(workflow_request, items):
    from reportlab.graphics.barcode.code128 import Code128
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas
    from settings_app.print_rendering import print_fonts

    stream = BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(100 * mm, 50 * mm))
    pdf.setTitle(f"{workflow_request.request_number} submission labels")
    regular, bold = print_fonts()
    for item in items:
        pdf.setFont(bold, 10)
        pdf.drawString(5 * mm, 42 * mm, workflow_request.request_number)
        text_width = max(1, stringWidth(item.submission_reference, regular, 10))
        size = 10 * min(1, 90 * mm / text_width)
        pdf.setFont(regular, size)
        pdf.drawString(5 * mm, 34 * mm, item.submission_reference)
        barcode = Code128(item.submission_barcode, barWidth=0.55, barHeight=15 * mm, humanReadable=True)
        barcode.drawOn(pdf, (100 * mm - barcode.width) / 2, 8 * mm)
        pdf.showPage()
    pdf.save()
    response = HttpResponse(stream.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{workflow_request.request_number}-labels.pdf"'
    response["Cache-Control"] = "private, no-store"
    return response
