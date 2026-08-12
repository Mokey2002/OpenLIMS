import hashlib
import re
from io import BytesIO

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from reportlab.graphics.barcode.code128 import Code128
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from core.permissions import is_admin, is_tech
from events.models import Event
from samples.access import get_sample_access_queryset
from samples.models import Sample, SampleBatch

from .models import BarcodeLabel, GeneratedArtifact


LABEL_TEMPLATE = "STANDARD_SAMPLE"
MAX_LABELS = 100


class LabelGenerationError(ValueError):
    pass


def _barcode_for(sample):
    return f"OPENLIMS-SAMPLE-{sample.id}-{sample.sample_id}"


def _selected_samples(message, user):
    lower = message.lower()
    queryset = get_sample_access_queryset(
        Sample.objects.select_related("project", "batch"),
        user,
    )
    batch_match = re.search(r"\bbatch\s+([A-Za-z0-9_.-]+)", message, re.IGNORECASE)
    if batch_match:
        batch = SampleBatch.objects.filter(code__iexact=batch_match.group(1)).first()
        return list(queryset.filter(batch=batch).order_by("id")[: MAX_LABELS + 1]) if batch else []

    range_match = re.search(
        r"\b([A-Za-z]+-?)(\d+)\s+(?:through|to)\s+([A-Za-z]+-?)(\d+)\b",
        message,
        re.IGNORECASE,
    )
    if range_match and range_match.group(1).lower() == range_match.group(3).lower():
        prefix = range_match.group(1)
        start = int(range_match.group(2))
        end = int(range_match.group(4))
        if end < start or end - start + 1 > MAX_LABELS:
            return []
        codes = [f"{prefix}{value}" for value in range(start, end + 1)]
        return list(queryset.filter(sample_id__in=codes).order_by("id"))

    code_match = re.search(r"\b(?:sample\s+)?([A-Za-z]+[-_][A-Za-z0-9_-]+)\b", message)
    if code_match:
        sample = queryset.filter(sample_id__iexact=code_match.group(1)).first()
        return [sample] if sample else []
    return []


def route_barcode_operations(message, user, context=None):
    del context
    lower = str(message or "").lower()
    if not any(word in lower for word in ["barcode", "label", "labels"]):
        return None
    if not any(word in lower for word in ["create", "generate", "print", "regenerate"]):
        return None
    if not (is_admin(user) or is_tech(user)):
        return {
            "answer": "Only Tech or Director users can generate or reprint labels.",
            "links": [],
            "skip_llm": True,
        }

    samples = _selected_samples(message, user)
    if not samples:
        return {
            "answer": "No accessible samples matched, or the request exceeds the 100-label limit.",
            "links": [],
            "skip_llm": True,
        }
    if len(samples) > MAX_LABELS:
        return {
            "answer": f"The request exceeds the {MAX_LABELS}-label limit. Narrow the sample set.",
            "links": [],
            "skip_llm": True,
        }
    existing = {
        label.sample_id: label
        for label in BarcodeLabel.objects.filter(
            sample__in=samples,
            template=LABEL_TEMPLATE,
        )
    }
    records = []
    reprint_count = 0
    for sample in samples:
        label = existing.get(sample.id)
        is_reprint = bool(label and label.generation_count)
        reprint_count += int(is_reprint)
        records.append({
            "id": sample.id,
            "label": sample.sample_id,
            "current": {
                "barcode": label.barcode if label else None,
                "times_generated": label.generation_count if label else 0,
            },
            "proposed": {
                "template": LABEL_TEMPLATE,
                "format": "DOWNLOADABLE_PDF",
                "reprint": is_reprint,
            },
        })
    preview = {
        "title": "Proposed barcode label generation",
        "operation": "GENERATE_LABELS",
        "project": "Samples shown below",
        "records_affected": len(records),
        "excluded_count": 0,
        "records": records,
        "current_values": {"previously_generated": reprint_count},
        "proposed_values": {
            "label_template": LABEL_TEMPLATE,
            "label_count": len(records),
            "output": "Downloadable PDF",
            "printer": None,
        },
        "warnings": ([f"{reprint_count} label(s) will be audited as reprints."] if reprint_count else []),
    }
    return {
        "answer": f"Generate {len(records)} label(s) as a downloadable PDF. {reprint_count} are reprints. Review the exact samples and confirm.",
        "links": [],
        "skip_llm": True,
        "pending_action": {
            "type": "LABEL_GENERATION",
            "summary": f"Generate {len(records)} sample barcode label(s)",
            "payload": {
                "operation": "GENERATE_LABELS",
                "template": LABEL_TEMPLATE,
                "sample_ids": [sample.id for sample in samples],
                "snapshots": {str(sample.id): sample.sample_id for sample in samples},
                "preview": preview,
            },
        },
    }


def _render_labels(labels):
    stream = BytesIO()
    page_width, page_height = letter
    pdf = canvas.Canvas(stream, pagesize=letter, pageCompression=1)
    pdf.setTitle("OpenLIMS Sample Barcode Labels")
    pdf.setAuthor("OpenLIMS")
    margin_x = 36
    margin_y = 36
    columns = 2
    rows = 5
    label_width = (page_width - (2 * margin_x)) / columns
    label_height = (page_height - (2 * margin_y)) / rows

    for index, (sample, label, is_reprint) in enumerate(labels):
        slot = index % (columns * rows)
        if index and slot == 0:
            pdf.showPage()
        row = slot // columns
        column = slot % columns
        x = margin_x + column * label_width
        y = page_height - margin_y - (row + 1) * label_height
        pdf.roundRect(x + 4, y + 4, label_width - 8, label_height - 8, 6)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(x + 14, y + label_height - 24, sample.sample_id)
        pdf.setFont("Helvetica", 8)
        project_code = sample.project.code if sample.project else "No project"
        pdf.drawString(x + 14, y + label_height - 38, project_code)
        barcode = Code128(label.barcode, barHeight=34, barWidth=0.65)
        barcode.drawOn(pdf, x + 14, y + 30)
        pdf.setFont("Helvetica", 7)
        pdf.drawCentredString(x + label_width / 2, y + 18, label.barcode)
        if is_reprint:
            pdf.setFont("Helvetica-Bold", 7)
            pdf.drawRightString(x + label_width - 14, y + label_height - 24, "REPRINT")

    pdf.save()
    return stream.getvalue()


@transaction.atomic
def execute_label_generation(action):
    payload = action.payload or {}
    sample_ids = payload.get("sample_ids") or []
    if not (is_admin(action.requested_by) or is_tech(action.requested_by)):
        raise LabelGenerationError(
            "Only Tech or Director users can generate or reprint labels."
        )
    if not sample_ids or len(sample_ids) > MAX_LABELS:
        raise LabelGenerationError("The frozen label set is empty or exceeds 100 samples.")
    snapshots = payload.get("snapshots") or {}
    samples = list(Sample.objects.select_for_update().filter(id__in=sample_ids).order_by("id"))
    if {sample.id for sample in samples} != set(sample_ids):
        raise LabelGenerationError("One or more frozen samples no longer exist.")
    allowed_ids = set(
        get_sample_access_queryset(
            Sample.objects.filter(id__in=sample_ids),
            action.requested_by,
        ).values_list("id", flat=True)
    )
    if allowed_ids != set(sample_ids):
        raise LabelGenerationError("Project access changed for one or more samples.")

    labels = []
    for sample in samples:
        if snapshots.get(str(sample.id)) != sample.sample_id:
            raise LabelGenerationError(f"Sample {sample.id} changed after preview.")
        label, _ = BarcodeLabel.objects.get_or_create(
            sample=sample,
            template=payload.get("template", LABEL_TEMPLATE),
            defaults={"barcode": _barcode_for(sample)},
        )
        if BarcodeLabel.objects.exclude(id=label.id).filter(barcode=label.barcode).exists():
            raise LabelGenerationError("A barcode resolves to more than one label record.")
        labels.append((sample, label, label.generation_count > 0))

    pdf_bytes = _render_labels(labels)
    checksum = hashlib.sha256(pdf_bytes).hexdigest()
    filename = f"openlims-labels-{timezone.now():%Y%m%d-%H%M%S}.pdf"
    artifact = GeneratedArtifact.objects.create(
        kind=GeneratedArtifact.KIND_LABEL_PDF,
        filename=filename,
        content_type="application/pdf",
        checksum_sha256=checksum,
        parameters={
            "sample_ids": sample_ids,
            "template": payload.get("template", LABEL_TEMPLATE),
        },
        created_by=action.requested_by,
    )
    artifact.file.save(filename, ContentFile(pdf_bytes), save=True)

    reprints = 0
    for sample, label, is_reprint in labels:
        label.generation_count += 1
        label.last_artifact = artifact
        label.last_generated_by = action.requested_by
        label.last_generated_at = timezone.now()
        label.save(update_fields=["generation_count", "last_artifact", "last_generated_by", "last_generated_at"])
        reprints += int(is_reprint)
        Event.objects.create(
            entity_type="Sample",
            entity_id=str(sample.id),
            action="LABEL_REPRINTED" if is_reprint else "LABEL_GENERATED",
            actor=action.requested_by,
            payload={"sample_code": sample.sample_id, "barcode": label.barcode, "template": label.template, "artifact_id": str(artifact.id), "assistant_action_id": str(action.id)},
        )

    return {
        "operation": "GENERATE_LABELS",
        "succeeded_count": len(labels),
        "failed_count": 0,
        "reprint_count": reprints,
        "artifact_id": str(artifact.id),
        "download_url": f"/api/assistant/artifacts/{artifact.id}/download/",
        "checksum_sha256": checksum,
    }
