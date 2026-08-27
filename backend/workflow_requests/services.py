import hashlib
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.audit import record_audit_event
from inventory.models import InventoryLot, InventoryReservation
from inventory.units import UnitConversionError, convert_quantity, units_compatible
from notifications.models import Notification
from pipelines.services import start_pipeline

from .models import (
    RequestResourceRequirement,
    WorkflowRequest,
    WorkflowRequestItem,
    WorkflowRunGroup,
)


def validate_submission_form(schema, data):
    schema = schema or {}
    data = data or {}
    if not isinstance(data, dict):
        raise ValidationError({"form_data": "Submission data must be an object."})
    for field in schema.get("required", []):
        if field not in data or data[field] is None or data[field] == "":
            raise ValidationError({"form_data": f"'{field}' is required."})
    type_map = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "array": list, "object": dict}
    for field, definition in (schema.get("properties") or {}).items():
        if field not in data or "type" not in definition:
            continue
        expected = type_map.get(definition["type"])
        if expected and not isinstance(data[field], expected):
            raise ValidationError({"form_data": f"'{field}' must be {definition['type']}."})
    return data


def next_request_number():
    year = timezone.now().year
    prefix = f"REQ-{year}-"
    latest = WorkflowRequest.objects.filter(request_number__startswith=prefix).order_by("-request_number").values_list("request_number", flat=True).first()
    sequence = int(latest.rsplit("-", 1)[-1]) + 1 if latest else 1
    return f"{prefix}{sequence:05d}"


def reserve_material(*, requirement, request_item, actor):
    needed = Decimal(requirement.quantity or 0)
    if needed <= 0:
        return []
    reservations = []
    lots = (
        InventoryLot.objects.select_for_update()
        .filter(item=requirement.inventory_item, status=InventoryLot.STATUS_ACTIVE)
        .order_by("expiration_date", "received_date", "id")
    )
    for lot in lots:
        if not units_compatible(requirement.unit, lot.unit):
            continue
        available = convert_quantity(lot.available_quantity, lot.unit, requirement.unit)
        if available <= 0:
            continue
        take = min(needed, available)
        reservation = InventoryReservation.objects.create(
            lot=lot,
            project=request_item.request.project,
            quantity=take,
            unit=requirement.unit,
            status=InventoryReservation.STATUS_ACTIVE,
            created_by=actor,
            work_item=(
                request_item.pipeline_run.steps.order_by("position").first().work_item
                if request_item.pipeline_run and request_item.pipeline_run.steps.order_by("position").first()
                else None
            ),
            request_item_public_id=request_item.public_id,
        )
        reservations.append(reservation)
        needed -= take
        if needed <= 0:
            break
    if needed > 0:
        raise ValidationError({"inventory": f"Insufficient {requirement.inventory_item.code}: missing {needed} {requirement.unit}."})
    return reservations


@transaction.atomic
def approve_request(*, workflow_request, actor, pipeline=None, reason="", group_name="Approved run group", batch=None, plate=None):
    workflow_request = WorkflowRequest.objects.select_for_update().select_related("request_type", "project").get(pk=workflow_request.pk)
    if workflow_request.status not in {WorkflowRequest.STATUS_SUBMITTED, WorkflowRequest.STATUS_TRIAGE}:
        raise ValidationError({"status": "Only submitted or triaged requests can be approved."})
    previous_status = workflow_request.status
    pipeline = pipeline or workflow_request.assigned_pipeline or workflow_request.request_type.default_pipeline
    if not pipeline:
        raise ValidationError({"pipeline": "Assign a pipeline before approval."})
    items = list(workflow_request.items.select_related("sample", "registry_record"))
    if not items:
        raise ValidationError({"items": "A request needs at least one item."})

    runs = []
    reservations = []
    for item in items:
        if item.sample_id:
            run = start_pipeline(sample=item.sample, template=pipeline, actor=actor)
            item.pipeline_run = run
            item.status = "QUEUED"
            item.save(update_fields=["pipeline_run", "status", "updated_at"])
            runs.append(run)
        for requirement in workflow_request.request_type.resource_requirements.filter(
            kind=RequestResourceRequirement.KIND_MATERIAL,
            required=True,
        ).select_related("inventory_item"):
            reservations.extend(reserve_material(requirement=requirement, request_item=item, actor=actor))

    group = WorkflowRunGroup.objects.create(
        request=workflow_request,
        name=group_name,
        batch=batch,
        plate=plate,
        created_by=actor,
    )
    group.items.set(items)
    group.pipeline_runs.set(runs)
    workflow_request.status = WorkflowRequest.STATUS_APPROVED
    workflow_request.assigned_pipeline = pipeline
    workflow_request.approved_by = actor
    workflow_request.approved_at = timezone.now()
    workflow_request.decision_reason = reason
    workflow_request.save(update_fields=["status", "assigned_pipeline", "approved_by", "approved_at", "decision_reason", "updated_at"])
    Notification.objects.create(
        user=workflow_request.requester,
        title=f"Request {workflow_request.request_number} approved",
        message=f"{pipeline.name} was assigned and required materials were reserved.",
        link=f"/workflow-requests?request={workflow_request.public_id}",
    )
    record_audit_event(
        entity=workflow_request,
        action="WORKFLOW_REQUEST_APPROVED",
        actor=actor,
        reason=reason,
        before={"status": previous_status},
        after={"status": workflow_request.status, "pipeline": pipeline.code},
        details={"items": len(items), "pipeline_runs": [str(run.public_id) for run in runs], "reservations": [str(row.public_id) for row in reservations]},
    )
    return workflow_request, reservations, runs


def file_checksum(uploaded_file):
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()
