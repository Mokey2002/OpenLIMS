import re
from datetime import timedelta
from decimal import Decimal

from core.permissions import is_admin, is_tech
from django.db.models import Q
from django.utils import timezone
from events.models import Event
from inventory.models import (
    Container,
    InventoryItem,
    InventoryLot,
    InventoryReservation,
    Location,
)
from inventory.units import (
    UnitConversionError,
    convert_quantity,
    normalize_unit,
    parse_quantity,
    units_compatible,
)
from projects.models import Project
from rest_framework.exceptions import PermissionDenied, ValidationError
from samples.access import (
    get_sample_access_queryset,
    require_sample_modify_access,
    validate_sample_project_assignment,
)
from samples.models import Sample

from .models import AssistantAction
from .sample_operations import _resolve_project, assistant_bulk_max_records

SAMPLE_CODE_PATTERN = r"[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+"
NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}


def _parse_number(value):
    return parse_quantity(NUMBER_WORDS.get(str(value).lower(), value))


def _write_user(user):
    return is_admin(user) or is_tech(user)


def _sample_queryset(user):
    return get_sample_access_queryset(
        Sample.objects.select_related(
            "project",
            "container",
            "container__location",
            "container__parent",
        ),
        user,
    )


def _resolve_sample(code, user):
    cleaned = str(code or "").strip().rstrip(".?!,;:")
    sample = _sample_queryset(user).filter(sample_id__iexact=cleaned).first()
    if sample:
        return sample, None
    return None, f"Sample {cleaned} was not found or is not accessible."


def _resolve_one(queryset, label):
    matches = list(queryset[:2])
    if not matches:
        return None, f"{label} was not found."
    if len(matches) > 1:
        return None, f"{label} is ambiguous. Use its exact identifier."
    return matches[0], None


def _resolve_location(reference, *, kind=None):
    cleaned = str(reference or "").strip().rstrip(".?!,;:")
    stripped = re.sub(r"^(?:freezer|fridge|room|shelf)\s+", "", cleaned, flags=re.I)
    query = Q(name__iexact=cleaned) | Q(name__iexact=stripped)
    if stripped != cleaned:
        query |= Q(name__iexact=f"{kind or ''} {stripped}".strip())
    queryset = Location.objects.filter(query)
    if kind:
        queryset = queryset.filter(kind__iexact=kind)
    return _resolve_one(queryset, f"Location {cleaned}")


def _resolve_container(reference, *, location=None, kind=None, parent=None):
    cleaned = str(reference or "").strip().rstrip(".?!,;:")
    queryset = Container.objects.select_related("location", "parent").filter(
        container_id__iexact=cleaned
    )
    if location:
        queryset = queryset.filter(location=location)
    if kind:
        queryset = queryset.filter(kind__iexact=kind)
    if parent is not None:
        queryset = queryset.filter(parent=parent)
    return _resolve_one(queryset, f"Container {cleaned}")


def _resolve_item(reference):
    cleaned = str(reference or "").strip().rstrip(".?!,;:")
    return _resolve_one(
        InventoryItem.objects.filter(code__iexact=cleaned),
        f"Inventory item {cleaned}",
    )


def _resolve_lot(reference):
    cleaned = str(reference or "").strip().rstrip(".?!,;:")
    return _resolve_one(
        InventoryLot.objects.select_related(
            "item", "location", "container", "container__parent"
        ).filter(lot_code__iexact=cleaned),
        f"Lot {cleaned}",
    )


def _location_path(container):
    return container.path_label if container else "Unassigned"


def _sample_snapshot(sample):
    return {"container_id": sample.container_id}


def _lot_snapshot(lot):
    return {
        "quantity": str(lot.quantity),
        "available_quantity": str(lot.available_quantity),
        "unit": lot.unit,
        "status": lot.status,
        "expiration_date": lot.expiration_date.isoformat()
        if lot.expiration_date
        else None,
        "location_id": lot.location_id,
        "container_id": lot.container_id,
    }


def _project_label(project):
    if not project:
        return {"label": "Not project-scoped"}
    return {
        "id": project.id,
        "code": project.code,
        "name": project.name,
        "label": f"{project.code} — {project.name}",
    }


def _preview(user, operation, records, *, project=None, warnings=None):
    return {
        "title": "Proposed inventory operation",
        "operation": operation,
        "project": _project_label(project),
        "requested_user": {"id": user.id, "username": user.username},
        "records_affected": len(records),
        "matching_records": len(records),
        "excluded_count": 0,
        "records": records,
        "excluded": [],
        "warnings": warnings or [],
        "validation_errors": [],
        "maximum_records": assistant_bulk_max_records(),
    }


def _proposal(
    user,
    operation,
    summary,
    payload,
    records,
    *,
    project=None,
    links=None,
    warnings=None,
):
    preview = _preview(user, operation, records, project=project, warnings=warnings)
    return {
        "answer": (
            f"{preview['title']}\n\n"
            f"Operation: {operation}\n"
            f"Records affected: {len(records)}\n\n"
            "Review the exact preview and explicitly confirm before OpenLIMS changes anything."
        ),
        "links": links or [],
        "context": {},
        "skip_llm": True,
        "pending_action": {
            "type": AssistantAction.ACTION_INVENTORY_OPERATION,
            "summary": summary,
            "payload": {**payload, "preview": preview},
        },
    }


def _error(message, *, context=None):
    return {
        "answer": message,
        "links": [],
        "context": context or {},
        "skip_llm": True,
    }


def _sample_link(sample):
    return {
        "label": f"Open {sample.sample_id}",
        "url": f"/samples/{sample.id}",
        "kind": "sample",
        "extra": {"id": sample.id, "sample_id": sample.sample_id},
    }


def _inventory_link(label="Open inventory"):
    return {"label": label, "url": "/inventory", "kind": "inventory", "extra": {}}


def _read_expiring(message, user):
    match = re.search(
        r"\b(?:reagents?|inventory\s+lots?)\b.*\bexpire\b.*\bnext\s+(\d+)\s+days?\b",
        message,
        re.I,
    )
    if not match:
        return None
    days = int(match.group(1))
    today = timezone.localdate()
    cutoff = today + timedelta(days=days)
    lots = list(
        InventoryLot.objects.select_related("item", "location", "container")
        .filter(
            item__category=InventoryItem.CATEGORY_REAGENT,
            status=InventoryLot.STATUS_ACTIVE,
            expiration_date__gte=today,
            expiration_date__lte=cutoff,
        )
        .order_by("expiration_date", "lot_code")[:100]
    )
    if not lots:
        return _error(f"No active reagent lots expire in the next {days} days.")
    lines = [f"{len(lots)} reagent lot(s) expire in the next {days} days:"]
    lines.extend(
        f"- {lot.item.code} / {lot.lot_code}: {lot.expiration_date} — {lot.available_quantity} {lot.unit} available"
        for lot in lots
    )
    return {
        "answer": "\n".join(lines),
        "links": [_inventory_link()],
        "context": {"inventory_lot_ids": [lot.id for lot in lots]},
        "skip_llm": True,
    }


def _available_in_default_unit(item):
    total = Decimal("0")
    for lot in item.lots.filter(status=InventoryLot.STATUS_ACTIVE).prefetch_related(
        "reservations"
    ):
        total += convert_quantity(lot.available_quantity, lot.unit, item.default_unit)
    return total


def _read_below_reorder(message, user):
    if not re.search(r"\binventory\b.*\bbelow\b.*\breorder\s+level\b", message, re.I):
        return None
    below = []
    for item in InventoryItem.objects.prefetch_related("lots__reservations").all():
        try:
            available = _available_in_default_unit(item)
        except UnitConversionError:
            continue
        if available < item.reorder_level:
            below.append((item, available))
    if not below:
        return _error("No inventory items are below their reorder level.")
    lines = [f"{len(below)} inventory item(s) are below reorder level:"]
    lines.extend(
        f"- {item.code} — {item.name}: {available} {item.default_unit} available; reorder at {item.reorder_level}"
        for item, available in below
    )
    return {
        "answer": "\n".join(lines),
        "links": [_inventory_link()],
        "context": {"inventory_item_ids": [item.id for item, _ in below]},
        "skip_llm": True,
    }


def _read_sample_location(message, user):
    match = re.search(
        rf"\bwhere\s+is\s+sample\s+({SAMPLE_CODE_PATTERN})\b", message, re.I
    )
    if not match:
        return None
    sample, error = _resolve_sample(match.group(1), user)
    if error:
        return _error(error)
    return {
        "answer": f"Sample {sample.sample_id} is stored at {_location_path(sample.container)}.",
        "links": [_sample_link(sample)],
        "context": {"sample_id": sample.id, "sample_code": sample.sample_id},
        "skip_llm": True,
    }


def _read_last_move(message, user, context=None):
    context = context or {}
    match = re.search(
        rf"\bwho\s+last\s+moved\s+(?:sample\s+)?({SAMPLE_CODE_PATTERN})\b",
        message,
        re.I,
    )
    if not match and not re.search(r"\bwho\s+last\s+moved\s+it\b", message, re.I):
        return None
    if match:
        sample, error = _resolve_sample(match.group(1), user)
    else:
        sample = _sample_queryset(user).filter(id=context.get("sample_id")).first()
        error = None if sample else "Tell me which sample you mean."
    if error:
        return _error(error)
    event = (
        Event.objects.select_related("actor")
        .filter(entity_type="Sample", entity_id=str(sample.id), action="SAMPLE_MOVED")
        .order_by("-timestamp")
        .first()
    )
    if not event:
        return _error(
            f"No audited assistant move has been recorded for sample {sample.sample_id}.",
            context={"sample_id": sample.id, "sample_code": sample.sample_id},
        )
    before = (event.payload or {}).get("before", {}).get("location", "Unassigned")
    after = (event.payload or {}).get("after", {}).get("location", "Unassigned")
    actor = event.actor.username if event.actor else "Unknown user"
    return {
        "answer": (
            f"{actor} last moved sample {sample.sample_id} on {event.timestamp.isoformat()} "
            f"from {before} to {after}."
        ),
        "links": [_sample_link(sample)],
        "context": {"sample_id": sample.id, "sample_code": sample.sample_id},
        "skip_llm": True,
    }


def _read_stored_in(message, user):
    match = re.search(
        r"\bwhat\s+is\s+stored\s+in\s+freezer\s+(.+?),\s*rack\s+(.+?)[.?!]?$",
        message,
        re.I,
    )
    if not match:
        return None
    location, error = _resolve_location(match.group(1), kind="FREEZER")
    if error:
        return _error(error)
    rack, error = _resolve_container(match.group(2), location=location, kind="RACK")
    if error:
        return _error(error)
    container_ids = list(rack.children.values_list("id", flat=True)) + [rack.id]
    samples = list(
        _sample_queryset(user)
        .filter(container_id__in=container_ids)
        .order_by("sample_id")[:100]
    )
    lots = list(
        InventoryLot.objects.select_related("item")
        .filter(container_id__in=container_ids)
        .order_by("lot_code")[:100]
    )
    if not samples and not lots:
        return _error(
            f"Nothing accessible is stored in {location.name} / {rack.container_id}."
        )
    lines = [f"Stored in {location.name} / {rack.container_id}:"]
    lines.extend(
        f"- Sample {sample.sample_id} — {_location_path(sample.container)}"
        for sample in samples
    )
    lines.extend(
        f"- Lot {lot.lot_code} ({lot.item.code}) — {lot.quantity} {lot.unit}"
        for lot in lots
    )
    return {
        "answer": "\n".join(lines),
        "links": [_sample_link(sample) for sample in samples[:20]]
        + [_inventory_link()],
        "context": {
            "sample_ids": [sample.id for sample in samples],
            "inventory_lot_ids": [lot.id for lot in lots],
        },
        "skip_llm": True,
    }


def _propose_sample_move(message, user):
    match = re.search(
        rf"\bmove\s+sample\s+({SAMPLE_CODE_PATTERN})\s+to\s+freezer\s+(.+?),\s*rack\s+(.+?),\s*box\s+(.+?)[.?!]?$",
        message,
        re.I,
    )
    if not match:
        return None
    if not _write_user(user):
        return _error("Only tech or admin users can move samples.")
    sample, error = _resolve_sample(match.group(1), user)
    if error:
        return _error(error)
    try:
        require_sample_modify_access(user, sample)
    except (PermissionDenied, ValidationError) as exc:
        return _error(str(exc))
    location, error = _resolve_location(match.group(2), kind="FREEZER")
    if error:
        return _error(error)
    rack, error = _resolve_container(match.group(3), location=location, kind="RACK")
    if error:
        return _error(error)
    box, error = _resolve_container(
        match.group(4), location=location, kind="BOX", parent=rack
    )
    if error:
        return _error(error)
    if sample.container_id == box.id:
        return _error(
            f"Sample {sample.sample_id} is already stored at {box.path_label}."
        )
    record = {
        "id": sample.id,
        "label": sample.sample_id,
        "current": {"location": _location_path(sample.container)},
        "proposed": {"location": box.path_label},
    }
    proposal = _proposal(
        user,
        "MOVE_SAMPLE",
        f"Move {sample.sample_id} to {box.path_label}",
        {
            "operation": "MOVE_SAMPLE",
            "sample_id": sample.id,
            "sample_snapshot": _sample_snapshot(sample),
            "target_container_id": box.id,
            "target_container_snapshot": {
                "location_id": box.location_id,
                "parent_id": box.parent_id,
                "kind": box.kind,
            },
        },
        [record],
        project=sample.project,
        links=[_sample_link(sample)],
    )
    proposal["context"] = {"sample_id": sample.id, "sample_code": sample.sample_id}
    return proposal


def _propose_reserve(message, user):
    match = re.search(
        r"\breserve\s+([0-9]+(?:\.[0-9]+)?|one|two|three|four|five|six|seven|eight|nine|ten)\s+([A-Za-zµμ]+)\s+of\s+reagent\s+([A-Za-z0-9_-]+)\s+for\s+(.+?)[.?!]?$",
        message,
        re.I,
    )
    if not match:
        return None
    if not _write_user(user):
        return _error("Only tech or admin users can reserve inventory.")
    try:
        quantity = _parse_number(match.group(1))
    except UnitConversionError as exc:
        return _error(str(exc))
    unit = normalize_unit(match.group(2))
    item, error = _resolve_item(match.group(3))
    if error:
        return _error(error)
    if item.category != InventoryItem.CATEGORY_REAGENT:
        return _error(f"{item.code} is not configured as a reagent.")
    if normalize_unit(unit) in {"unit", "units", "each"}:
        unit = normalize_unit(item.default_unit)
    project, error = _resolve_project(match.group(4), user, write=True)
    if error:
        return _error(error)
    if not units_compatible(unit, item.default_unit):
        return _error(
            f"Unit {unit} is incompatible with {item.default_unit} for {item.code}."
        )
    today = timezone.localdate()
    selected = None
    for lot in (
        item.lots.select_related("item")
        .prefetch_related("reservations")
        .filter(status=InventoryLot.STATUS_ACTIVE)
        .filter(Q(expiration_date__isnull=True) | Q(expiration_date__gte=today))
        .order_by("expiration_date", "lot_code")
    ):
        try:
            required = convert_quantity(quantity, unit, lot.unit)
        except UnitConversionError:
            continue
        if lot.available_quantity >= required:
            selected = lot
            break
    if not selected:
        return _error(
            f"No active lot of {item.code} has enough compatible available quantity."
        )
    required_lot_unit = convert_quantity(quantity, unit, selected.unit)
    record = {
        "id": selected.id,
        "label": f"{item.code} / {selected.lot_code}",
        "current": {"available": f"{selected.available_quantity} {selected.unit}"},
        "proposed": {
            "reserve": f"{quantity} {unit}",
            "available_after": f"{selected.available_quantity - required_lot_unit} {selected.unit}",
        },
    }
    return _proposal(
        user,
        "RESERVE_REAGENT",
        f"Reserve {quantity} {unit} of {item.code} for {project.code}",
        {
            "operation": "RESERVE_REAGENT",
            "lot_id": selected.id,
            "lot_snapshot": _lot_snapshot(selected),
            "project_id": project.id,
            "quantity": str(quantity),
            "unit": unit,
        },
        [record],
        project=project,
        links=[_inventory_link()],
    )


def _propose_consume(message, user):
    match = re.search(
        r"\brecord\s+consumption\s+of\s+([0-9]+(?:\.[0-9]+)?)\s+([A-Za-zµμ]+)\s+from\s+lot\s+([A-Za-z0-9_-]+)[.?!]?$",
        message,
        re.I,
    )
    if not match:
        return None
    if not _write_user(user):
        return _error("Only tech or admin users can consume inventory.")
    try:
        quantity = parse_quantity(match.group(1))
    except UnitConversionError as exc:
        return _error(str(exc))
    unit = normalize_unit(match.group(2))
    lot, error = _resolve_lot(match.group(3))
    if error:
        return _error(error)
    if lot.status != InventoryLot.STATUS_ACTIVE:
        return _error(f"Lot {lot.lot_code} is {lot.status} and cannot be consumed.")
    try:
        amount = convert_quantity(quantity, unit, lot.unit)
    except UnitConversionError as exc:
        return _error(str(exc))
    if amount > lot.available_quantity:
        return _error(
            f"Lot {lot.lot_code} has only {lot.available_quantity} {lot.unit} unreserved; consumption cannot make quantity negative."
        )
    record = {
        "id": lot.id,
        "label": f"{lot.item.code} / {lot.lot_code}",
        "current": {"quantity": f"{lot.quantity} {lot.unit}"},
        "proposed": {
            "quantity": f"{lot.quantity - amount} {lot.unit}",
            "consumed": f"{quantity} {unit}",
        },
    }
    return _proposal(
        user,
        "CONSUME_LOT",
        f"Consume {quantity} {unit} from {lot.lot_code}",
        {
            "operation": "CONSUME_LOT",
            "lot_id": lot.id,
            "lot_snapshot": _lot_snapshot(lot),
            "quantity": str(quantity),
            "unit": unit,
        },
        [record],
        links=[_inventory_link()],
    )


def _propose_mark_expired(message, user):
    match = re.search(
        r"\bmark\s+lot\s+([A-Za-z0-9_-]+)\s+as\s+expired\b", message, re.I
    )
    if not match:
        return None
    if not _write_user(user):
        return _error("Only tech or admin users can mark inventory expired.")
    lot, error = _resolve_lot(match.group(1))
    if error:
        return _error(error)
    if lot.status == InventoryLot.STATUS_EXPIRED:
        return _error(f"Lot {lot.lot_code} is already expired.")
    record = {
        "id": lot.id,
        "label": f"{lot.item.code} / {lot.lot_code}",
        "current": {"status": lot.status},
        "proposed": {"status": InventoryLot.STATUS_EXPIRED},
    }
    return _proposal(
        user,
        "MARK_LOT_EXPIRED",
        f"Mark lot {lot.lot_code} expired",
        {
            "operation": "MARK_LOT_EXPIRED",
            "lot_id": lot.id,
            "lot_snapshot": _lot_snapshot(lot),
        },
        [record],
        links=[_inventory_link()],
    )


def route_inventory_operations(message, user, context=None):
    text = str(message or "").strip()
    context = context or {}
    for router in [
        _propose_sample_move,
        _propose_reserve,
        _propose_consume,
        _propose_mark_expired,
    ]:
        result = router(text, user)
        if result:
            return result
    last_move = _read_last_move(text, user, context)
    if last_move:
        return last_move
    for router in [
        _read_expiring,
        _read_below_reorder,
        _read_sample_location,
        _read_stored_in,
    ]:
        result = router(text, user)
        if result:
            return result
    return None


def _audit(action, entity_type, entity_id, event_action, payload):
    Event.objects.create(
        entity_type=entity_type,
        entity_id=str(entity_id),
        action=event_action,
        actor=action.requested_by,
        payload={
            **payload,
            "assistant_action_id": str(action.id),
            "idempotency_key": str(action.idempotency_key),
            "source": "assistant_confirmation",
        },
    )


def execute_inventory_operation(action):
    payload = action.payload or {}
    operation = payload.get("operation")
    if operation not in {
        "MOVE_SAMPLE",
        "RESERVE_REAGENT",
        "CONSUME_LOT",
        "MARK_LOT_EXPIRED",
    }:
        raise ValueError("Unsupported inventory operation.")
    if not _write_user(action.requested_by):
        raise PermissionDenied(
            "Only tech or admin users can confirm inventory operations."
        )

    if operation == "MOVE_SAMPLE":
        sample = (
            Sample.objects.select_for_update()
            .filter(id=payload.get("sample_id"))
            .first()
        )
        if not sample:
            raise ValueError("The sample no longer exists.")
        sample = Sample.objects.select_related(
            "project", "container", "container__location"
        ).get(id=sample.id)
        require_sample_modify_access(action.requested_by, sample)
        if _sample_snapshot(sample) != (payload.get("sample_snapshot") or {}):
            raise ValueError(
                "The sample location changed after preview; no move was applied."
            )
        target_row = (
            Container.objects.select_for_update()
            .filter(id=payload.get("target_container_id"))
            .first()
        )
        if not target_row:
            raise ValueError("The target container no longer exists.")
        target = Container.objects.select_related("location", "parent").get(
            id=target_row.id
        )
        target_snapshot = payload.get("target_container_snapshot") or {}
        if {
            "location_id": target.location_id,
            "parent_id": target.parent_id,
            "kind": target.kind,
        } != target_snapshot:
            raise ValueError(
                "The target container changed after preview; no move was applied."
            )
        if (
            target.kind.upper() != "BOX"
            or not target.parent
            or target.parent.kind.upper() != "RACK"
        ):
            raise ValueError("The target must be a box inside a rack.")
        before_path = _location_path(sample.container)
        sample.container = target
        sample.save(update_fields=["container", "updated_at"])
        _audit(
            action,
            "Sample",
            sample.id,
            "SAMPLE_MOVED",
            {
                "sample_id": sample.id,
                "sample_code": sample.sample_id,
                "project_id": sample.project_id,
                "before": {
                    "container_id": payload["sample_snapshot"].get("container_id"),
                    "location": before_path,
                },
                "after": {"container_id": target.id, "location": target.path_label},
                "changed_fields": ["container_id"],
            },
        )
        return {
            "operation": operation,
            "succeeded_count": 1,
            "failed_count": 0,
            "succeeded": [{"id": sample.id, "label": sample.sample_id}],
            "failed": [],
            "context": {"sample_id": sample.id, "sample_code": sample.sample_id},
        }

    lot = (
        InventoryLot.objects.select_for_update()
        .filter(id=payload.get("lot_id"))
        .first()
    )
    if not lot:
        raise ValueError("The inventory lot no longer exists.")
    lot = (
        InventoryLot.objects.select_related("item", "location", "container")
        .prefetch_related("reservations")
        .get(id=lot.id)
    )
    if _lot_snapshot(lot) != (payload.get("lot_snapshot") or {}):
        raise ValueError(
            "The inventory lot changed after preview; no update was applied."
        )

    if operation == "RESERVE_REAGENT":
        project = Project.objects.filter(id=payload.get("project_id")).first()
        if not project:
            raise ValueError("The reservation project no longer exists.")
        validate_sample_project_assignment(action.requested_by, project)
        quantity = parse_quantity(payload.get("quantity"))
        unit = payload.get("unit")
        required = convert_quantity(quantity, unit, lot.unit)
        if (
            lot.status != InventoryLot.STATUS_ACTIVE
            or required > lot.available_quantity
        ):
            raise ValueError("The lot no longer has enough active, available quantity.")
        reservation = InventoryReservation.objects.create(
            lot=lot,
            project=project,
            quantity=quantity,
            unit=unit,
            created_by=action.requested_by,
        )
        lot._prefetched_objects_cache.pop("reservations", None)
        _audit(
            action,
            "InventoryLot",
            lot.id,
            "INVENTORY_RESERVED",
            {
                "item_code": lot.item.code,
                "lot_code": lot.lot_code,
                "project_id": project.id,
                "project_code": project.code,
                "quantity": str(quantity),
                "unit": unit,
                "reservation_id": reservation.id,
                "before": payload["lot_snapshot"],
                "after": {
                    **_lot_snapshot(lot),
                    "available_quantity": str(lot.available_quantity),
                },
            },
        )
        result_id = reservation.id
        label = f"Reservation #{reservation.id}"
    elif operation == "CONSUME_LOT":
        quantity = parse_quantity(payload.get("quantity"))
        unit = payload.get("unit")
        amount = convert_quantity(quantity, unit, lot.unit)
        if lot.status != InventoryLot.STATUS_ACTIVE:
            raise ValueError("Only active lots can be consumed.")
        if amount > lot.available_quantity or amount > lot.quantity:
            raise ValueError("Consumption would reduce available quantity below zero.")
        before = _lot_snapshot(lot)
        lot.quantity -= amount
        if lot.quantity == 0:
            lot.status = InventoryLot.STATUS_DEPLETED
        lot.save(update_fields=["quantity", "status", "updated_at"])
        _audit(
            action,
            "InventoryLot",
            lot.id,
            "INVENTORY_CONSUMED",
            {
                "item_code": lot.item.code,
                "lot_code": lot.lot_code,
                "quantity_consumed": str(quantity),
                "unit": unit,
                "before": before,
                "after": _lot_snapshot(lot),
            },
        )
        result_id = lot.id
        label = lot.lot_code
    else:
        if lot.status == InventoryLot.STATUS_EXPIRED:
            raise ValueError("The lot is already expired.")
        before = _lot_snapshot(lot)
        lot.status = InventoryLot.STATUS_EXPIRED
        lot.save(update_fields=["status", "updated_at"])
        _audit(
            action,
            "InventoryLot",
            lot.id,
            "INVENTORY_LOT_EXPIRED",
            {
                "item_code": lot.item.code,
                "lot_code": lot.lot_code,
                "before": before,
                "after": _lot_snapshot(lot),
            },
        )
        result_id = lot.id
        label = lot.lot_code

    return {
        "operation": operation,
        "succeeded_count": 1,
        "failed_count": 0,
        "succeeded": [{"id": result_id, "label": label}],
        "failed": [],
        "context": {"inventory_lot_id": lot.id},
    }
