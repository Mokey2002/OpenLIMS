"""Bounded general-chat history, separate from permission-checked lab tools.

The browser carries a signed (not encrypted), user-bound transcript. It is never
an authorization token and contains no automatically collected tool responses.
"""

import re

from django.core import signing


CONTEXT_KEY = "general_conversation"
SALT = "assistant.general-conversation.v1"
MAX_AGE = 1800
MAX_EXCHANGES = 4
MAX_MESSAGE_CHARS = 4000
MAX_HISTORY_CHARS = 12000
MAX_TOKEN_CHARS = 24000
TRUNCATION_MARKER = "\n[Earlier message truncated.]"
FOLLOW_UP = re.compile(
    r"(?:why|why is that|how so|what does that mean|"
    r"tell me more|go on|elaborate|explain (?:further|in more detail)|"
    r"explain (?:it|that|this)(?: (?:more simply|in simpler terms|in more detail|"
    r"in (?:english|spanish|french|german|portuguese|italian|español)))?|"
    r"(?:make|keep) (?:it|that) (?:simpler|shorter|more detailed)|"
    r"(?:give me|show me|show) (?:an|another) example|"
    r"(?:compare|summarize) (?:them|that|it)|"
    r"what were we (?:talking about|discussing)|where were we|"
    r"recap (?:our|this) conversation)",
    re.IGNORECASE,
)


def _valid_history(messages):
    if not isinstance(messages, list) or not messages or len(messages) > MAX_EXCHANGES * 2:
        return False
    if len(messages) % 2:
        return False
    total = 0
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            return False
        if message["role"] != ("user" if index % 2 == 0 else "assistant"):
            return False
        content = message["content"]
        if not isinstance(content, str) or not content.strip() or len(content) > MAX_MESSAGE_CHARS:
            return False
        total += len(content)
    return total <= MAX_HISTORY_CHARS


def recall(context, user):
    token = (context or {}).get(CONTEXT_KEY)
    if not isinstance(token, str) or len(token) > MAX_TOKEN_CHARS:
        return []
    try:
        state = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except (signing.BadSignature, ValueError, TypeError):
        return []
    if not isinstance(state, dict) or state.get("user") != user.pk:
        return []
    messages = state.get("messages")
    return messages if _valid_history(messages) else []


def resume(message, context, user):
    """Recognize bounded explanation follow-ups, never commands or lab reads."""
    text = str(message or "").strip().rstrip(".!? ")
    text = re.sub(r"^(?:(?:can|could|would) you\s+)?(?:please\s+)?", "", text, flags=re.I)
    if FOLLOW_UP.fullmatch(text) and recall(context, user):
        from .conversation import general_question_result
        return general_question_result()
    return None


def _excerpt(content):
    if len(content) <= MAX_MESSAGE_CHARS:
        return content
    return content[:MAX_MESSAGE_CHARS - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER


def remember_exchange(user, history, message, answer):
    messages = list(history) if _valid_history(history) else []
    messages += [
        {"role": "user", "content": _excerpt(message)},
        {"role": "assistant", "content": _excerpt(answer)},
    ]
    while len(messages) > MAX_EXCHANGES * 2 or sum(len(item["content"]) for item in messages) > MAX_HISTORY_CHARS:
        messages = messages[2:]
    if not _valid_history(messages):
        return None
    token = signing.dumps({"user": user.pk, "messages": messages}, salt=SALT, compress=True)
    return token if len(token) <= MAX_TOKEN_CHARS else None


def remember_response(message, previous, result, user):
    """Save successful general answers; never replay lab evidence or failures."""
    from .conversation import is_courtesy_reply

    context = dict(result.get("context") or {})
    context.pop(CONTEXT_KEY, None)
    history = recall(previous, user)
    if result.get("response_type") == "general":
        if result.get("llm_enabled") and result.get("mode") in {"openai", "ollama"}:
            token = remember_exchange(user, history, message, result["answer"])
            if token:
                context[CONTEXT_KEY] = token
        elif history:
            # Keep the last successful exchange for a retry, without recording
            # a provider error or pretending the fallback answered the question.
            context[CONTEXT_KEY] = previous[CONTEXT_KEY]
    elif is_courtesy_reply(message) and history:
        context[CONTEXT_KEY] = previous[CONTEXT_KEY]
    result["context"] = context
