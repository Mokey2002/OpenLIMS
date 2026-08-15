import re

from django.conf import settings
from django.utils import timezone

from .intent_matching import contains_any_intent_phrase, normalize_intent_text
from .suggestions import comparison_prompt, without_empty


OPENLIMS_SUGGESTIONS = [
    "What needs my attention?",
    "Show samples needing QC review",
    "What can you do?",
]


def _utility_response(answer, suggestions=None):
    return {
        "answer": answer,
        "links": [],
        "suggestions": suggestions or OPENLIMS_SUGGESTIONS,
        "response_type": "utility",
        "skip_llm": True,
    }


def _current_app_time():
    now = timezone.now()
    if timezone.is_aware(now):
        now = timezone.localtime(now)
    hour = now.strftime("%I").lstrip("0") or "0"
    clock = f"{hour}:{now.strftime('%M %p')}"
    date = f"{now.strftime('%A, %B')} {now.day}, {now.year}"
    zone = str(getattr(settings, "TIME_ZONE", "UTC") or "UTC")
    return clock, date, zone


def _is_time_question(message):
    return contains_any_intent_phrase(
        message,
        [
            "what time is it",
            "what time it is",
            "what is the current time",
            "tell me the time",
            "tell me what time it is",
            "give me the current time",
            "show the current time",
        ],
    )


def _is_date_question(message):
    lower = str(message or "").strip().lower().replace("’", "'")
    return bool(
        contains_any_intent_phrase(
            message,
            [
                "what date is it",
                "what is the current date",
                "what day is it",
                "tell me the date",
            ],
        )
        or re.search(r"\b(?:what(?:'s| is)\s+)?today'?s\s+date\b", lower)
    )


def _is_greeting(normalized):
    return bool(
        re.fullmatch(
            r"(?:hello|hi|hey|good morning|good afternoon|good evening)(?: there)?",
            normalized,
        )
    )


def _is_thanks(normalized):
    return bool(
        re.fullmatch(
            r"(?:thanks|thank you|thanks a lot|great thanks|okay thanks|ok thanks)",
            normalized,
        )
    )


def _is_help_question(message, normalized):
    if normalized in {"help", "assistant help", "show help"}:
        return True
    return contains_any_intent_phrase(
        message,
        [
            "what can you do",
            "how can you help",
            "what questions can i ask",
            "show me your capabilities",
            "what are your capabilities",
        ],
    )


def route_conversation_utility(message, user=None):
    normalized = normalize_intent_text(message)
    if not normalized:
        return None

    if _is_time_question(message):
        clock, date, zone = _current_app_time()
        return _utility_response(
            f"The current OpenLIMS time is {clock} on {date} ({zone})."
        )

    if _is_date_question(message):
        _clock, date, zone = _current_app_time()
        return _utility_response(
            f"The current OpenLIMS date is {date} ({zone})."
        )

    if contains_any_intent_phrase(
        message,
        ["who are you", "what are you", "what is this assistant"],
    ):
        return _utility_response(
            "I'm the OpenLIMS Assistant. I use permission-filtered OpenLIMS tools "
            "for laboratory records and a separately constrained language model for "
            "general questions. The language model never receives direct database access."
        )

    if _is_help_question(message, normalized):
        return _utility_response(
            "I can use permission-filtered tools to find and summarize accessible "
            "samples, projects, results, QC work, "
            "inventory, migrations, sequences, SOPs, notifications, and system status. "
            "I can compare or investigate records, create charts when requested, and "
            "preview supported actions for explicit confirmation. I can also answer "
            "basic conversational and general-knowledge questions when an LLM is enabled.",
            suggestions=without_empty(
                "What needs my attention?",
                "Which samples need QC review?",
                comparison_prompt(user, "project") or "Compare two projects",
                "What time is it?",
            ),
        )

    if _is_greeting(normalized):
        return _utility_response(
            "Hello! What would you like to check in OpenLIMS?"
        )

    if _is_thanks(normalized):
        return _utility_response("You're welcome.")

    return None


def general_question_result():
    return {
        "answer": (
            "I couldn't answer that general question right now. No OpenLIMS data "
            "or workflow action was accessed."
        ),
        "links": [],
        "suggestions": OPENLIMS_SUGGESTIONS,
        "response_type": "general",
    }
