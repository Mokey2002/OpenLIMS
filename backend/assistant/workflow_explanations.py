"""Human-readable semantics of validated workflow queries; no sample reads."""
from .workflow_dates import deadline_windows, describe_deadlines


MEANINGS = {
    "blocked": ("A failed step, unmet dependency or activation gate, missing required fields, pending QC gate, or blocked pipeline. This does not change sample status.", "Paso fallido, dependencia o activación pendiente, campos obligatorios faltantes, requisito de QC pendiente o pipeline bloqueado. No cambia el estado de la muestra."),
    "missing": ("Required result fields are missing or invalid on an unfinished step.", "Faltan campos obligatorios o son inválidos en un paso pendiente."),
    "qc": ("A required QC gate is not approved after work completion or while the step awaits QC.", "Un requisito de QC no está aprobado tras completar el trabajo o mientras el paso espera QC."),
    "qc_failed": ("An outstanding QC gate has REJECTED or RERUN_REQUIRED status.", "Un requisito de QC pendiente tiene estado REJECTED o RERUN_REQUIRED."),
    "overdue": ("Available active work has a recorded deadline before the current server time.", "Trabajo activo disponible con fecha registrada anterior a la hora actual del servidor."),
    "unassigned": ("Available active work has no assigned user.", "Trabajo activo disponible sin usuario asignado."),
    "assigned": ("Non-cancelled work on an unfinished step belongs to the exact username shown. Completed work awaiting QC can qualify; this is the work owner, not the QC reviewer.", "Trabajo no cancelado de un paso pendiente asignado al usuario exacto indicado. Puede incluir trabajo completado pendiente de QC; es el responsable del trabajo, no el revisor de QC."),
    "ready": ("Available active work has all required fields and PENDING_REVIEW QC status. It still needs review and completion; QC approval is separate.", "Trabajo activo disponible con campos obligatorios completos y QC en PENDING_REVIEW. Aún requiere revisión y finalización; la aprobación de QC es independiente."),
    "all": ("Workflow overview includes accessible non-final samples even without an active pipeline.", "El resumen incluye muestras accesibles no finalizadas, incluso sin pipeline activo."),
}
for _mode in ("due_today", "due_tomorrow", "due_soon"):
    MEANINGS[_mode] = ("Available active work with a recorded deadline in the displayed window, including the start and excluding the end.", "Trabajo activo disponible con fecha registrada dentro de la ventana indicada, incluyendo el inicio y excluyendo el final.")


def explain_query(state, now, page_size, scan_limit):
    spanish = state["language"] == "es"
    def t(en, es):
        return es if spanish else en
    filters = [{"key": mode, "meaning": MEANINGS[mode][int(spanish)]} for mode in state["filters"]]
    match = t("AND: every condition must match.", "Y: deben cumplirse todas las condiciones.") if state["match"] == "all" else t("OR: at least one condition must match.", "O: debe cumplirse al menos una condición.")
    scope = t("Conditions must match the same step in the same pipeline run.", "Las condiciones deben coincidir en el mismo paso de la misma ejecución del pipeline.") if state["scope"] == "step" else t("Conditions may match different steps or pipeline runs across the sample.", "Las condiciones pueden coincidir en distintos pasos o ejecuciones del pipeline de la muestra.")
    records, window_text = describe_deadlines(deadline_windows(now, state["filters"]), spanish)
    notes = [
        t("Only samples you can currently access in the primary or linked project; REPORTED, CANCELLED and ARCHIVED samples are excluded. Evidence uses unfinished steps in ACTIVE or BLOCKED pipelines.", "Solo muestras actualmente accesibles del proyecto principal o vinculado; se excluyen REPORTED, CANCELLED y ARCHIVED. Los registros usan pasos pendientes de pipelines ACTIVE o BLOCKED."),
        t("Available active work means PENDING or IN_PROGRESS work on a READY or IN_PROGRESS step with satisfied dependencies.", "Trabajo activo disponible significa trabajo PENDING o IN_PROGRESS en un paso READY o IN_PROGRESS con dependencias satisfechas."),
        t(f"Each request shows up to {page_size} matching samples and checks up to {scan_limit} samples. Partial scans are not project totals.", f"Cada consulta muestra hasta {page_size} coincidencias y revisa hasta {scan_limit} muestras. Las revisiones parciales no son totales del proyecto."),
        t("Read-only explanation: no sample scan was run. Your page position is preserved. Refresh results restarts from page one; Next page continues with live records.", "Explicación de solo lectura: no se revisaron muestras. Se conserva la posición de página. Actualizar resultados reinicia desde la primera página; Siguiente página continúa con registros actuales."),
    ]
    if records:
        notes.append(t("These are the deadline windows if run now, not the windows of an earlier result.", "Estas son las ventanas si se ejecuta ahora, no las de un resultado anterior."))
        notes.append(window_text)
    title = t(f"Query explained: {state['project_code']}", f"Explicación de consulta: {state['project_code']}")
    owner = state.get("assignee")
    owner_text = t(f"Work owner: {owner}", f"Responsable del trabajo: {owner}") if owner else None
    details = {"project_code": state["project_code"], "match": state["match"], "scope": state["scope"],
               "limits": {"matching_samples_per_page": page_size, "checked_samples_per_request": scan_limit},
               "title": title, "filters": filters, "match_description": match, "scope_description": scope,
               "assignee": owner, "assignee_description": owner_text, "notes": notes, "deadline_windows": records,
               "language": state["language"], "generated_at": now.isoformat(), "read_only": True}
    answer = "\n".join([title, match, scope, *([owner_text] if owner_text else []),
                        *[f"{f['key']}: {f['meaning']}" for f in filters], *notes])
    return answer, details
