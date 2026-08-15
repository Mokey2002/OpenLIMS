import re


FILLER_TOKENS = {
    "a",
    "all",
    "an",
    "any",
    "current",
    "currently",
    "exactly",
    "just",
    "kindly",
    "me",
    "my",
    "now",
    "our",
    "please",
    "really",
    "right",
    "some",
    "the",
    "us",
    "you",
    "your",
}

COMMAND_FILLER_TOKENS = FILLER_TOKENS | {
    "can",
    "could",
    "do",
    "does",
    "for",
    "would",
    "will",
}

TOKEN_ALIASES = {
    "needed": "need",
    "needing": "need",
    "needs": "need",
    "require": "need",
    "required": "need",
    "requires": "need",
    "requiring": "need",
    "reviewed": "review",
    "reviewing": "review",
    "reviews": "review",
    "warnings": "warning",
}

CONTRACTIONS = {
    "can't": "cannot",
    "can’t": "cannot",
    "i'm": "i am",
    "i’m": "i am",
    "what's": "what is",
    "what’s": "what is",
    "who's": "who is",
    "who’s": "who is",
}


def intent_tokens(value):
    text = str(value or "").strip().lower()
    for contraction, replacement in CONTRACTIONS.items():
        text = text.replace(contraction, replacement)
    tokens = re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", text)
    return [TOKEN_ALIASES.get(token, token) for token in tokens]


def normalize_intent_text(value):
    return " ".join(intent_tokens(value))


def compact_command_text(value):
    return " ".join(
        token for token in intent_tokens(value) if token not in COMMAND_FILLER_TOKENS
    )


def contains_intent_phrase(message, phrase):
    """Match a phrase while allowing harmless conversational filler between words."""
    message_tokens = intent_tokens(message)
    phrase_tokens = intent_tokens(phrase)
    if not message_tokens or not phrase_tokens:
        return False

    for start, token in enumerate(message_tokens):
        if token != phrase_tokens[0]:
            continue
        phrase_index = 1
        if phrase_index == len(phrase_tokens):
            return True
        for candidate in message_tokens[start + 1 :]:
            if candidate == phrase_tokens[phrase_index]:
                phrase_index += 1
                if phrase_index == len(phrase_tokens):
                    return True
                continue
            if candidate in FILLER_TOKENS:
                continue
            break
    return False


def contains_any_intent_phrase(message, phrases):
    return any(contains_intent_phrase(message, phrase) for phrase in phrases)
