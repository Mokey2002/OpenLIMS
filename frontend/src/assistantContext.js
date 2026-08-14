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

export function describeAssistantContext(context) {
  if (!context || typeof context !== "object" || !Object.keys(context).length) {
    return null;
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
