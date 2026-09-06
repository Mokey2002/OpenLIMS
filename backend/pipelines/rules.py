"""Typed comparison shared by previews and pinned workflow execution."""
import math
from datetime import date
from rest_framework.exceptions import ValidationError


def normalize_expected(field, operator, value):
    if operator not in {"EQ", "NE", "GT", "GTE", "LT", "LTE", "IN"}:
        raise ValidationError("Unsupported operator. / Operador no compatible.")
    kind = field["type"]
    if operator in {"GT", "GTE", "LT", "LTE"} and kind != "number":
        raise ValidationError("Ordering requires a numeric measurement. / Se requiere una medición numérica.")
    def convert(v):
        if kind == "number":
            try:
                if isinstance(v, bool):
                    raise ValueError()
                result = float(v)
                if not math.isfinite(result):
                    raise ValueError()
                return result
            except (ValueError, TypeError, OverflowError):
                raise ValidationError("Expected a finite number. / Se requiere un número finito.") from None
        if kind == "boolean":
            if isinstance(v, bool):
                return v
            if isinstance(v, str) and v.lower() in {"true", "false"}:
                return v.lower() == "true"
            raise ValidationError("Expected true or false. / Se requiere true o false.")
        if not isinstance(v, str) or (kind == "select" and v not in field["choices"]):
            raise ValidationError("Invalid comparison value. / Valor de comparación inválido.")
        if kind == "date":
            try:
                if date.fromisoformat(v).isoformat() != v:
                    raise ValueError()
            except ValueError:
                raise ValidationError("Use an ISO date. / Use una fecha ISO.") from None
        return v
    if operator == "IN":
        options = value if isinstance(value, list) else str(value).split(",")
        if not 1 <= len(options) <= 100:
            raise ValidationError("Use 1–100 options. / Use entre 1 y 100 opciones.")
        return [convert(v.strip() if isinstance(v, str) else v) for v in options]
    return convert(value)


def matches(actual, operator, expected):
    # Missing measurements never activate a branch, including NE.
    if actual is None or actual == "":
        return False
    if operator == "IN":
        return actual in expected
    if operator == "EQ":
        return actual == expected
    if operator == "NE":
        return actual != expected
    if type(actual) not in (int, float) or not math.isfinite(actual):
        return False
    return {"GT": actual > expected, "GTE": actual >= expected,
            "LT": actual < expected, "LTE": actual <= expected}[operator]
