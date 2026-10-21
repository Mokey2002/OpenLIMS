import re


ALLOWED_CONTEXT_KEYS = {
    "explanation_language",
    "read_intent",
    "awaiting_read",
    "clarification_topic",
    "sample_registration",
    "guidance",
    "project_workflows",
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
    sanitized = {
        key: _safe_value(value)
        for key, value in context.items()
        if key in ALLOWED_CONTEXT_KEYS
    }
    token = context.get("provider_conversation")
    if isinstance(token, str) and len(token) <= 12000:
        sanitized["provider_conversation"] = token
    memory = context.get("dialogue_memory")
    if isinstance(memory, str) and len(memory) <= 6000:
        sanitized["dialogue_memory"] = memory
    from .general_conversation import CONTEXT_KEY, MAX_TOKEN_CHARS
    general = context.get(CONTEXT_KEY)
    if isinstance(general, str) and len(general) <= MAX_TOKEN_CHARS:
        sanitized[CONTEXT_KEY] = general
    return sanitized


def update_conversation_context(message, previous, result):
    from .conversation import is_courtesy_reply

    previous = sanitize_context(previous)
    supplied = sanitize_context((result or {}).get("context") or {})
    if (result or {}).get("response_type") == "general":
        # General chat must not carry an active lab record or pending operation.
        # Its verified transcript is attached separately after model generation.
        return {}
    if (result or {}).get("replace_context"):
        return supplied
    if supplied:
        return supplied
    # Courtesy replies should not discard the current task or its clarification.
    if is_courtesy_reply(message):
        return previous
    if (result or {}).get('routing', {}).get('route') in {'monitoring', 'identity'}:
        return {}
    if FOLLOW_UP_PATTERN.search(str(message or "")) and previous:
        return previous
    return {}
