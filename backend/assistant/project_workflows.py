"""Read-only, permission-scoped questions about workflows across a project."""
import re

from django.db.models import Prefetch, Q
from django.utils import timezone

from core.permissions import is_admin
from pipelines.models import PipelineRun, PipelineStepRun
from pipelines.services import missing_required_fields
from projects.models import Project
from samples.access import get_sample_access_queryset
from samples.models import Sample
from .workflow_dates import DEADLINE_LABELS, deadline_windows, describe_deadlines
from .workflow_query import context_filters, context_scope, edit_filters, extract_assignee, extract_scope, normalize_deadline_phrases, parse_filters, valid_assignee

PAGE_SIZE = 25
SCAN_BATCH_SIZE = 25
MAX_SCAN = 250
BLOCKER_KINDS = {"failed", "dependency", "activation", "missing", "qc", "run_blocked"}
MAX_REASONS = 6
NEXT_PAGE = re.compile(r"(?:next page|show more|more samples|siguiente p[aá]gina|m[aá]s muestras)[.!?]*", re.I)
RESET = re.compile(r"(?:start over|clear context|empezar de nuevo)[.!?]*", re.I)
WRITE = re.compile(r"\b(?:assign|approve|complete|delete|cancel|create|update|add|asigna|aprueba|completa|elimina|cancela|crea|actualiza|agrega)\b", re.I)


def _response(answer, **kwargs):
    return {"answer": answer, "links": [], "suggestions": [], "skip_llm": True,
            "context": {}, "replace_context": True, **kwargs}


def _resolve_assignee(project, target, user, allow_self=False):
    if not valid_assignee(target):
        return None
    if allow_self and target.casefold() in {"me", "mi", "mí"}:
        return user if user.is_active else None
    if target == user.username and user.is_active:
        return user
    # Never look up or suggest users outside this accessible project's members.
    return project.members.filter(username=target, is_active=True).first()


def _recover_query(state, user, spanish, error):
    """Keep only a validated, still-accessible query, never attempted edits.

    Recovery does not run the query or keep an old cursor/results. A subsequent
    choice goes through the normal live permission and evidence checks.
    """
    modes, match, context_error = context_filters(state)
    scope = context_scope(state)
    code = state.get("project_code")
    if (context_error or scope is None or (scope == "step" and "all" in modes)
            or not isinstance(code, str) or not code):
        return None
    projects = Project.objects.all() if is_admin(user) else Project.objects.filter(members=user)
    projects = list(projects.filter(code__iexact=code).distinct()[:2])
    if len(projects) != 1:
        return None
    assignee = _resolve_assignee(projects[0], state.get("assignee"), user) if "assigned" in modes else None
    if "assigned" in modes and assignee is None:
        return None
    def t(en, es):
        return es if spanish else en
    labels = {
        "overdue": t("overdue", "vencidas"),
        "unassigned": t("unassigned", "sin asignar"),
        "missing": t("missing results", "campos faltantes"),
        "qc": "QC", "qc_failed": t("failed QC", "QC rechazado"),
        "blocked": t("blocked", "bloqueadas"), "ready": t("ready", "listas"),
        "all": t("workflow overview", "resumen del flujo"),
        "assigned": t(f"assigned to {assignee.username if assignee else ''}", f"asignadas a {assignee.username if assignee else ''}"),
    }
    labels.update({mode: names[int(spanish)] for mode, names in DEADLINE_LABELS.items()})
    joiner = t(" AND ", " Y ") if match == "all" else t(" OR ", " O ")
    description = joiner.join(labels[mode] for mode in modes)
    scope_label = t("on the same step", "en el mismo paso") if scope == "step" else t("across the sample", "en toda la muestra")
    saved = {"project_code": projects[0].code, "filters": modes, "match": match,
             "filter": (" and " if match == "all" else " or ").join(modes),
             "scope": scope, "after": 0, "has_more": False,
             "language": "es" if spanish else "en"}
    if assignee:
        saved["assignee"] = assignee.username
    suggestions = [t("Refresh results", "Actualizar resultados")]
    if len(modes) > 1:
        suggestions.append(t("Match any condition", "Cumplir cualquier condición") if match == "all" else t("Require all conditions", "Cumplir todas las condiciones"))
        suggestions.extend(t(f"Remove the {labels[mode]} filter", f"Quitar el filtro de {labels[mode]}") for mode in modes)
    suggestions.append(t("Start over", "Empezar de nuevo"))
    explanations = {
        "mixed": t("Use AND or OR, not a mixture; adding an AND filter to an OR query needs a new complete question.", "Usa Y u O, no una mezcla; agregar un filtro Y a una consulta O requiere una pregunta completa nueva."),
        "connector": t("Join each condition with AND or OR and finish both sides.", "Une cada condición con Y u O y completa ambos lados."),
        "scope": t("Choose one scope; same-step scope requires specific filters.", "Elige un alcance; el mismo paso requiere filtros específicos."),
        "edit": t("Remove one active filter and keep at least one filter.", "Quita un filtro activo y conserva al menos uno."),
    }
    explanation = explanations.get(error, t(
        "That condition is unsupported here. Use one exact assignee and supported deadlines (today, tomorrow, next 7 days); negation, other dates and nested conditions need a different question.",
        "Esa condición no es compatible aquí. Usa un responsable exacto y vencimientos compatibles (hoy, mañana, próximos 7 días); las negaciones, otras fechas y condiciones anidadas requieren otra pregunta."))
    answer = t(
        f"I haven't applied that change. Kept your previous query: {projects[0].code} — {description}, {scope_label}. Choose an option below or restate the filters. Refresh results reruns the previous query from page one; removing a filter does not exclude those samples.",
        f"No apliqué ese cambio. Conservé la consulta anterior: {projects[0].code} — {description}, {scope_label}. Elige una opción o vuelve a indicar los filtros. Actualizar resultados repite la consulta anterior desde la primera página; quitar un filtro no excluye esas muestras.")
    return _response(explanation + "\n" + answer, context={"project_workflows": saved}, suggestions=suggestions,
                     clarification={"required": True, "previous_query_retained": True})


def _reason(step, kind, text):
    work = step.work_item
    return {"kind": kind, "run_id": step.pipeline_run_id, "step": step.position,
            "step_name": step.name, "step_status": step.status,
            "work_item_id": work.pk if work else None,
            "assignee": work.assigned_to.username if work and work.assigned_to else None,
            "qc_status": work.qc_status if work else None, "reason": text}


def _evidence(runs, spanish, assignee=None, now=None, windows=None):
    now = now or timezone.now()
    windows = windows or {}
    def t(en, es):
        return es if spanish else en
    reasons = []
    for run in runs:
        steps = list(run.steps.all())
        by_position = {step.position: step for step in steps}
        for step in steps:
            if step.status in {"COMPLETED", "SKIPPED", "CANCELLED"}:
                continue
            work = step.work_item
            if assignee and work and work.assigned_to_id == assignee.pk and work.status != "CANCELLED":
                reasons.append(_reason(step, "assigned", t(f"Unfinished pipeline step has work assigned to {assignee.username}.", f"El paso pendiente tiene trabajo asignado a {assignee.username}.")))
            waiting = [str(p) for p in step.dependency_positions
                       if p not in by_position or by_position[p].status not in {"COMPLETED", "SKIPPED"}]
            if step.status == "FAILED":
                detail = step.failure_reason[:250] or t("Review the failed step and retry options.", "Revisa el fallo y las opciones de reintento.")
                reasons.append(_reason(step, "failed", detail))
            if waiting:
                reasons.append(_reason(step, "dependency", t("Waiting for steps: ", "Espera los pasos: ") + ", ".join(waiting)))
            if step.status == "BLOCKED" and not waiting:
                reasons.append(_reason(step, "activation", t("Activation condition or pipeline gate is not satisfied; open the sample.", "Falta cumplir una condición de activación o requisito; abre la muestra.")))
            if work and not waiting and work.status in {"PENDING", "IN_PROGRESS"} and step.status in {"READY", "IN_PROGRESS"}:
                if work.due_at and work.due_at < now:
                    reasons.append({**_reason(step, "overdue", t("Work is past its due date.", "El trabajo está vencido.")), "due_at": work.due_at.isoformat()})
                if not work.assigned_to_id:
                    reasons.append(_reason(step, "unassigned", t("Available work has no assignee.", "El trabajo disponible no tiene responsable.")))
                for mode, (start, end) in windows.items():
                    if work.due_at and start <= work.due_at < end:
                        label = DEADLINE_LABELS[mode][int(spanish)]
                        reasons.append({**_reason(step, mode, t(f"Recorded work deadline matches: {label}.", f"La fecha registrada coincide: {label}.")), "due_at": work.due_at.isoformat()})
            missing = missing_required_fields(work, step) if work else []
            if missing:
                reasons.append({**_reason(step, "missing", t("Missing or invalid required fields: ", "Campos obligatorios faltantes o inválidos: ") + ", ".join(missing)), "missing_fields": missing})
            if step.requires_qc and work and (work.status == "COMPLETED" or step.status == "AWAITING_QC") and work.qc_status != "APPROVED":
                reasons.append(_reason(step, "qc", t("QC gate: ", "Requisito de QC: ") + work.qc_status))
            if (step.status in {"READY", "IN_PROGRESS"} and not waiting and not missing and work
                    and work.status in {"PENDING", "IN_PROGRESS"} and work.qc_status == "PENDING_REVIEW"):
                reasons.append(_reason(step, "ready", t("Required fields are present; review and finish this work. QC approval is separate.", "Los campos obligatorios están completos; revisa y termina el trabajo. QC es independiente.")))
        if run.status == "BLOCKED" and not any(r["run_id"] == run.pk and r["kind"] in BLOCKER_KINDS for r in reasons):
            reasons.append({"kind": "run_blocked", "run_id": run.pk, "step": None,
                            "reason": t("Pipeline is BLOCKED; inspect its execution history.", "El pipeline está BLOCKED; revisa su historial.")})
    actions = {
        "failed": t("Inspect the failure and permitted retry options.", "Revisa el fallo y las opciones de reintento permitidas."),
        "qc": t("Ask an authorized reviewer to inspect this QC gate.", "Pide a un revisor autorizado que revise este requisito de QC."),
        "missing": t("Enter or correct the listed required fields.", "Completa o corrige los campos obligatorios indicados."),
        "dependency": t("Finish the referenced upstream steps and their required reviews.", "Termina los pasos previos indicados y sus revisiones obligatorias."),
        "activation": t("Inspect the step activation conditions in the sample.", "Revisa las condiciones de activación del paso en la muestra."),
        "run_blocked": t("Review pipeline execution history.", "Revisa el historial del pipeline."),
        "overdue": t("Review the due date and work assignment with the team.", "Revisa la fecha límite y la asignación con el equipo."),
        "unassigned": t("Have an authorized team member assign this work.", "Pide a un miembro autorizado que asigne este trabajo."),
        "ready": t("Review the work before marking it complete; QC remains separate.", "Revisa el trabajo antes de completarlo; QC es independiente."),
        "assigned": t("Review this assigned work and its current step requirements.", "Revisa este trabajo asignado y los requisitos actuales del paso."),
    }
    actions.update({mode: t("Review the deadline, assignee and remaining step requirements.", "Revisa la fecha límite, el responsable y los requisitos pendientes del paso.") for mode in DEADLINE_LABELS})
    for reason in reasons:
        reason["next_action"] = actions[reason["kind"]]
    # Prioritize recorded failures and QC problems before routine dependencies.
    priority = {"failed": 0, "qc": 1, "overdue": 2, "missing": 3, "unassigned": 4,
                "assigned": 4, "activation": 5, "run_blocked": 5, "dependency": 6, "ready": 7}
    priority.update({mode: 2 for mode in DEADLINE_LABELS})
    return sorted(reasons, key=lambda r: priority[r["kind"]])


def _select_reasons(evidence, mode):
    if mode == "all":
        return evidence
    if mode == "blocked":
        return [r for r in evidence if r["kind"] in BLOCKER_KINDS]
    if mode == "qc_failed":
        return [r for r in evidence if r["kind"] == "qc" and r.get("qc_status") in {"REJECTED", "RERUN_REQUIRED"}]
    return [r for r in evidence if r["kind"] == mode]


def _match_reasons(evidence, modes, match):
    groups = [_select_reasons(evidence, mode) for mode in modes]
    matches = [bool(group) or mode == "all" for group, mode in zip(groups, modes)]
    accepted = all(matches) if match == "all" else any(matches)
    # Preserve priority order and never duplicate overlapping evidence.
    selected_ids = {id(reason) for group in groups for reason in group}
    selected = [reason for reason in evidence if id(reason) in selected_ids]
    return accepted, selected


def _match_scoped_reasons(evidence, modes, match, scope):
    if scope == "sample":
        return _match_reasons(evidence, modes, match)
    steps = {}
    for reason in evidence:
        if reason.get("step") is not None and reason.get("run_id") is not None:
            steps.setdefault((reason["run_id"], reason["step"]), []).append(reason)
    selected_ids = set()
    for reasons in steps.values():
        accepted, selected = _match_reasons(reasons, modes, match)
        if accepted:
            selected_ids.update(id(reason) for reason in selected)
    return bool(selected_ids), [r for r in evidence if id(r) in selected_ids]


def route_project_workflows(message, user, context=None):
    text = str(message or "").strip().lstrip("¿¡")
    state = (context or {}).get("project_workflows")
    state = state if isinstance(state, dict) else {}
    protected_text, explicit_assignee, conflicting_assignees = extract_assignee(text)
    protected_text = normalize_deadline_phrases(protected_text)
    edit = edit_filters(protected_text, state)
    if state and RESET.fullmatch(text):
        return _response("Project context cleared. / Contexto de proyecto borrado.")
    if WRITE.search(protected_text):
        return None
    more = bool(state and NEXT_PAGE.fullmatch(text))
    refresh = bool(state and re.fullmatch(r"(?:refresh(?: results)?|actualizar(?: resultados)?)[.!?]*", text, re.I))
    query_text, explicit_scope, conflicting_scope = extract_scope(protected_text)
    scope_only = bool(explicit_scope and re.fullmatch(r"(?:(?:only|solo)\s*)?[.!?]*", query_text, re.I))
    intent_text = re.sub(r"\b(?:in|en)\s+(?:(?:project|proyecto)\s+)?[\w./-]+|\b(?:project|proyecto)\s+[\w./-]+", "", query_text, flags=re.I)
    modes, match, parse_error = context_filters(state) if more or refresh or scope_only else parse_filters(intent_text)
    if edit is not None:
        modes, match, parse_error = edit
    plural = bool(re.search(r"\b(?:samples|muestras)\b", text, re.I))
    followup = bool(state and re.match(
        r"(?:which (?:ones )?are|and|what about|only|show|also|y|solo|muestra|adem[aá]s|tambi[eé]n)\b",
        text, re.I))
    refine = bool(followup and re.match(r"(?:also|and only|adem[aá]s|tambi[eé]n)\b", text, re.I))
    unsupported_deadline = not modes and bool(re.search(r"\b(?:due|vencen|vence|vencimiento)\b", protected_text, re.I)) and (plural or followup)
    if unsupported_deadline:
        parse_error = "deadline"
    if not (more or refresh or scope_only or conflicting_scope or edit is not None or unsupported_deadline) and not (modes and (plural or followup)):
        return None
    # "in QC" is an existing sample-status query, not a project named QC.
    if not re.search(r"project|proyecto", text, re.I) and re.search(r"\b(?:in|en)\s+(?:QC|IN_PROGRESS|RECEIVED|REPORTED|ARCHIVED|CANCELLED)\b", text, re.I):
        return None
    reference_text = re.sub(r"\b(?:in|en)\s+(?:this|that|este|ese)\s+(?:project|proyecto)\b", "", query_text, flags=re.I)
    references = re.findall(r"\b(?:in|en)\s+(?:(?:project|proyecto)\s+)?([\w./-]+)|\b(?:project|proyecto)\s+([\w./-]+)", reference_text, re.I)
    codes = list(dict.fromkeys((a or b).rstrip(".?!").casefold() for a, b in references
                              if (a or b).casefold() not in {"this", "that", "este", "ese"}))
    if not codes and not state and not (scope_only or conflicting_scope or edit is not None) and "blocked" not in modes and not re.search(r"project|proyecto", text, re.I):
        return None  # Keep existing generic QC and sample searches.
    inherited_scope = context_scope(state) if (more or refresh or scope_only or followup or edit is not None) and not codes else "sample"
    scope = explicit_scope or inherited_scope
    if conflicting_scope or inherited_scope is None or (scope == "step" and "all" in modes):
        parse_error = "scope"
    spanish = bool(re.search(r"muestras|proyecto|bloquead|faltan|listas|siguiente|m[aá]s|venc|atrasad|sin asignar|rechazado|campos|tambi[eé]n|adem[aá]s|solo|mismo paso|toda la muestra|cumplir|quitar", text, re.I)) or ((more or refresh) and state.get("language") == "es")
    def t(en, es):
        return es if spanish else en
    if scope_only and not state:
        return _response(t("First ask a project question with its exact code and filters, then choose the scope.",
                           "Primero consulta un proyecto con su código exacto y filtros; después elige el alcance."), clarification={"required": True})
    if refine and not parse_error:
        previous_modes, previous_match, parse_error = context_filters(state)
        if codes:
            parse_error = "project_refinement"
        if not parse_error and ((previous_match == "any" and len(previous_modes) > 1)
                                or (match == "any" and len(modes) > 1)):
            parse_error = "mixed"
        if not parse_error:
            modes = list(dict.fromkeys([*[m for m in previous_modes if m != "all"], *modes]))
            match = "all"
            if "all" in modes and len(modes) > 1:
                parse_error = "mixed"
    assignee_target = None
    if "assigned" in modes:
        assignee_target = explicit_assignee or (state.get("assignee") if not codes and (more or refresh or scope_only or followup or edit is not None) else None)
        if not valid_assignee(assignee_target):
            parse_error = "assignee"
        # Adding a second owner is ambiguous; use Only assigned to ... to replace.
        refined_target = user.username if explicit_assignee and explicit_assignee.casefold() in {"me", "mi", "mí"} else explicit_assignee
        if refine and explicit_assignee and "assigned" in context_filters(state)[0] and refined_target != state.get("assignee"):
            parse_error = "assignee"
    if conflicting_assignees:
        parse_error = "assignee"
    if parse_error:
        # A failed follow-up must not silently replace the last valid query.
        # Explicit project questions and invalid/revoked contexts still clear it.
        if state and not codes and not re.search(r"\b(?:projects?|proyectos?)\b", text, re.I):
            recovered = _recover_query(state, user, spanish, parse_error)
            if recovered:
                return recovered
        if edit is not None:
            return _response(t("Ask a project question first. You can then match any/all conditions or remove one active filter, keeping at least one. Removing a filter does not exclude those samples. Repeat the project code and filters to reset an invalid query.",
                               "Primero consulta un proyecto. Después puedes cumplir cualquier/todas las condiciones o quitar un filtro activo, conservando al menos uno. Quitar un filtro no excluye esas muestras. Repite el código y los filtros para reiniciar una consulta inválida."), clarification={"required": True})
        if parse_error == "assignee":
            return _response(t("Use one exact username: assigned to maria, or assigned to me. Use Only assigned to ... to replace the filter; multiple assignees are not supported.",
                               "Usa un nombre de usuario exacto: asignadas a maria, o asignadas a mí. Usa Solo asignadas a ... para reemplazar el filtro; no se admiten varios responsables."), clarification={"required": True})
        if parse_error == "scope":
            return _response(t("Choose one scope: on the same step, or across the sample. Same-step scope requires specific filters, not workflow overview. Repeat the project code and filters.",
                               "Elige un alcance: en el mismo paso o en toda la muestra. El mismo paso requiere filtros específicos, no un resumen del flujo. Repite el código del proyecto y los filtros."), clarification={"required": True})
        return _response(t(
            "Use filters joined by AND or OR: blocked, missing results, QC, failed QC, overdue, due today/tomorrow/within 7 days, unassigned, assigned to one exact username, ready. Negation, other dates and nested conditions are unsupported. Repeat the project code and filters.",
            "Usa filtros unidos por Y o por O: bloqueadas, campos faltantes, QC, QC rechazado, vencidas, vencen hoy/mañana/en los próximos 7 días, sin asignar, asignadas a un usuario exacto, listas. No se admiten negaciones, otras fechas ni condiciones anidadas. Repite el código y los filtros."), clarification={"required": True})
    if len(codes) > 1 or re.search(r"\b(?:projects|proyectos)\b", protected_text, re.I):
        return _response(t("Choose one exact project code.", "Elige un solo código exacto de proyecto."), clarification={"required": True})
    code = codes[0] if codes else state.get("project_code")
    if not isinstance(code, str) or not code or not modes:
        return _response(t("Which project? Include its exact code, for example: Which samples in project DEMO-360 are blocked, and why?", "¿Qué proyecto? Incluye su código exacto: ¿Qué muestras en proyecto DEMO-360 están bloqueadas y por qué?"), clarification={"required": True})
    projects = Project.objects.all() if is_admin(user) else Project.objects.filter(members=user)
    matches = list(projects.filter(code__iexact=code).distinct()[:2])
    if len(matches) != 1:
        return _response(t("Project not found, ambiguous, or inaccessible.", "Proyecto no encontrado, ambiguo o sin acceso."))
    project = matches[0]
    assignee = _resolve_assignee(project, assignee_target, user, allow_self=bool(explicit_assignee)) if "assigned" in modes else None
    if "assigned" in modes and assignee is None:
        return _response(t("Assignee not found or unavailable in this project. Use an exact active project username or assigned to me.",
                           "Responsable no encontrado o no disponible en este proyecto. Usa un usuario activo exacto del proyecto o asignadas a mí."), clarification={"required": True})
    after = state.get("after", 0) if more else 0
    if type(after) is not int or after < 0 or after > 9223372036854775807:
        return _response(t("Invalid page context. Ask the project question again.", "Contexto de página inválido. Repite la pregunta del proyecto."))
    if more and not state.get("has_more"):
        return _response(t("No more pages in this view. Ask the project question again to refresh.", "No hay más páginas. Repite la pregunta para actualizar."))
    samples = get_sample_access_queryset(Sample.objects.all(), user).filter(
        Q(project=project) | Q(linked_projects=project)
    ).exclude(status__in=["REPORTED", "CANCELLED", "ARCHIVED"]).distinct()
    total = samples.count()
    runs = PipelineRun.objects.filter(status__in=["ACTIVE", "BLOCKED"]).prefetch_related(
        Prefetch("steps", queryset=PipelineStepRun.objects.select_related("work_item__assigned_to").prefetch_related("work_item__results")))
    # Scan past nonmatches, but bound work per request for large projects.
    observed_at = timezone.now()
    windows = deadline_windows(observed_at, modes)
    rows = []
    checked = 0
    filter_counts = {mode: 0 for mode in modes}
    across_sample_count = 0
    without_pipeline = 0
    cursor = after
    while len(rows) < PAGE_SIZE and checked < MAX_SCAN:
        batch = list(samples.filter(pk__gt=cursor).order_by("pk").prefetch_related(
            Prefetch("pipeline_runs", queryset=runs, to_attr="current_runs"))[:min(SCAN_BATCH_SIZE, MAX_SCAN - checked)])
        if not batch:
            break
        for sample in batch:
            cursor = sample.pk
            checked += 1
            evidence = _evidence(sample.current_runs, spanish, assignee, observed_at, windows)
            without_pipeline += not bool(sample.current_runs)
            for condition in modes:
                condition_matches, _ = _match_scoped_reasons(evidence, [condition], "all", scope)
                filter_counts[condition] += condition_matches
            if scope == "step":
                across_sample_count += _match_reasons(evidence, modes, match)[0]
            accepted, selected = _match_scoped_reasons(evidence, modes, match, scope)
            if accepted:
                rows.append({"sample_id": sample.pk, "sample_code": sample.sample_id, "status": sample.status,
                             "url": f"/samples/{sample.pk}", "reasons": selected[:MAX_REASONS],
                             "additional_reasons": max(0, len(selected) - MAX_REASONS),
                             "has_active_pipeline": bool(sample.current_runs)})
            if len(rows) >= PAGE_SIZE:
                break
        if len(batch) < SCAN_BATCH_SIZE:
            break
    remaining = samples.filter(pk__gt=cursor).count()
    has_more = remaining > 0
    scan_limit_reached = checked >= MAX_SCAN and has_more and len(rows) < PAGE_SIZE
    complete_scan = after == 0 and not has_more
    match_total = len(rows) if complete_scan else None
    mode = (" and " if match == "all" else " or ").join(f"assigned to {assignee.username}" if item == "assigned" else item for item in modes)
    lines = [t(f"{project.code}: {len(rows)} matching samples shown ({mode}). Checked {checked} samples in this request; {remaining} remain to check. Project scope: {total} accessible, non-final samples.",
               f"{project.code}: {len(rows)} muestras coincidentes ({mode}). Se revisaron {checked} en esta consulta; quedan {remaining} por revisar. Alcance: {total} muestras accesibles no finalizadas.")]
    if complete_scan:
        lines.append(t(f"Complete project scan: {match_total} matching samples.", f"Revisión completa del proyecto: {match_total} muestras coincidentes."))
    window_records = []
    if windows:
        window_records, window_text = describe_deadlines(windows, spanish)
        lines.append(window_text)
    diagnostics = None
    diagnostic_suggestions = []
    if not rows:
        diagnostics = {
            "coverage": "complete_project" if complete_scan else "current_scan",
            "checked_samples": checked,
            "filter_counts": filter_counts,
            "samples_without_active_pipeline": without_pipeline,
            "across_sample_matches": across_sample_count if scope == "step" else None,
        }
        lines.append(t("No matches for the current query; filters have not been changed.",
                       "Sin coincidencias para la consulta actual; no se cambiaron los filtros."))
        if checked:
            labels = {"overdue": t("overdue", "vencidas"), "unassigned": t("unassigned", "sin asignar"),
                      "missing": t("missing results", "campos faltantes"), "qc": "QC",
                      "qc_failed": t("failed QC", "QC rechazado"), "blocked": t("blocked", "bloqueadas"),
                      "ready": t("ready", "listas"), "all": t("workflow overview", "resumen del flujo")}
            labels["assigned"] = t(f"assigned to {assignee.username if assignee else ''}", f"asignadas a {assignee.username if assignee else ''}")
            labels.update({mode: names[int(spanish)] for mode, names in DEADLINE_LABELS.items()})
            counts = "; ".join(f"{labels[condition]}: {count}" for condition, count in filter_counts.items())
            lines.append(t(f"Individual conditions among the {checked} samples checked in this request: {counts}. Counts overlap; do not add them together.",
                           f"Condiciones individuales entre las {checked} muestras revisadas en esta consulta: {counts}. Los conteos pueden solaparse; no los sumes."))
            if not complete_scan:
                lines.append(t("These diagnostic counts cover this scan only, not the whole project or previous pages.",
                               "Estos conteos cubren solo esta revisión, no todo el proyecto ni páginas anteriores."))
            if without_pipeline:
                lines.append(t(f"{without_pipeline} checked samples have no active or blocked pipeline run; this does not mean their work is complete.",
                               f"{without_pipeline} muestras revisadas no tienen ejecuciones de pipeline activas o bloqueadas; esto no significa que su trabajo esté completo."))
            if scope == "step" and across_sample_count:
                lines.append(t(f"{across_sample_count} checked samples satisfy the query across the sample, but not on the same step. Choose Across the sample to inspect them; the scope is unchanged until you choose.",
                               f"{across_sample_count} muestras revisadas cumplen la consulta en toda la muestra, pero no en el mismo paso. Elige En toda la muestra para revisarlas; el alcance no cambia hasta que lo elijas."))
                diagnostic_suggestions.append(t("Across the sample", "En toda la muestra"))
            if match == "all" and len(modes) > 1 and any(filter_counts.values()):
                lines.append(t("Some checked samples match individual conditions. Match any condition uses OR instead of AND; it is a different query.",
                               "Algunas muestras revisadas cumplen condiciones individuales. Cumplir cualquier condición usa O en lugar de Y; es una consulta diferente."))
                diagnostic_suggestions.append(t("Match any condition", "Cumplir cualquier condición"))
        elif total == 0:
            lines.append(t("There are no accessible, non-final samples in this project scope.",
                           "No hay muestras accesibles no finalizadas en este alcance del proyecto."))
    header_lines = list(lines)
    for row in rows:
        details = [f"Run #{r['run_id']}" + (f" / {t('step', 'paso')} {r['step']}" if r.get("step") is not None else "") + ": " + r["reason"] for r in row["reasons"]]
        lines.append(f"{row['sample_code']} — " + ("; ".join(details) or t("No active pipeline or unfinished step evidence.", "Sin pipeline activo o pasos pendientes registrados.")))
        if row["additional_reasons"]:
            lines.append(t(f"{row['additional_reasons']} more reasons: open the sample.", f"{row['additional_reasons']} motivos adicionales: abre la muestra."))
    summary_start = len(lines)
    if scope == "step":
        lines.append(t("Conditions must match the same step within the same pipeline run. Only matching step evidence is shown.",
                       "Las condiciones deben coincidir en el mismo paso de la misma ejecución. Solo se muestran registros de pasos coincidentes."))
    elif len(modes) > 1:
        lines.append(t(
            f"Matching {'ALL' if match == 'all' else 'ANY'} listed conditions per sample. Evidence may come from different steps; this is not a same-step filter.",
            f"Coincidencia con {'TODAS las' if match == 'all' else 'CUALQUIERA de las'} condiciones por muestra. Los registros pueden provenir de pasos distintos; no se exige el mismo paso."))
    lines.append(t("Blockers include ordinary dependencies; a sample may still have another step available. Ready means required fields are present, not QC-approved or ready for sequencing.", "Los bloqueos incluyen dependencias normales; otra rama puede estar disponible. Listo indica campos completos, no aprobación de QC ni preparación para secuenciación."))
    if scan_limit_reached:
        lines.append(t(f"Scan limit reached ({MAX_SCAN} samples). Continue with Next page even if this page has no matches.", f"Límite de revisión alcanzado ({MAX_SCAN} muestras). Continúa con Siguiente página aunque no haya coincidencias."))
    if has_more:
        lines.append(t("More samples remain to check. Ask Next page; page counts are not project-wide match totals.", "Faltan muestras por revisar. Pide Siguiente página; los conteos son de esta página."))
    lines.append(t("Read from current records; no lab records changed.", "Consulta de registros actuales; no se modificaron registros del laboratorio."))
    next_state = {"project_code": project.code, "filter": mode, "filters": modes, "match": match, "scope": scope, "after": cursor,
                  "has_more": has_more, "language": "es" if spanish else "en"}
    if assignee:
        next_state["assignee"] = assignee.username
    suggestions = ([t("Next page", "Siguiente página")] if has_more else []) + [t(f"Which samples in project {project.code} are missing results?", f"¿Qué muestras en proyecto {project.code} tienen campos faltantes?"), t(f"Which samples in project {project.code} need QC?", f"¿Qué muestras en proyecto {project.code} necesitan QC?")]
    suggestions += [t("Only failed QC", "Solo QC rechazado"), t("Only overdue", "Solo vencidas"), t("Only unassigned", "Solo sin asignar"), t("Refresh results", "Actualizar resultados")]
    if match == "all" and "unassigned" not in modes:
        suggestions.append(t("Also unassigned", "También sin asignar"))
    # The response contract displays at most eight choices. Keep query controls
    # ahead of generic examples so scope/owner refinements are actually visible.
    controls = [t("Refresh results", "Actualizar resultados")]
    if "all" not in modes:
        controls.append(t("Across the sample", "En toda la muestra") if scope == "step" else t("On the same step", "En el mismo paso"))
    if len(modes) > 1:
        controls.append(t("Match any condition", "Cumplir cualquier condición") if match == "all" else t("Require all conditions", "Cumplir todas las condiciones"))
    controls.append(t("Only assigned to me", "Solo asignadas a mí"))
    if match == "all" and "due_today" not in modes:
        controls.append(t("Also due today", "También vencen hoy"))
    if match == "all" and "assigned" not in modes:
        controls.append(t("Also assigned to me", "También asignadas a mí"))
    suggestions = list(dict.fromkeys(([t("Next page", "Siguiente página")] if has_more else []) + diagnostic_suggestions + controls + suggestions))[:8]
    return _response("\n".join(lines), context={"project_workflows": next_state}, suggestions=suggestions,
                     links=[{"label": row["sample_code"], "url": row["url"], "kind": "sample"} for row in rows],
                     project_workflows={"project_code": project.code, "filter": mode, "filters": modes, "match": match, "scope": scope, "rows": rows,
                                        "assignee": assignee.username if assignee else None,
                                        "deadline_windows": window_records,
                                        "language": "es" if spanish else "en",
                                        "summary": "\n".join([*header_lines, *lines[summary_start:]]),
                                        "checked_on_page": checked, "accessible_sample_count": total,
                                        "remaining_to_check": remaining, "matching_sample_count": match_total,
                                        "complete_project_scan": complete_scan, "scan_limit_reached": scan_limit_reached,
                                        "empty_result_diagnostics": diagnostics,
                                        "has_more": has_more, "as_of": observed_at.isoformat(), "read_only": True})
