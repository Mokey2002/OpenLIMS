const labels = {
  EXPERIMENT_REVISION_CREATED: "Experiment saved", DRAFT_CREATED_FROM_RUN: "Experiment draft created",
  ASSISTANT_ACTION_PROPOSED: "Assistant action proposed", ASSISTANT_ACTION_CONFIRMED: "Assistant action confirmed",
  ASSISTANT_ACTION_COMPLETED: "Assistant task completed", ASSISTANT_ACTION_FAILED: "Assistant action failed",
};
const object = value => value && typeof value === "object" && !Array.isArray(value) ? value : {};
const text = value => typeof value === "string" ? value.trim() : "";
const identity = value => value;
export const humanizeAudit = value => String(value || "").replace(/([a-z])([A-Z])/g, "$1 $2").replaceAll("_", " ").toLowerCase().replace(/^./, letter => letter.toUpperCase());

export function auditAction(event, t = identity) {
  return t(event.action_label || labels[event.action] || humanizeAudit(event.action));
}

export function auditRecord(event, t = identity) {
  if (text(event.entity_label) && !event.entity_label.endsWith(" (name unavailable)")) return event.entity_label;
  const payload = object(event.payload), after = object(payload.after), before = object(payload.before);
  const kind = String(event.entity_type || "").replaceAll("_", "").toLowerCase();
  const fields = {
    container: ["container_id", "name"], location: ["name", "code"], sample: ["sample_code", "sample_id"],
    project: ["code", "name", "project_code"], experiment: ["title"], notebook: ["name"],
    user: ["username"], assistantaction: ["summary", "action_type"],
  }[kind] || ["name", "title", "code", "sample_code", "run_id"];
  const label = text(object(payload.entity).label);
  if (label) return label;
  for (const snapshot of [payload, after, before]) for (const key of fields) if (text(snapshot[key])) return snapshot[key];
  return `${t(humanizeAudit(event.entity_type) || "Record")} (${t("name unavailable")})`;
}

export function auditReason(event) {
  const reason = text(object(event.payload).reason);
  return /^Assistant source draft \/ action [0-9a-f-]{36}$/i.test(reason) ? "Assistant source draft" : reason;
}

export function auditDescription(event, t = identity, language = "en") {
  const payload = object(event.payload), before = object(payload.before), after = object(payload.after);
  if (Number.isInteger(after.revision)) {
    const es = language === "es";
    let summary = Number.isInteger(before.revision)
      ? `${es ? "Revisión" : "Revision"} ${before.revision} → ${after.revision}`
      : `${es ? "Revisión inicial" : "Initial revision"} ${after.revision}`;
    const changes = object(object(payload.details).changes), parts = [];
    for (const kind of ["blocks", "links"]) for (const action of ["added", "removed", "modified"]) {
      const count = changes[`${kind}_${action}`];
      if (!Number.isInteger(count) || count <= 0) continue;
      const noun = es ? kind === "blocks" ? count === 1 ? "bloque" : "bloques" : count === 1 ? "enlace" : "enlaces" : count === 1 ? kind.slice(0, -1) : kind;
      const verb = es ? { added: count === 1 ? "añadido" : "añadidos", removed: count === 1 ? "eliminado" : "eliminados", modified: count === 1 ? "modificado" : "modificados" }[action] : action;
      parts.push(`${count} ${noun} ${verb}`);
    }
    if (parts.length) summary += `; ${parts.join(", ")}`;
    return summary;
  }
  if (Array.isArray(payload.changed_fields)) {
    const changes = payload.changed_fields.filter(field => typeof field === "string").map(field => {
      const format = value => value === null || value === undefined ? t("Not set") : typeof value === "object" ? JSON.stringify(value) : String(value);
      return `${t(humanizeAudit(field))}: ${format(before[field])} → ${format(after[field])}`;
    });
    if (changes.length) return changes.join("; ");
  }
  if (String(event.entity_type).toLowerCase() === "assistantaction") return text(payload.summary) || text(object(payload.result).message) || auditAction(event, t);
  return language === "en" && event.description ? event.description : `${auditAction(event, t)}: ${auditRecord(event, t)}`;
}
