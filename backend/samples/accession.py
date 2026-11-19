"""Explicit barcode accessioning; scans alone never change laboratory records."""
from io import BytesIO

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from events.models import Event
from workflow_requests.intake import registered_submission, submission_context, submission_for_barcode
from .access import require_sample_modify_access, user_can_access_sample
from .models import Sample, SampleAccession, SampleCustodyEvent
from .serializers import SampleSerializer


class BarcodeInput(serializers.Serializer):
    barcode = serializers.CharField(max_length=128, trim_whitespace=True)

    def validate_barcode(self, value):
        if any(ord(char) < 32 or ord(char) > 126 for char in value):
            raise serializers.ValidationError("Use a printable ASCII barcode without control characters.")
        return value


class ReceiptInput(BarcodeInput):
    reason = serializers.CharField(min_length=10, max_length=2000, trim_whitespace=True)


class LabelInput(serializers.Serializer):
    size = serializers.ChoiceField(choices=["100x50", "75x35", "A4"], default="100x50")


def code_from(data, receipt=False):
    serializer = (ReceiptInput if receipt else BarcodeInput)(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def resolve(code, user):
    # Resolve globally before checking access: a hidden or ambiguous ID is never a new sample.
    matches = list(Sample.objects.filter(
        Q(sample_id__iexact=code) | Q(barcode_labels__barcode__iexact=code)
    ).distinct()[:2])
    if not matches:
        return None
    if len(matches) != 1 or not user_can_access_sample(user, matches[0]):
        raise NotFound("Barcode unavailable. Check the code or contact the project owner.")
    return matches[0]


def primary_barcode(sample):
    label = sample.barcode_labels.filter(template="ACCESSION_SAMPLE").first()
    return label.barcode if label else sample.sample_id


def state(sample, request):
    accession = SampleAccession.objects.select_related(
        "receipt__performed_by", "label_verified_by"
    ).filter(sample=sample).first()
    # Existing custody receipts remain visible, without manufacturing a new receipt on lookup.
    receipt = accession.receipt if accession else sample.custody_events.filter(
        action=SampleCustodyEvent.ACTION_RECEIVE
    ).select_related("performed_by").order_by("occurred_at", "id").first()
    barcode = primary_barcode(sample)
    result = {
        "sample": SampleSerializer(sample, context={"request": request}).data,
        "barcode": barcode,
        "receipt": {"received_at": receipt.occurred_at, "received_by": receipt.performed_by.username,
                    "scanned_code": receipt.scanned_code} if receipt else None,
        "label_verified_at": accession.label_verified_at if accession else None,
        "label_verified_by": accession.label_verified_by.username if accession and accession.label_verified_by else None,
    }
    submission = registered_submission(sample, barcode, request.user)
    if submission:
        result["submission"] = submission
    return result


def require_active(request):
    if not request.user.is_active:
        raise PermissionDenied("An active account is required for accessioning.")


def lookup(request):
    require_active(request)
    code = code_from(request.query_params)["barcode"]
    sample = resolve(code, request.user)
    if sample:
        return Response({"kind": "existing", **state(sample, request)})
    submission = submission_for_barcode(code, request.user)
    if submission:
        return Response({
            "kind": "new", "barcode": submission.submission_barcode, "submission": submission_context(submission),
        })
    return Response({"kind": "new", "barcode": code})


@transaction.atomic
def register(view, request):
    require_active(request)
    code = code_from(request.data)["barcode"]
    if len(code) > 64 or code.upper().startswith("OPENLIMS-SAMPLE-"):
        raise ValidationError({"barcode": "New sample barcodes must be at most 64 characters and must not use the reserved OPENLIMS-SAMPLE- prefix."})
    if resolve(code, request.user):
        raise ValidationError({"barcode": "This identifier is unavailable. Scan again to open its sample."})
    submission = submission_for_barcode(code, request.user, lock=True)
    if submission:
        if submission.sample_id:
            raise ValidationError({"barcode": "This submission already has a sample. Scan again to open it."})
        code = submission.submission_barcode
    # Do not accept status, actor, schema, receipt or confirmation fields from a scanner/client.
    payload = {key: request.data[key] for key in ("sample_type", "project", "form_values") if key in request.data}
    if not payload.get("project"):
        raise ValidationError({"project": "Choose the project receiving this sample."})
    if not payload.get("sample_type"):
        raise ValidationError({"sample_type": "Choose a sample type."})
    serializer = SampleSerializer(
        data={**payload, "sample_id": code},
        context={"request": request, "submission_barcode": code if submission else None},
    )
    serializer.is_valid(raise_exception=True)
    from custom_fields.models import SampleForm
    if SampleForm.objects.filter(published=True).exists() and not serializer.validated_data.get("form_schema"):
        raise ValidationError({"sample_type": "Choose a published sample type so the lab's required fields can be checked."})
    # Existing sample visibility requires project membership, even for administrators.
    if not serializer.validated_data["project"].members.filter(pk=request.user.pk).exists():
        raise ValidationError({"project": "Join the receiving project before registering a sample here."})
    if submission and serializer.validated_data["project"].pk != submission.request.project_id:
        raise ValidationError({"project": "Use the project on the submission label."})
    try:
        with transaction.atomic():
            if submission:
                # The approved test request assigns and starts this sample's pipeline.
                sample = serializer.save(created_by=request.user)
                submission.sample = sample
                submission.save(update_fields=["sample", "updated_at"])
            else:
                view.perform_create(serializer)
            from assistant.models import BarcodeLabel
            BarcodeLabel.objects.create(sample=serializer.instance, template="ACCESSION_SAMPLE", barcode=code)
    except IntegrityError:
        raise ValidationError({"barcode": "This identifier is unavailable. Scan again before retrying."}) from None
    return Response({"kind": "existing", **state(serializer.instance, request)}, status=201)


def receive(view, request):
    require_active(request)
    values = code_from(request.data, receipt=True)
    with transaction.atomic():
        candidate = view.get_object()
        sample = Sample.objects.select_for_update().get(pk=candidate.pk)
        require_sample_modify_access(request.user, sample)
        scanned = resolve(values["barcode"], request.user)
        if not scanned or scanned.pk != sample.pk:
            raise ValidationError({"barcode": "This barcode does not match the selected sample. Nothing was recorded."})
        if sample.status in (Sample.STATUS_ARCHIVED, Sample.STATUS_CANCELLED):
            raise ValidationError("Archived or cancelled samples cannot be received.")
        if not SampleAccession.objects.filter(sample=sample).exists():
            receipt = sample.custody_events.filter(action=SampleCustodyEvent.ACTION_RECEIVE).order_by("occurred_at", "id").first()
            if receipt is None:
                receipt = SampleCustodyEvent.objects.create(
                    sample=sample, action=SampleCustodyEvent.ACTION_RECEIVE,
                    scanned_code=values["barcode"], performed_by=request.user,
                    reason=values["reason"], from_container=sample.container,
                    to_container=sample.container, from_custodian=sample.custodian,
                    to_custodian=sample.custodian,
                )
                Event.objects.create(entity_type="Sample", entity_id=str(sample.pk), actor=request.user,
                    action="SAMPLE_RECEIVED", payload={"custody_event_id": receipt.pk,
                    "barcode": values["barcode"], "reason": values["reason"], "received_at": receipt.occurred_at.isoformat()})
            SampleAccession.objects.create(sample=sample, receipt=receipt)
        return Response(state(sample, request))


def verify(view, request):
    require_active(request)
    code = code_from(request.data)["barcode"]
    with transaction.atomic():
        sample = Sample.objects.select_for_update().get(pk=view.get_object().pk)
        require_sample_modify_access(request.user, sample)
        scanned = resolve(code, request.user)
        if not scanned or scanned.pk != sample.pk:
            raise ValidationError({"barcode": "Wrong label. Scan the label attached to the selected sample. Nothing was changed."})
        accession = SampleAccession.objects.filter(sample=sample).first()
        if not accession:
            legacy = sample.custody_events.filter(action=SampleCustodyEvent.ACTION_RECEIVE).order_by("occurred_at", "id").first()
            if not legacy:
                raise ValidationError("Record physical receipt before confirming its label.")
            accession = SampleAccession.objects.create(sample=sample, receipt=legacy)
        if sample.status in (Sample.STATUS_ARCHIVED, Sample.STATUS_CANCELLED):
            raise ValidationError("Archived or cancelled samples cannot be label-confirmed.")
        if accession.label_verified_at is None:
            accession.label_verified_at = timezone.now()
            accession.label_verified_by = request.user
            accession.save(update_fields=["label_verified_at", "label_verified_by"])
            Event.objects.create(entity_type="Sample", entity_id=str(sample.pk), actor=request.user,
                action="SAMPLE_LABEL_VERIFIED", payload={"barcode": code, "receipt_id": accession.receipt_id,
                "verified_at": accession.label_verified_at.isoformat()})
        return Response(state(sample, request))


def print_label(view, request):
    require_active(request)
    from reportlab.graphics.barcode.code128 import Code128
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from settings_app.print_rendering import print_fonts

    inputs = LabelInput(data=request.data)
    inputs.is_valid(raise_exception=True)
    size = inputs.validated_data["size"]
    sizes = {"100x50": (100 * mm, 50 * mm), "75x35": (75 * mm, 35 * mm), "A4": (210 * mm, 297 * mm)}
    with transaction.atomic():
        sample = Sample.objects.select_for_update().get(pk=view.get_object().pk)
        require_sample_modify_access(request.user, sample)
        code = code_from({"barcode": primary_barcode(sample)})["barcode"]
        resolved = resolve(code, request.user)
        if not resolved or resolved.pk != sample.pk:
            raise ValidationError("This sample ID is ambiguous. Contact your administrator before printing.")
        width, height = sizes[size]
        barcode = Code128(code, barWidth=0.8, barHeight=20 * mm, humanReadable=True)
        scale = min(1, (width - 10 * mm) / barcode.width)
        if scale < 0.7:
            raise ValidationError({"size": "This barcode needs a larger label. Select A4 and print at actual size."})
        regular, bold = print_fonts()
        stream = BytesIO()
        pdf = canvas.Canvas(stream, pagesize=(width, height))
        pdf.setTitle("OpenLIMS Sample Label")
        pdf.setFont(bold, 10)
        pdf.drawString(5 * mm, height - 7 * mm, "OpenLIMS")
        pdf.setFont(regular, 8)
        from reportlab.lib.utils import simpleSplit
        lines = simpleSplit(sample.sample_id, regular, 8, width - 10 * mm)
        if size == "75x35" and len(lines) > 1:
            raise ValidationError({"size": "This sample ID needs a larger label. Select 100x50 or A4."})
        for index, line in enumerate(lines):
            pdf.drawString(5 * mm, height - (12 + 4 * index) * mm, line)
        project = sample.project.code if sample.project else "No project"
        pdf.drawString(5 * mm, height - (16 + 4 * len(lines)) * mm, project[:40])
        # The bars sit below the text; preserve bar height when fitting a narrow label.
        pdf.saveState()
        pdf.translate(5 * mm, height - (39 + 4 * len(lines)) * mm if size == "A4" else 3 * mm)
        pdf.scale(scale, 0.55 if size == "75x35" else 0.8)
        barcode.drawOn(pdf, 0, 0)
        pdf.restoreState()
        pdf.showPage()
        pdf.save()
        from assistant.models import BarcodeLabel
        # Retain a stable scan alias even if the readable sample ID is later corrected.
        label = sample.barcode_labels.filter(barcode__iexact=code).first()
        if not label:
            label = BarcodeLabel.objects.create(sample=sample, template="ACCESSION_SAMPLE", barcode=code)
        label.generation_count += 1
        label.last_generated_at = timezone.now()
        label.last_generated_by = request.user
        label.save(update_fields=["generation_count", "last_generated_at", "last_generated_by"])
        Event.objects.create(entity_type="Sample", entity_id=str(sample.pk), actor=request.user,
            action="SAMPLE_LABEL_GENERATED", payload={"barcode": code, "size": size, "source": "accessioning"})
        response = HttpResponse(stream.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="sample-{sample.pk}-label.pdf"'
        return response
