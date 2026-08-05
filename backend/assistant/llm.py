import json
import logging
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

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
- Keep the answer concise and useful.

User question:
{message}

OpenLIMS tool result:
{safe_json(tool_context)}
"""


def call_openai(prompt):
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    response = client.responses.create(
        model=getattr(settings, "OPENAI_MODEL", "gpt-5"),
        input=prompt,
        store=False,
    )

    return getattr(response, "output_text", "").strip()


def call_ollama(prompt):
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
                "content": (
                    "You are the OpenLIMS Assistant. You are read-only. "
                    "Only summarize the OpenLIMS tool result. Do not invent data."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    }

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
    prompt = build_assistant_prompt(message, tool_result)

    try:
        if provider == "openai":
            answer = call_openai(prompt)
            mode = "openai"
        elif provider == "ollama":
            answer = call_ollama(prompt)
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
