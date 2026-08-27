from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.audit import record_audit_event
from core.entities import content_object_fields, entity_reference, get_entity_type_for_object, resolve_entity

from .models import (
    BarcodeIdentity,
    InventoryAlert,
    InventoryCycleCount,
    InventoryCycleCountLine,
    InventoryItem,
    InventoryLot,
    InventoryReservation,
    InventoryTransaction,
)
from .units import UnitConversionError, convert_quantity, units_compatible


def decimal_value(value, field="amount"):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({field: "Enter a valid quantity."}) from exc


@transaction.atomic
def assign_barcode(*, obj, barcode, actor):
    barcode = str(barcode or "").strip()
    if not barcode:
        raise ValidationError({"barcode": "A barcode is required."})
    if not hasattr(obj, "public_id"):
        raise ValidationError({"target": "Barcode targets require a stable public ID."})
    entity_type = get_entity_type_for_object(obj)
    fields = content_object_fields(obj)
    existing = BarcodeIdentity.objects.filter(**fields, active=True).first()
    if existing:
        if existing.barcode == barcode:
            return existing, False
        existing.active = False
        existing.save(update_fields=["active"])
    identity = BarcodeIdentity.objects.create(
        barcode=barcode,
        target_public_id=obj.public_id,
        entity_type=entity_type,
        created_by=actor,
        **fields,
    )
    return identity, True


def resolve_barcode(barcode, user):
    identity = BarcodeIdentity.objects.select_related("content_type").filter(
        barcode=str(barcode or "").strip(), active=True
    ).first()
    if not identity:
        raise ValidationError({"barcode": "No active inventory identity matches this barcode."})
    try:
        obj = resolve_entity(identity.entity_type, identity.target_public_id, user, write=False)
    except (ValueError, LookupError, PermissionError) as exc:
        raise ValidationError({"barcode": str(exc)}) from exc
    return identity, obj


@transaction.atomic
def perform_inventory_operation(
    *, lot, operation, actor, reason, amount=0, unit=None, to_location=None,
    to_container=None, work_item=None, experiment=None, request_item_public_id=None,
    metadata=None,
):
    lot = InventoryLot.objects.select_for_update().select_related("item", "location", "container").get(pk=lot.pk)
    operation = str(operation or "").upper()
    choices = {choice[0] for choice in InventoryTransaction.OP_CHOICES}
    if operation not in choices:
        raise ValidationError({"operation": "Choose a supported inventory operation."})
    if not str(reason or "").strip():
        raise ValidationError({"reason": "A reason is required for every inventory transaction."})

    unit = str(unit or lot.unit)
    if not units_compatible(unit, lot.unit):
        raise ValidationError({"unit": "The operation unit is incompatible with the lot unit."})
    entered_amount = decimal_value(amount)
    try:
        converted = convert_quantity(entered_amount, unit, lot.unit)
    except UnitConversionError as exc:
        raise ValidationError({"unit": str(exc)}) from exc

    before_quantity = lot.quantity
    before_status = lot.status
    from_location = lot.location
    from_container = lot.container
    after_quantity = before_quantity
    after_status = before_status

    if operation == InventoryTransaction.OP_RECEIVE:
        if converted <= 0:
            raise ValidationError({"amount": "Received quantity must be positive."})
        after_quantity += converted
        after_status = InventoryLot.STATUS_ACTIVE
    elif operation in {InventoryTransaction.OP_CONSUME, InventoryTransaction.OP_DISPOSE, InventoryTransaction.OP_RETURN}:
        if converted <= 0:
            raise ValidationError({"amount": "The quantity must be positive."})
        if converted > before_quantity:
            raise ValidationError({"amount": "The operation cannot reduce inventory below zero."})
        if operation == InventoryTransaction.OP_CONSUME and converted > lot.available_quantity:
            linked_reserved = Decimal("0")
            if work_item:
                linked_reserved = sum(
                    convert_quantity(row.quantity, row.unit, lot.unit)
                    for row in lot.reservations.filter(status=InventoryReservation.STATUS_ACTIVE, work_item=work_item)
                )
            if converted > lot.available_quantity + linked_reserved:
                raise ValidationError({"amount": "The quantity exceeds unreserved inventory."})
        after_quantity -= converted
        if operation == InventoryTransaction.OP_DISPOSE and after_quantity == 0:
            after_status = InventoryLot.STATUS_DISPOSED
        elif operation == InventoryTransaction.OP_RETURN and after_quantity == 0:
            after_status = InventoryLot.STATUS_RETURNED
        elif after_quantity == 0:
            after_status = InventoryLot.STATUS_DEPLETED
    elif operation == InventoryTransaction.OP_COUNT:
        if converted < 0:
            raise ValidationError({"amount": "Counted quantity cannot be negative."})
        after_quantity = converted
        after_status = InventoryLot.STATUS_DEPLETED if converted == 0 else before_status
    elif operation == InventoryTransaction.OP_ADJUST:
        after_quantity = before_quantity + converted
        if after_quantity < 0:
            raise ValidationError({"amount": "The adjustment cannot reduce inventory below zero."})
        if after_quantity == 0:
            after_status = InventoryLot.STATUS_DEPLETED
        elif before_status == InventoryLot.STATUS_DEPLETED:
            after_status = InventoryLot.STATUS_ACTIVE
    elif operation == InventoryTransaction.OP_QUARANTINE:
        after_status = InventoryLot.STATUS_QUARANTINED
        lot.quarantine_reason = str(reason)
    elif operation in {InventoryTransaction.OP_MOVE, InventoryTransaction.OP_TRANSFER}:
        if not to_location and not to_container:
            raise ValidationError({"to_location": "A destination location or container is required."})

    if to_container:
        if to_location and to_container.location_id != to_location.pk:
            raise ValidationError({"to_container": "The container is not in the destination location."})
        to_location = to_location or to_container.location
    if operation in {InventoryTransaction.OP_MOVE, InventoryTransaction.OP_TRANSFER}:
        lot.location = to_location
        lot.container = to_container

    lot.quantity = after_quantity
    lot.status = after_status
    lot.save(update_fields=["quantity", "status", "location", "container", "quarantine_reason", "updated_at"])
    ledger_amount = after_quantity - before_quantity
    entry = InventoryTransaction.objects.create(
        lot=lot,
        operation=operation,
        amount=ledger_amount,
        unit=lot.unit,
        before_quantity=before_quantity,
        after_quantity=after_quantity,
        before_status=before_status,
        after_status=after_status,
        from_location=from_location,
        to_location=lot.location,
        from_container=from_container,
        to_container=lot.container,
        actor=actor,
        reason=reason,
        work_item=work_item,
        experiment=experiment,
        request_item_public_id=request_item_public_id,
        metadata=metadata or {},
    )

    if operation == InventoryTransaction.OP_CONSUME:
        reservations = lot.reservations.filter(status=InventoryReservation.STATUS_ACTIVE)
        if work_item:
            reservations = reservations.filter(work_item=work_item)
        elif request_item_public_id:
            reservations = reservations.filter(request_item_public_id=request_item_public_id)
        for reservation in reservations:
            reserved = convert_quantity(reservation.quantity, reservation.unit, lot.unit)
            if reserved <= converted:
                reservation.status = InventoryReservation.STATUS_CONSUMED
                reservation.save(update_fields=["status", "updated_at"])

    record_audit_event(
        entity=lot,
        action=f"INVENTORY_{operation}",
        actor=actor,
        reason=reason,
        before={"quantity": str(before_quantity), "status": before_status, "location": from_location_id(from_location), "container": from_container_id(from_container)},
        after={"quantity": str(after_quantity), "status": after_status, "location": from_location_id(lot.location), "container": from_container_id(lot.container)},
        details={"transaction_public_id": str(entry.public_id), "amount": str(entry.amount), "unit": entry.unit, "work_item": str(work_item.public_id) if work_item else None, "experiment": str(experiment.public_id) if experiment else None},
    )
    return entry


def from_location_id(location):
    return str(location.public_id) if location else None


def from_container_id(container):
    return str(container.public_id) if container else None


@transaction.atomic
def reconcile_cycle_count(*, cycle_count, actor, reason):
    cycle_count = InventoryCycleCount.objects.select_for_update().get(pk=cycle_count.pk)
    if cycle_count.status == InventoryCycleCount.STATUS_RECONCILED:
        raise ValidationError({"status": "This cycle count is already reconciled."})
    missing = cycle_count.lines.filter(observed_quantity__isnull=True)
    if missing.exists():
        raise ValidationError({"lines": "Every cycle-count line requires an observed quantity."})
    transactions = []
    for line in cycle_count.lines.select_related("lot"):
        if not units_compatible(line.unit, line.lot.unit):
            raise ValidationError({"unit": f"Count unit for {line.lot.lot_code} is incompatible."})
        transaction_row = perform_inventory_operation(
            lot=line.lot,
            operation=InventoryTransaction.OP_COUNT,
            actor=actor,
            reason=reason,
            amount=line.observed_quantity,
            unit=line.unit,
            metadata={"cycle_count_public_id": str(cycle_count.public_id)},
        )
        transactions.append(transaction_row)
    cycle_count.status = InventoryCycleCount.STATUS_RECONCILED
    cycle_count.reconciled_by = actor
    cycle_count.reconciled_at = timezone.now()
    cycle_count.save(update_fields=["status", "reconciled_by", "reconciled_at"])
    return transactions


def refresh_inventory_alerts(now=None):
    now = now or timezone.now()
    active_keys = set()
    expiry_cutoff = (now + timedelta(days=30)).date()
    for lot in InventoryLot.objects.select_related("item").exclude(status__in=[InventoryLot.STATUS_DISPOSED, InventoryLot.STATUS_RETURNED]):
        if lot.expiration_date and lot.expiration_date <= expiry_cutoff:
            key = f"expiration:{lot.public_id}:{lot.expiration_date.isoformat()}"
            active_keys.add(key)
            InventoryAlert.objects.update_or_create(
                deduplication_key=key,
                defaults={
                    "alert_type": InventoryAlert.TYPE_EXPIRATION,
                    "item": lot.item,
                    "lot": lot,
                    "message": f"Lot {lot.lot_code} expires on {lot.expiration_date.isoformat()}.",
                    "status": InventoryAlert.STATUS_OPEN,
                    "due_at": timezone.make_aware(datetime.combine(lot.expiration_date, time.min)),
                },
            )

    for item in InventoryItem.objects.prefetch_related("lots__reservations"):
        available = Decimal("0")
        for lot in item.lots.filter(status=InventoryLot.STATUS_ACTIVE):
            try:
                available += convert_quantity(lot.available_quantity, lot.unit, item.default_unit)
            except UnitConversionError:
                continue
        if available <= item.reorder_level:
            key = f"reorder:{item.public_id}"
            active_keys.add(key)
            InventoryAlert.objects.update_or_create(
                deduplication_key=key,
                defaults={
                    "alert_type": InventoryAlert.TYPE_REORDER if available == 0 else InventoryAlert.TYPE_LOW_STOCK,
                    "item": item,
                    "lot": None,
                    "message": f"{item.code} has {available} {item.default_unit} available; reorder level is {item.reorder_level}.",
                    "status": InventoryAlert.STATUS_OPEN,
                },
            )

    for reservation in InventoryReservation.objects.filter(
        status=InventoryReservation.STATUS_ACTIVE
    ).select_related("lot", "lot__item", "project"):
        key = f"reservation:{reservation.public_id}"
        active_keys.add(key)
        InventoryAlert.objects.update_or_create(
            deduplication_key=key,
            defaults={
                "alert_type": InventoryAlert.TYPE_RESERVATION,
                "item": reservation.lot.item,
                "lot": reservation.lot,
                "message": (
                    f"{reservation.quantity} {reservation.unit} from lot "
                    f"{reservation.lot.lot_code} is reserved for "
                    f"{reservation.project.code}."
                ),
                "status": InventoryAlert.STATUS_OPEN,
            },
        )
    InventoryAlert.objects.filter(status=InventoryAlert.STATUS_OPEN).exclude(deduplication_key__in=active_keys).update(status=InventoryAlert.STATUS_RESOLVED)
    return InventoryAlert.objects.filter(status=InventoryAlert.STATUS_OPEN).count()
