from difflib import SequenceMatcher

from core.permissions import is_admin
from projects.models import Project
from samples.access import get_sample_access_queryset
from samples.models import Sample, SampleBatch


def accessible_entity_queryset(kind, user):
    if kind == "sample":
        return get_sample_access_queryset(
            Sample.objects.select_related("project", "batch").all(),
            user,
        ).order_by("sample_id")
    if kind == "project":
        queryset = Project.objects.all().order_by("code")
        return queryset if is_admin(user) else queryset.filter(members=user).distinct()
    if kind == "batch":
        queryset = SampleBatch.objects.select_related("project").order_by("code")
        return queryset if is_admin(user) else queryset.filter(project__members=user).distinct()
    raise ValueError(f"Unsupported entity kind: {kind}")


def entity_identifier(kind, entity):
    return entity.sample_id if kind == "sample" else entity.code


def _aliases(kind, entity):
    aliases = [entity_identifier(kind, entity)]
    if kind == "project":
        aliases.append(entity.name)
    return [str(value).strip() for value in aliases if str(value).strip()]


def resolve_entities(kind, identifiers, user, limit=10):
    wanted = [str(value).strip() for value in identifiers or [] if str(value).strip()][:limit]
    candidates = list(accessible_entity_queryset(kind, user)[:2000])
    exact = {}
    for entity in candidates:
        for alias in _aliases(kind, entity):
            exact[alias.casefold()] = entity

    resolved = []
    missing = []
    ambiguous = {}
    corrected = {}
    seen_ids = set()

    for value in wanted:
        normalized = value.casefold()
        entity = exact.get(normalized)
        if not entity:
            partial = [
                candidate
                for candidate in candidates
                if any(normalized in alias.casefold() for alias in _aliases(kind, candidate))
            ]
            partial = list({candidate.pk: candidate for candidate in partial}.values())
            if len(partial) == 1:
                entity = partial[0]
                corrected[value] = entity_identifier(kind, entity)
            elif len(partial) > 1:
                ambiguous[value] = [entity_identifier(kind, item) for item in partial[:5]]
                continue

        if not entity and candidates:
            scored = []
            for candidate in candidates:
                score = max(
                    SequenceMatcher(None, normalized, alias.casefold()).ratio()
                    for alias in _aliases(kind, candidate)
                )
                scored.append((score, candidate))
            scored.sort(key=lambda item: item[0], reverse=True)
            best_score, best = scored[0]
            runner_up = scored[1][0] if len(scored) > 1 else 0
            if best_score >= 0.86 and best_score - runner_up >= 0.06:
                entity = best
                corrected[value] = entity_identifier(kind, best)
            elif best_score >= 0.72:
                ambiguous[value] = [
                    entity_identifier(kind, item)
                    for score, item in scored[:5]
                    if score >= max(0.72, best_score - 0.08)
                ]
                continue

        if not entity:
            missing.append(value)
            continue
        if entity.pk not in seen_ids:
            resolved.append(entity)
            seen_ids.add(entity.pk)

    return {
        "entities": resolved,
        "missing": missing,
        "ambiguous": ambiguous,
        "corrected": corrected,
    }


def entity_clarification(kind, resolution):
    ambiguous = resolution.get("ambiguous") or {}
    if not ambiguous:
        return None
    options = []
    for requested, candidates in ambiguous.items():
        for candidate in candidates:
            options.append({
                "id": f"{kind}:{candidate}",
                "label": candidate,
                "message": candidate,
                "description": f"Use {candidate} for ‘{requested}’." ,
            })
    question = f"Which {kind} did you mean?"
    return {
        "answer": question,
        "clarification": {
            "topic": f"{kind}_resolution",
            "question": question,
            "options": options[:10],
        },
        "links": [],
        "suggestions": [option["message"] for option in options[:5]],
        "skip_llm": True,
    }
