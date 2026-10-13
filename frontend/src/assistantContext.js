function values(value) {
  if (Array.isArray(value)) return value.filter(Boolean);
  return value ? [value] : [];
}

function summarizeValues(items, prefix = "") {
  const visible = items.slice(0, 3).map((item) => `${prefix}${item}`);
  const remaining = items.length - visible.length;
  return `${visible.join(", ")}${remaining > 0 ? ` +${remaining} more` : ""}`;
}

function titleCase(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function describeWorkflowFilters(workflow) {
  const spanish = workflow.language === "es";
  const labels = {
    blocked: ["Blocked", "Bloqueadas"], missing: ["Missing fields", "Campos faltantes"],
    qc: ["QC", "QC"], qc_failed: ["Failed QC", "QC rechazado"],
    overdue: ["Overdue", "Vencidas"], unassigned: ["Unassigned", "Sin asignar"],
    due_today: ["Due today", "Vencen hoy"], due_tomorrow: ["Due tomorrow", "Vencen mañana"],
    due_soon: ["Due within 7 days", "Vencen en los próximos 7 días"],
    assigned: [`Assigned to ${workflow.assignee || "?"}`, `Asignadas a ${workflow.assignee || "?"}`],
    ready: ["Available work", "Trabajo disponible"], all: ["Workflow overview", "Resumen del flujo"],
  };
  const filters = Array.isArray(workflow.filters) ? workflow.filters : [workflow.filter];
  const names = filters.map(filter => labels[filter]?.[spanish ? 1 : 0] || titleCase(filter));
  const join = workflow.match === "any" ? (spanish ? " O " : " OR ") : (spanish ? " Y " : " AND ");
  return names.join(join);
}

export function describeWorkflowScope(workflow) {
  if (workflow.language === "es") return workflow.scope === "step" ? "Mismo paso" : "Toda la muestra";
  return workflow.scope === "step" ? "Same step" : "Across sample";
}

export function groupWorkflowReasons(reasons = []) {
  const groups = new Map();
  for (const reason of reasons) {
    const key = `${reason.run_id}:${reason.step ?? "run"}`;
    if (!groups.has(key)) groups.set(key, { ...reason, key, reasons: [] });
    groups.get(key).reasons.push(reason);
  }
  return [...groups.values()];
}

export function describeAssistantContext(context) {
  if (!context || typeof context !== "object" || !Object.keys(context).length) {
    return null;
  }

  const projectWorkflows = context.project_workflows;
  if (projectWorkflows?.project_code) {
    return {
      kind: "project_workflows",
      label: `Project workflows · ${projectWorkflows.project_code}`,
      detail: `${describeWorkflowFilters(projectWorkflows)} · ${describeWorkflowScope(projectWorkflows)} · ${projectWorkflows.language === "es" ? "Registros actuales revisados en cada consulta" : "Current records checked on each question"}`,
    };
  }

  const investigation = context.investigation;
  if (investigation?.identifier) {
    return {
      kind: "investigation",
      label: `Investigation · ${investigation.identifier}`,
      detail: `${titleCase(investigation.group_by || "overview")} evidence`,
    };
  }

  const comparison = context.comparison;
  if (comparison) {
    const identifiers = values(comparison.identifiers);
    return {
      kind: "comparison",
      label: `${titleCase(comparison.analysis || "comparison")} · ${titleCase(
        comparison.kind || "records"
      )}`,
      detail: identifiers.length
        ? summarizeValues(identifiers)
        : "Permission-filtered comparison",
    };
  }

  if (context.intent === "RUN_BLAST") {
    return {
      kind: "blast",
      label: "BLAST setup",
      detail: "Follow-up answers apply to the pending BLAST request.",
    };
  }

  const sampleCodes = [
    ...values(context.sample_codes),
    ...values(context.sample_code),
  ];
  if (sampleCodes.length) {
    return {
      kind: "samples",
      label: "Sample selection",
      detail: summarizeValues([...new Set(sampleCodes)]),
    };
  }

  const resultIds = [
    ...new Set([...values(context.result_ids), ...values(context.result_id)]),
  ];
  if (resultIds.length) {
    return {
      kind: "results",
      label: resultIds.length === 1 ? "Result selection" : `${resultIds.length} results selected`,
      detail: summarizeValues(resultIds, "R-"),
    };
  }

  const sampleIds = values(context.sample_ids);
  if (sampleIds.length) {
    return {
      kind: "samples",
      label: sampleIds.length === 1 ? "Sample selection" : `${sampleIds.length} samples selected`,
      detail: "Follow-up answers can use this permission-filtered selection.",
    };
  }

  const inventoryLotIds = [
    ...new Set([
      ...values(context.inventory_lot_ids),
      ...values(context.inventory_lot_id),
    ]),
  ];
  if (inventoryLotIds.length) {
    return {
      kind: "inventory",
      label: inventoryLotIds.length === 1 ? "Inventory lot" : `${inventoryLotIds.length} inventory lots`,
      detail: "Follow-up answers can use this lot selection.",
    };
  }

  const inventoryItemIds = values(context.inventory_item_ids);
  if (inventoryItemIds.length) {
    return {
      kind: "inventory",
      label: inventoryItemIds.length === 1 ? "Inventory item" : `${inventoryItemIds.length} inventory items`,
      detail: "Follow-up answers can use this inventory selection.",
    };
  }

  if (context.batch_code) {
    return {
      kind: "batch",
      label: `Batch · ${context.batch_code}`,
      detail: "Follow-up answers can use this batch.",
    };
  }

  return {
    kind: "selection",
    label: "Conversation context",
    detail: "Follow-up answers can use the current record selection.",
  };
}
