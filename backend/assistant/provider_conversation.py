"""Short-lived, user-bound conversational state; never an authorization token."""
import re
from django.core import signing

SALT = "assistant.provider.conversation.v1"
MAX_AGE = 1800
QUESTIONS = {
    "sample": "Which sample should I look at? You can reply with its sample ID.",
    "topic": "What topic should I look for in earlier experiments?",
    "count": "How many samples are you planning to process?",
    "procedure": "Which procedure will you use? Reply with its exact code.",
    "project": "Which project should I use? You can reply with its project code.",
    "lot": "Which lot do you have in mind? Reply with its lot code.",
    "procedures": "Which procedures should the workflow include, and in what order? Use their codes and versions, such as EXTRACT@1, QC@1.",
    "source": "Whose unfinished work should the handover cover? Reply with their username, or say ‘me’.",
    "recipient": "Who is taking over? Reply with their username.",
    "left": "Which experiment should we start with? Use its exact title or public ID.",
    "right": "Which other experiment should I compare it with?",
    "command": "What would you like me to do? Include the record and any filters or changes you have in mind.",
}
CONTINUATION = re.compile(r"^(?:and |also |what about |how about |same (?:for|but|with)|do (?:that|the same)|instead\b|actually\b|change (?:it|that)|use .+ instead|refresh\b|again\b)", re.I)


def remember(plan, user):
    from .provider_tools import DIRECT_TOOLS, validate_tool_plan
    valid = validate_tool_plan(plan)
    if not valid or valid["tool"] not in DIRECT_TOOLS:
        return None
    return signing.dumps({"user": user.pk, "plan": valid, "provider": plan.get("provider", "llm")}, salt=SALT, compress=True)


def recall(context, user):
    from .provider_tools import DIRECT_TOOLS, validate_tool_plan
    token = (context or {}).get("provider_conversation")
    if not isinstance(token, str) or len(token) > 12000:
        return None
    try:
        state = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except (signing.BadSignature, ValueError, TypeError):
        return None
    if not isinstance(state, dict) or state.get("user") != user.pk:
        return None
    valid = validate_tool_plan(state.get("plan"))
    if not valid or valid["tool"] not in DIRECT_TOOLS:
        return None
    return {**valid, "provider": state.get("provider", "llm")}


def missing_fields(plan):
    from .provider_tools import DIRECT_TOOLS
    return [key for key in DIRECT_TOOLS[plan["tool"]][2] if key != "version" and
            (key not in plan["arguments"] or not str(plan["arguments"][key]).strip())]


def classifier_context(context, user, message):
    from .general_conversation import CONTEXT_KEY, recall as recall_general

    # Do not pass arbitrary client plans or conversational tokens to a model.
    clean = {key: value for key, value in (context or {}).items()
             if key not in {"provider_conversation", "verified_feature_context", "dialogue_memory",
                            CONTEXT_KEY, "verified_general_history"}}
    previous = recall(context, user)
    if previous and (missing_fields(previous) or CONTINUATION.search(message.strip())):
        clean["verified_feature_context"] = {"tool": previous["tool"], "arguments": previous["arguments"]}
    history = recall_general(context, user)
    if history:
        clean["verified_general_history"] = history
    return clean


def resume(message, user, context):
    from .provider_tools import dispatch_tool, validate_tool_plan
    from .lab_helpers import response
    previous = recall(context, user)
    if not previous:
        if (context or {}).get("provider_conversation") and (CONTINUATION.search(message.strip()) or re.fullmatch(r"[\w.@+:/-]+", message.strip())):
            return response("That earlier request is no longer available. Tell me what you'd like to do again, and we'll start fresh.")
        return None
    text = message.strip()
    if text.lower().rstrip('.!') in {"cancel", "never mind", "nevermind", "start over", "forget that", "cancelar", "olvídalo"}:
        return response("No problem—we can start fresh. What would you like to do next?")
    missing = missing_fields(previous)
    if missing:
        field = missing[0]
        value = re.sub(r"^(?:it(?:'s| is)|use|for|to|from)\s+", "", text, flags=re.I).strip()
        quoted = len(value) > 1 and value[0] == value[-1] and value[0] in {'"', "'"}
        if quoted:
            value = value[1:-1]
        # Only consume unambiguous short answers. Full questions/new commands
        # continue through ordinary routing and can reset the topic.
        reserved = {"hi", "hello", "thanks", "thank", "yes", "no", "help", "stop", "cancel", "status", "again", "refresh", "ok", "okay", "understood"}
        simple = bool(re.fullmatch(r"[\w.@+:/-]+", value)) and value.casefold() not in reserved
        if field == "count":
            candidate = int(value) if re.fullmatch(r"\d{1,6}", value) else None
        else:
            candidate = value if simple or quoted else None
        if candidate is not None:
            if field in {"source", "recipient"} and str(candidate).casefold() in {"me", "myself", "mí"}:
                candidate = user.username
            plan = {**previous, "arguments": {**previous["arguments"], field: candidate}}
            if not validate_tool_plan(plan):
                hint = "Please enter a whole number between 1 and 100000." if field == "count" else QUESTIONS[field]
                return response(hint, clarification={"required": True, "fields": missing},
                                context={"provider_conversation": context["provider_conversation"]})
            return dispatch_tool(plan, user, context)
    if CONTINUATION.search(text):
        return response("I can help with that follow-up. If I can't interpret it, please tell me the feature and record you want to use.", route_unmatched=True)
    return None
