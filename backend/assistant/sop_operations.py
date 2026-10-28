import re
from functools import reduce
from operator import or_

from django.db import connection
from django.db.models import Case, IntegerField, Q, Value, When
from core.permissions import is_admin

from django.utils import timezone

from events.models import Event

from .intent_matching import contains_any_intent_phrase
from .models import SOPDocument


STOP_WORDS = {
    "a", "an", "and", "are", "can", "do", "for", "how", "i", "in",
    "is", "it", "me", "my", "of", "our", "the", "this", "to", "what",
    "which", "why", "with", "sop", "say", "says", "about", "according",
    "show", "find", "relevant", "documentation", "instruction", "policy", "does", "please",
}


def _accessible_documents(user):
    queryset = SOPDocument.objects.filter(
        approved=True, status=SOPDocument.STATUS_CURRENT,
        effective_at__lte=timezone.now(),
    )
    if is_admin(user):
        return queryset
    return queryset.filter(
        Q(project__isnull=True) | Q(project__members=user)
    ).filter(
        Q(allowed_groups__isnull=True) | Q(allowed_groups__in=user.groups.all())
    ).distinct()


def _terms(message):
    return {
        token
        for token in re.findall(r"[^\W_][\w-]*", message.lower())
        if len(token) > 2 and token not in STOP_WORDS
    }


def route_sop_assistant(message, user, context=None):
    del context
    lower = str(message or "").lower()
    question_signals = [
        "how do i", "how can i", "what is the procedure", "procedure",
        "which sop", "why can't", "why can’t",
        "what does the sop say", "show the sop", "according to the sop",
        "documentation", "instruction", "policy",
    ]
    if not contains_any_intent_phrase(message, question_signals):
        return None
    if re.search(
        r"\bhow\s+do\s+i\s+(?:show|list|find|count|compare|graph|plot)\b",
        lower,
    ):
        return None
    return search_sops(message, user)


def _ranked_documents(message, user):
    terms = sorted(_terms(message))[:12]
    queryset = _accessible_documents(user)
    if not terms:
        return [], terms
    if connection.vendor == "postgresql":
        from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank, SearchVector
        vector = (SearchVector("document_code", "title", weight="A", config="english")
                  + SearchVector("section", weight="B", config="english")
                  + SearchVector("content", weight="C", config="english"))
        query = reduce(or_, (SearchQuery(term, config="english") for term in terms))
        queryset = queryset.annotate(
            search_vector=vector, search_rank=SearchRank(vector, query),
            matched_passage=SearchHeadline("content", query, config="english", start_sel="", stop_sel="",
                                           max_words=80, min_words=30, max_fragments=1),
        ).filter(search_vector=query)
    else:
        # Portable deterministic fallback for development SQLite installations.
        predicates = [Q(title__icontains=term) | Q(section__icontains=term) | Q(content__icontains=term)
                      | Q(document_code__icontains=term) for term in terms]
        score = sum((Case(When(title__icontains=term, then=Value(3)),
                          When(condition, then=Value(1)), default=Value(0), output_field=IntegerField())
                     for term, condition in zip(terms, predicates)), Value(0))
        queryset = queryset.filter(reduce(or_, predicates)).annotate(search_rank=score)
    return list(queryset.order_by("-search_rank", "document_code", "section", "pk")[:3]), terms


def _passage(content, terms, limit=600):
    text = " ".join(content.split())
    # Center on a dense matching window instead of taking the document prefix.
    matches = list(re.finditer(r"\b(?:" + "|".join(re.escape(term) for term in terms) + r")\w*", text, re.I)) if terms else []
    from collections import Counter
    counts, right, best, anchor = Counter(), 0, 0, 0
    for left, hit in enumerate(matches):
        while right < len(matches) and matches[right].start() < hit.start() + limit - 120:
            counts[matches[right][0].casefold()] += 1
            right += 1
        if len(counts) > best:
            best, anchor = len(counts), hit.start()
        key = matches[left][0].casefold()
        counts[key] -= 1
        if not counts[key]:
            del counts[key]
    start = max(0, anchor - 120)
    if start:
        boundary = text.find(" ", start)
        start = boundary + 1 if boundary >= 0 else start
    end = min(len(text), start + limit)
    if end < len(text):
        boundary = text.rfind(" ", start, end)
        end = boundary if boundary > start else end
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else ""), bool(start or end < len(text))


def search_sops(message, user):
    matches, terms = _ranked_documents(message, user)
    if not matches:
        return {
            "answer": "The approved OpenLIMS documentation available to you does not contain an answer to that question.",
            "links": [], "citations": [], "skip_llm": True, "unavailable": True,
            "sop_search": {"method": "full_text" if connection.vendor == "postgresql" else "keyword", "matches": 0},
        }
    lines = ["Approved documentation answer:", "Relevant passages from current approved sections (review the full section before applying instructions):", ""]
    citations, links = [], []
    for document in matches:
        excerpt, truncated = _passage(getattr(document, "matched_passage", document.content), terms)
        truncated = truncated or len(excerpt) < len(" ".join(document.content.split()))
        citation = f"{document.document_code} version {document.version}, section {document.section}"
        lines.extend([f"According to {citation}:", excerpt, ""])
        url = f"/sops/{document.pk}"
        citations.append({
            "kind": "sop", "id": document.pk, "label": citation, "url": url,
            "document_code": document.document_code, "title": document.title,
            "version": document.version, "section": document.section,
            "excerpt": excerpt, "excerpt_truncated": truncated,
            "scope": "Search match from a current approved section, not proof that the procedure applies to this sample.",
        })
        links.append({"label": citation, "url": url})
        Event.objects.create(
            entity_type="SOPDocument", entity_id=str(document.id), action="SOP_ANSWER_PROVIDED", actor=user,
            payload={"document_code": document.document_code, "version": document.version,
                     "section": document.section, "question": str(message)[:500]},
        )
    lines.append("This answer is informational only; no OpenLIMS action was executed.")
    return {
        "answer": "\n".join(lines), "links": links, "citations": citations,
        "suggestions": ["Prepare a review assignment"] if "review" in message.lower() or "qc" in message.lower() else [],
        "skip_llm": True,
        "sop_search": {"method": "full_text" if connection.vendor == "postgresql" else "keyword", "matches": len(matches)},
    }
