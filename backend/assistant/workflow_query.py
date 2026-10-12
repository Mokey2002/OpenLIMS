"""Bounded bilingual workflow expressions; never execute model-generated queries."""
import re


FILTER_PATTERNS = (
    ("qc_failed", r"\b(?:(?:failed|rejected|rerun|re-run|rechazad\w*|fallid\w*)\s+qc|qc\s+(?:failed|rejected|rerun|re-run|rechazad\w*|fallid\w*))\b"),
    ("overdue", r"\b(?:overdue|vencid\w*|atrasad\w*)\b"),
    ("unassigned", r"\b(?:unassigned|sin asignar|sin responsable)\b"),
    ("blocked", r"\b(?:blocked|blockers?|bloquead\w*|qu[eé] impide)\b"),
    ("missing", r"\b(?:missing(?: results| fields)?|faltan\w*|incomplet\w*|campos faltantes)\b"),
    ("qc", r"\b(?:qc|quality review|revisi[oó]n)\b"),
    ("ready", r"\b(?:ready|list[ao]s?|can proceed)\b"),
    ("all", r"\b(?:workflow(?: overview)?|pipeline|flujo)\b"),
)
FILTERS = {kind for kind, _ in FILTER_PATTERNS}
SCOPES = {
    "step": r"\b(?:on|in) (?:the )?same step\b|\ben el mismo paso\b",
    "sample": r"\bacross (?:the )?sample\b|\ben toda la muestra\b",
}


def extract_scope(text):
    """Remove explicit scope phrases before interpreting project references."""
    found = [scope for scope, pattern in SCOPES.items() if re.search(pattern, text, re.I)]
    for pattern in SCOPES.values():
        text = re.sub(pattern, "", text, flags=re.I)
    return text.strip(), found[0] if len(found) == 1 else None, len(found) > 1


def context_scope(state):
    scope = state.get("scope", "sample")
    return scope if isinstance(scope, str) and scope in SCOPES else None

# Anything outside this small grammar asks for clarification instead of silently
# ignoring an assignee, date, negation, threshold, or unsupported condition.
FILLER = re.compile(
    r"\b(?:which|what|samples|are|is|have|has|with|need|needs|needing|show|me|the|"
    r"ones|those|that|only|also|and|or|why|about|both|either|please|all|"
    r"qu[eé]|cu[aá]les|muestras|est[aá]n|son|tienen|necesitan|con|campos|"
    r"resultados|obligatorios|muestra|mu[eé]strame|las|los|solo|s[oó]lo|y|o|"
    r"por|favor|adem[aá]s|tambi[eé]n|que|este|ese|this|that|project|proyecto)\b", re.I)


def parse_filters(text):
    """Return (filters, all/any, error). Matches are ordered as spoken."""
    remaining = text
    found = []
    for kind, pattern in FILTER_PATTERNS:
        for match in re.finditer(pattern, remaining, re.I):
            found.append((match.start(), match.end(), kind))
        remaining = re.sub(pattern, lambda m: " " * len(m.group()), remaining, flags=re.I)
    found.sort()
    modes = list(dict.fromkeys(kind for _, _, kind in found))
    if not modes:
        return [], "all", None
    residual = FILLER.sub("", remaining)
    if re.search(r"[^\s,.?!¿¡]", residual):
        return modes, "all", "unsupported"
    prefix, suffix = text[:found[0][0]], text[found[-1][1]:]
    # A dangling operator is an incomplete question, not a single-filter query.
    if (re.search(r"\b(?:or|o)\b", prefix, re.I)
            or re.search(r"\b(?:and|or|y|o)\b", re.sub(r"\b(?:and why|y por qu[eé])\b", "", suffix, flags=re.I), re.I)):
        return modes, "all", "connector"
    connectors = set()
    for left, right in zip(found, found[1:]):
        between = text[left[1]:right[0]]
        if re.search(r"\b(?:or|o)\b", between, re.I):
            connectors.add("any")
        if re.search(r"\b(?:and|y)\b", between, re.I):
            connectors.add("all")
        if not re.search(r"\b(?:and|y|or|o)\b", between, re.I):
            return modes, "all", "connector"
    if len(connectors) > 1 or ("all" in modes and len(modes) > 1):
        return modes, "all", "mixed"
    if (("any" in connectors and re.search(r"\bboth\b", prefix, re.I))
            or ("all" in connectors and re.search(r"\beither\b", prefix, re.I))):
        return modes, "all", "mixed"
    return modes, next(iter(connectors), "all"), None


def context_filters(state):
    """Accept old single-filter contexts, validate all client-supplied fields."""
    modes = state.get("filters", [state.get("filter")])
    match = state.get("match", "all")
    if (not isinstance(modes, list) or not 1 <= len(modes) <= len(FILTERS)
            or any(not isinstance(mode, str) or mode not in FILTERS for mode in modes)
            or not isinstance(match, str) or match not in {"all", "any"}
            or ("all" in modes and len(modes) > 1)):
        return [], "all", "context"
    return list(dict.fromkeys(modes)), match, None
