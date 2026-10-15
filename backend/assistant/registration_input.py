"""Strict field parsing for a confirmed registration request, without ignored text."""
import json
import math
import re


def _invalid_constant(value):
    raise ValueError(f"{value} is not a finite JSON value.")


def _validate_json(value, depth=0):
    if depth > 20:
        raise ValueError("Custom field values are nested too deeply.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Custom field numbers must be finite.")
    if isinstance(value, (dict, list)):
        for item in (value.values() if isinstance(value, dict) else value):
            _validate_json(item, depth + 1)


def parse_registration_fields(text):
    values = {}
    remaining = text.strip()
    if not remaining:
        raise ValueError("Supply field_name=value after 'with'.")
    while remaining:
        match = re.match(r"([A-Za-z][A-Za-z0-9_]*)\s*=\s*", remaining)
        if not match:
            raise ValueError("Use comma-separated field_name=value pairs; no extra instructions.")
        name = match[1]
        if name in values:
            raise ValueError(f"Field {name} is repeated. Supply it only once.")
        raw = remaining[match.end():]
        if raw.startswith(('"', "[", "{")):
            try:
                value, end = json.JSONDecoder(parse_constant=_invalid_constant).raw_decode(raw)
            except (ValueError, RecursionError) as exc:
                raise ValueError(f"Invalid JSON value for {name}; check quotes and brackets.") from exc
            remaining = raw[end:].strip()
            if remaining in {".", "?", "!"}:
                remaining = ""
            if remaining and not remaining.startswith(","):
                raise ValueError("Separate fields with commas; no trailing instructions.")
        else:
            raw, separator, tail = raw.partition(",")
            raw = raw.strip()
            if not separator:
                raw = raw.rstrip(".?!")
            if not raw or ";" in raw or "=" in raw or re.search(r"\b(?:and|then)\s+(?:create|register|delete|approve|assign|archive|update|cancel)\b", raw, re.I):
                raise ValueError(f"Supply a value for {name}; quote text containing instructions as a JSON string.")
            if raw in {"NaN", "Infinity", "-Infinity"}:
                raise ValueError(f"{name} must contain a finite value; quote literal text.")
            try:
                value = json.loads(raw)
            except ValueError:
                value = raw
            remaining = "," + tail if separator else ""
        _validate_json(value)
        values[name] = value
        if remaining:
            remaining = remaining[1:].strip()
            if not remaining:
                raise ValueError("A trailing comma needs another field_name=value pair.")
    return values
