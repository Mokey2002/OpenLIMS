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

PAGE_SIZE = 25
MAX_REASONS = 6
FILTERS = {"blocked", "missing", "qc", "ready", "all"}
NEXT_PAGE = re.compile(r"(?:next page|show more|more samples|siguiente p[aá]gina|m[aá]s muestras)[.!?]*", re.I)
RESET = re.compile(r"(?:start over|clear context|empezar de nuevo)[.!?]*", re.I)
WRITE = re.compile(r"\b(?:assign|approve|complete|delete|cancel|create|update|add|asigna|aprueba|completa|elimina|cancela|crea|actualiza|agrega)\b", re.I)


def _response(answer, **kwargs):
    return {"answer": answer, "links": [], "suggestions": [], "skip_llm": True,
            "context": {}, "replace_context": True, **kwargs}


def _filter(text):
    if re.search(r"blocked|blockers?|bloquead|qu[eé].*impide", text, re.I):
        return "blocked"
    if re.search(r"missing|faltan?|incomplet", text, re.I):
        return "missing"
    if re.search(r"\bqc\b|quality review|revisi[oó]n", text, re.I):
        return "qc"
    if re.search(r"ready|list[ao]s?|can proceed", text, re.I):
        return "ready"
    if re.search(r"workflow|pipeline|flujo", text, re.I):
        return "all"
    return None


def _reason(step, kind, text):
    work = step.work_item
    return {"kind": kind, "run_id": step.pipeline_run_id, "step": step.position,
            "step_name": step.name, "step_status": step.status,
            "work_item_id": work.pk if work else None,
            "assignee": work.assigned_to.username if work and work.assigned_to else None,
            "qc_status": work.qc_status if work else None, "reason": text}


def _evidence(runs, spanish):
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
            waiting = [str(p) for p in step.dependency_positions
                       if p not in by_position or by_position[p].status not in {"COMPLETED", "SKIPPED"}]
            if step.status == "FAILED":
                detail = step.failure_reason[:250] or t("Review the failed step and retry options.", "Revisa el fallo y las opciones de reintento.")
                reasons.append(_reason(step, "failed", detail))
            if waiting:
                reasons.append(_reason(step, "dependency", t("Waiting for steps: ", "Espera los pasos: ") + ", ".join(waiting)))
            if step.status == "BLOCKED" and not waiting:
                reasons.append(_reason(step, "activation", t("Activation condition or pipeline gate is not satisfied; open the sample.", "Falta cumplir una condición de activación o requisito; abre la muestra.")))
            missing = missing_required_fields(work, step) if work else []
            if missing:
                reasons.append({**_reason(step, "missing", t("Missing or invalid required fields: ", "Campos obligatorios faltantes o inválidos: ") + ", ".join(missing)), "missing_fields": missing})
            if step.requires_qc and work and (work.status == "COMPLETED" or step.status == "AWAITING_QC") and work.qc_status != "APPROVED":
                reasons.append(_reason(step, "qc", t("QC gate: ", "Requisito de QC: ") + work.qc_status))
            if (step.status in {"READY", "IN_PROGRESS"} and not waiting and not missing and work
                    and work.status in {"PENDING", "IN_PROGRESS"} and work.qc_status == "PENDING_REVIEW"):
                reasons.append(_reason(step, "ready", t("Required fields are present; review and finish this work. QC approval is separate.", "Los campos obligatorios están completos; revisa y termina el trabajo. QC es independiente.")))
        if run.status == "BLOCKED" and not any(r["run_id"] == run.pk and r["kind"] != "ready" for r in reasons):
            reasons.append({"kind": "run_blocked", "run_id": run.pk, "step": None,
                            "reason": t("Pipeline is BLOCKED; inspect its execution history.", "El pipeline está BLOCKED; revisa su historial.")})
    return reasons


def route_project_workflows(message, user, context=None):
    text = str(message or "").strip().lstrip("¿¡")
    state = (context or {}).get("project_workflows")
    state = state if isinstance(state, dict) else {}
    if state and RESET.fullmatch(text):
        return _response("Project context cleared. / Contexto de proyecto borrado.")
    if WRITE.search(text):
        return None
    more = bool(state and NEXT_PAGE.fullmatch(text))
    mode = state.get("filter") if more else _filter(text)
    plural = bool(re.search(r"\b(?:samples|muestras)\b", text, re.I))
    followup = bool(state and re.fullmatch(
        r"(?:which (?:ones )?are (?:ready|blocked|missing results)|(?:and|what about) (?:qc|ready samples|missing results))[?.! ]*",
        text, re.I))
    if not more and not (mode and (plural or followup)):
        return None
    # "in QC" is an existing sample-status query, not a project named QC.
    if not re.search(r"project|proyecto", text, re.I) and re.search(r"\b(?:in|en)\s+(?:QC|IN_PROGRESS|RECEIVED|REPORTED|ARCHIVED|CANCELLED)\b", text, re.I):
        return None
    reference_text = re.sub(r"\b(?:in|en)\s+(?:this|that|este|ese)\s+(?:project|proyecto)\b", "", text, flags=re.I)
    references = re.findall(r"\b(?:in|en)\s+(?:(?:project|proyecto)\s+)?([\w./-]+)|\b(?:project|proyecto)\s+([\w./-]+)", reference_text, re.I)
    codes = list(dict.fromkeys((a or b).rstrip(".?!").casefold() for a, b in references
                              if (a or b).casefold() not in {"this", "that", "este", "ese"}))
    if not codes and not state and mode != "blocked" and not re.search(r"project|proyecto", text, re.I):
        return None  # Keep existing generic QC and sample searches.
    spanish = bool(re.search(r"muestras|proyecto|bloquead|faltan|listas|siguiente|m[aá]s", text, re.I)) or (more and state.get("language") == "es")
    def t(en, es):
        return es if spanish else en
    if len(codes) > 1 or re.search(r"\b(?:projects|proyectos)\b", text, re.I):
        return _response(t("Choose one exact project code.", "Elige un solo código exacto de proyecto."), clarification={"required": True})
    code = codes[0] if codes else state.get("project_code")
    if not isinstance(code, str) or not code or mode not in FILTERS:
        return _response(t("Which project? Include its exact code, for example: Which samples in project DEMO-360 are blocked, and why?", "¿Qué proyecto? Incluye su código exacto: ¿Qué muestras en proyecto DEMO-360 están bloqueadas y por qué?"), clarification={"required": True})
    projects = Project.objects.all() if is_admin(user) else Project.objects.filter(members=user)
    matches = list(projects.filter(code__iexact=code).distinct()[:2])
    if len(matches) != 1:
        return _response(t("Project not found, ambiguous, or inaccessible.", "Proyecto no encontrado, ambiguo o sin acceso."))
    project = matches[0]
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
    page = list(samples.filter(pk__gt=after).order_by("pk").prefetch_related(
        Prefetch("pipeline_runs", queryset=runs, to_attr="current_runs"))[:PAGE_SIZE + 1])
    has_more = len(page) > PAGE_SIZE
    page = page[:PAGE_SIZE]
    rows = []
    for sample in page:
        evidence = _evidence(sample.current_runs, spanish)
        selected = evidence if mode == "all" else [r for r in evidence if (r["kind"] != "ready" if mode == "blocked" else r["kind"] == mode)]
        if not selected and mode != "all":
            continue
        rows.append({"sample_id": sample.pk, "sample_code": sample.sample_id, "status": sample.status,
                     "url": f"/samples/{sample.pk}", "reasons": selected[:MAX_REASONS],
                     "additional_reasons": max(0, len(selected) - MAX_REASONS),
                     "has_active_pipeline": bool(sample.current_runs)})
    lines = [t(f"{project.code}: {len(rows)} matching samples on this page ({mode}). Checked {len(page)} of {total} accessible, non-final samples.",
               f"{project.code}: {len(rows)} muestras coincidentes en esta página ({mode}). Se revisaron {len(page)} de {total} muestras accesibles no finalizadas.")]
    for row in rows:
        details = [f"Run #{r['run_id']}" + (f" / {t('step', 'paso')} {r['step']}" if r.get("step") is not None else "") + ": " + r["reason"] for r in row["reasons"]]
        lines.append(f"{row['sample_code']} — " + ("; ".join(details) or t("No active pipeline or unfinished step evidence.", "Sin pipeline activo o pasos pendientes registrados.")))
        if row["additional_reasons"]:
            lines.append(t(f"{row['additional_reasons']} more reasons: open the sample.", f"{row['additional_reasons']} motivos adicionales: abre la muestra."))
    summary_start = len(lines)
    lines.append(t("Blockers include ordinary dependencies; a sample may still have another step available. Ready means required fields are present, not QC-approved or ready for sequencing.", "Los bloqueos incluyen dependencias normales; otra rama puede estar disponible. Listo indica campos completos, no aprobación de QC ni preparación para secuenciación."))
    if has_more:
        lines.append(t("More samples remain to check. Ask Next page; page counts are not project-wide match totals.", "Faltan muestras por revisar. Pide Siguiente página; los conteos son de esta página."))
    lines.append(t("Read from current records; no lab records changed.", "Consulta de registros actuales; no se modificaron registros del laboratorio."))
    next_state = {"project_code": project.code, "filter": mode, "after": page[-1].pk if page else after,
                  "has_more": has_more, "language": "es" if spanish else "en"}
    suggestions = ([t("Next page", "Siguiente página")] if has_more else []) + [t(f"Which samples in project {project.code} are missing results?", f"¿Qué muestras en proyecto {project.code} tienen campos faltantes?"), t(f"Which samples in project {project.code} need QC?", f"¿Qué muestras en proyecto {project.code} necesitan QC?")]
    return _response("\n".join(lines), context={"project_workflows": next_state}, suggestions=suggestions,
                     links=[{"label": row["sample_code"], "url": row["url"], "kind": "sample"} for row in rows],
                     project_workflows={"project_code": project.code, "filter": mode, "rows": rows,
                                        "language": "es" if spanish else "en",
                                        "summary": "\n".join([lines[0], *lines[summary_start:]]),
                                        "checked_on_page": len(page), "accessible_sample_count": total,
                                        "has_more": has_more, "as_of": timezone.now().isoformat(), "read_only": True})
