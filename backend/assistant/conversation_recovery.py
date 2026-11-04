"""Recover read scopes after unknown wording, with live access checks."""
from rest_framework.exceptions import ValidationError

from .context_state import sanitize_context
from .lab_helpers import response


def recover_unknown_context(user, context):
    context = sanitize_context(context)
    if not context:
        return None
    try:
        if "daily_work" in context:
            from .daily_work import daily_reply
            reply = daily_reply(user, context["daily_work"])
            if "daily_work" not in reply:
                raise ValueError()
            suggestions = ["Why these priorities?", "Only overdue", "Show daily unassigned work"]
        elif "project_investigation" in context:
            from .project_investigations import ProjectQCSerializer, investigation_reply
            spec = context["project_investigation"]
            if not isinstance(spec, dict) or "project_id" not in spec or set(spec) - {"project_id", *ProjectQCSerializer().fields}:
                raise ValueError()
            if type(spec["project_id"]) is not int or not 0 < spec["project_id"] < 2**63:
                raise ValueError()
            reply = investigation_reply(spec, user)
            suggestions = ["Which ones failed?", "Why?", "Group by instrument", "Export this investigation as CSV"]
        elif "lab_concept" in context:
            from .lab_concepts import explain_concepts
            reply = explain_concepts(context["lab_concept"])
            if reply is None:
                raise ValueError()
            suggestions = reply["suggestions"]
        elif context.get("sample_id") is not None or context.get("sample_ids"):
            from .sample_operations import _sample_queryset
            ids = context.get("sample_ids", [])
            if not isinstance(ids, list):
                raise ValueError()
            ids = ids + ([context["sample_id"]] if context.get("sample_id") is not None else [])
            if not ids or any(type(pk) is not int or not 0 < pk < 2**63 for pk in ids):
                raise ValueError()
            samples = list(_sample_queryset(user).filter(pk__in=ids).order_by("pk"))
            if len(samples) != len(set(ids)):
                raise ValueError()
            saved = {"sample_ids": [sample.pk for sample in samples]}
            if len(samples) == 1:
                saved.update(sample_id=samples[0].pk, sample_code=samples[0].sample_id)
            if context.get("read_intent") in {"sample_summary", "sample_history", "sample_location", "sample_sequences", "sample_explanation", "sample_evidence", "sample_checks", "sample_unknowns"}:
                saved["read_intent"] = context["read_intent"]
            reply = response("", context=saved)
            suggestions = ["Summarize this sample", "What should I do next?", "Show evidence for sample " + samples[0].sample_id] if len(samples) == 1 else ["Choose one sample by its exact ID"]
        elif context.get("project_id") is not None:
            from .lab_reviews import _projects
            pk = context["project_id"]
            project = _projects(user).filter(pk=pk).first() if type(pk) is int and 0 < pk < 2**63 else None
            if project is None:
                raise ValueError()
            intent = context.get("read_intent")
            saved = {"project_id": project.pk}
            if intent in {"project_summary", "project_samples", "project_quality"}:
                saved["read_intent"] = intent
            reply = response("", context=saved)
            suggestions = ["Summarize this project", "Show samples in that project", "Which samples are overdue?"]
        else:
            return None
    except (ValueError, KeyError, TypeError, ValidationError):
        return response("The earlier view is unavailable or your access changed. Choose an accessible record or start a new request.", replace_context=True)
    reply.update(answer="I didn't understand that follow-up. Your last accessible read view is still selected. Choose a follow-up below, or tell me the new task and target.",
                 suggestions=suggestions, replace_context=True, clarification={"required": True})
    return reply
