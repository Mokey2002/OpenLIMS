import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


def assistant_llm_enabled():
    return bool(
        getattr(settings, "OPENLIMS_ASSISTANT_LLM_ENABLED", False)
        and getattr(settings, "OPENAI_API_KEY", "")
        and OpenAI is not None
    )


def safe_json(data):
    return json.dumps(data, indent=2, default=str)


def enhance_with_llm(message, tool_result):
    """
    Optional LLM layer.

    The OpenLIMS database is still accessed only through the existing safe,
    read-only assistant tools. The LLM only rewrites/summarizes the result.
    """
    result = {
        **tool_result,
        "mode": "rules",
        "llm_enabled": False,
    }

    if not assistant_llm_enabled():
        return result

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)

        tool_context = {
            "answer": tool_result.get("answer", ""),
            "links": tool_result.get("links", []),
            "suggestions": tool_result.get("suggestions", []),
        }

        prompt = f"""
You are the OpenLIMS Assistant.

You help users understand records in a laboratory information management system.
You are read-only. Do not claim you changed, created, deleted, approved, imported, or updated anything.
Only summarize the provided OpenLIMS tool result.

User question:
{message}

OpenLIMS tool result:
{safe_json(tool_context)}

Write a clear, concise answer. Preserve important IDs, sample IDs, project codes, migration job numbers, statuses, and errors.
Do not invent data that is not present in the tool result.
"""

        response = client.responses.create(
            model=getattr(settings, "OPENAI_MODEL", "gpt-5-mini"),
            input=prompt,
        )

        answer = getattr(response, "output_text", "")

        if not answer:
            return result

        return {
            **tool_result,
            "answer": answer.strip(),
            "mode": "llm",
            "llm_enabled": True,
        }

    except Exception as exc:
        logger.exception("OpenLIMS Assistant LLM fallback triggered: %s", exc)

        return {
            **tool_result,
            "mode": "rules",
            "llm_enabled": False,
            "llm_error": "LLM unavailable; returned rule-based response.",
        }
