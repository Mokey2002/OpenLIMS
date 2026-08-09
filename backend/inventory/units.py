from decimal import Decimal, InvalidOperation

UNIT_FACTORS = {
    "ul": ("volume", Decimal("0.000001")),
    "µl": ("volume", Decimal("0.000001")),
    "ml": ("volume", Decimal("0.001")),
    "l": ("volume", Decimal("1")),
    "ug": ("mass", Decimal("0.000001")),
    "µg": ("mass", Decimal("0.000001")),
    "mg": ("mass", Decimal("0.001")),
    "g": ("mass", Decimal("1")),
    "kg": ("mass", Decimal("1000")),
    "unit": ("count", Decimal("1")),
    "units": ("count", Decimal("1")),
    "each": ("count", Decimal("1")),
}


class UnitConversionError(ValueError):
    pass


def normalize_unit(unit):
    return str(unit or "").strip().lower().replace("μ", "µ")


def parse_quantity(value):
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise UnitConversionError("Quantity must be a valid number.") from exc
    if not quantity.is_finite() or quantity <= 0:
        raise UnitConversionError("Quantity must be greater than zero.")
    return quantity


def units_compatible(source_unit, target_unit):
    source = UNIT_FACTORS.get(normalize_unit(source_unit))
    target = UNIT_FACTORS.get(normalize_unit(target_unit))
    return bool(source and target and source[0] == target[0])


def convert_quantity(value, source_unit, target_unit):
    quantity = Decimal(str(value))
    source = UNIT_FACTORS.get(normalize_unit(source_unit))
    target = UNIT_FACTORS.get(normalize_unit(target_unit))
    if not source or not target or source[0] != target[0]:
        raise UnitConversionError(
            f"Units {source_unit!r} and {target_unit!r} are not compatible."
        )
    return quantity * source[1] / target[1]
