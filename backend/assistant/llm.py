import json
import logging
import urllib.request

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

ASSISTANT_ROUTES = {
    "attention",
    "barcode",
    "calculation",
    "chart",
    "clarification",
    "comparison",
    "confirmed_action",
    "general",
    "identity",
    "investigation",
    "inventory",
    "migration",
    "monitoring",
    "notifications",
    "qc",
    "record_search",
    "reporting",
    "samples",
    "sequences",
    "sop",
    "unknown",
    "work_items",
}

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


def llm_provider():
    return str(
        getattr(settings, "OPENLIMS_ASSISTANT_LLM_PROVIDER", "openai")
    ).strip().lower()


def assistant_llm_enabled():
    enabled = bool(getattr(settings, "OPENLIMS_ASSISTANT_LLM_ENABLED", False))

    if not enabled:
        return False

    provider = llm_provider()

    if provider == "openai":
        return bool(getattr(settings, "OPENAI_API_KEY", "") and OpenAI is not None)

    if provider == "ollama":
        return bool(
            getattr(settings, "OLLAMA_BASE_URL", "")
            and getattr(settings, "OLLAMA_MODEL", "")
        )

    return False


def assistant_llm_routing_enabled():
    return bool(
        getattr(settings, "OPENLIMS_ASSISTANT_LLM_ROUTING_ENABLED", True)
    ) and assistant_llm_enabled()


def model_info_for(mode, error=""):
    if mode == "openai":
        model = getattr(settings, "OPENAI_MODEL", "gpt-5")
        return {
            "provider": "openai",
            "model": model,
            "display_name": f"OpenAI · {model}",
            "is_llm": True,
            "error": error,
        }

    if mode == "ollama":
        model = getattr(settings, "OLLAMA_MODEL", "llama3.1")
        return {
            "provider": "ollama",
            "model": model,
            "display_name": f"Ollama · {model}",
            "is_llm": True,
            "error": error,
        }

    return {
        "provider": "openlims",
        "model": "rules",
        "display_name": "OpenLIMS Rules",
        "is_llm": False,
        "error": error,
    }


def configured_model_info():
    if not assistant_llm_enabled():
        return model_info_for("openlims")

    provider = llm_provider()

    if provider == "openai":
        return model_info_for("openai")

    if provider == "ollama":
        return model_info_for("ollama")

    return model_info_for("openlims")


def safe_json(data):
    return json.dumps(data, indent=2, default=str)


def build_assistant_prompt(message, tool_result):
    tool_context = {
        "answer": tool_result.get("answer", ""),
        "links": tool_result.get("links", []),
        "suggestions": tool_result.get("suggestions", []),
        "chart": tool_result.get("chart"),
    }

    return f"""
You are the OpenLIMS Assistant.

You help users understand records in a laboratory information management system.

Rules:
- You are read-only.
- Do not claim you changed, created, deleted, approved, imported, or updated anything.
- Only summarize the provided OpenLIMS tool result.
- Preserve important IDs, sample IDs, project codes, migration job numbers, statuses, and errors.
- Do not invent data that is not present in the tool result.
- Do not claim that unlisted samples, results, or projects are normal, clear, or unaffected.
- Preserve the exact scope of the tool result and do not generalize beyond it.
- Keep the answer concise and useful.

User question:
{message}

OpenLIMS tool result:
{safe_json(tool_context)}
"""


GENERAL_ASSISTANT_SYSTEM_MESSAGE = (
    "You are the OpenLIMS Assistant in constrained general-conversation mode. "
    "Answer the user's non-OpenLIMS question concisely. You have no database, "
    "record, tool, web, or workflow access in this mode. Never claim that you "
    "looked up or changed OpenLIMS data. If the request actually requires "
    "OpenLIMS records or an application action, say that it needs a supported "
    "OpenLIMS tool instead of inventing a result. Admit uncertainty and avoid "
    "presenting high-stakes medical, legal, or financial guidance as definitive."
)


def build_general_assistant_prompt(message):
    now = timezone.now()
    if timezone.is_aware(now):
        now = timezone.localtime(now)
    current_time = now.isoformat()
    app_timezone = str(getattr(settings, "TIME_ZONE", "UTC") or "UTC")
    return f"""
Answer this general user question without using or implying access to OpenLIMS data.

Current OpenLIMS application time: {current_time}
Application timezone: {app_timezone}

User question:
{message}
"""


def build_route_classifier_prompt(message, context=None):
    context = context or {}
    active_context = [
        key
        for key in ["comparison", "investigation", "intent", "result_id", "sample_id"]
        if context.get(key)
    ]
    route_descriptions = {
        "attention": "general priorities, pending items, or what needs review",
        "barcode": "create or reprint sample barcode labels",
        "calculation": "counts, percentages, or worklists",
        "chart": "an explicitly requested graph, plot, or chart",
        "clarification": "an underspecified samples, results, failures, or inventory request",
        "comparison": "compare samples, projects, or batches; trends, outliers, bottlenecks",
        "confirmed_action": "run alignment/import/report or create migration mappings",
        "general": "greetings, small talk, general knowledge, or educational questions that require no OpenLIMS data or action",
        "identity": "current signed-in username or identity",
        "investigation": "investigate a QC failure or its evidence and possible associations",
        "inventory": "locations, reagent stock, lots, reservations, consumption, expiration",
        "migration": "migration/import jobs or migration rows",
        "monitoring": "system, API, worker, queue, database, or service health",
        "notifications": "create, list, or cancel an alert/subscription",
        "qc": "QC worklists, failures, approvals, results, or review actions",
        "record_search": "find or summarize a project, sample, migration job, or row",
        "reporting": "compliance or audit report generation",
        "samples": "sample lookup, creation, status, archive, batch, or assignment",
        "sequences": "sequence lookup, BLAST, FASTA, DNA, RNA, or protein",
        "sop": "approved SOP, policy, procedure, or documentation question",
        "unknown": "none of the supported routes is sufficiently clear",
        "work_items": "create, assign, or list laboratory work items",
    }
    routes = "\n".join(
        f"- {name}: {description}"
        for name, description in route_descriptions.items()
    )
    return f"""
Classify one OpenLIMS user request. Do not answer the request and do not run a tool.

Return strict JSON only with this shape:
{{"route": "one_allowed_route", "confidence": 0.0}}

Allowed routes:
{routes}

Rules:
- Select chart only when the user explicitly requests a visual.
- Select attention for broad questions about priorities, pending work, or what needs review.
- Select clarification when the domain is named but the requested subset is ambiguous.
- Select general only when the request can be answered without OpenLIMS records, tools, approved SOP content, or an application action.
- Educational or scientific explanations unrelated to the user's records may use general.
- Never select general for an unsupported request to read or change samples, projects, QC, inventory, instruments, users, or system state; use unknown instead.
- Existing context may help interpret short follow-ups, but must not override an unrelated new request.
- Use unknown when uncertain. Never invent identifiers or facts.

Active context types: {safe_json(active_context)}
User request: {message}
"""


def call_openai(prompt):
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    response = client.responses.create(
        model=getattr(settings, "OPENAI_MODEL", "gpt-5"),
        input=prompt,
        store=False,
    )

    return getattr(response, "output_text", "").strip()


def call_ollama(prompt, system_message=None, json_response=False):
    base_url = str(
        getattr(settings, "OLLAMA_BASE_URL", "http://ollama:11434")
    ).rstrip("/")
    model = getattr(settings, "OLLAMA_MODEL", "llama3.1")
    timeout = int(getattr(settings, "OLLAMA_TIMEOUT_SECONDS", 60))

    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": system_message or (
                    "You are the OpenLIMS Assistant. You are read-only. "
                    "Only summarize the OpenLIMS tool result. Do not invent data. "
                    "Never make claims about unlisted records or broaden the result scope."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    }
    if json_response:
        payload["format"] = "json"
        payload["options"] = {"temperature": 0}

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")

    parsed = json.loads(raw)
    return parsed.get("message", {}).get("content", "").strip()


def _parse_route_classification(raw):
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    route = str(data.get("route") or "").strip().lower()
    if route not in ASSISTANT_ROUTES:
        return None
    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        return None
    threshold = float(
        getattr(settings, "OPENLIMS_ASSISTANT_LLM_ROUTING_MIN_CONFIDENCE", 0.65)
    )
    if confidence < threshold:
        return None
    return {
        "route": route,
        "confidence": min(max(confidence, 0.0), 1.0),
    }


def classify_route_with_llm(message, context=None):
    if not assistant_llm_routing_enabled():
        return None
    provider = llm_provider()
    prompt = build_route_classifier_prompt(message, context=context)
    try:
        if provider == "openai":
            raw = call_openai(prompt)
        elif provider == "ollama":
            raw = call_ollama(
                prompt,
                system_message=(
                    "You are a constrained OpenLIMS intent classifier. "
                    "Return JSON only. Never answer the user or invent a route."
                ),
                json_response=True,
            )
        else:
            return None
        result = _parse_route_classification(raw)
        if result:
            result["provider"] = provider
        return result
    except Exception as exc:
        logger.warning("OpenLIMS LLM route classification unavailable: %s", exc)
        return None


def enhance_with_llm(message, tool_result):
    fallback = {
        **tool_result,
        "mode": "openlims",
        "llm_enabled": False,
        "model_info": model_info_for("openlims"),
    }

    if tool_result.get("skip_llm"):
        return fallback

    if not assistant_llm_enabled():
        return fallback

    provider = llm_provider()
    is_general = tool_result.get("response_type") == "general"
    prompt = (
        build_general_assistant_prompt(message)
        if is_general
        else build_assistant_prompt(message, tool_result)
    )

    try:
        if provider == "openai":
            answer = call_openai(prompt)
            mode = "openai"
        elif provider == "ollama":
            answer = call_ollama(
                prompt,
                system_message=(
                    GENERAL_ASSISTANT_SYSTEM_MESSAGE if is_general else None
                ),
            )
            mode = "ollama"
        else:
            return fallback

        if not answer:
            return fallback

        return {
            **tool_result,
            "answer": answer,
            "mode": mode,
            "llm_enabled": True,
            "model_info": model_info_for(mode),
        }

    except Exception as exc:
        logger.exception("OpenLIMS Assistant LLM fallback triggered: %s", exc)

        error_message = f"{provider} unavailable; returned OpenLIMS rule-based response."

        return {
            **tool_result,
            "mode": "openlims",
            "llm_enabled": False,
            "llm_error": error_message,
            "model_info": model_info_for("openlims", error=error_message),
            "configured_model_info": model_info_for(provider),
        }
