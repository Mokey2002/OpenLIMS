"""Plain-language explanations of fresh, permission-filtered sample evidence."""

import re

from django.utils import timezone

from .lab_helpers import response
from .natural_requests import normalize_request
from .sample_briefing import sample_briefing
from .sample_operations import _sample_queryset


INTENTS = {
    "summary": "sample_explanation",
    "evidence": "sample_evidence",
    "next_steps": "sample_checks",
    "unknowns": "sample_unknowns",
}
IDENTIFIER = r'(?:"(?P<quoted>[^"\n]{1,64})"|(?P<code>[\w][\w.:/-]{0,63}))'
EXPLICIT = [
    ("summary", "en", r"explain sample "),
    ("evidence", "en", r"show (?:the )?evidence for sample "),
    ("next_steps", "en", r"what should I check first for sample "),
    ("unknowns", "en", r"what is still unknown about sample "),
    ("summary", "es", r"explica (?:la )?muestra "),
    ("evidence", "es", r"muestra (?:la )?evidencia de (?:la )?muestra "),
    ("next_steps", "es", r"qu[eé] debo revisar primero (?:para|en) (?:la )?muestra "),
    ("unknowns", "es", r"qu[eé] no sabemos de (?:la )?muestra "),
]
FOLLOWUPS = [
    ("summary", None, r"explain (?:that|it|this|this sample|that sample) (?:more simply|in plain language)|give me a (?:short|brief) explanation"),
    ("evidence", None, r"why does (?:it|this|that|this sample|that sample) need attention|show (?:me )?(?:the )?(?:supporting )?evidence|explain (?:that|it|this) in more detail|more detail"),
    ("next_steps", None, r"what should I check first"),
    ("unknowns", None, r"what (?:is still unknown|don't we know|do we not know)"),
    ("summary", "es", r"expl[ií]calo (?:m[aá]s simple|en palabras sencillas)"),
    ("evidence", "es", r"por qu[eé] (?:necesita|requiere) atenci[oó]n|muestra (?:la )?evidencia|m[aá]s detalles"),
    ("next_steps", "es", r"qu[eé] debo revisar primero"),
    ("unknowns", "es", r"qu[eé] no sabemos|qu[eé] (?:falta|queda) por saber"),
    (None, "es", r"(?:explain (?:that|it|this) in spanish|in spanish|en espa[nñ]ol)"),
    (None, "en", r"(?:explain (?:that|it|this) in english|in english|en ingl[eé]s)"),
]


def _parse(message, context):
    text = normalize_request(message)
    for focus, language, prefix in EXPLICIT:
        match = re.fullmatch(prefix + IDENTIFIER, text, re.I)
        if match:
            language = "es" if language == "es" or context.get("explanation_language") == "es" else "en"
            return focus, language, match["quoted"] or match["code"]
    for focus, language, pattern in FOLLOWUPS:
        if re.fullmatch(pattern, text, re.I):
            if focus is None:
                focus = next((key for key, intent in INTENTS.items() if context.get("read_intent") == intent), "summary")
            return focus, language or ("es" if context.get("explanation_language") == "es" else "en"), None
    return None


def _selected_sample(context, user):
    ids = context.get("sample_ids", [])
    if not isinstance(ids, list):
        return None
    ids = list(ids)
    if context.get("sample_id") is not None:
        ids.append(context["sample_id"])
    if not ids or any(type(pk) is not int or not 0 < pk < 2**63 for pk in ids) or len(set(ids)) != 1:
        return None
    return _sample_queryset(user).filter(pk=ids[0]).first()


def _signals(briefing, t):
    work, results = briefing["work"], briefing["results"]
    definitions = [
        ("failed_checks", results["failed_checks"], "Results with failed QC checks: {}.", "Resultados con controles de QC fallidos: {}."),
        ("rejected_results", results["rejected"], "Results rejected by review: {}.", "Resultados rechazados en revisión: {}."),
        ("failed_work", work["failed"], "Unfinished work items marked failed: {}.", "Trabajos sin finalizar marcados como fallidos: {}."),
        ("work_qc", work["qc_review"], "Unfinished work items with rejected/rerun QC: {}.", "Trabajos sin finalizar con QC rechazado o repetición requerida: {}."),
        ("pending_review", results["awaiting_review"], "Results awaiting review or reopened: {}.", "Resultados pendientes de revisión o reabiertos: {}."),
        ("overdue_work", work["overdue"], "Overdue unfinished work items: {}.", "Trabajos sin finalizar vencidos: {}."),
        ("unassigned_work", work["unassigned"], "Unassigned unfinished work items: {}.", "Trabajos sin finalizar sin responsable: {}."),
    ]
    return [{"kind": kind, "count": count, "text": t(en, es).format(count)}
            for kind, count, en, es in definitions if count]


def _checks(briefing, t):
    work, results = briefing["work"], briefing["results"]
    checks = []
    if results["failed_checks"] or results["rejected"]:
        checks.append(t("Review the flagged results and recorded reasons with an authorized QC reviewer. A failed check and a review decision are separate evidence.",
                        "Revisa los resultados señalados y sus motivos registrados con un revisor de QC autorizado. Un control fallido y una decisión de revisión son evidencias distintas."))
    if work["failed"] or work["qc_review"]:
        checks.append(t("Inspect failed work and rejected/rerun requirements in the sample before deciding how to proceed.",
                        "Inspecciona el trabajo fallido y los requisitos de rechazo o repetición en la muestra antes de decidir cómo continuar."))
    if results["awaiting_review"]:
        checks.append(t("Ask an authorized reviewer to assess pending or reopened results; work completion does not grant QC approval.",
                        "Pide a un revisor autorizado que evalúe los resultados pendientes o reabiertos; terminar un trabajo no concede aprobación de QC."))
    if work["overdue"]:
        checks.append(t("Review overdue deadlines with the recorded work owners.", "Revisa los vencimientos con los responsables registrados del trabajo."))
    if work["unassigned"]:
        checks.append(t("Check with the project team who should own unassigned work; no assignee is inferred.",
                        "Consulta con el equipo quién debe encargarse del trabajo sin asignar; no se infiere un responsable."))
    if not checks:
        checks.append(t("Open workflow guidance and history to check remaining steps, dependencies, and required reviews.",
                        "Abre la guía del flujo y el historial para comprobar pasos pendientes, dependencias y revisiones requeridas."))
    return checks


def _unknowns(briefing, t):
    unknowns = [t("Work/QC flags alone do not establish the scientific root cause.",
                  "Las alertas de trabajo o QC por sí solas no establecen la causa científica.")]
    if not briefing["results"]["total"]:
        unknowns.append(t("No results are recorded; the QC outcome is unknown.", "No hay resultados registrados; se desconoce el resultado de QC."))
    for item in briefing["attention"]["work_items"]:
        missing = []
        if item["assigned_to"] is None:
            missing.append(t("no assignee recorded", "sin responsable registrado"))
        if item["due_at"] is None:
            missing.append(t("no deadline recorded", "sin fecha límite registrada"))
        if missing:
            unknowns.append(t("Displayed work #{}: ", "Trabajo mostrado #{}: ").format(item["id"]) + "; ".join(missing) + ".")
    rows = {row["id"]: row for row in briefing["recent_results"] + briefing["attention"]["results"]}
    for row in rows.values():
        missing = []
        if row["qc_passed"] is None:
            missing.append(t("QC check not evaluated", "control de QC no evaluado"))
        if row["qc_passed"] is False and not row["qc_failure_reason"]:
            missing.append(t("no QC failure reason recorded", "sin motivo registrado del fallo de QC"))
        if row["qc_status"] == "REJECTED" and not row["qc_review_note"]:
            missing.append(t("no rejection note recorded", "sin nota registrada del rechazo"))
        if row["reference_comparison"] == "invalid_limits":
            missing.append(t("invalid reference limits; comparison unavailable", "límites de referencia inválidos; comparación no disponible"))
        elif row["reference_min"] is None and row["reference_max"] is None:
            missing.append(t("no reference range configured", "sin rango de referencia configurado"))
        elif row["reference_comparison"] == "not_numeric":
            missing.append(t("numeric reference comparison unavailable for this value", "comparación numérica de referencia no disponible para este valor"))
        if row["value_invalid"] or row["value"] is None or row["value"] == "":
            missing.append(t("no usable value recorded", "sin valor utilizable registrado"))
        if row["qc_failure_reason_truncated"] or row["qc_review_note_truncated"]:
            missing.append(t("notes are excerpted; open the record for the full text", "notas recortadas; abre el registro para leer el texto completo"))
        if missing:
            unknowns.append(f"R-{row['id']}: " + "; ".join(missing) + ".")
    unknowns.append(t("Result-specific gaps above refer only to the displayed evidence, not every result in the sample.",
                      "Los datos faltantes de resultados indicados se refieren solo a la evidencia mostrada, no a todos los resultados de la muestra."))
    unknowns.append(t("These counts cannot establish release readiness. Check workflow dependencies, approved procedures, and required sign-off.",
                      "Estos recuentos no establecen si se puede liberar la muestra. Revisa dependencias, procedimientos aprobados y autorizaciones requeridas."))
    return unknowns


def _evidence_lines(briefing, t):
    attention = briefing["attention"]
    lines = [t("Priority evidence (bounded lists; counts include older records):", "Evidencia prioritaria (listas limitadas; los recuentos incluyen registros antiguos):")]
    lines.append(t("Work shown: {} of {} flagged items.", "Trabajos mostrados: {} de {} señalados.").format(len(attention["work_items"]), attention["work_total"]))
    for item in attention["work_items"]:
        lines.append(f"- #{item['id']} / {item['name']} — {item['status']}; "
                     + t("owner: {}; deadline: {}.", "responsable: {}; vencimiento: {}.").format(
                         item["assigned_to"] or t("unassigned", "sin asignar"), item["due_at"] or t("not recorded", "no registrado")))
    # If no results are flagged, still show recent evidence without implying
    # that passing a check grants review approval or establishes readiness.
    rows = attention["results"] or briefing["recent_results"][:3]
    lines.append(t("Results shown: {} of {} recorded; {} flagged in total.", "Resultados mostrados: {} de {} registrados; {} señalados en total.").format(len(rows), briefing["results"]["total"], attention["result_total"]))
    for row in rows:
        value = t("invalid value", "valor inválido") if row["value_invalid"] else t("not recorded", "no registrado") if row["value"] in (None, "") else str(row["value"])
        if row["unit"] and row["value"] not in (None, ""):
            value += " " + row["unit"]
        check = {True: t("passed", "aprobado"), False: t("failed", "fallido"), None: t("not evaluated", "no evaluado")}[row["qc_passed"]]
        lines.append(f"- R-{row['id']} / {row['key']} ({row['work_item']}): {value}; "
                     + t("QC check: {}; review: {}; recorded: {}.", "control de QC: {}; revisión: {}; registrado: {}.").format(check, row["qc_status"], row["created_at"]))
        for key, en, es in [("qc_failure_reason", "Recorded QC reason", "Motivo de QC registrado"), ("qc_review_note", "Recorded review note", "Nota de revisión registrada")]:
            if row[key]:
                excerpt = t(" (excerpt)", " (extracto)") if row[key + "_truncated"] else ""
                lines.append(f"  {t(en, es)}{excerpt}: {row[key]}")
        if row["reference_comparison"] == "invalid_limits":
            lines.append(t("  Reference limits are invalid; comparison unavailable.", "  Los límites de referencia son inválidos; comparación no disponible."))
        elif row["reference_min"] is None and row["reference_max"] is None:
            lines.append(t("  Reference range not configured.", "  Rango de referencia no configurado."))
        else:
            low = row["reference_min"] if row["reference_min"] is not None else t("no lower bound", "sin límite inferior")
            high = row["reference_max"] if row["reference_max"] is not None else t("no upper bound", "sin límite superior")
            comparison = {"below": t("below minimum", "bajo el mínimo"), "above": t("above maximum", "sobre el máximo"),
                          "within": t("within limits", "dentro de los límites"), "not_numeric": t("no numeric comparison", "sin comparación numérica")}.get(row["reference_comparison"], t("comparison unavailable", "comparación no disponible"))
            unit = " " + row["unit"] if row["unit"] else ""
            lines.append(t("  Configured limits (inclusive): {} to {}{}; {}.", "  Límites configurados (inclusivos): {} a {}{}; {}.").format(low, high, unit, comparison))
    return lines


def route_sample_explanations(message, user, context=None):
    context = context or {}
    parsed = _parse(message, context)
    if not parsed:
        return None
    focus, language, code = parsed
    def t(en, es):
        return es if language == "es" else en
    if code is not None:
        matches = list(_sample_queryset(user).filter(sample_id__iexact=code)[:2])
        sample = matches[0] if len(matches) == 1 else None
    else:
        sample = _selected_sample(context, user)
    if sample is None:
        return response(t("Which sample should I explain? Reply with one exact accessible sample ID.",
                          "¿Qué muestra debo explicar? Responde con un único ID exacto de una muestra accesible."),
                        context={"awaiting_read": INTENTS[focus], "explanation_language": language}, clarification={"required": True})
    briefing = sample_briefing(sample)
    signals = _signals(briefing, t)
    checks = _checks(briefing, t)
    unknowns = _unknowns(briefing, t)
    titles = {"summary": t("In plain language", "En palabras sencillas"), "evidence": t("Why this needs review", "Por qué requiere revisión"),
              "next_steps": t("What to check first", "Qué revisar primero"), "unknowns": t("What is still unknown", "Qué no sabemos")}
    lines = [f"{sample.sample_id} — {sample.status}", titles[focus] + ":"]
    if focus == "unknowns":
        lines += ["- " + item for item in unknowns]
    else:
        shown_signals = signals[:3] if focus == "summary" else signals
        lines += ["- " + item["text"] for item in shown_signals]
        if len(shown_signals) < len(signals):
            lines.append(t("More recorded flags are available with 'Show the evidence'.", "Hay más alertas registradas disponibles con 'Muestra la evidencia'."))
        if not signals:
            lines.append(t("No attention flags appear in these work/QC counts. This does not establish release readiness.",
                           "No aparecen alertas en estos recuentos de trabajo/QC. Esto no establece si se puede liberar la muestra."))
        if focus == "evidence":
            lines += [""] + _evidence_lines(briefing, t)
            lines += ["", unknowns[0]]
        elif focus == "next_steps":
            lines += [""] + [f"{index}. {item}" for index, item in enumerate(checks[:3], 1)]
            if len(checks) > 3:
                lines.append(t("Additional review checks remain; see the evidence and workflow guidance.", "Quedan comprobaciones adicionales; consulta la evidencia y la guía del flujo."))
        else:
            lines += ["", t("First check: ", "Primero revisa: ") + checks[0]]
        if not briefing["results"]["total"]:
            lines.append(t("No results are recorded; the QC outcome is unknown.", "No hay resultados registrados; se desconoce el resultado de QC."))
    lines += ["", t("Counts may overlap. Work flags exclude completed/cancelled items; results may be historical. QC checks and review decisions are separate.",
                     "Los recuentos pueden solaparse. Las alertas excluyen trabajo completado/cancelado; los resultados pueden ser históricos. Los controles y las decisiones de revisión de QC son distintos."),
              t("Read from current records. No records or approvals were changed.", "Consulta de registros actuales. No se cambiaron registros ni aprobaciones.")]
    return response("\n".join(lines), sample_briefing=briefing,
                    sample_explanation={"sample_id": sample.pk, "focus": focus, "language": language, "as_of": timezone.now().isoformat(),
                                        "signals": signals, "recommended_checks": checks, "unknowns": unknowns, "read_only": True},
                    context={"sample_id": sample.pk, "sample_code": sample.sample_id, "read_intent": INTENTS[focus], "explanation_language": language},
                    links=[{"label": sample.sample_id, "url": f"/samples/{sample.pk}", "kind": "sample"}],
                    suggestions=[t("Explain that more simply", "Explícalo más simple"), t("Show the evidence", "Muestra la evidencia"),
                                 t("What should I check first?", "¿Qué debo revisar primero?"), t("What don't we know?", "¿Qué no sabemos?"),
                                 f"What next for sample {sample.sample_id}?"])
