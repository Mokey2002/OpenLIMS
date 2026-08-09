import re

from django.utils import timezone

from events.models import Event

from .models import SOPDocument


STOP_WORDS = {
    "a", "an", "and", "are", "can", "do", "for", "how", "i", "in",
    "is", "it", "me", "my", "of", "our", "the", "this", "to", "what",
    "which", "why", "with",
}


def _is_admin(user):
    return user.is_superuser or user.groups.filter(name="admin").exists()


def _accessible_documents(user):
    queryset = (
        SOPDocument.objects.filter(
            approved=True,
            status=SOPDocument.STATUS_CURRENT,
            effective_at__lte=timezone.now(),
        )
        .select_related("project")
        .prefetch_related("allowed_groups")
    )
    if _is_admin(user):
        return list(queryset)
    group_ids = set(user.groups.values_list("id", flat=True))
    documents = []
    for document in queryset:
        if document.project_id and not document.project.members.filter(id=user.id).exists():
            continue
        allowed_group_ids = {group.id for group in document.allowed_groups.all()}
        if allowed_group_ids and not allowed_group_ids.intersection(group_ids):
            continue
        documents.append(document)
    return documents


def _terms(message):
    return {
        token
        for token in re.findall(r"[A-Za-z0-9_-]+", message.lower())
        if len(token) > 2 and token not in STOP_WORDS
    }


def route_sop_assistant(message, user, context=None):
    del context
    lower = str(message or "").lower()
    question_signals = [
        "how do i", "procedure", "which sop", "why can't", "why can’t",
        "documentation", "instruction", "policy",
    ]
    if not any(signal in lower for signal in question_signals):
        return None
    terms = _terms(message)
    scored = []
    for document in _accessible_documents(user):
        haystack = " ".join([
            document.document_code,
            document.title,
            document.section,
            document.content,
        ]).lower()
        score = sum(3 if term in document.title.lower() else 1 for term in terms if term in haystack)
        if score:
            scored.append((score, document))
    scored.sort(key=lambda item: (-item[0], item[1].document_code, item[1].section))
    if not scored:
        return {
            "answer": "The approved OpenLIMS documentation available to you does not contain an answer to that question.",
            "links": [],
            "skip_llm": True,
        }

    matches = [item[1] for item in scored[:3]]
    lines = ["Approved documentation answer:", ""]
    citations = []
    for document in matches:
        excerpt = " ".join(document.content.split())
        if len(excerpt) > 500:
            excerpt = excerpt[:497].rstrip() + "..."
        citation = f"{document.document_code} version {document.version}, section {document.section}"
        lines.extend([f"According to {citation}:", excerpt, ""])
        citations.append({
            "document_code": document.document_code,
            "title": document.title,
            "version": document.version,
            "section": document.section,
        })
        Event.objects.create(
            entity_type="SOPDocument",
            entity_id=str(document.id),
            action="SOP_ANSWER_PROVIDED",
            actor=user,
            payload={"document_code": document.document_code, "version": document.version, "section": document.section, "question": str(message)[:500]},
        )
    lines.append("This answer is informational only; no OpenLIMS action was executed.")
    return {
        "answer": "\n".join(lines),
        "links": [],
        "citations": citations,
        "suggestions": ["Prepare a review assignment"] if "review" in lower or "qc" in lower else [],
        "skip_llm": True,
    }
