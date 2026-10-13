// Produce only the bounded grammar understood by the workflow assistant.
export const WORKFLOW_FILTERS = {
  blocked: ["blocked", "bloqueadas"], missing: ["missing results", "campos faltantes"],
  qc: ["QC", "QC"], qc_failed: ["failed QC", "QC rechazado"],
  overdue: ["overdue", "vencidas"], due_today: ["due today", "vencen hoy"],
  due_tomorrow: ["due tomorrow", "vencen mañana"], due_soon: ["due within 7 days", "vencen en los próximos 7 días"],
  unassigned: ["unassigned", "sin asignar"], assigned: ["assigned", "asignadas"],
  ready: ["ready", "listas"], all: ["workflow overview", "flujo"],
};

export function buildWorkflowQuestion(draft) {
  const es = draft.language === "es";
  const error = (en, spanish) => ({ question: "", error: es ? spanish : en });
  const project = String(draft.project_code || "").trim();
  if (!/^[\p{L}\p{N}_./-]{1,64}$/u.test(project) || project.endsWith(".")) {
    return error("Enter an exact project code (letters, numbers, _, -, / or internal periods).", "Escribe un código exacto (letras, números, _, -, / o puntos internos).");
  }
  const filters = draft.filters;
  if (!Array.isArray(filters) || !filters.length || filters.some(key => !Object.hasOwn(WORKFLOW_FILTERS, key))) {
    return error("Select at least one filter.", "Selecciona al menos un filtro.");
  }
  if (!["all", "any"].includes(draft.match) || !["sample", "step"].includes(draft.scope)) {
    return error("Choose valid matching and scope options.", "Elige opciones válidas de coincidencia y alcance.");
  }
  if (filters.includes("all") && (filters.length > 1 || draft.scope === "step")) {
    return error("Workflow overview uses sample scope and cannot be combined with other filters.", "El resumen del flujo usa toda la muestra y no se combina con otros filtros.");
  }
  const owner = String(draft.assignee || "").trim();
  if (filters.includes("assigned") && !/^[\p{L}\p{N}_@.+-]{1,150}$/u.test(owner)) {
    return error("Enter one exact username, or me.", "Escribe un usuario exacto, o mí.");
  }
  const phrases = [...new Set(filters)].map(key => {
    const label = key === "assigned" ? `${es ? "asignadas a" : "assigned to"} ${owner}` : WORKFLOW_FILTERS[key][es ? 1 : 0];
    if (es) return `${key.startsWith("due_") ? "" : key === "qc" ? "necesitan " : ["missing", "qc_failed", "all"].includes(key) ? "tienen " : "están "}${label}`;
    return `${key === "qc" ? "need" : ["missing", "all"].includes(key) ? "have" : "are"} ${label}`;
  });
  const join = draft.match === "any" ? (es ? " o " : " or ") : (es ? " y " : " and ");
  const scope = draft.scope === "step" ? (es ? " en el mismo paso" : " on the same step") : (es ? " en toda la muestra" : " across the sample");
  return { question: `${es ? "¿Qué muestras en proyecto" : "Which samples in project"} ${project} ${phrases.join(join)}${scope}?`, error: "" };
}
