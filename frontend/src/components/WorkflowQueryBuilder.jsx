import { useId, useState } from "react";
import { buildWorkflowQuestion, WORKFLOW_FILTERS } from "../workflowQuestion.js";

export default function WorkflowQueryBuilder({ context, onRun, disabled = false }) {
  const id = useId();
  const saved = context?.project_workflows;
  const [draft, setDraft] = useState({ project_code: "", filters: ["blocked"], match: "all", scope: "sample", assignee: "me", language: "en" });
  const es = draft.language === "es";
  const t = (en, spanish) => es ? spanish : en;
  const set = (key, value) => setDraft(current => ({ ...current, [key]: value }));
  const preview = buildWorkflowQuestion(draft);
  function toggle(key) {
    setDraft(current => ({ ...current, filters: current.filters.includes(key) ? current.filters.filter(value => value !== key) : [...current.filters.filter(value => value !== "all" && key !== "all"), key], scope: key === "all" ? "sample" : current.scope }));
  }
  function preset(filters, scope = "step") {
    setDraft(current => ({ ...current, filters, scope, match: "all", assignee: es ? "mí" : "me" }));
  }
  return (
    <details className="workflow-query-builder border rounded p-2 my-2">
      <summary className="fw-semibold">{t("Build a workflow question", "Crear una consulta de flujo")}</summary>
      <fieldset disabled={disabled} className="mt-2">
        <legend className="visually-hidden">{t("Workflow query options", "Opciones de consulta")}</legend>
        <div className="d-flex gap-2 flex-wrap mb-2">
          <label className="flex-grow-1">{t("Project code", "Código del proyecto")}
            <input className="form-control form-control-sm" value={draft.project_code} maxLength={64} onChange={e => set("project_code", e.target.value)} placeholder="DEMO-360" />
          </label>
          <label>{t("Language", "Idioma")}
            <select className="form-select form-select-sm" value={draft.language} onChange={e => set("language", e.target.value)}><option value="en">English</option><option value="es">Español</option></select>
          </label>
        </div>
        {saved && <button type="button" className="btn btn-sm btn-outline-secondary mb-2" onClick={() => setDraft({ project_code: saved.project_code, filters: [...(saved.filters || [saved.filter])], match: saved.match || "all", scope: saved.scope || "sample", assignee: saved.assignee || "me", language: saved.language || "en" })}>{t("Load current query", "Cargar consulta actual")}</button>}
        <div className="d-flex flex-wrap gap-1 mb-2" aria-label={t("Quick starts", "Consultas rápidas")}>
          <button type="button" className="btn btn-sm btn-outline-dark" onClick={() => preset(["assigned", "overdue"])}>{t("My overdue work", "Mi trabajo vencido")}</button>
          <button type="button" className="btn btn-sm btn-outline-dark" onClick={() => preset(["unassigned", "due_soon"])}>{t("Due soon, unassigned", "Próximo a vencer, sin asignar")}</button>
          <button type="button" className="btn btn-sm btn-outline-dark" onClick={() => preset(["qc_failed"], "sample")}>{t("QC problems", "Problemas de QC")}</button>
        </div>
        <div className="d-flex flex-wrap gap-2 mb-2">
          {Object.entries(WORKFLOW_FILTERS).map(([key, names]) => <label key={key} className="form-check-label" htmlFor={`${id}-${key}`}><input id={`${id}-${key}`} type="checkbox" className="form-check-input me-1" checked={draft.filters.includes(key)} onChange={() => toggle(key)} />{names[es ? 1 : 0]}</label>)}
        </div>
        {draft.filters.includes("assigned") && <label className="d-block mb-2">{t("Exact username or me", "Usuario exacto o mí")}<input className="form-control form-control-sm" value={draft.assignee} maxLength={150} onChange={e => set("assignee", e.target.value)} /></label>}
        <label className="d-block mb-2">{t("Match", "Coincidencia")}<select className="form-select form-select-sm" value={draft.match} onChange={e => set("match", e.target.value)}><option value="all">{t("All conditions (AND)", "Todas las condiciones (Y)")}</option><option value="any">{t("Any condition (OR)", "Cualquier condición (O)")}</option></select></label>
        <label className="d-block mb-2">{t("Scope", "Alcance")}<select className="form-select form-select-sm" value={draft.scope} disabled={draft.filters.includes("all")} onChange={e => set("scope", e.target.value)}><option value="sample">{t("Across the sample", "En toda la muestra")}</option><option value="step">{t("On the same step", "En el mismo paso")}</option></select></label>
        <p className="small mb-2">{t("Preview a read-only question. Running it starts at page one and checks current access and records.", "Vista previa de solo lectura. Al ejecutar, comienza desde la primera página y verifica permisos y registros actuales.")}</p>
        <p className="small mb-2" aria-live="polite">{preview.error || preview.question}</p>
        <button type="button" className="btn btn-sm btn-dark" disabled={disabled || !!preview.error} onClick={() => onRun(preview.question)}>{t("Run question", "Ejecutar consulta")}</button>
      </fieldset>
    </details>
  );
}
