import re


ALLOWED_CONTEXT_KEYS = {
    "analytics",
    "batch_code",
    "comparison",
    "intent",
    "inventory_item_ids",
    "inventory_lot_id",
    "inventory_lot_ids",
    "investigation",
    "project_id",
    "request_text",
    "result_id",
    "result_ids",
    "sample_code",
    "sample_codes",
    "sample_id",
    "sample_ids",
}

FOLLOW_UP_PATTERN = re.compile(
    r"\b(?:also|and those|do that|include|make it|show it|plot it|graph it|"
    r"chart it|use it|export it|same|them|these|those)\b",
    re.IGNORECASE,
)


def _safe_value(value, depth=0):
    if depth > 3:
        return None
    if isinstance(value, dict):
        return {
            str(key)[:64]: safe
            for key, item in list(value.items())[:30]
            if (safe := _safe_value(item, depth + 1)) is not None
        }
    if isinstance(value, list):
        return [safe for item in value[:50] if (safe := _safe_value(item, depth + 1)) is not None]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value[:256] if isinstance(value, str) else value
    return str(value)[:256]


def sanitize_context(context):
    if not isinstance(context, dict):
        return {}
    return {
        key: _safe_value(value)
        for key, value in context.items()
        if key in ALLOWED_CONTEXT_KEYS
    }


def update_conversation_context(message, previous, result):
    previous = sanitize_context(previous)
    supplied = sanitize_context((result or {}).get("context") or {})
    if supplied:
        return supplied
    if FOLLOW_UP_PATTERN.search(str(message or "")) and previous:
        return previous
    return {}
