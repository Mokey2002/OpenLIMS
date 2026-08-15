import re


ASSISTANT_ROUTES = {
    "analytics",
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

CHART_TYPES = {"auto", "bar", "line", "scatter", "dot"}
ENTITY_KINDS = {"sample", "project", "batch", "result"}
ALLOWED_FILTERS = {
    "assigned_to",
    "batch",
    "days",
    "project",
    "qc_status",
    "status",
}


def _contains(message, pattern):
    return bool(re.search(pattern, str(message or ""), re.IGNORECASE))


def extract_structured_entities(message):
    text = str(message or "")
    entities = []
    seen = set()
    noun_patterns = {
        "sample": r"\bsamples?\b\s+(.+?)(?=\s+(?:using|with|as|for|over|during|from|by|on)\b|[?.!]|$)",
        "project": r"\bprojects?\b\s+(.+?)(?=\s+(?:using|with|as|for|over|during|from|by|on)\b|[?.!]|$)",
        "batch": r"\bbatches?\b\s+(.+?)(?=\s+(?:using|with|as|for|over|during|from|by|on)\b|[?.!]|$)",
    }
    for kind, pattern in noun_patterns.items():
        for match in re.finditer(pattern, text, re.IGNORECASE):
            values = re.split(
                r"\s*(?:,|\band\b|\bversus\b|\bvs\.?\b)\s*",
                match.group(1),
                flags=re.IGNORECASE,
            )
            for raw in values:
                value = re.sub(
                    rf"^(?:the\s+)?{kind}\s+",
                    "",
                    raw.strip(),
                    flags=re.IGNORECASE,
                ).strip(" \t\r\n'\"()[]{}:;")
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", value or ""):
                    continue
                key = (kind, value.lower())
                if key in seen:
                    continue
                seen.add(key)
                entities.append({"kind": kind, "identifier": value})
    return entities[:10]


def _extract_days(message):
    match = re.search(r"\b(?:last|past|previous)\s+(\d+)\s+days?\b", str(message or ""), re.I)
    if not match:
        return None
    return min(max(int(match.group(1)), 1), 3650)


def _extract_chart_type(message):
    lower = str(message or "").lower()
    if re.search(r"\bscatter(?:\s+(?:plot|chart|graph))?\b", lower):
        return "scatter"
    if re.search(r"\bdot\s+(?:plot|chart|graph)\b|\bplotted\s+(?:dots|points)\b", lower):
        return "dot"
    if re.search(r"\bbar\s+(?:plot|chart|graph)\b", lower):
        return "bar"
    if re.search(r"\bline\s+(?:plot|chart|graph)\b", lower):
        return "line"
    return "auto"


def classify_route_with_rules(message, context=None):
    """Return a high-confidence routing plan or ``None``.

    The selected route is still validated by its route handler. This layer only
    gives the existing deterministic handlers a common, testable first pass.
    """
    text = str(message or "").strip()
    if not text:
        return None

    route = None
    confidence = 0.0
    if _contains(text, r"\b(?:compare|comparar|compara|difference between|versus|\bvs\.?\b|outliers?|inusuales?|unusual|bottlenecks?|trend|tendencia)\b"):
        route, confidence = "comparison", 0.94
    elif _contains(
        text,
        r"\b(?:group|agrupa|agrupar|break\s+down|aggregate)\b.*\b(?:by|per|por)\b|"
        r"\b(?:count|how many)\b.*\b(?:by|per)\b|"
        r"\b(?:highest|lowest|average|rate)\b.*\b(?:qc|failure|samples?|results?|instrument)\b",
    ):
        route, confidence = "analytics", 0.91
    elif _contains(text, r"\b(?:what needs (?:my )?attention|what should i (?:review|look at)|priorit(?:y|ies|ize)|qu[eé] necesita mi atenci[oó]n|qu[eé] debo revisar)\b"):
        route, confidence = "attention", 0.96
    elif _contains(text, r"\b(?:investigate|investiga|investigar|root cause|causa ra[ií]z|why did|why has|por qu[eé])\b"):
        route, confidence = "investigation", 0.94
    elif _contains(text, r"\b(?:notifications?|notificaciones?|notify me|av[ií]same|alert me|inventory alert|subscription|suscripci[oó]n)\b"):
        route, confidence = "notifications", 0.9
    elif _contains(text, r"\b(?:sop|standard operating procedure|procedimiento operativo|procedimiento aprobado|approved procedure|policy|pol[ií]tica)\b"):
        route, confidence = "sop", 0.93
    elif _contains(text, r"\b(?:system status|system health|system healthy|estado del sistema|salud del sistema|worker|queue health|database health|api health|api healthy)\b"):
        route, confidence = "monitoring", 0.94
    elif _contains(text, r"\b(?:migration|migraci[oó]n|import job|importaci[oó]n|migration row|skipped rows?)\b"):
        route, confidence = "migration", 0.9
    elif _contains(text, r"\b(?:quality control|control de calidad|qc|failed qc|qc review|revisi[oó]n de qc|approve result|reject result)\b"):
        route, confidence = "qc", 0.91
    elif _contains(text, r"\b(?:inventory|inventario|reagents?|reactivos?|lots?|lotes?|stock|existencias|expiration|caducidad|reorder|reservation|consume)\b"):
        route, confidence = "inventory", 0.9
    elif _contains(text, r"\b(?:work items?|work queue|overdue work|unassigned work|assign work|trabajo vencido|trabajo sin asignar|cola de trabajo)\b"):
        route, confidence = "work_items", 0.91
    elif _contains(text, r"\b(?:blast|fasta|sequences?|secuencias?|alignment|alineamiento|dna|adn|rna|arn|protein|prote[ií]na)\b"):
        route, confidence = "sequences", 0.9
    elif _contains(text, r"\b(?:barcode|c[oó]digo de barras|labels?|etiquetas?)\b"):
        route, confidence = "barcode", 0.88
    elif _contains(text, r"\b(?:audit report|compliance report|generate report|export report|informe de auditor[ií]a|genera un informe|exporta el informe)\b"):
        route, confidence = "reporting", 0.9
    elif _contains(text, r"\b(?:project|projects|proyecto|proyectos|record|records|registro|registros)\b"):
        route, confidence = "record_search", 0.8
    elif _contains(text, r"\b(?:sample|samples|muestra|muestras|batch|batches)\b"):
        route, confidence = "samples", 0.82

    if not route:
        return None

    filters = {}
    days = _extract_days(text)
    if days:
        filters["days"] = days
    return {
        "route": route,
        "intent": route,
        "entities": extract_structured_entities(text),
        "filters": filters,
        "metrics": [],
        "chart_type": _extract_chart_type(text),
        "confidence": confidence,
        "source": "rules",
        "accepted": True,
        "context_keys": sorted((context or {}).keys()),
    }


def validate_routing_plan(data, min_confidence=0.65):
    if not isinstance(data, dict):
        return None
    route = str(data.get("route") or "").strip().lower()
    if route not in ASSISTANT_ROUTES:
        return None
    try:
        confidence = min(max(float(data.get("confidence", 0)), 0.0), 1.0)
    except (TypeError, ValueError):
        return None

    entities = []
    for entity in data.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        kind = str(entity.get("kind") or "").strip().lower()
        identifier = str(entity.get("identifier") or "").strip()[:128]
        if kind in ENTITY_KINDS and identifier:
            entities.append({"kind": kind, "identifier": identifier})

    filters = {
        str(key): value
        for key, value in (data.get("filters") or {}).items()
        if str(key) in ALLOWED_FILTERS and isinstance(value, (str, int, float, bool))
    }
    if "days" in filters:
        try:
            filters["days"] = min(max(int(filters["days"]), 1), 3650)
        except (TypeError, ValueError):
            filters.pop("days", None)

    metrics = [
        str(value).strip()[:64]
        for value in (data.get("metrics") or [])
        if str(value).strip()
    ][:10]
    chart_type = str(data.get("chart_type") or "auto").strip().lower()
    if chart_type not in CHART_TYPES:
        chart_type = "auto"
    return {
        "route": route,
        "intent": str(data.get("intent") or route).strip()[:64] or route,
        "entities": entities[:10],
        "filters": filters,
        "metrics": metrics,
        "chart_type": chart_type,
        "confidence": confidence,
        "accepted": confidence >= float(min_confidence),
    }
