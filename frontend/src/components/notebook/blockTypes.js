export const BLOCK_CATALOG = [
  { type: "RICH_TEXT", label: "Rich text", description: "Narrative notes and observations" },
  { type: "HEADING", label: "Heading", description: "Organize the experiment into sections" },
  { type: "PROTOCOL_STEP", label: "Protocol step", description: "Record an executable method step" },
  { type: "CHECKLIST", label: "Checklist", description: "Track preparation and completion" },
  { type: "TABLE", label: "Table", description: "Capture a small structured data grid" },
  { type: "STRUCTURED_RESULT", label: "Structured result", description: "Record a value, unit, and QC state" },
  { type: "CALCULATION", label: "Calculation", description: "Preserve an expression and result" },
  { type: "IMAGE", label: "Image", description: "Embed an image with its source and caption" },
  { type: "ATTACHMENT", label: "Attachment", description: "Reference an experiment file" },
  { type: "SEQUENCE_VIEW", label: "Sequence view", description: "Embed a linked molecular sequence" },
];

export function newBlock(type) {
  const defaults = {
    RICH_TEXT: { text: "" },
    HEADING: { text: "", level: 2 },
    PROTOCOL_STEP: { text: "", completed: false, notes: "" },
    CHECKLIST: { items: [{ text: "New checklist item", checked: false }] },
    TABLE: { rows: [["Column 1", "Column 2"], ["", ""]] },
    STRUCTURED_RESULT: { name: "Result", value: "", unit: "", status: "RECORDED", notes: "" },
    CALCULATION: { expression: "", result: "", unit: "", notes: "" },
    IMAGE: { url: "", alt: "", caption: "" },
    ATTACHMENT: { name: "", url: "", description: "" },
    SEQUENCE_VIEW: { sequence_public_id: "", label: "", start: "", end: "", strand: "+" },
  };
  return {
    _key: crypto.randomUUID(),
    block_type: type,
    data: defaults[type] || { text: "" },
  };
}
