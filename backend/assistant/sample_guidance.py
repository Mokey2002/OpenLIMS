"""Read-only workflow guidance, grounded in accessible records on every request."""

from django.utils import timezone

from pipelines.models import PipelineRun
from pipelines.services import missing_required_fields
from samples.access import user_can_modify_sample

from .sample_operations import _sample_queryset
from .guidance_conversation import interpret


def route_sample_guidance(message, user, context=None):
    context = context or {}
    parsed = interpret(message, context)
    if not parsed:
        return None
    base = {"skip_llm": True, "links": [], "suggestions": [], "context": {}, "replace_context": True}
    if parsed.get("reset"):
        return {**base, "answer": "Sample context cleared. / Contexto de muestra borrado."}
    spanish = parsed["language"] == "es"
    def t(en, es):
        return es if spanish else en
    codes = parsed["codes"]
    pending = {"guidance": {"awaiting_sample": True, "language": parsed["language"], "focus": parsed["focus"], "steps": parsed["steps"]}}
    if len(codes) > 1:
        return {**base, "context": pending, "answer": t("Choose one sample ID so I can explain its next steps.", "Elige un ID de muestra para explicar sus próximos pasos."), "clarification": {"required": True}}
    code = codes[0] if codes else context.get("sample_code")
    if not isinstance(code, str) or not code:
        return {**base, "context": pending, "answer": t("Which sample? Reply with its exact ID, for example DEMO-360-001.", "¿Qué muestra? Responde con su ID exacto, por ejemplo DEMO-360-001."), "clarification": {"required": True}}
    matches = list(_sample_queryset(user).filter(sample_id__iexact=code)[:2])
    if len(matches) != 1:
        return {**base, "answer": t("That sample was not found, is ambiguous, or is not accessible. Provide its exact ID.", "La muestra no se encontró, es ambigua o no es accesible. Indica su ID exacto."), "clarification": {"required": True}}
    sample = matches[0]
    lines = [f"{sample.sample_id} — {sample.status}"]
    if sample.container:
        lines.append(t("Storage: ", "Almacenamiento: ") + sample.container.container_id)
    editable = user_can_modify_sample(user, sample)
    if not editable:
        lines.append(t("You have read-only access to this sample. An authorized team member must make changes.", "Tienes acceso de lectura a esta muestra. Un miembro autorizado debe realizar los cambios."))
    runs = list(PipelineRun.objects.filter(sample=sample).prefetch_related(
        "steps__work_item__results", "steps__work_item__assigned_to").order_by("-id")[:6])
    new_sample = bool(codes) and code != str(context.get("sample_code", "")).casefold()
    selected = parsed["steps"]
    if not selected and not new_sample and parsed["focus"] == "owner":
        prior_step = parsed["state"].get("step")
        if type(prior_step) is int:
            selected = [prior_step]
    conversation = {"language": parsed["language"]}
    response_context = {"sample_code": sample.sample_id, "sample_id": sample.pk, "guidance": conversation}
    if selected:
        candidates = [(run, step) for run in runs[:5] for step in run.steps.all() if step.position in selected]
        if len(selected) != 1 or len(candidates) != 1 or len(runs) > 5:
            return {**base, "context": response_context, "answer": t("That step is missing or ambiguous across pipeline runs. Open the sample to select the correct step.", "Ese paso no existe o es ambiguo entre pipelines. Abre la muestra para elegir el paso correcto."),
                    "links": [{"label": sample.sample_id, "url": f"/samples/{sample.pk}", "kind": "sample"}], "clarification": {"required": True}}
        conversation["step"] = selected[0]
    evidence = []
    if not runs:
        lines.append(t("No pipeline is linked. Open the sample and choose the appropriate pipeline with your project team.", "No hay un pipeline vinculado. Abre la muestra y elige el pipeline adecuado con tu equipo."))
    for run in runs[:5]:
        lines.append(f"Pipeline #{run.pk}: {run.status}")
        steps = list(run.steps.all())
        by_position = {step.position: step for step in steps}
        shown_steps = [step for step in steps if step.position in selected] if selected else steps[:50]
        for step in shown_steps:
            work = step.work_item
            missing = missing_required_fields(work, step) if work else []
            waiting = [str(pos) for pos in step.dependency_positions if pos not in by_position or by_position[pos].status not in {"COMPLETED", "SKIPPED"}]
            if run.status in {"COMPLETED", "CANCELLED"}:
                instruction = t("Historical run; no next action proposed.", "Ejecución histórica; no se propone una acción.")
            elif step.status in {"COMPLETED", "SKIPPED", "CANCELLED"}:
                instruction = t("No action needed for this step.", "Este paso no requiere acción.")
            elif step.status == "FAILED":
                instruction = t("Review the recorded failure and retry options in the sample.", "Revisa el fallo registrado y las opciones de reintento en la muestra.")
            elif waiting:
                instruction = t("Waiting for steps: ", "Espera los pasos: ") + ", ".join(waiting)
            elif step.status == "BLOCKED":
                instruction = t("Review the activation condition and run status in the sample; do not skip the gate.", "Revisa la condición de activación y el estado del pipeline; no omitas el requisito.")
            elif missing:
                instruction = t("Enter or correct required fields: ", "Completa o corrige los campos obligatorios: ") + ", ".join(missing)
            elif work and work.status != "COMPLETED":
                instruction = t("Required fields are present. Review the work and mark it COMPLETED when finished. QC approval alone does not complete work.", "Los campos obligatorios están presentes. Revisa el trabajo y márcalo COMPLETED al terminar. Aprobar QC no completa el trabajo.")
            elif work and step.requires_qc and work.qc_status != "APPROVED":
                instruction = t("Work is complete; an authorized QC reviewer must review it. It is not yet QC-approved.", "El trabajo está completo; un revisor autorizado debe revisar QC. Aún no tiene aprobación de QC.")
            else:
                instruction = t("Review this step in the sample for its current execution state.", "Revisa este paso en la muestra para conocer su estado actual.")
            owner = work.assigned_to.username if work and work.assigned_to else t("Unassigned", "Sin asignar")
            if parsed["focus"] == "owner":
                instruction = t("Recorded work assignee: ", "Responsable registrado del trabajo: ") + owner + ". " + instruction
                if step.requires_qc:
                    instruction += t(" The assignee is not necessarily the QC reviewer; no reviewer is inferred.", " El responsable no es necesariamente el revisor de QC; no se infiere un revisor.")
            lines.append(f"{step.position}. {step.name} — {step.status} ({owner}): {instruction}")
            evidence.append({"run_id": run.pk, "step": step.position, "status": step.status,
                             "work_item_id": work.pk if work else None, "qc_status": work.qc_status if work else None,
                             "missing_fields": missing, "waiting_for": waiting, "next_action": instruction})
        if len(steps) > 50 and not selected:
            lines.append(t("Only the first 50 steps are shown; open the sample for the full run.", "Solo se muestran los primeros 50 pasos; abre la muestra para verlos todos."))
    if len(runs) > 5:
        lines.append(t("Showing the latest five runs. Open the sample for full history.", "Se muestran las últimas cinco ejecuciones. Abre la muestra para ver el historial completo."))
    lines.append(t("Read from current records. No results, statuses or approvals were changed.", "Consulta de registros actuales. No se cambiaron resultados, estados ni aprobaciones."))
    return {**base, "answer": "\n".join(lines), "links": [{"label": sample.sample_id, "url": f"/samples/{sample.pk}", "kind": "sample"}],
            "context": response_context,
            "sample_guidance": {"sample_id": sample.pk, "as_of": timezone.now().isoformat(), "steps": evidence, "read_only": True},
            "suggestions": [t("What's holding this up?", "¿Qué falta?"), t("Who is assigned?", "¿Quién está asignado?"), t("What next?", "¿Qué sigue?")]}
